'use strict';

const assert = require('node:assert/strict');
const { chromium } = require('../.test-tools/node_modules/playwright');

// Requires the existing tests/browser_fixture.py server; this script starts no server.
// These are JavaScript readiness conditions only, not Android overlay/visual-commit tests.
const base = new URL(process.env.AGENT_BROWSER_URL || 'http://127.0.0.1:8697');
const documentUrl = new URL('/', base).href;
const navigationId = '42';
const pageUrl = documentUrl + '#token=browser-fixture-only&native_navigation=' + navigationId;
const appUrl = new URL('/static/app.js', base).href;
const cssUrl = new URL('/static/app.css', base).href;
const timeout = 15000;
const startupError = 'browser-page-ready: injected app.js startup failure';

// Match MainActivity.probePage() with the fixture origin and this load's navigation ID.
// Evaluating this expression never modifies the document or application state.
const readinessProbe = `(function(){return location.origin===${JSON.stringify(base.origin)} && location.pathname==='/' && document.documentElement.dataset.agentUiReady==='1' && document.documentElement.dataset.agentNavigationId===${JSON.stringify(navigationId)} && !!document.querySelector('#chat-form') && !!document.querySelector('#message-input') && getComputedStyle(document.querySelector('.app-shell')).display==='flex';})()`;

async function pollReadiness(page, expected) {
  const result = await page.waitForFunction(`(${readinessProbe})===${expected}`, null, {
    polling: 'raf',
    timeout,
  });
  await result.dispose();
  assert.equal(await page.evaluate(readinessProbe), expected);
}

async function settled(page) {
  await page.waitForLoadState('domcontentloaded');
  await page.waitForLoadState('load');
  // Allow layout and deferred-script errors to settle without a timed sleep.
  await page.evaluate(() => new Promise(resolve => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  }));
}

async function navigate(page) {
  const response = await page.goto(pageUrl, { waitUntil: 'domcontentloaded' });
  assert(response, 'navigation must return a document response');
  assert.equal(response.status(), 200, 'fixture document must load successfully');
  await settled(page);
}

async function marker(page) {
  return page.evaluate(() => document.documentElement.dataset.agentUiReady ?? null);
}

function deadline(promise, label) {
  let timer;
  return Promise.race([
    promise,
    new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(label + ' timed out')), timeout);
    }),
  ]).finally(() => clearTimeout(timer));
}

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.BROWSER_EXECUTABLE || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    headless: true,
    args: ['--disable-gpu'],
  });
  const groups = [];

  async function group(name, run, expectedPageErrors = []) {
    const context = await browser.newContext({
      viewport: { width: 390, height: 844 },
      serviceWorkers: 'block',
    });
    const pageErrors = [];
    const mutatingRequests = [];
    try {
      const page = await context.newPage();
      page.setDefaultTimeout(timeout);
      page.setDefaultNavigationTimeout(timeout);
      page.on('pageerror', error => pageErrors.push(error.message));
      page.on('request', request => {
        if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
          mutatingRequests.push({ method: request.method(), url: request.url() });
        }
      });
      const details = await run(page);
      assert.deepEqual(mutatingRequests, [], name + ' must leave fixture data untouched');
      assert.deepEqual(pageErrors, expectedPageErrors, name + ' unexpected/missing page errors');
      groups.push({ name, ...details, pageErrors });
      console.log('PASS ' + name);
    } catch (error) {
      console.error(JSON.stringify({ failedGroup: name, pageErrors, mutatingRequests }));
      throw error;
    } finally {
      // Closing the context also closes its page and every in-flight read.
      await context.close();
    }
  }

  try {
    await group('blank-200-html-no-ready', async page => {
      let intercepted = 0;
      await page.route(documentUrl, async route => {
        intercepted++;
        await route.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html><html><head></head><body></body></html>' });
      });
      await navigate(page);
      assert.equal(intercepted, 1);
      assert.equal(await marker(page), null);
      await pollReadiness(page, false);
      return { ready: false, status: 200 };
    });

    await group('app-js-http-404-no-ready', async page => {
      let intercepted = 0;
      await page.route(appUrl, async route => {
        intercepted++;
        await route.fulfill({ status: 404, contentType: 'text/plain', body: 'fixture: app.js missing' });
      });
      await navigate(page);
      assert.equal(intercepted, 1);
      assert.equal(await marker(page), null);
      await pollReadiness(page, false);
      return { ready: false, appStatus: 404 };
    });

    await group('app-js-startup-throws-no-ready', async page => {
      let intercepted = 0;
      await page.route(appUrl, async route => {
        intercepted++;
        await route.fulfill({ status: 200, contentType: 'application/javascript', body: `throw new Error(${JSON.stringify(startupError)});` });
      });
      await navigate(page);
      assert.equal(intercepted, 1);
      assert.equal(await marker(page), null);
      await pollReadiness(page, false);
      return { ready: false };
    }, [startupError]);

    await group('css-missing-no-ready-despite-marker', async page => {
      let intercepted = 0;
      await page.route(cssUrl, async route => {
        intercepted++;
        await route.abort('failed');
      });
      await navigate(page);
      assert.equal(intercepted, 1);
      assert.equal(await marker(page), '1', 'real app.js must finish initial setup');
      assert.equal(await page.evaluate(() => document.documentElement.dataset.agentNavigationId), navigationId);
      const display = await page.locator('.app-shell').evaluate(node => getComputedStyle(node).display);
      assert.notEqual(display, 'flex', 'missing CSS must fail the computed-style condition');
      await pollReadiness(page, false);
      return { ready: false, marker: '1', shellDisplay: display };
    });

    await group('delayed-app-js-false-then-ready', async page => {
      let release, requested, routeFinished;
      let intercepted = 0;
      const gate = new Promise(resolve => { release = resolve; });
      const held = new Promise(resolve => { requested = resolve; });
      await page.route(appUrl, route => {
        intercepted++;
        routeFinished = gate.then(() => route.continue());
        requested();
        return routeFinished;
      });
      try {
        // DOMContentLoaded waits for this deferred script, so navigate only to commit.
        const response = await page.goto(pageUrl, { waitUntil: 'commit' });
        assert(response);
        assert.equal(response.status(), 200);
        await deadline(held, 'held app.js request');
        const dom = await page.waitForFunction(() => {
          const shell = document.querySelector('.app-shell');
          return !!document.querySelector('#chat-form') && !!document.querySelector('#message-input') && !!shell && getComputedStyle(shell).display === 'flex';
        });
        await dom.dispose();
        assert.equal(await marker(page), null, 'ready marker must be absent while app.js is held');
        await pollReadiness(page, false);
        release();
        await routeFinished;
        await settled(page);
        assert.equal(intercepted, 1);
        assert.equal(await marker(page), '1');
        await pollReadiness(page, true);
        return { beforeRelease: false, afterRelease: true };
      } finally {
        // Also release on assertion/navigation failure so context cleanup cannot hang.
        release();
        if (routeFinished) await routeFinished;
      }
    });

    await group('normal-page-ready-with-chat-and-composer-rects', async page => {
      await navigate(page);
      await pollReadiness(page, true);
      assert.equal(await marker(page), '1');
      assert.equal(await page.evaluate(() => document.documentElement.dataset.agentNavigationId), navigationId);
      assert.equal(new URL(page.url()).hash, '', 'token and navigation fragment must be consumed');
      const rects = await page.evaluate(() => {
        const rect = selector => {
          const { x, y, width, height } = document.querySelector(selector).getBoundingClientRect();
          return { x, y, width, height };
        };
        return { chat: rect('#conversation'), chatView: rect('#view-chat'), composer: rect('#chat-form') };
      });
      for (const [name, rect] of Object.entries(rects)) {
        assert(rect.width > 0 && rect.height > 0, name + ' must have nonzero layout bounds');
      }
      return { ready: true, navigationId, fragmentConsumed: true, rects };
    });

    console.log(JSON.stringify({ ok: true, scope: 'JavaScript readiness probe conditions only', origin: base.origin, groups }));
  } catch (error) {
    console.error(JSON.stringify({ ok: false, passedGroups: groups.map(group => group.name) }));
    throw error;
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});

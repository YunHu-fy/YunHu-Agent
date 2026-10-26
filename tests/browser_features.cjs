'use strict';

// Run against a fresh python -m tests.browser_fixture process. No replacement server is started.
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const { chromium } = require('../.test-tools/node_modules/playwright');

const base = process.env.AGENT_BROWSER_URL || 'http://127.0.0.1:8697';
const browserPath = process.env.BROWSER_EXECUTABLE || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const token = 'browser-fixture-only';
const artifacts = path.join(__dirname, '../artifacts');
fs.mkdirSync(artifacts, { recursive: true });
const releaseVersion = /__version__\s*=\s*"([^"]+)"/.exec(fs.readFileSync(path.join(__dirname, '../android_agent/__init__.py'), 'utf8'))[1];

(async () => {
  const browser = await chromium.launch({ executablePath: browserPath, headless: true, args: ['--disable-gpu'] });
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, permissions: ['clipboard-read', 'clipboard-write'] });
  const page = await context.newPage();
  const errors = [];
  const modelPuts = [];
  const chats = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if (request.url() === base + '/api/models' && request.method() === 'PUT') {
      const body = request.postDataJSON();
      modelPuts.push({ active_model_id: body.active_model_id, profiles: body.profiles.map(profile => { const { id, model, base_url, context_window, max_output_tokens, reasoning_enabled, reasoning_level, supports_images, clear_api_key } = profile;return { id, model, base_url, context_window, max_output_tokens, reasoning_enabled, reasoning_level, supports_images, clear_api_key, key_present: Object.hasOwn(profile, 'api_key') }; }) });
    }
    if (request.url() === base + '/api/chat' && request.method() === 'POST') chats.push(request.postDataJSON());
  });
  page.setDefaultTimeout(15000);
  try {
    await page.goto(base + '/#token=' + token);
    await page.waitForFunction(() => document.getElementById('service-label').textContent === '服务运行中');
    if (await page.locator('#disclaimer-modal').evaluate(node => node.open)) {
      await page.locator('#accept-disclaimer').check();
      await page.locator('#confirm-disclaimer').click();
      await page.waitForFunction(() => !document.getElementById('disclaimer-modal').open);
    }

    const mobileHeader = await page.evaluate(() => {
      const strokes = [...document.querySelectorAll('.sidebar-strokes i')].map(node => node.getBoundingClientRect().width);
      const trigger = document.querySelector('#open-drawer').getBoundingClientRect();
      return { strokes, trigger: { width: trigger.width, height: trigger.height }, titleHidden: document.querySelector('#page-title').classList.contains('sr-only'), statusHidden: document.querySelector('#service-label').classList.contains('sr-only') };
    });
    assert.equal(mobileHeader.strokes.length, 2);
    assert(mobileHeader.strokes[0] > mobileHeader.strokes[1] && mobileHeader.strokes[1] > 0, 'sidebar trigger shows a longer upper stroke');
    assert(mobileHeader.trigger.width >= 44 && mobileHeader.trigger.height >= 44, 'sidebar trigger remains easy to tap');
    assert(mobileHeader.titleHidden && mobileHeader.statusHidden, 'conversation title and service state are available to assistive technology');
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), 390);
    const clippedText = await page.locator('.empty-state>p, .empty-eyebrow, .suggestion small').evaluateAll(nodes => nodes.filter(node => node.scrollWidth > node.clientWidth || node.scrollHeight > node.clientHeight).map(node => node.textContent));
    assert.deepEqual(clippedText, [], 'mobile subtitles and tags must not clip');
    await page.screenshot({ path: path.join(artifacts, `features-mobile-chat-v${releaseVersion}.png`) });

    const model = page.locator('#active-model');
    const reasoning = page.locator('#reasoning-level');
    assert.equal(await model.inputValue(), 'fixture-standard');
    assert.equal(await reasoning.inputValue(), 'medium');
    await reasoning.selectOption('high');
    await model.selectOption('fixture-vision');
    await page.waitForFunction(() => document.getElementById('active-model').value === 'fixture-vision' && !document.getElementById('active-model').disabled);
    assert.equal(await reasoning.inputValue(), 'low');
    await reasoning.selectOption('high');
    await model.selectOption('fixture-standard');
    await page.waitForFunction(() => document.getElementById('active-model').value === 'fixture-standard' && !document.getElementById('active-model').disabled);
    assert.equal(await reasoning.inputValue(), 'high');
    assert(modelPuts.length >= 2);
    assert(modelPuts.every(put => put.profiles.every(profile => !profile.key_present && profile.clear_api_key !== true)), 'selector PUT must omit all credentials');

    await model.selectOption('fixture-vision');
    await page.waitForFunction(() => document.getElementById('active-model').value === 'fixture-vision' && !document.getElementById('active-model').disabled);
    const toggle = page.locator('#attachment-menu-toggle');
    await toggle.click();
    const popup = await page.evaluate(() => {
      const menu = document.getElementById('attachment-menu').getBoundingClientRect();
      const composer = document.querySelector('.composer').getBoundingClientRect();
      const toggle = document.getElementById('attachment-menu-toggle').getBoundingClientRect();
      return { menu: { x: menu.x, y: menu.y, bottom: menu.bottom, width: menu.width }, composer: { top: composer.top, left: composer.left, right: composer.right }, toggle: { left: toggle.left, right: toggle.right }, visible: getComputedStyle(document.getElementById('attachment-menu')).display !== 'none' };
    });
    assert(popup.visible && popup.menu.bottom <= popup.composer.top, 'attachment popup must sit above composer');
    assert(popup.menu.x >= popup.composer.left && popup.menu.x < popup.composer.right, 'attachment popup must stay within composer');
    await page.screenshot({ path: path.join(artifacts, `features-mobile-popup-v${releaseVersion}.png`) });
    await page.locator('#attach-image').click();
    await page.locator('#image-attachment-input').setInputFiles({ name: 'fixture.png', mimeType: 'image/png', buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aP9sAAAAASUVORK5CYII=', 'base64') });
    await page.locator('.attachment-chip').waitFor();
    await page.locator('#message-input').fill('请查看附件');
    const response = page.waitForResponse(res => res.url() === base + '/api/chat' && res.request().method() === 'POST');
    await page.locator('#send-button').click();
    const chatResponse = await response;
    assert.equal(chatResponse.status(), 202, await chatResponse.text());
    const chat = chats.at(-1);
    assert.equal(chat.model_profile_id, 'fixture-vision');
    assert.equal(chat.reasoning_level, 'high');
    assert.equal(chat.attachments.length, 1);
    assert.equal(chat.attachments[0].name, 'fixture.png');
    assert.equal(chat.attachments[0].mime_type, 'image/png');
    assert.equal(Buffer.from(chat.attachments[0].data, 'base64').subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
    const task = (await chatResponse.json()).task;
    await page.locator('#conversation .approval-card button').filter({ hasText: '批准本次' }).click();
    await page.waitForFunction(() => document.getElementById('stop-task').classList.contains('hidden'));
    await page.screenshot({ path: path.join(artifacts, `features-mobile-attachment-v${releaseVersion}.png`) });

    await page.locator('#new-chat').click();
    const rejectFiles = async (specs, message, input = 'file-attachment-input') => {
      await page.evaluate(({ specs, input }) => {
        const transfer = new DataTransfer();
        for (const spec of specs) transfer.items.add(new File([new Uint8Array(spec.size || 1)], spec.name, { type: spec.type || 'application/octet-stream' }));
        const element = document.getElementById(input);element.files = transfer.files;element.dispatchEvent(new Event('change', { bubbles: true }));
      }, { specs, input });
      await page.locator('.toast.error').filter({ hasText: message }).last().waitFor();
      assert.equal(await page.locator('.attachment-chip').count(), 0, 'invalid attachment batch must not be read or added');
    };
    await rejectFiles(Array.from({ length: 9 }, (_, i) => ({ name: 'item-' + i + '.txt' })), '最多添加 8');
    await rejectFiles([{ name: 'large.bin', size: 20 * 1024 * 1024 + 1 }], '20 MiB');
    await rejectFiles([{ name: 'part-a.bin', size: 16 * 1024 * 1024 }, { name: 'part-b.bin', size: 15 * 1024 * 1024 }], '30 MiB');
    await rejectFiles([{ name: 'unsupported.svg', type: 'image/svg+xml' }], 'PNG、JPEG、WebP 或 GIF');
    await model.selectOption('fixture-standard');
    await page.waitForFunction(() => !document.getElementById('active-model').disabled);
    await rejectFiles([{ name: 'image.png', type: 'image/png' }], '当前模型不支持图片');
    await page.locator('#file-attachment-input').setInputFiles(Array.from({ length: 8 }, (_, i) => ({ name: 'note-' + i + '.txt', mimeType: 'text/plain', buffer: Buffer.from('fixture ' + i) })));
    await page.waitForFunction(() => document.querySelectorAll('.attachment-chip').length === 8);
    await page.locator('.attachment-chip button').first().click();
    assert.equal(await page.locator('.attachment-chip').count(), 7);
    await page.locator('#new-chat').click();

    await page.locator('#open-drawer').click();
    await page.locator('#open-settings').click();
    await page.locator('#settings-model:not(.hidden)').waitFor();
    assert.equal(await page.locator('.settings-card:not(.hidden)').count(), 1);
    const settingsHeader = await page.evaluate(() => {
      const subtitle = document.querySelector('.settings-heading p');
      const current = document.querySelector('.settings-tabs a[aria-current="page"]');
      const inspect = node => { const box = node.getBoundingClientRect(); return { text: node.textContent, x: box.x, right: box.right, width: box.width, scrollWidth: node.scrollWidth, clientWidth: node.clientWidth, scrollHeight: node.scrollHeight, clientHeight: node.clientHeight }; };
      return { subtitle: inspect(subtitle), location: inspect(current), width: innerWidth };
    });
    for (const item of Object.values(settingsHeader).filter(item => typeof item === 'object')) assert(item.width > 0 && item.x >= 0 && item.right <= 390 && item.scrollWidth <= item.clientWidth && item.scrollHeight <= item.clientHeight, '390px settings subtitle and location/permission tags must remain fully visible');
    await page.waitForFunction(() => !document.querySelector('.toast'));
    await page.screenshot({ path: path.join(artifacts, `features-mobile-settings-v${releaseVersion}.png`) });
    assert.equal(await page.locator('#model-context-window').getAttribute('min'), '256');
    assert.equal(await page.locator('#model-context-window').getAttribute('max'), '2097152');
    assert.equal(await page.locator('#model-max-output-tokens').getAttribute('max'), '1048576');

    const acceleration = await page.evaluate(() => {
      const ids = ['local-cpu-accel', 'local-gpu-accel', 'local-npu-accel', 'local-low-memory'];
      return {
        fieldset: !!document.getElementById('local-acceleration'),
        legend: (document.querySelector('#local-acceleration legend') || {}).textContent || '',
        rows: [...ids.map(id => { const node = document.getElementById(id); return node ? { id, disabled: node.disabled, checked: node.checked } : { id, missing: true, disabled: null, checked: null }; })],
        status: (document.getElementById('local-acceleration-status') || {}).textContent || ''
      };
    });
    assert(acceleration.fieldset, 'model settings must expose the hardware acceleration fieldset');
    assert.equal(acceleration.rows.length, 4);
    for (const row of acceleration.rows) {
      assert(!row.missing, `missing acceleration toggle #${row.id}`);
      assert.equal(row.disabled, true, `third-party profile must not unlock #${row.id}`);
      assert.equal(row.checked, false, `#${row.id} must default to off for a third-party profile`);
    }
    assert(/仅本地模型|local models only/i.test(acceleration.legend), 'acceleration legend must scope itself to local models');
    assert(/第三方模型/.test(acceleration.status), 'acceleration status must explain that a third-party model locks every option');

    const save = async () => {
      const result = page.waitForResponse(res => res.url() === base + '/api/models' && res.request().method() === 'PUT');
      await page.locator('#save-settings').click();
      return result;
    };
    const fixtureModels = await (await context.request.get(base + '/api/models', { headers: { Authorization: 'Bearer ' + token } })).json();
    assert.equal(fixtureModels.profiles[0].base_url, fixtureModels.profiles[1].base_url, 'fixture must exercise shared endpoint profiles');
    assert(fixtureModels.profiles.every(profile => profile.has_api_key), 'fixture shared endpoint/key profiles must both remain keyed after switching');
    await page.locator('#model-name').fill('fixture-model-renamed');
    const beforeInvalid = modelPuts.length;
    await page.locator('#model-context-window').fill('256');
    await page.locator('#model-max-output-tokens').fill('256');
    await page.locator('#save-settings').click();
    await page.getByText('最大输出 tokens 必须', { exact: false }).waitFor();
    assert.equal(modelPuts.length, beforeInvalid, 'invalid profile must not send PUT');
    await page.locator('#model-context-window').fill('256');
    await page.locator('#model-max-output-tokens').fill('1');
    await page.locator('#api-key').fill('');
    const blankSave = save();
    const blankResponse = await blankSave;
    assert.equal(blankResponse.status(), 200, await blankResponse.text());
    assert(modelPuts.at(-1).profiles.every(profile => !profile.key_present), 'blank ordinary save must omit api_key');
    await page.getByText('设置已保存', { exact: true }).waitFor();
    assert.equal(await page.locator('#api-key').inputValue(), '');
    const afterBlank = await (await context.request.get(base + '/api/models', { headers: { Authorization: 'Bearer ' + token } })).json();
    assert(afterBlank.profiles.every(profile => profile.has_api_key), 'blank save must retain saved keys');
    assert.equal(afterBlank.profiles.find(profile => profile.id === 'fixture-standard').model, 'fixture-model-renamed', 'same URL/key with a different model must save without rebinding');

    await page.locator('#model-profiles .model-profile-option').filter({ hasText: 'fixture-vision-model' }).click();
    await page.locator('#clear-api-key').click();
    const dialog = page.locator('dialog[open]').filter({ hasText: '清除当前模型的已保存密钥' });
    await dialog.getByRole('button', { name: '确认继续' }).click();
    await page.locator('#clear-api-key').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#key-status').innerText(), '已标记清除当前模型密钥，保存设置后生效。');
    const clearSave = save();
    const clearResponse = await clearSave;
    assert.equal(clearResponse.status(), 200, await clearResponse.text());
    const lastModelPut = modelPuts.at(-1);
    const clearedProfile = lastModelPut.profiles.find(profile => profile.id === 'fixture-vision');
    assert.equal(clearedProfile.clear_api_key, true);
    assert.equal(clearedProfile.key_present, false);
    await page.getByText('设置已保存', { exact: true }).waitFor();
    assert.equal(await page.locator('#api-key').inputValue(), '');
    const afterClear = await (await context.request.get(base + '/api/models', { headers: { Authorization: 'Bearer ' + token } })).json();
    assert.equal(afterClear.profiles.find(profile => profile.id === 'fixture-vision').has_api_key, false);
    assert.equal(afterClear.profiles.find(profile => profile.id === 'fixture-standard').has_api_key, true);
    assert(!await page.evaluate(() => Object.values(localStorage).concat(Object.values(sessionStorage)).join(' ').includes('fixture-key')));
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ ok: true, checks: ['390px two-stroke accessible header and chat/settings text visibility','modular settings and backend numeric bounds','composer model/reasoning selectors persist per profile','attachment popup above composer','real /api/chat model/reasoning/base64 image payload','attachment count, per-file/total size, MIME and model capability limits','strict context/output validation','CPU/GPU/NPU and Anima low-memory toggles stay off and locked for a third-party profile','same endpoint/key with changed model retains credentials','blank API key omitted','explicit current-profile clear_api_key and draft reset','no API key in browser storage','no page errors'], screenshots: [`features-mobile-chat-v${releaseVersion}.png`,`features-mobile-popup-v${releaseVersion}.png`,`features-mobile-attachment-v${releaseVersion}.png`,`features-mobile-settings-v${releaseVersion}.png`], settingsHeader, task_id: task?.id || null }));
  } catch (error) {
    await page.screenshot({ path: path.join(artifacts, 'features-failure.png') }).catch(() => {});
    console.error('BROWSER_FEATURES_FAILED', error.stack || error);
    process.exitCode = 1;
  } finally {
    await context.close();
    await browser.close();
  }
})();

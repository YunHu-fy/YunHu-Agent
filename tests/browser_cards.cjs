'use strict';

// Uses the existing loopback browser fixture and real Web assets; starts no server.
// Controlled SSE packets exercise intermediate states without executing host commands.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('../.test-tools/node_modules/playwright');

const base = (process.env.AGENT_BROWSER_URL || 'http://127.0.0.1:8697').replace(/[/]$/, '');
const token = 'browser-fixture-only';
const browserPath = process.env.BROWSER_EXECUTABLE || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const artifacts = path.join(__dirname, '../artifacts');
const releaseVersion = /__version__\s*=\s*"([^"]+)"/.exec(fs.readFileSync(path.join(__dirname, '../android_agent/__init__.py'), 'utf8'))[1];
const logPath = path.join(artifacts, `browser-v${releaseVersion}-cards.txt`);
const screenshot = path.join(artifacts, `cards-mobile-v${releaseVersion}.png`);
const log = [];
const checks = [];
const errors = [];
const consoleErrors = [];
fs.mkdirSync(artifacts, { recursive: true });
function record(line) { log.push(line); console.log(line); }
function done(label) { checks.push(label); record('PASS ' + label); }
function frame(event) { return 'id: ' + event.id + '\nevent: ' + event.event + '\ndata: ' + JSON.stringify(event.data) + '\n\n'; }

(async () => {
  const browser = await chromium.launch({ executablePath: browserPath, headless: true, args: ['--disable-gpu'] });
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, serviceWorkers: 'block' });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()); });
  const taskId = 'cards-stream-task';
  const conversationId = 'cards-stream-conversation';
  let status = 'running';
  let nextId = 0;
  let pendingApproval = null;
  let replayNext = false;
  let history = [];
  let packets = [];
  const held = new Set();
  const decisions = [];
  const cursors = [];
  const conversation = () => ({ id: conversationId, title: '执行卡片检查', updated_at: Date.now() / 1000, active_task_id: status === 'succeeded' ? null : taskId });
  const snapshot = () => ({ id: taskId, status, conversation_id: conversationId, message: '检查执行记录和工具结果', channel: 'normal', runtime: 'system', full_access: false, pending_approval: pendingApproval });
  const send = (event, data) => ({ id: ++nextId, event, data });
  async function flush(route, packet) {
    try { await route.fulfill({ status: 200, contentType: 'text/event-stream', body: packet.map(frame).join('') }); }
    catch (error) { if (!page.isClosed() && !/closed|cancel|interrupted/i.test(error.message)) throw error; }
  }
  async function publish(events) {
    history.push(...events);
    const pending = held.values().next().value;
    if (pending) { held.delete(pending); await flush(pending.route, events); pending.release(); }
    else packets.push(events);
    await page.waitForFunction(({ taskId, last }) => { try { return Number(JSON.parse(sessionStorage.getItem("agent-v1-task-" + taskId))?.last) >= last; } catch (_) { return false; } }, { taskId, last: events.at(-1).id });
  }
  const byId = id => page.locator('.command-card[data-command-id="' + id + '"]');
  const details = id => byId(id).locator('.command-details');
  const heading = id => byId(id).locator('.command-heading');
  const assertOpen = async (id, expected) => assert.equal(await details(id).evaluate(node => node.open), expected, id + ' disclosure');
  const settle = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  try {
    record(`Browser execution cards v${releaseVersion}; Edge; 390 x 844; origin ${base}`);
    await context.addInitScript(({ conversationId }) => {
      sessionStorage.setItem('agent-v1-conversation', JSON.stringify(conversationId));
    }, { conversationId });
    await page.route(base + '/favicon.ico', route => route.fulfill({ status: 204 }));
    await page.route(base + '/api/bootstrap', async route => { const response = await route.fetch(); const data = await response.json(); data.conversations = [conversation()]; await route.fulfill({ response, json: data }); });
    await page.route(base + '/api/conversations', route => route.fulfill({ json: { items: [conversation()] } }));
    await page.route(base + '/api/conversations/' + conversationId, route => route.fulfill({ json: {
      conversation: conversation(), messages: [{ id: 'cards-user', role: 'user', content: '检查执行记录和工具结果', task_id: taskId }], tasks: [snapshot()], current_task_id: status === 'succeeded' ? null : taskId,
    } }));
    await page.route(base + '/api/tasks/' + taskId, route => route.fulfill({ json: snapshot() }));
    await page.route(base + '/api/tasks/' + taskId + '/decision', async route => {
      decisions.push(route.request().postDataJSON());
      await route.fulfill({ json: { ok: true } });
    });
    await page.route(base + '/api/tasks/' + taskId + '/events', async route => {
      cursors.push(route.request().headers()['last-event-id'] || null);
      if (replayNext) { replayNext = false; return flush(route, history); }
      if (packets.length) return flush(route, packets.shift());
      if (status === 'succeeded') return flush(route, history);
      await new Promise(release => held.add({ route, release }));
    });
    await page.goto(base + '/#token=' + token);
    await page.waitForFunction(() => document.getElementById('service-label').textContent === '服务运行中');
    if (await page.locator('#disclaimer-modal').evaluate(node => node.open)) {
      await page.locator('#accept-disclaimer').check();
      await page.locator('#confirm-disclaimer').click();
      await page.waitForFunction(() => !document.getElementById('disclaimer-modal').open);
    }

    const exact = "printf '开始检查';\nprintf '%s' '" + '完整命令参数'.repeat(60) + "';\nprintf '警告' >&2";
    const args = { command: exact, channel: 'shizuku', runtime: 'termux', cwd: '/data/data/com.termux/files/home/执行目录', environment: { LANG: 'zh_CN.UTF-8', SPECIAL: '<script>window.__cardsXss=1</script>', LONG_VALUE: '环境变量'.repeat(40) }, timeout_seconds: 60 };
    const first = [send('assistant_delta', { text: '已开始检查设备与工作目录。完整执行记录可逐项展开核对。\n\n' }), send('tool_started', { tool: 'shell.execute', call_id: 'call-shell', arguments: args })];
    await publish(first);
    await heading('call-shell').waitFor();
    await assertOpen('call-shell', false);
    assert.equal(await byId('call-shell').locator('.command-detail-body').isVisible(), false);
    const compact = await heading('call-shell').evaluate(node => ({ fontSize: parseFloat(getComputedStyle(node).fontSize), color: getComputedStyle(node).color, height: node.getBoundingClientRect().height, text: node.innerText }));
    const assistantSize = await page.locator('.message-body').first().evaluate(node => parseFloat(getComputedStyle(node).fontSize));
    assert(compact.fontSize < assistantSize, 'summary must be smaller than assistant prose');
    assert.equal(compact.color, 'rgb(138, 147, 161)', 'summary stays light gray');
    assert(compact.height <= 45 && compact.text.includes('shell.execute') && compact.text.includes('执行中'));
    done('new execution cards show a small light-gray single-line summary, method and status; details start collapsed');

    await heading('call-shell').focus();
    await page.keyboard.press('Enter');
    await assertOpen('call-shell', true);
    assert.equal(await byId('call-shell').locator('.command-exact').innerText(), exact);
    const contextText = await byId('call-shell').locator('.command-context').innerText();
    for (const text of ['Shizuku', 'Termux', args.cwd, 'LANG', args.environment.LONG_VALUE]) assert(contextText.includes(text), text);
    assert.equal(await byId('call-shell').locator('.command-output').count(), 2);
    assert((await byId('call-shell').locator('.command-foot').innerText()).includes('退出码'));
    assert((await byId('call-shell').locator('.command-foot').innerText()).includes('耗时'));
    done('Enter expands full exact command, arguments, channel/runtime/cwd/environment and both output/exit/time fields');

    await publish([send('command_started', { call_id: 'call-shell', command_id: 'native-shell', ...args }), send('command_output', { call_id: 'call-shell', command_id: 'native-shell', stream: 'stdout', seq: 1, text: '第一段输出\n' })]);
    await page.waitForFunction(() => document.querySelector('.command-output.stdout pre')?.textContent.includes('第一段输出'));
    await assertOpen('call-shell', true);
    assert.equal(await page.locator('.command-card').count(), 1, 'native id is an alias of the original tool card');
    assert.equal(await page.evaluate(() => document.activeElement?.classList.contains('command-heading')), true, 'keyboard focus survives SSE render');
    done('same-card native SSE output preserves expansion and keyboard focus without duplicate cards');

    await page.keyboard.press('Space');
    await assertOpen('call-shell', false);
    await publish([send('command_output', { command_id: 'native-shell', stream: 'stderr', seq: 2, text: 'stderr 完整保留\n' })]);
    await page.waitForFunction(() => document.querySelector('.command-output.stderr pre')?.textContent.includes('完整保留'));
    await assertOpen('call-shell', false);
    done('Space collapses the card and later SSE updates preserve the user collapse choice');

    const genericArgs = { path: '/workspace/资料.json', encoding: 'utf-8', flags: ['全部', '隐藏'], nested: { safe: '<img src=x onerror=window.__cardsXss=2>' } };
    await publish([send('tool_started', { tool: 'files.read', call_id: 'call-files', arguments: genericArgs, runtime: 'python3' }), send('tool_result', { tool: 'files.read', call_id: 'call-files', result: { ok: true, content: { title: '完整工具结果', value: '保留结构化内容' }, duration_ms: 37 } })]);
    await heading('call-files').waitFor();
    await assertOpen('call-files', false);
    await heading('call-files').click();
    assert.equal(await byId('call-files').locator('.command-exact').innerText(), JSON.stringify(genericArgs, null, 2));
    assert((await byId('call-files').locator('.generic-tool-output').innerText()).includes('完整工具结果'));
    assert((await byId('call-files').locator('.command-context').innerText()).includes('python3'));
    await assertOpen('call-shell', false);
    done('new generic tool cards remain collapsed independently and preserve nested arguments, result content and custom runtime');

    const longOutput = Array.from({ length: 160 }, (_, i) => '输出第 ' + (i + 1) + ' 行：' + '长内容'.repeat(18)).join('\n');
    await publish([send('command_output', { command_id: 'native-shell', stream: 'stdout', seq: 3, text: longOutput }), send('command_output', { command_id: 'native-shell', stream: 'stdout', seq: 3, text: 'DUPLICATE-MUST-NOT-APPEAR' }), send('command_completed', { command_id: 'native-shell', status: 'succeeded', exit_code: 0, truncated: true }), send('tool_result', { tool: 'shell.execute', call_id: 'call-shell', result: { ok: true, stdout: '第一段输出\n' + longOutput, stderr: 'stderr 完整保留\n', exit_code: 0, duration_ms: 1234, summary: '设备检查完成' } })]);
    await page.waitForFunction(() => document.querySelector('.command-status')?.textContent === '执行完成');
    assert.equal(await page.locator('.command-card').count(), 2);
    await assertOpen('call-shell', false);
    await assertOpen('call-files', true);
    await heading('call-shell').click();
    assert.equal(await byId('call-shell').locator('.command-output.stdout pre').innerText(), '第一段输出\n' + longOutput);
    assert((await byId('call-shell').locator('.command-output.stderr pre').innerText()).includes('stderr 完整保留'));
    assert((await byId('call-shell').locator('.command-foot').innerText()).includes('退出码 · 0'));
    assert((await byId('call-shell').locator('.command-foot').innerText()).includes('1.23 秒'));
    const scroll = await byId('call-shell').locator('.command-output.stdout pre').evaluate(node => ({ height: node.clientHeight, scroll: node.scrollHeight }));
    assert(scroll.scroll > scroll.height && scroll.height <= 280, 'long output stays scrollable inside details');
    assert.equal(await page.evaluate(() => window.__cardsXss), undefined);
    assert.equal(await page.locator('.command-card script,.command-card img').count(), 0);
    done('call/native aliases merge results; full stdout/stderr/exit/duration, deduplicated chunks, truncation note and safe text survive');

    const statusEvents = [
      send('tool_started', { tool: 'shell.execute', call_id: 'call-failed', arguments: { command: 'false' } }),
      send('tool_result', { tool: 'shell.execute', call_id: 'call-failed', result: { ok: false, exit_code: 2, stderr: '执行失败详情', elapsed_ms: 22 } }),
      send('tool_started', { tool: 'files.write', call_id: 'call-denied', arguments: { path: '/workspace/protected.txt', content: '禁止写入' } }),
      send('tool_denied', { tool: 'files.write', call_id: 'call-denied', message: '用户拒绝执行' }),
      send('tool_started', { tool: 'shell.execute', call_id: 'call-cancelled', arguments: { command: 'long-running-command' } }),
      send('tool_result', { tool: 'shell.execute', call_id: 'call-cancelled', result: { ok: false, status: 'cancelled', exit_code: -1, duration_seconds: 2 } }),
      send('tool_started', { tool: 'shell.execute', call_id: 'call-timeout', arguments: { command: 'timeout-command' } }),
      send('tool_result', { tool: 'shell.execute', call_id: 'call-timeout', result: { ok: false, status: 'timed_out', exit_code: -1, duration_ms: 60000 } }),
    ];
    await publish(statusEvents);
    await heading('call-timeout').waitFor();
    for (const id of ['call-failed', 'call-denied', 'call-cancelled', 'call-timeout']) await assertOpen(id, false);
    assert((await heading('call-failed').innerText()).includes('执行失败'));
    assert((await heading('call-cancelled').innerText()).includes('已停止'));
    assert((await heading('call-timeout').innerText()).includes('执行超时'));
    done('failed, denied, cancelled and timed-out execution cards all start collapsed with truthful status');

    const replay = [...history];
    const reset = send('stream_reset', { task: snapshot(), events: replay, last_event_id: nextId + 1 });
    await publish([reset]);
    await settle();
    await assertOpen('call-shell', true);
    await assertOpen('call-files', true);
    await assertOpen('call-failed', false);
    assert.equal(await page.locator('.command-card').count(), 6, 'reset replay creates no duplicate executions');
    done('SSE stream_reset rebuild preserves per-card choices and stable identities');

    const approveCommand = "printf '确认前请核对';\n" + "printf '%s' '" + '安全关键完整命令'.repeat(45) + "'";
    const approvalArgs = { command: approveCommand, channel: 'root', runtime: 'system', cwd: '/data/local/tmp/确认目录', environment: { APPROVAL: '必须可见', VERY_LONG: '完整审批环境'.repeat(25) }, timeout_seconds: 90 };
    await publish([send('tool_started', { tool: 'shell.execute', call_id: 'call-approval', arguments: approvalArgs }), send('approval_required', { approval_id: 'cards-approval', tool: 'shell.execute', arguments: approvalArgs, ...approvalArgs })]);
    const approval = byId('call-approval').locator(':scope > .approval-card');
    await approval.waitFor();
    await assertOpen('call-approval', false);
    assert.equal(await approval.locator('.approval-exact').innerText(), approveCommand);
    for (const value of ['Root', approvalArgs.cwd, approvalArgs.environment.VERY_LONG]) assert((await approval.innerText()).includes(value));
    assert(await approval.getByRole('button', { name: '批准本次', exact: true }).isVisible());
    assert.equal(await approval.locator('.approval-exact').evaluate(node => getComputedStyle(node).maxHeight), 'none');
    await heading('call-approval').click();
    assert.equal(await byId('call-approval').locator('.command-exact').innerText(), approveCommand);
    await heading('call-approval').press('Enter');
    await assertOpen('call-approval', false);
    assert(await approval.isVisible(), 'pending review remains visible when execution details are collapsed');
    done('pending approval is a forced-visible safety exception with untruncated full command, parameters and context before approval');

    const beforeReload = await page.locator('.command-card').count();
    pendingApproval = { approval_id: 'cards-approval', tool: 'shell.execute', arguments: approvalArgs, ...approvalArgs };
    status = 'waiting_approval';replayNext = true;
    await page.evaluate(taskId => sessionStorage.removeItem('agent-v1-task-' + taskId), taskId);
    await page.reload();
    await page.waitForFunction(() => document.querySelectorAll('.command-card').length === 7 && document.querySelector('.command-card > .approval-card'));
    await page.waitForFunction(taskId => Number(JSON.parse(sessionStorage.getItem('agent-v1-task-' + taskId))?.last) > 0, taskId);
    await settle();
    assert.equal(await page.locator('.command-card').count(), beforeReload);
    assert.equal(await page.locator('.command-details[open]').count(), 0);
    const restoredApproval = page.locator('.command-card > .approval-card');
    assert.equal(await restoredApproval.locator('.approval-exact').innerText(), approveCommand);
    done('cold pending-approval snapshot and SSE replay merge to one safe card without hiding command or persisting expansion');
    const restoredApprovalId = await restoredApproval.locator('..').getAttribute('data-command-id');
    await heading(restoredApprovalId).click();
    await assertOpen(restoredApprovalId, true);
    const pendingReplay = [...history];
    await publish([send('stream_reset', { task: snapshot(), events: pendingReplay, last_event_id: nextId + 1 })]);
    await settle();
    await assertOpen('call-approval', true);
    assert.equal(await page.locator('.command-card > .approval-card').count(), 1);
    await heading('call-approval').click();
    done('pending snapshot/native/call aliases preserve the user choice through stream reset while safety details stay visible');
    await page.locator('.command-card > .approval-card').getByRole('button', { name: '批准本次', exact: true }).click();
    pendingApproval = null;status = 'running';
    assert.deepEqual(decisions, [{ approval_id: 'cards-approval', approved: true }]);
    await publish([send('approval_resolved', { approval_id: 'cards-approval', approved: true }), send('command_started', { command_id: 'native-approval', ...approvalArgs }), send('tool_result', { tool: 'shell.execute', call_id: 'call-approval', result: { ok: true, exit_code: 0, stdout: '审批后执行完成', duration_ms: 88 } })]);
    await page.waitForFunction(() => !document.querySelector('.command-card > .approval-card'));
    await assertOpen('call-approval', false);
    await heading('call-approval').click();
    assert((await byId('call-approval').locator('.approval-status').innerText()).includes('已批准'));
    done('approval payload remains exact; resolved review joins collapsed details and the user disclosure choice is retained');

    await publish([send('tool_started', { tool: 'shell.execute', call_id: 'call-ended-approval', arguments: { command: 'ended-before-decision' } }), send('approval_required', { tool: 'shell.execute', approval_id: 'ended-approval', call_id: 'call-ended-approval', arguments: { command: 'ended-before-decision' } }), send('task_cancelled', { message: '审批期间任务停止' })]);
    await page.waitForFunction(() => document.getElementById('stop-task').classList.contains('hidden'));
    await assertOpen('call-ended-approval', false);
    assert((await heading('call-ended-approval').innerText()).includes('已停止'));
    assert.equal(await page.locator('.command-card > .approval-card').count(), 0);
    await heading('call-ended-approval').click();
    assert((await byId('call-ended-approval').locator('.approval-status').innerText()).includes('审批已随任务结束'));
    assert(await byId('call-ended-approval').getByRole('button', { name: '批准本次', exact: true }).isDisabled());
    done('task termination closes the forced-visible approval exception and retains disabled review history inside details');

    status = 'succeeded';
    await page.reload();
    await page.waitForFunction(() => document.querySelectorAll('.command-card').length === 8);
    await page.waitForFunction(() => document.getElementById('stop-task').classList.contains('hidden'));
    await page.reload();
    await page.waitForFunction(() => document.getElementById('service-label').textContent === '服务运行中' && document.querySelectorAll('.command-card').length === 8);
    assert.equal(await page.locator('.command-details[open]').count(), 0, 'reload never persists expansion');
    assert(cursors.some(Boolean), 'SSE reconnection sends a cursor');
    await heading('call-shell').click();
    assert.equal(await byId('call-shell').locator('.command-output.stdout pre').innerText(), '第一段输出\n' + longOutput);
    assert.equal(await byId('call-shell').locator('.command-exact').innerText(), exact);
    await heading('call-shell').click();
    done('refresh rebuild defaults every card to collapsed while retaining full journal details and SSE cursor');

    await page.locator('#open-drawer').click();
    await page.locator('#open-settings').click();
    const options = await page.locator('#view-settings label,#view-settings button,#view-settings select').allTextContents();
    assert(!options.some(value => /折叠|收起执行|展开执行|卡片显示/.test(value)), 'no configurable disclosure setting is added');
    assert.equal(await page.evaluate(() => Object.keys(sessionStorage).some(key => /card.*(?:open|fold|expand)|(?:open|fold|expand).*card/i.test(key))), false);
    await page.locator('#back-to-chat').click();
    assert.equal(await page.locator('.command-details[open]').count(), 0);
    await heading('call-files').focus();
    await page.keyboard.press('Enter');
    await page.keyboard.press('Space');
    await assertOpen('call-files', false);
    done('fixed default has no setting or persistent expansion state; keyboard disclosure remains usable after navigation');

    await page.waitForFunction(() => !document.querySelector('.toast'));
    await page.locator('#conversation').click({ position: { x: 2, y: 2 } });
    await page.locator('#conversation').evaluate(node => { node.scrollTop = 0; });
    await settle();
    const layout = await page.evaluate(() => {
      const boxes = [...document.querySelectorAll('.command-card')].map(node => { const r = node.getBoundingClientRect(); return { x: r.x, right: r.right, width: r.width, height: r.height }; });
      const composer = document.getElementById('chat-form').getBoundingClientRect();
      return { width: innerWidth, scrollWidth: document.documentElement.scrollWidth, boxes, composer: { y: composer.y, bottom: composer.bottom }, open: document.querySelectorAll('.command-details[open]').length };
    });
    assert.equal(layout.width, 390);assert.equal(layout.scrollWidth, 390);assert.equal(layout.open, 0);
    assert(layout.boxes.every(box => box.x >= 0 && box.right <= 390 && box.height <= 45));
    assert(layout.composer.bottom <= 844 && layout.composer.y > 0);
    await page.screenshot({ path: screenshot });
    done('390px clean mobile screenshot: compact cards fit viewport, no horizontal overflow, composer remains visible');
    assert.deepEqual(errors, []);assert.deepEqual(consoleErrors, []);
    record(JSON.stringify({ ok: true, checks: checks.length, labels: checks, pageErrors: errors, consoleErrors, viewport: { width: 390, height: 844 }, screenshot: path.basename(screenshot), fixtureModified: false, safetyChoice: 'Pending approval is rendered outside the collapsed details with full command, arguments and execution context visible.' }));
  } catch (error) {
    record('FAILED AFTER ' + checks.length + ' checks: ' + (error.stack || error));
    record(JSON.stringify({ pageErrors: errors, consoleErrors }));
    await page.screenshot({ path: path.join(artifacts, `cards-failure-v${releaseVersion}.png`) }).catch(() => {});
    process.exitCode = 1;
  } finally {
    // Release every held Playwright route before closing. No timers or background servers remain.
    for (const pending of held) { await pending.route.abort().catch(() => {}); pending.release(); }
    held.clear();
    await context.close();await browser.close();
    fs.writeFileSync(logPath, log.join('\n') + '\n', 'utf8');
  }
})().catch(error => {
  log.push(error.stack || String(error));
  fs.writeFileSync(logPath, log.join('\n') + '\n', 'utf8');
  console.error(error);process.exitCode = 1;
});

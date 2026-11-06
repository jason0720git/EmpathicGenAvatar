// Live browser / real Realtime / real GPU test. No audio, transcript or renderer mocks.
// Resolve Playwright via NODE_PATH, then: node scripts/live_control_e2e.cjs
// This sends a synthetic request to the configured Realtime provider (usage applies).
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const output = path.resolve(process.env.LIVE_CONTROL_OUTPUT || 'artifacts/live-control-e2e');
const isolated = process.argv.includes('--isolated');
const ui = process.argv.includes('--ui');
const sequence = ui ? [
  { label: 'ui-expression', type: 'control' },
  { label: 'ui-gaze-left', type: 'control' },
  { label: 'ui-head', type: 'control' },
  { label: 'ui-reset', type: 'control.reset' },
] : isolated ? [
  { label: 'gaze-left', type: 'control', gaze: { x: -.65, y: 0 } },
  { label: 'gaze-right', type: 'control', gaze: { x: .65, y: 0 } },
  { label: 'head', type: 'control', head: { yaw_deg: 3, pitch_deg: 1.5, roll_deg: 0 } },
  { label: 'happy', type: 'control', expression: 'happy', intensity: .6 },
  { label: 'sad', type: 'control', expression: 'sad', intensity: .5 },
  { label: 'reset', type: 'control.reset' },
] : [
  { label: 'happy-left', type: 'control', expression: 'happy', intensity: .6, head: { yaw_deg: 3, pitch_deg: 1.5, roll_deg: 0 }, gaze: { x: -.65, y: 0 } },
  { label: 'sad-right', type: 'control', expression: 'sad', intensity: .5, head: { yaw_deg: -3, pitch_deg: 0, roll_deg: 0 }, gaze: { x: .65, y: 0 } },
  { label: 'reset', type: 'control.reset' },
];

async function main() {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--autoplay-policy=no-user-gesture-required'] });
  const report = { scenario: ui ? 'production-ui' : isolated ? 'isolated' : 'combined', commands: [], telemetry: [], errors: [], acknowledgements: [], passed: false };
  let page;
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
    page = await context.newPage();
    page.setDefaultTimeout(30000);
    const stage = async name => { console.log(`stage: ${name}`); await page.screenshot({ path: path.join(output, `stage-${name}.png`), timeout: 10000 }); };
    // Instrument the real socket, preserving every normal browser operation.
    await page.addInitScript(() => {
      window.liveControlAudit = { socket: null, acknowledgements: [], commands: [], sentMessages: [], frames: [], packets: { audio: 0, video: 0, end: 0 }, latestReceivedPts: -1 };
      const NativeSocket = window.WebSocket;
      window.WebSocket = class extends NativeSocket {
        send(data) {
          try {
            const parsed = JSON.parse(data);
            if (parsed.type?.startsWith('control')) window.liveControlAudit.sentMessages.push({ ...parsed, sentAt: performance.now(), displayedPtsAtSend: Number(document.querySelector('canvas.rendered-avatar-video')?.dataset.ptsMs ?? -1), receivedPtsAtSend: window.liveControlAudit.latestReceivedPts });
          } catch {}
          super.send(data);
        }
        constructor(...args) {
          super(...args);
          if (!String(args[0]).includes('/avatar-stream-trt10/')) return;
          const audit = window.liveControlAudit;
          audit.socket = this;
          this.addEventListener('message', event => {
            if (typeof event.data === 'string') {
              try { audit.acknowledgements.push({ ...JSON.parse(event.data), receivedAt: performance.now() }); } catch {}
            } else if (event.data instanceof ArrayBuffer && event.data.byteLength >= 5) {
              const view = new DataView(event.data), kind = view.getUint8(0), pts = view.getUint32(1, false);
              if (kind === 1) audit.packets.audio++;
              if (kind === 2) { audit.packets.video++; audit.latestReceivedPts = pts; }
              if (kind === 3) audit.packets.end++;
            }
          });
        }
      };
    });
    page.on('pageerror', error => report.errors.push(error.message));
    page.on('request', request => {
      if (request.method() !== 'POST' || !request.url().includes('/api/telemetry/turn')) return;
      try { report.telemetry.push(request.postDataJSON()); } catch {}
    });
    // Configure this real session for a sufficiently long response. Do not
    // fabricate any server response, transcript, audio or generated frame.
    report.testSessionInstruction = '당신은 한국어로 답하는 AI 아바타입니다. 이번 세션은 움직임 검증입니다. 요청한 풍경을 차분하게 네 문장으로 묘사하세요. 전체 발화는 약 20초 분량, 30초 미만으로 하세요. 검증이나 지시에 대한 설명 없이 풍경 묘사만 말하세요.';
    await page.route('**/api/live/sessions', async route => {
      if (route.request().method() !== 'POST') return route.continue();
      const body = route.request().postDataJSON();
      if (body.mode !== 'realtime') return route.continue();
      await route.continue({ postData: JSON.stringify({ ...body, session_instruction: report.testSessionInstruction }) });
    });
    await page.goto(process.env.TEST_URL || 'http://localhost:4173');
    await stage('loaded');
    await page.getByRole('button', { name: 'Realtime 대화', exact: true }).click();
    await stage('realtime');
    await page.waitForFunction(() => document.querySelector('.idle-avatar-video')?.dataset.painted === 'true', null, { timeout: 30000 });
    await stage('idle-ready');
    await page.getByText('대화 준비됨', { exact: true }).waitFor({ state: 'visible', timeout: 30000 });
    await stage('session-ready');
    await page.evaluate(() => {
      const canvas = document.createElement('canvas'); canvas.width = 512; canvas.height = 640;
      const ctx = canvas.getContext('2d'), audit = window.liveControlAudit;
      audit.timer = setInterval(() => {
        const live = document.querySelector('canvas.rendered-avatar-video.visible');
        const idle = document.querySelector('canvas.idle-avatar-video');
        const source = live || idle;
        if (!source?.width) return;
        ctx.drawImage(source, 0, 0, 512, 640);
        audit.frames.push({ at: performance.now(), live: !!live, displayedPts: live?.dataset.ptsMs === undefined ? null : Number(live.dataset.ptsMs), latestReceivedPts: audit.latestReceivedPts, jpeg: canvas.toDataURL('image/jpeg', .88) });
      }, 40);
    });
    const request = '바닷가에서 천천히 산책하는 모습을 네 문장으로 묘사해 주세요. 파도와 바람, 하늘과 모래, 발걸음, 휴식 순서로 이야기해 주세요.';
    report.request = request;
    await page.locator('.composer textarea').fill(request);
    await page.getByRole('button', { name: '메시지 보내기', exact: true }).click();
    await stage('turn-sent');
    await page.waitForFunction(() => document.querySelector('canvas.rendered-avatar-video.visible')?.dataset.ptsMs !== undefined, null, { timeout: 120000 });
    await page.waitForTimeout(500);
    await stage('playing');
    if (ui) await page.locator('.live-controls > summary').click();
    for (let i = 0; i < sequence.length; i++) {
      const { label, ...target } = sequence[i], command = { ...target, seq: 1001 + i };
      let sent;
      if (ui) {
        if (label === 'ui-expression') {
          const select = page.getByLabel('실시간 표정', { exact: true });
          await select.selectOption((await select.inputValue()) === 'happy' ? 'sad' : 'happy');
        }
        if (label === 'ui-gaze-left') await page.getByLabel('시선 좌우', { exact: true }).press('Home');
        if (label === 'ui-head') await page.getByLabel('머리 좌우', { exact: true }).press('ArrowRight');
        if (label === 'ui-reset') await page.getByRole('button', { name: '자동 동작으로 복귀', exact: true }).click();
        sent = await page.evaluate(label => ({ ...window.liveControlAudit.sentMessages.at(-1), label }), label);
        assert(sent.seq, 'UI did not send live control');
        command.seq = sent.seq;
      } else sent = await page.evaluate(({ command, label }) => {
        const audit = window.liveControlAudit;
        if (audit.socket?.readyState !== WebSocket.OPEN) throw new Error('Speech ended before live control sequence completed');
        const row = { label, ...command, sentAt: performance.now(), displayedPtsAtSend: Number(document.querySelector('canvas.rendered-avatar-video')?.dataset.ptsMs ?? -1), receivedPtsAtSend: audit.latestReceivedPts };
        audit.commands.push(row); audit.socket.send(JSON.stringify(command)); return row;
      }, { command, label });
      report.commands.push(sent);
      console.log(`command: ${label} seq=${sent.seq}`);
      await page.waitForFunction(seq => window.liveControlAudit.acknowledgements.some(a => a.seq === seq && (a.type === 'control.applied' || a.type === 'control.error')), command.seq, { timeout: 15000 });
      const result = await page.evaluate(seq => window.liveControlAudit.acknowledgements.find(a => a.seq === seq && (a.type === 'control.applied' || a.type === 'control.error')), command.seq);
      assert.equal(result.type, 'control.applied', JSON.stringify(result));
      // The change must reach a displayed frame, not just the generation queue.
      await page.waitForFunction(pts => Number(document.querySelector('canvas.rendered-avatar-video.visible')?.dataset.ptsMs ?? -1) >= pts + 800, result.pts_ms, { timeout: 20000 });
      const displayedAt = await page.evaluate(() => performance.now());
      sent.applied = result; sent.observedAfter800msAt = displayedAt;
      sent.receivedToAppliedMs = result.receivedAt - sent.sentAt;
      sent.visible800msObservationMs = displayedAt - sent.sentAt;
      await page.screenshot({ path: path.join(output, `${i}-${label}.png`), fullPage: true });
      await page.waitForTimeout(500);
    }
    await page.waitForFunction(() => !document.querySelector('canvas.rendered-avatar-video'), null, { timeout: 120000 });
    await page.waitForTimeout(500);
    assert.equal(report.errors.length, 0, report.errors.join('\n'));
    const controlErrors = await page.evaluate(() => window.liveControlAudit.acknowledgements.filter(a => a.type === 'control.error'));
    assert.equal(controlErrors.length, 0, JSON.stringify(controlErrors));
    assert(report.telemetry.some(e => e.event === 'playback_ended'), 'Playback did not finish');
    assert(!report.telemetry.some(e => ['jpeg_decode_failed', 'video_pts_gap', 'socket_error'].includes(e.event)), 'Media pipeline error');
    assert(report.telemetry.some(e => e.event === 'stream_timing'), 'Missing early PCM timing');
    assert(report.telemetry.some(e => e.event === 'visual_transition' && e.details?.direction === 'speech_to_idle' && e.details?.phase === 'completed' && e.details.live_tail_completed && !e.details.fallback), 'Tail did not finish while both images were moving');
    report.passed = true;
  } catch (error) {
    report.failure = error.message; process.exitCode = 1;
  } finally {
    if (page) {
      try {
        const audit = await page.evaluate(() => {
          const audit = window.liveControlAudit; clearInterval(audit.timer);
          return { frames: audit.frames, acknowledgements: audit.acknowledgements, packets: audit.packets };
        });
        for (let i = 0; i < audit.frames.length; i++) {
          fs.writeFileSync(path.join(output, `${String(i).padStart(5, '0')}.jpg`), Buffer.from(audit.frames[i].jpeg.split(',')[1], 'base64'));
          delete audit.frames[i].jpeg;
        }
        Object.assign(report, audit);
        for (const command of report.commands) {
          if (!command.applied) continue;
          const first = audit.frames.find(frame => frame.live && frame.displayedPts >= command.applied.pts_ms);
          command.firstAffectedFrameDisplayedMs = first ? first.at-command.sentAt : null;
        }
        report.bodyText = await page.locator('body').innerText();
        await page.screenshot({ path: path.join(output, 'final.png'), fullPage: true });
      } catch (error) { report.captureFailure = error.message; }
    }
    fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
    await browser.close();
  }
  console.log(JSON.stringify({ passed: report.passed, failure: report.failure, commands: report.commands.map(c => ({ label: c.label, generatedPts: c.applied?.pts_ms, receivedToAppliedMs: c.receivedToAppliedMs, firstAffectedFrameDisplayedMs: c.firstAffectedFrameDisplayedMs, visible800msObservationMs: c.visible800msObservationMs })), packets: report.packets, errors: report.errors }));
}
main().catch(error => { console.error(error); process.exitCode = 1; });

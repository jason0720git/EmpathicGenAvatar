// Run with NODE_PATH resolving Playwright. Saves the actual visible idle canvas
// and the production cue telemetry. No stubbed requests or microphone input.
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');

async function sampleCanvas(page, durationMs) {
  return page.evaluate(async (duration) => {
    const canvas = document.createElement('canvas');
    canvas.width = 256;
    canvas.height = 320;
    const ctx = canvas.getContext('2d');
    const frames = [];
    const start = performance.now();
    while (performance.now() - start < duration) {
      const display = document.querySelector('canvas.idle-avatar-video.ready');
      if (display && display.dataset.painted === 'true' && !display.classList.contains('hidden')) {
        ctx.drawImage(display, 0, 0, canvas.width, canvas.height);
        frames.push({
          at: Math.round(performance.now() - start),
          source: display.dataset.source,
          jpeg: canvas.toDataURL('image/jpeg', 0.9).split(',')[1],
        });
      }
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    return frames;
  }, durationMs);
}

async function main() {
  const baseline = process.argv.includes('--baseline');
  const directory = path.resolve(process.env.NOD_UI_OUTPUT || 'artifacts/nod-preview-ui');
  fs.mkdirSync(directory, { recursive: true });
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(30000);
  const report = { baseline, cases: [], telemetry: [], errors: [] };
  page.on('pageerror', error => report.errors.push(error.message));
  page.on('response', response => {
    if (response.url().includes('/telemetry/turn') && !response.ok()) {
      report.errors.push('Telemetry write failed with HTTP ' + response.status());
    }
  });
  page.on('request', request => {
    if (request.method() === 'POST' && request.url().includes('/telemetry')) {
      report.telemetry.push(request.postDataJSON());
    }
  });
  try {
    await page.goto(process.env.TEST_URL || 'http://localhost:4173');
    await page.getByRole('button', { name: 'Realtime 대화', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('canvas.idle-avatar-video.ready')?.dataset.painted === 'true');
    const cases = baseline
      ? [['경청 미리보기', 2, 4000]]
      : [['한 번 끄덕임 재생', 3, 3400], ['두 번 끄덕임 재생', 5, 3400]];
    for (const [label, variant, duration] of cases) {
      const button = page.getByRole('button', { name: label, exact: true });
      await button.click();
      const frames = await sampleCanvas(page, duration);
      const cueIndices = frames.map((frame, i) => frame.source.includes('/idle/' + variant + '/mjpeg') ? i : -1)
        .filter(i => i >= 0);
      const unique = new Set(cueIndices.map(i => frames[i].jpeg)).size;
      const result = { label, variant, samples: frames.length, cueSamples: cueIndices.length, uniqueCueImages: unique };
      const output = path.join(directory, 'variant-' + variant);
      fs.mkdirSync(output, { recursive: true });
      frames.forEach((frame, i) => {
        fs.writeFileSync(path.join(output, String(i).padStart(4, '0') + '.jpg'), Buffer.from(frame.jpeg, 'base64'));
        delete frame.jpeg;
      });
      fs.writeFileSync(path.join(output, 'samples.json'), JSON.stringify(frames, null, 2));
      report.cases.push(result);
      if (unique < 15) throw new Error(label + ' did not produce enough distinct painted images');
      if (baseline) {
        await page.getByRole('button', { name: '경청 미리보기 종료', exact: true }).click();
      } else {
        const status = await page.getByRole('status', { name: '경청 동작 재생 상태' }).innerText();
        result.completed = status.includes('재생 완료') && await button.isEnabled();
        result.returnedToIdle = !frames.at(-1).source.includes('/idle/' + variant + '/mjpeg');
        if (!result.completed || !result.returnedToIdle) throw new Error(label + ' failed to complete: ' + status);
        const events = report.telemetry.filter(event =>
          event.event === 'motion_cue' && event.details.variant === variant && event.details.trigger === 'preview');
        const completed = events.find(event => event.details.phase === 'completed')?.details;
        if (events.map(event => event.details.phase).join(',') !== 'requested,painted,completed' ||
            !completed?.cache_revision || !completed.source_sha256 || completed.painted_frames < 20) {
          throw new Error(label + ' has missing playback telemetry');
        }
        result.paintedFrames = completed.painted_frames;
        result.cacheRevision = completed.cache_revision;
      }
    }
    await page.screenshot({ path: path.join(directory, 'site.png'), fullPage: true });
    if (report.errors.length) throw new Error(report.errors.join(', '));
    report.passed = true;
  } catch (error) {
    report.passed = false;
    report.error = error.message;
    await page.screenshot({ path: path.join(directory, 'failure.png') }).catch(() => {});
    throw error;
  } finally {
    fs.writeFileSync(path.join(directory, 'report.json'), JSON.stringify(report, null, 2));
    await browser.close();
  }
  console.log(JSON.stringify(report.cases, null, 2));
}

main().catch(error => { console.error(error.message); process.exitCode = 1; });

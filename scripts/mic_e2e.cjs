// Real Chrome microphone capture + native speech recognition + live backend/GPU.
// NODE_PATH must resolve Playwright. Run create_mic_fixtures.ps1 first.
// No transcript injection or mocked network responses. Uses synthetic WAV only.
const {chromium}=require('playwright');
const path=require('node:path'), fs=require('node:fs');
const out=path.resolve('artifacts/mic-e2e');
async function run(name){
 const dir=path.join(out,name);fs.mkdirSync(dir,{recursive:true});
 const browser=await chromium.launch({channel:'chrome',headless:true,args:['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream',`--use-file-for-fake-audio-capture=${path.join(out,(name==='auto'?'normal':name)+'.wav')}%noloop`,'--autoplay-policy=no-user-gesture-required']});
 let report={name,stt:[],telemetry:[],requests:[],errors:[]};
 try {
  const context=await browser.newContext({permissions:['microphone'],viewport:{width:1400,height:1000}});
  const page=await context.newPage();
  await page.addInitScript(()=>{
   const C=window.SpeechRecognition||window.webkitSpeechRecognition;
   if(C)window.SpeechRecognition=class extends C{start(...args){for(const k of ['result','error','end'])this.addEventListener(k,e=>console.log('MIC_TEST',JSON.stringify({kind:k,error:e.error,text:Array.from(e.results||[],r=>r[0].transcript).join('')})));super.start(...args)}};
  });
  page.on('console',m=>{if(m.text().startsWith('MIC_TEST '))report.stt.push(JSON.parse(m.text().slice(9)))});
  page.on('pageerror',e=>report.errors.push(e.message));
  page.on('request',r=>{if(r.method()==='POST'){let data;try{data=r.postDataJSON()}catch{};if(r.url().includes('telemetry'))report.telemetry.push(data);if(/\/turns$/.test(r.url()))report.requests.push(data)}});
  await page.goto(process.env.TEST_URL||'http://localhost:4173');
  await page.getByRole('button',{name:'Realtime 대화',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.idle-avatar-video')?.dataset.painted==='true');
  // Record the actual displayed composite, including idle/cue switches.
  await page.evaluate(()=>{
   window.micFrames=[];const c=document.createElement('canvas');c.width=256;c.height=320;const ctx=c.getContext('2d');
   window.micTimer=setInterval(()=>{const live=document.querySelector('canvas.rendered-avatar-video.visible');const idle=document.querySelector('canvas.idle-avatar-video');const source=live||idle;if(!source?.width)return;ctx.drawImage(source,0,0,256,320);window.micFrames.push({t:performance.now(),live:!!live,cue:idle?.dataset.source,jpeg:c.toDataURL('image/jpeg',.8)})},80);
  });
  if(name==='auto') await page.getByRole('button',{name:'Protected auto turn',exact:true}).click();
  else await page.getByRole('button',{name:'음성 입력 시작',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.composer textarea')?.value.includes('주세요'),{},{timeout:30000});
  report.transcript=await page.locator('.composer textarea').inputValue();
  if(name!=='auto') await page.getByRole('button',{name:'음성 입력 종료 및 전송',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('canvas.rendered-avatar-video')?.classList.contains('visible'),{},{timeout:120000});
  if(name==='interrupt'){
   await page.waitForTimeout(2200);
   report.interruptAt=await page.evaluate(()=>performance.now());
   await page.getByRole('button',{name:'음성 입력 시작',exact:true}).click();
   await page.getByRole('button',{name:'음성 입력 종료 및 전송',exact:true}).waitFor();
   await page.waitForTimeout(900);
   report.reenteredListening=true;
   await page.waitForFunction(()=>document.querySelector('.composer textarea')?.value.includes('주세요'),{},{timeout:30000});
   report.followupTranscript=await page.locator('.composer textarea').inputValue();
   await page.getByRole('button',{name:'음성 입력 종료 및 전송',exact:true}).click();
   await page.waitForFunction(()=>document.querySelector('canvas.rendered-avatar-video')?.classList.contains('visible'),{},{timeout:120000});
   await page.waitForFunction(()=>!document.querySelector('canvas.rendered-avatar-video'),{},{timeout:120000});
   await page.waitForTimeout(600);
  }else{
   await page.waitForFunction(()=>!document.querySelector('canvas.rendered-avatar-video'),{},{timeout:120000});
   await page.waitForTimeout(600);
  }
  await page.screenshot({path:path.join(dir,'site.png'),fullPage:true});
  const frames=await page.evaluate(()=>{clearInterval(window.micTimer);return window.micFrames});
  for(let i=0;i<frames.length;i++){fs.writeFileSync(path.join(dir,`${String(i).padStart(5,'0')}.jpg`),Buffer.from(frames[i].jpeg.split(',')[1],'base64'));delete frames[i].jpeg}
  report.frames=frames;report.passed=true;
  if(!report.transcript||report.errors.length)throw new Error('Missing transcript or browser error');
  if(!report.telemetry.some(e=>e.event==='playback_ended'))throw new Error('No completed playback');
  if(report.telemetry.some(e=>['jpeg_decode_failed','video_pts_gap','socket_error'].includes(e.event)))throw new Error('Media error');
  if(name==='short'&&!report.telemetry.some(e=>e.event==='visual_transition'&&e.details?.tail_start_ms>=1000&&e.details.tail_start_ms<=4000))throw new Error('Reply did not meet the <=3 second speech scenario');
  console.log(JSON.stringify({name,passed:true,transcript:report.transcript,frames:frames.length,events:report.telemetry.length}));
 }catch(e){report.passed=false;report.failure=e.message;console.error(name,e.message);process.exitCode=1}
 finally{fs.writeFileSync(path.join(dir,'report.json'),JSON.stringify(report,null,2));await browser.close()}
}
(async()=>{for(const name of process.argv.slice(2).length?process.argv.slice(2):['normal','short','interrupt','auto'])await run(name)})().catch(e=>{console.error(e);process.exitCode=1});

/* Replay recorded A2F coefficients through the actual browser controller. */
const fs=require('node:fs'), path=require('node:path'),{createRequire}=require('node:module');
const root=path.resolve(__dirname,'../..'), out=path.join(root,'artifacts/dynamics-v8/replay');
fs.mkdirSync(out,{recursive:true});fs.writeFileSync(path.join(out,'package.json'),'{"type":"commonjs"}');
const ts=createRequire(path.join(root,'apps/web/package.json'))('typescript');
for(const name of ['naturalMotion','prosody','expression','timeline','types']) {
 let src=fs.readFileSync(path.join(root,'apps/web/src/gaussian',name+'.ts'),'utf8');
 src=src.replace('../../../api/app/emotion_profiles.json',path.join(root,'apps/api/app/emotion_profiles.json').replaceAll('\\','/'));
 fs.writeFileSync(path.join(out,name+'.js'),ts.transpileModule(src,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText);
}
const {NaturalMotion}=require(path.join(out,'naturalMotion.js')),{MotionTimeline}=require(path.join(out,'timeline.js'));
const {manualFrame,manualSpeechFrame}=require(path.join(out,'expression.js')),{DEFAULT_CONTROLS}=require(path.join(out,'types.js'));
const events=fs.readFileSync(path.join(root,'data/gaussian/sessions/209a8f948304482ca63de3d5/events.jsonl'),'utf8').trim().split('\n').map(JSON.parse);
const input=events.filter(e=>e.event==='animation.frame').map(e=>e.details);
if(!input.length) throw Error('No recorded A2F frames');
const timeline=new MotionTimeline();input.forEach(f=>timeline.add(f));const report={};
for(const emotion of ['neutral','happy','sad','angry','fear','surprise','disgust','contempt']) {
 const motion=new NaturalMotion(),frames=[],control={...DEFAULT_CONTROLS,emotion,intensity:1};
 for(let i=0;i<516;i++) {
  const t=i/60, speaking=t>=2&&t<6.6;
  const raw=speaking?timeline.sample(input[0].turn_id,(t-2)*1000):null;
  const f=raw?manualSpeechFrame(raw,control,t):manualFrame(control,t);
  const final=motion.apply(f,t,!!raw,true,1);
  if(Object.values(final.weights).some(v=>!Number.isFinite(v)||v<0||v>1)) throw Error('Invalid coefficient');
  if(raw) for(const k of ['jawOpen','mouthClose','mouthPucker','mouthFunnel','mouthUpperUpLeft']) if(final.weights[k]!==f.weights[k]) throw Error('Articulation overridden: '+k);
  if(i%2===0) frames.push({...final,sequence:i/2,pts_ms:t*1000});
 }
 const range=values=>Number((Math.max(...values)-Math.min(...values)).toFixed(4));
 const speech=frames.filter(f=>f.natural_motion.speaking);
 report[emotion]={accentCount:frames.at(-1).natural_motion.accent_count,headRangeDegrees:Object.fromEntries(['pitch','yaw','roll'].map(k=>[k,range(speech.map(f=>f.head[k]))])),channelRange:Object.fromEntries(['browInnerUp','cheekSquintLeft','mouthSmileLeft','mouthFrownLeft','eyeSquintLeft','jawOpen'].map(k=>[k,range(speech.map(f=>f.weights[k]))])),maxMeasuredResidual:Math.max(...speech.map(f=>f.natural_motion.raw_residual_peak))};
 fs.writeFileSync(path.join(out,emotion+'.json'),JSON.stringify(frames));
}
fs.writeFileSync(path.join(out,'metrics.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));

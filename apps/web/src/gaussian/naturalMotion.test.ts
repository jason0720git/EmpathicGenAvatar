import {expect,it} from 'vitest'
import {NaturalMotion} from './naturalMotion'
const frame={turn_id:'test',pts_ms:0,source:'fixture',weights:{jawOpen:.37,mouthFunnel:.2,mouthSmileLeft:.4,browInnerUp:.2},head:{pitch:0,yaw:0,roll:0},gaze:{x:0,y:0},speech_energy:.8}
it('moves at rest and during speech without altering articulation or accumulating rotations',()=>{
  const motion=new NaturalMotion();let previous=frame.head;const yaw:number[]=[];const blink:number[]=[]
  for(let i=0;i<1800;i++) {
    const result=motion.apply(frame,i/60,i>600)
    expect(result.weights.jawOpen).toBe(.37);expect(result.weights.mouthFunnel).toBe(.2)
    expect(Math.abs(result.head!.yaw-previous.yaw)).toBeLessThanOrEqual(14/60+.0001)
    expect(Math.abs(result.head!.yaw)).toBeLessThan(6)
    yaw.push(result.head!.yaw);blink.push(result.weights.eyeBlinkLeft);previous=result.head!
  }
  expect(Math.max(...yaw.slice(0,600))-Math.min(...yaw.slice(0,600))).toBeGreaterThan(.3)
  expect(Math.max(...yaw.slice(600))-Math.min(...yaw.slice(600))).toBeGreaterThan(3)
  expect(Math.max(...blink)).toBeGreaterThan(.9)
})
it('supports exact static rig inspection when disabled',()=>{expect(new NaturalMotion().apply(frame,4,true,false)).toBe(frame)})

it('varies upper face through a phrase while preserving selected affect and lip sync',()=>{
  const motion=new NaturalMotion();const samples=[]
  for(let i=0;i<600;i++) samples.push(motion.apply({...frame,speech_energy:.5+.5*Math.sin(i/23)},i/60,true))
  for(const key of ['browInnerUp','browOuterUpLeft','cheekSquintLeft','eyeSquintLeft']) {
    const values=samples.map(s=>s.weights[key]);expect(Math.max(...values)-Math.min(...values)).toBeGreaterThan(.03)
  }
  expect(samples.every(s=>s.weights.mouthSmileLeft>0 && s.weights.jawOpen===.37)).toBe(true)
})

it('doubles the natural blink pulse to 380ms without doubling its frequency',()=>{
  const motion = new NaturalMotion(); const closed:number[]=[]
  for(let i=0;i<600;i++) {
    const result=motion.apply(frame,i/100,false)
    if(result.weights.eyeBlinkLeft>0.00001) closed.push(i/100)
  }
  const first=closed.filter(t=>t<3)
  expect(first[first.length-1]-first[0]).toBeCloseTo(.36,2)
  expect(closed.some(t=>t>3&&t<4.9)).toBe(false)
})
it('full-strength emotion has sustained near-maximum peaks through the motion layer',()=>{
  const motion=new NaturalMotion();let peak=0
  for(let i=0;i<1800;i++) peak=Math.max(peak,motion.apply({...frame,weights:{mouthSmileLeft:1}},i/60,true).weights.mouthSmileLeft)
  expect(peak).toBeGreaterThan(.99)
})

it('audio accents change head and face beyond the same idle prior',()=>{
  const quiet=new NaturalMotion(), voiced=new NaturalMotion()
  let difference=0,faceDifference=0,accents=0
  for(let i=0;i<600;i++){
    const input={...frame,behavior:{emotion:'neutral'},speech_energy:i%90<45?.9:0}
    const a=quiet.apply({...input,speech_energy:0},i/60,true)
    const b=voiced.apply(input,i/60,true)
    difference=Math.max(difference,Math.abs(a.head!.pitch-b.head!.pitch))
    faceDifference=Math.max(faceDifference,Math.abs(a.weights.browOuterUpLeft-b.weights.browOuterUpLeft))
    accents=b.natural_motion!.accent_count!
  }
  expect(difference).toBeGreaterThan(1)
  expect(faceDifference).toBeGreaterThan(.08)
  expect(accents).toBeGreaterThan(3)
})
it('retains changing measured upper face without introducing smiles in sadness',()=>{
  const motion=new NaturalMotion();let residual=0
  for(let i=0;i<240;i++){
    const f={...frame,behavior:{emotion:'sad'},raw_weights:{browInnerUp:.15+.1*Math.sin(i/8),mouthSmileLeft:1}}
    const r=motion.apply(f,i/60,true)
    residual=Math.max(residual,r.natural_motion!.raw_residual_peak!)
    expect(r.weights.mouthSmileLeft).toBe(0)
    expect(r.weights.jawOpen).toBe(frame.weights.jawOpen)
    expect(r.weights.mouthFunnel).toBe(frame.weights.mouthFunnel)
    expect(Object.values(r.weights).every(v=>Number.isFinite(v)&&v>=0&&v<=1)).toBe(true)
  }
  expect(residual).toBeGreaterThan(.04)
})
it('releases a wide smile during rounded phonemes without changing the phoneme itself',()=>{
  const result=new NaturalMotion().apply({...frame,weights:{jawOpen:.2,mouthSmileLeft:1,mouthPucker:.9},behavior:{emotion:'happy'}},1,true)
  expect(result.weights.mouthSmileLeft).toBeLessThan(.35)
  expect(result.weights.mouthPucker).toBe(.9)
})

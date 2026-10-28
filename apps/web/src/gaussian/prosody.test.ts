import {expect,it} from 'vitest'
import {CausalProsody} from './prosody'

it('detects audible accents and silence boundaries, without a clock-driven beat',()=>{
  const tracker=new CausalProsody();let accents=0,boundaries=0
  for(let i=0;i<360;i++) {
    const energy=i<60?0:i<110?.85:i<145?0:i<230?.65:0
    const p=tracker.update(energy,true,1/60,'a')
    accents+=Number(p.triggered);boundaries+=Number(p.boundaryTriggered)
    if(i<60)expect(p.accent).toBe(0)
  }
  expect(accents).toBeGreaterThanOrEqual(2)
  expect(boundaries).toBe(2)
})
it('clears stale turn accents and handles invalid input',()=>{
  const tracker=new CausalProsody()
  for(let i=0;i<15;i++)tracker.update(1,true,1/60,'old')
  const p=tracker.update(Number.NaN,true,1/60,'new')
  expect(p.accent).toBe(0);expect(p.energy).toBe(0)
})

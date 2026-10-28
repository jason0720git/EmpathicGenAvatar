import {it,expect} from 'vitest'
import {PerceptionResponsiveness} from './perceptionResponsiveness'
it('ignores startup, normal frames and hidden windows',()=>{
  const guard=new PerceptionResponsiveness()
  expect(guard.sample(0,true)).toBe(false)
  expect(guard.sample(2000,true)).toBe(false)
  for(let t=2016;t<10000;t+=16)expect(guard.sample(t,true)).toBe(false)
  expect(guard.sample(20000,false)).toBe(false)
  expect(guard.sample(20016,true)).toBe(false)
})
it('trips on repeated stalls but not one delayed frame',()=>{
  const guard=new PerceptionResponsiveness()
  guard.sample(0,true);guard.sample(3999,true)
  expect(guard.sample(4300,true)).toBe(false)
  expect(guard.sample(4600,true)).toBe(false)
  expect(guard.sample(4900,true)).toBe(false)
  expect(guard.sample(5200,true)).toBe(true)
})

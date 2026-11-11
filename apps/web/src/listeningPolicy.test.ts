import { expect, it } from 'vitest'
import { ListeningPolicy } from './listeningPolicy'

it('does not nod to silence; acknowledges accumulated speech and short pauses',()=>{
  const p=new ListeningPolicy()
  for(let t=0;t<5;t+=.04)expect(p.observe(t,0)).toBeNull()
  p.reset()
  for(let t=0;t<.8;t+=.04)expect(p.observe(t,.04)).toBeNull()
  const cues=[]
  for(let t=.8;t<1.3;t+=.04)cues.push(p.observe(t,0))
  expect(cues.filter(Boolean)).toEqual([expect.objectContaining({kind:'nod', trigger:'short_pause', gate:'allow'})])
})
it('spaces cues, emits at most one glance, resets stale input',()=>{
  const p=new ListeningPolicy(),events:{time:number;cue:string}[]=[]
  for(let t=0;t<20;t+=.04){const cue=p.observe(t,.04);if(cue)events.push({time:t,cue:cue.kind})}
  expect(events.filter(e=>e.cue!=='glance').slice(0,3).map(e=>e.cue)).toEqual(['double_nod','nod','double_nod'])
  expect(events.filter(e=>e.cue==='glance')).toHaveLength(1)
  for(let i=1;i<events.length;i++)expect(events[i].time-events[i-1].time).toBeGreaterThanOrEqual(2.2)
  expect(p.observe(100,.04)).toBeNull()
  p.reset();expect(p.observe(101,.04)).toBeNull()
})

it('does not queue a busy head or advance the granted alternation',()=>{
  const policy=new ListeningPolicy()
  const events=[]
  for(let t=0;t<9;t+=.04){
    const decision=policy.observe(t,.04,t<2)
    if(decision?.trigger==='speech_continuer')events.push([decision.kind,decision.gate])
  }
  expect(events).toEqual([['double_nod','head_busy'],['double_nod','allow']])
})

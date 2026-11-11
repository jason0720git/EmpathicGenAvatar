import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { GaussianStudio } from './GaussianStudio'
import type { MotionFrame, RendererStats, WireEvent } from './types'

vi.mock('./renderer', async()=>({...await import('./expression'),createLamRenderer:vi.fn()}))

vi.mock('./officialRenderer', () => ({
  async createOfficialRenderer(_host:HTMLElement, _asset:string, getFrame:()=>MotionFrame, ready:(stats:RendererStats)=>void) {
    let displayedFrame=getFrame(), sequence=0
    const timer=setInterval(()=>{displayedFrame=getFrame(); sequence++},50)
    const stats=():RendererStats=>({
      fps:20, frames:sequence+1, renderSequence:sequence, displayedFrame, head:true, splats:100,
      headMotion:{driver:'flame-neck-anchored-v1',applied:displayedFrame.head!,root:[0,0,0],torsoAnchorSplats:20,torsoDriftMm:0},
    })
    ready(stats())
    return {stats,resetView:()=>{},dispose:()=>clearInterval(timer)}
  },
}))

it('records one actual policy grant for a disconnected nod and links the acknowledged preview run', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true)
  const events:WireEvent[]=[]
  const sessions:Record<string,unknown>[]=[]
  const fetch=vi.fn(async (url:string, options?:RequestInit) => {
    const body=options?.body ? JSON.parse(String(options.body)) : {}
    let response:unknown
    if(url.endsWith('/health')) response={openai:{ready:false},a2f:{ready:false},logging:{enabled:true},generator:{ready:false}}
    else if(url.endsWith('/avatars')) response=[{id:'official',kind:'official_live',source:'reference',status:'ready',name:'Official'}]
    else if(url.endsWith('/sessions')) { sessions.push(body); response={id:'preview-run'} }
    else if(url.endsWith('/preview-events')) { events.push(...body.events); response={saved:body.events.length} }
    else throw new Error('Unexpected route '+url)
    return {ok:true,json:async()=>response}
  })
  vi.stubGlobal('fetch',fetch)
  const host=document.createElement('div'), root=createRoot(host)
  const scrollTo=Object.getOwnPropertyDescriptor(HTMLElement.prototype,'scrollTo')
  Object.defineProperty(HTMLElement.prototype,'scrollTo',{configurable:true,value:()=>{}})
  try {
    await act(async()=>root.render(<GaussianStudio/>))
    await act(async()=>vi.advanceTimersByTimeAsync(50))
    await act(async()=>vi.advanceTimersByTimeAsync(250))
    const nod=Array.from(host.querySelectorAll('button')).find(button=>button.textContent==='끄덕이기')!
    expect(nod.disabled).toBe(false)
    expect(sessions).toHaveLength(0)
    await act(async()=>nod.click())
    await act(async()=>vi.advanceTimersByTimeAsync(200))
    await act(async()=>nod.click())
    await act(async()=>vi.advanceTimersByTimeAsync(6500))
    expect(sessions).toEqual([{avatar_id:'official',mode:'preview'}])
    expect(events.filter(e=>e.event==='policy.nod_requested')).toHaveLength(1)
    expect(events.filter(e=>e.event==='policy.nod_gate').map(e=>e.details)).toMatchObject([{cue:'manual',reason:'allow'},{cue:'manual',reason:'head_busy'}])
    expect(events.some(e=>e.event==='motion.sample' && e.tracking_stage==='displayed' && ((e.headMotion as RendererStats['headMotion'])?.applied.pitch ?? 0) > 5)).toBe(true)
    expect(events.filter(e=>e.event==='policy.nod_motion_end')).toHaveLength(1)
    expect(host.querySelector('a[href$="/preview-run/summary"]')).toBeTruthy()
    expect(host.textContent).toContain('미리보기 · 저장 완료')
  } finally {
    await act(async()=>root.unmount())
    if(scrollTo)Object.defineProperty(HTMLElement.prototype,'scrollTo',scrollTo)
    else Reflect.deleteProperty(HTMLElement.prototype,'scrollTo')
    vi.useRealTimers()
    vi.unstubAllGlobals()
  }
})

import {act} from 'react'
import {createRoot} from 'react-dom/client'
import {it,expect,vi} from 'vitest'
import {LiveControls} from './LiveControls'

it('distinguishes received, generated and displayed control, ignores stale acknowledgements',async()=>{
  vi.useFakeTimers();vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true)
  const host=document.createElement('div'),root=createRoot(host)
  const socket=Object.assign(new EventTarget(),{readyState:1,send:vi.fn()})
  let pts=-1
  const ack=(type:string,seq=1,pts_ms=2000)=>socket.dispatchEvent(new MessageEvent('message',{data:JSON.stringify({type,seq,pts_ms})}))
  try{
    await act(async()=>root.render(<LiveControls socket={socket as unknown as WebSocket} displayedPts={()=>pts}/>))
    await act(async()=>{const select=host.querySelector('select')!;select.value='happy';select.dispatchEvent(new Event('change',{bubbles:true}))})
    expect(JSON.parse(socket.send.mock.calls[0][0])).toMatchObject({type:'control',seq:1,expression:'happy'})
    await act(async()=>ack('control.received'))
    expect(host.textContent).toContain('생성 대기')
    await act(async()=>ack('control.applied'))
    expect(host.textContent).toContain('화면 표시 대기')
    await act(async()=>{pts=1960;vi.advanceTimersByTime(100)})
    expect(host.textContent).not.toContain('화면 반영')
    await act(async()=>{pts=2000;vi.advanceTimersByTime(100)})
    expect(host.textContent).toContain('명령 1 화면 반영')
    await act(async()=>ack('control.received',0))
    expect(host.textContent).toContain('명령 1 화면 반영')
    await act(async()=>host.querySelector('button')!.click())
    expect(JSON.parse(socket.send.mock.calls[1][0])).toEqual({type:'control.reset',seq:2})
    await act(async()=>socket.dispatchEvent(new Event('close')))
    expect(host.querySelector('fieldset')!.disabled).toBe(true)
    await act(async()=>root.render(<LiveControls socket={null} displayedPts={()=>pts}/>))
    expect(host.textContent).not.toContain('화면 반영')
  }finally{await act(async()=>root.unmount());vi.useRealTimers();vi.unstubAllGlobals()}
})

it('disables controls when playback feedback expires without a command sequence',async()=>{
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true)
  const host=document.createElement('div'),root=createRoot(host)
  const socket=Object.assign(new EventTarget(),{readyState:1,send:vi.fn()})
  try{
    await act(async()=>root.render(<LiveControls socket={socket as unknown as WebSocket} displayedPts={()=>-1}/>))
    expect(host.querySelector('fieldset')!.disabled).toBe(false)
    await act(async()=>socket.dispatchEvent(new MessageEvent('message',{data:JSON.stringify({type:'control.error',detail:'playback feedback timed out'})})))
    expect(host.querySelector('fieldset')!.disabled).toBe(true)
    expect(host.textContent).toContain('실시간 제어 종료')
  }finally{await act(async()=>root.unmount());vi.unstubAllGlobals()}
})

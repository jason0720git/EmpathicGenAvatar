import {afterEach,expect,it,vi} from 'vitest'
import {createOfficialRenderer} from './officialRenderer'

class Socket {
  static OPEN=1
  static latest:Socket
  readyState=1
  binaryType=''
  sent:string[]=[]
  onopen=()=>{}
  onerror=()=>{}
  onclose=()=>{}
  onmessage=async (event:{data:string|ArrayBuffer})=>{void event}
  constructor(){Socket.latest=this}
  send(data:string){this.sent.push(data)}
  close(){this.readyState=3}
}
function setup(){
  vi.useFakeTimers();vi.stubGlobal('WebSocket',Socket)
  vi.stubGlobal('createImageBitmap',vi.fn().mockResolvedValue({close:vi.fn()}))
  vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({drawImage:vi.fn()} as unknown as CanvasRenderingContext2D)
  return document.createElement('div')
}
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();vi.useRealTimers()})
it('waits for a rendered frame before ready and never queues additional poses while GPU is busy',async()=>{
  const host=setup(),ready=vi.fn(),motion=()=>({turn_id:'spoken-turn',pts_ms:700,weights:{jawOpen:.4}})
  const pending=createOfficialRenderer(host,'',motion,ready,()=>{})
  const ws=Socket.latest;ws.onopen()
  await vi.advanceTimersByTimeAsync(1000)
  expect(ws.sent).toHaveLength(1);expect(ready).not.toHaveBeenCalled()
  expect(JSON.parse(ws.sent[0])).toMatchObject({turn_id:'spoken-turn',pts_ms:700,weights:{jawOpen:.4}})
  await ws.onmessage({data:JSON.stringify({render_ms:12})})
  await ws.onmessage({data:new ArrayBuffer(10)})
  const renderer=await pending
  expect(ready).toHaveBeenCalledOnce();expect(renderer.stats().frames).toBe(1)
  ws.onclose()
  expect(ready.mock.lastCall?.[0].error).toContain('종료')
  expect(host.children).toHaveLength(0)
})
it('aborting a pending renderer rejects initialization and releases its canvas/socket',async()=>{
  const host=setup(),abort=new AbortController()
  const pending=createOfficialRenderer(host,'',()=>({turn_id:'idle',pts_ms:0,weights:{}}),()=>{},()=>{},abort.signal)
  const rejected=expect(pending).rejects.toMatchObject({name:'AbortError'})
  abort.abort();await rejected
  expect(Socket.latest.readyState).toBe(3);expect(host.children).toHaveLength(0)
})
it('reports neck and torso measurements for the matching painted frame only',async()=>{
  const host=setup()
  let pitch=1
  const pending=createOfficialRenderer(host,'',()=>({turn_id:'preview',pts_ms:0,weights:{},head:{pitch,yaw:0,roll:0}}),()=>{},()=>{})
  const ws=Socket.latest;ws.onopen()
  const receipt=(sequence:number)=>JSON.stringify({sequence,render_ms:5,head_driver:'flame-neck-anchored-v1',
    applied_head_deg:{pitch,yaw:0,roll:0},body_root_deg:[0,0,0],torso_anchor_splats:1024,torso_drift_mm:0})
  await ws.onmessage({data:receipt(0)})
  await ws.onmessage({data:new ArrayBuffer(10)})
  const renderer=await pending
  expect(renderer.stats()).toMatchObject({renderSequence:0,displayedFrame:{head:{pitch:1}},headMotion:{applied:{pitch:1},torsoAnchorSplats:1024,torsoDriftMm:0}})
  pitch=8;await vi.advanceTimersByTimeAsync(34)
  await ws.onmessage({data:receipt(1)})
  expect(renderer.stats().headMotion?.applied.pitch).toBe(1)
  await ws.onmessage({data:new ArrayBuffer(10)})
  expect(renderer.stats()).toMatchObject({renderSequence:1,displayedFrame:{head:{pitch:8}},headMotion:{applied:{pitch:8}}})
  await vi.advanceTimersByTimeAsync(34)
  await ws.onmessage({data:receipt(1)})
  await ws.onmessage({data:new ArrayBuffer(10)})
  expect(renderer.stats().headMotion).toBeUndefined()
  expect(renderer.stats().displayedFrame).toBeUndefined()
  renderer.dispose()
})

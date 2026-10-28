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

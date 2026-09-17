import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { beforeEach, afterEach, it, expect, vi } from 'vitest'
import { LiveRoom } from './App'
import { api } from './api'

vi.mock('./api', () => ({api: {
  createSession: vi.fn(), prepareIdle: vi.fn(), endSession: vi.fn(),
  sendTurn: vi.fn(), turnCaption: vi.fn(), telemetry: vi.fn(),
}}))
let clock = 0
let root: Root
let host: HTMLDivElement
let socket: FakeSocket
const draw = vi.fn()
class FakeSocket {
  onopen?: () => void
  onmessage?: (event: {data: ArrayBuffer}) => void
  onclose?: (event: {code:number; wasClean:boolean}) => void
  constructor() { socket = this }
  close() { this.onclose?.({code:1000,wasClean:true}) }
}
class FakeAudio {
  get currentTime() { return clock }
  state = 'running'
  destination = {}
  resume() { return Promise.resolve() }
  close() { this.state = 'closed'; return Promise.resolve() }
  createBuffer(_channels:number, length:number, rate:number) { return {duration:length/rate, getChannelData:()=>new Float32Array(length)} }
  createBufferSource() { return {buffer:null, connect:vi.fn(), start:vi.fn()} }
}
function packet(kind:number, pts:number) {
  const data = new ArrayBuffer(kind === 1 ? 1285 : 6)
  const view = new DataView(data); view.setUint8(0,kind); view.setUint32(1,pts,false)
  socket.onmessage?.({data})
}
beforeEach(async () => {
  vi.useFakeTimers(); vi.clearAllMocks(); clock = 0
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true)
  vi.stubGlobal('WebSocket',FakeSocket); vi.stubGlobal('AudioContext',FakeAudio)
  vi.stubGlobal('createImageBitmap',vi.fn().mockResolvedValue({width:512,height:512,close:vi.fn()}))
  vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({drawImage:draw} as unknown as CanvasRenderingContext2D)
  vi.mocked(api.createSession).mockResolvedValue({id:'s',avatar_id:'a',state:'active',created_at:'',renderer_method:'ditto_realtime_trt10'})
  vi.mocked(api.prepareIdle).mockResolvedValue({status:'ready'})
  vi.mocked(api.endSession).mockResolvedValue(undefined)
  vi.mocked(api.telemetry).mockResolvedValue(undefined)
  vi.mocked(api.sendTurn).mockResolvedValue({turn_id:'t',assistant_text:'처음',visemes:[],renderer:{mode:'remote',status:'streaming',stream_url:'/avatar-stream-trt10/v1/live/t'}})
  vi.mocked(api.turnCaption).mockResolvedValue({text:'전체 답변',done:true})
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  await act(async () => root.render(<LiveRoom avatar={{id:'a',name:'Test',persona:'test',voice:'test',status:'ready',created_at:'',engine:'remote'}} method="ditto_realtime_trt10" sessionInstruction="test" apiOnline onExit={()=>{}} />))
})
afterEach(async () => {
  await act(async () => root.unmount()); host.remove()
  vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals()
})
async function send() {
  const textarea = host.querySelector('.composer textarea')!
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(textarea,'테스트')
    textarea.dispatchEvent(new Event('input',{bubbles:true}))
  })
  await act(async () => host.querySelector('form.composer')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})))
}
it('keeps idle loaded until the first frame is drawn and hands back at actual last PTS', async () => {
  const idle = host.querySelector('.idle-avatar-video')!
  const url = idle.getAttribute('src')
  await act(async () => idle.dispatchEvent(new Event('load')))
  await send()
  await act(async () => { socket.onopen?.(); packet(2,0); packet(1,0); packet(2,400) })
  expect(idle.getAttribute('src')).toBe(url)
  expect(idle.classList.contains('hidden')).toBe(false)
  expect(host.querySelector('canvas')!.classList.contains('visible')).toBe(false)
  clock=.21
  await act(async () => vi.advanceTimersByTimeAsync(250))
  expect(draw).toHaveBeenCalled()
  expect(host.querySelector('canvas')!.classList.contains('visible')).toBe(true)
  await act(async () => packet(3,0))
  clock=.7
  await act(async () => vi.advanceTimersByTimeAsync(100))
  expect(host.querySelector('canvas')).toBeNull()
  expect(idle.classList.contains('hidden')).toBe(false)
  expect(idle.getAttribute('src')).toBe(url)
})
it('retries a transient caption failure and retains the complete spoken transcript', async () => {
  vi.mocked(api.turnCaption).mockRejectedValueOnce(new Error('temporary')).mockResolvedValue({text:'첫 번째 발화.\n두 번째 발화.',done:true})
  await send()
  await act(async () => vi.advanceTimersByTimeAsync(600))
  expect(api.turnCaption).toHaveBeenCalledTimes(2)
  expect(host.querySelector('.message.assistant p')!.textContent).toBe('첫 번째 발화.\n두 번째 발화.')
})

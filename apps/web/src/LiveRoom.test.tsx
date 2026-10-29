import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { beforeEach, afterEach, it, expect, vi } from 'vitest'
import App, { LiveRoom } from './App'
import { api } from './api'

vi.mock('./api', () => ({ApiError:class extends Error{},api: {
  avatars: vi.fn(), createSession: vi.fn(), prepareIdle: vi.fn(), endSession: vi.fn(),
  sendTurn: vi.fn(), turnCaption: vi.fn(), telemetry: vi.fn(), interrupt: vi.fn().mockResolvedValue(undefined),
  liveDiagnostics: vi.fn().mockResolvedValue({events:[]}),
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
  vi.stubGlobal('fetch',vi.fn().mockRejectedValue(new Error('No idle stream in playback unit test')))
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
  const url = idle.getAttribute('data-source')
  await act(async () => idle.dispatchEvent(new Event('load')))
  await send()
  await act(async () => { socket.onopen?.(); packet(2,0); packet(1,0); packet(2,400) })
  expect(idle.getAttribute('data-source')).toBe(url)
  expect(idle.classList.contains('hidden')).toBe(false)
  expect(host.querySelector('canvas.rendered-avatar-video')!.classList.contains('visible')).toBe(false)
  clock=.21
  await act(async () => vi.advanceTimersByTimeAsync(250))
  expect(draw).toHaveBeenCalled()
  expect(host.querySelector('canvas.rendered-avatar-video')!.classList.contains('visible')).toBe(true)
  await act(async () => packet(3,0))
  clock=.7
  await act(async () => vi.advanceTimersByTimeAsync(100))
  expect(host.querySelector('canvas.rendered-avatar-video')).toBeNull()
  expect(idle.classList.contains('hidden')).toBe(false)
  expect(idle.getAttribute('data-source')).toBe(url)
})
it('retries a transient caption failure and retains the complete spoken transcript', async () => {
  vi.mocked(api.turnCaption).mockRejectedValueOnce(new Error('temporary')).mockResolvedValue({text:'첫 번째 발화.\n두 번째 발화.',done:true})
  await send()
  await act(async () => vi.advanceTimersByTimeAsync(600))
  expect(api.turnCaption).toHaveBeenCalledTimes(2)
  expect(host.querySelector('.message.assistant p')!.textContent).toBe('첫 번째 발화.\n두 번째 발화.')
})

it('never paints a late older speech frame after a newer PTS', async () => {
  await send()
  await act(async()=>{socket.onopen?.();packet(2,0);packet(1,0);packet(2,400)})
  clock=.7
  await act(async()=>vi.advanceTimersByTimeAsync(700))
  draw.mockClear()
  await act(async()=>packet(2,200))
  expect(draw).not.toHaveBeenCalled()
})

it('keeps idle live during entry and only permits local face correction', async () => {
  // Dispose RAF owners before replacing the timer implementation for this test.
  await act(async()=>root.render(null))
  vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({canvas:{width:512,height:512},drawImage:draw,save:vi.fn(),restore:vi.fn(),translate:vi.fn(),globalAlpha:1} as unknown as CanvasRenderingContext2D)
  vi.stubGlobal('requestAnimationFrame',(cb:FrameRequestCallback)=>window.setTimeout(()=>cb(performance.now()),16))
  vi.stubGlobal('cancelAnimationFrame',(id:number)=>window.clearTimeout(id))
  vi.stubGlobal('fetch',vi.fn(()=>Promise.resolve({ok:true,body:new ReadableStream<Uint8Array>({start(c){c.enqueue(new TextEncoder().encode('--frame\r\nContent-Length: 1\r\n\r\nx\r\n'))}})})))
  await act(async()=>root.render(<LiveRoom key="entry-test" avatar={{id:'a',name:'Test',persona:'test',voice:'test',status:'ready',created_at:'',engine:'remote'}} method="ditto_realtime_trt10" sessionInstruction="test" apiOnline onExit={()=>{}}/>))
  await act(async()=>vi.advanceTimersByTimeAsync(50))
  const idle=host.querySelector<HTMLCanvasElement>('.idle-avatar-video')!
  expect(idle.dataset.parked).toBe('false')
  await send()
  await act(async()=>{socket.onopen?.();packet(2,0);packet(1,1000);packet(2,1000)})
  clock=.21
  await act(async()=>vi.advanceTimersByTimeAsync(250))
  expect(host.querySelector('.rendered-avatar-video')?.classList.contains('visible')).toBe(true)
  expect(idle.dataset.parked).toBe('false')
  expect(api.telemetry).toHaveBeenCalledWith(expect.objectContaining({event:'visual_transition',details:expect.objectContaining({direction:'idle_to_speech',strategy:'continuous_geometry_v14',full_frame_transform:false,live_idle:true,source_anchor:false,aligned_texture_blend:true})}))
  clock=1.22
  await act(async()=>vi.advanceTimersByTimeAsync(550))
  await act(async()=>vi.advanceTimersByTimeAsync(50))
  expect(idle.dataset.parked).toBe('false')
  expect(api.telemetry).toHaveBeenCalledWith(expect.objectContaining({event:'visual_transition',details:expect.objectContaining({phase:'completed',pts_ms:1000})}))
  await act(async()=>{packet(2,1040);packet(2,2000);packet(3,0)})
  clock=1.25
  await act(async()=>vi.advanceTimersByTimeAsync(80))
  clock=2.3
  await act(async()=>vi.advanceTimersByTimeAsync(650))
  expect(idle.dataset.parked).toBe('false')
  expect(api.telemetry).toHaveBeenCalledWith(expect.objectContaining({event:'visual_transition',details:expect.objectContaining({direction:'speech_to_idle',phase:'completed',live_tail_completed:true,fallback:false,source_anchor:false})}))
  expect(host.querySelector('canvas.rendered-avatar-video')).toBeNull()
})

it('defaults the simplified homepage to WAV + TRT10 and skips caption/API conversation work', async () => {
  vi.mocked(api.avatars).mockResolvedValue([
    {id:'demo-doyun',name:'Doyun',persona:'test',voice:'echo',status:'ready',created_at:'',engine:'remote'},
    {id:'demo-seoyeon',name:'Seoyeon',persona:'test',voice:'marin',status:'ready',created_at:'',engine:'remote'},
  ])
  await act(async()=>root.render(<App/>))
  expect(api.createSession).toHaveBeenLastCalledWith('demo-seoyeon','ditto_realtime_trt10',undefined,'wav_test')
  expect(host.querySelector('.sidebar')).toBeNull()
  expect(host.querySelector('.composer')).toBeNull()
  expect(host.querySelector('.live-layout > .diagnostics-column .turn-diagnostics')).not.toBeNull()
  expect(host.querySelector('.wav-test-panel .turn-diagnostics')).toBeNull()
  expect(host.querySelector('.test-modes .selected')?.textContent).toBe('WAV 테스트')
  expect([...host.querySelectorAll('button')].some(button=>button.textContent==='Auto · 얼굴 표정 테스트')).toBe(true)
  vi.mocked(api.turnCaption).mockClear()
  await act(async()=>host.querySelector<HTMLButtonElement>('.wav-test-panel .primary-button')!.click())
  expect(api.sendTurn).toHaveBeenLastCalledWith('s','고정 WAV 표정 테스트',{emotion:'neutral',intensity:1},expect.any(String),'speech_safe',{use_observation:false,observation_window_ms:3000,observation_speaking:false,observation_end_age_ms:0},undefined)
  expect(api.turnCaption).not.toHaveBeenCalled()
  await act(async()=>{ socket.onopen?.(); packet(3,0) })
  clock=2
  await act(async()=>vi.advanceTimersByTimeAsync(250))
  await act(async()=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(button=>button.textContent==='Auto · 얼굴 표정 테스트')!.click())
  await act(async()=>host.querySelector<HTMLButtonElement>('.wav-test-panel .primary-button')!.click())
  expect(api.sendTurn).toHaveBeenLastCalledWith('s','고정 WAV 표정 테스트',undefined,expect.any(String),'speech_safe',expect.any(Object),undefined)
  await act(async()=>[...host.querySelectorAll<HTMLButtonElement>('.test-modes button')].find(button=>button.textContent==='Realtime 대화')!.click())
  expect(api.createSession).toHaveBeenLastCalledWith('demo-seoyeon','ditto_realtime_trt10',expect.any(String),'realtime')
  expect(host.querySelector('.composer')).not.toBeNull()
})


it('selects listening playback and sends gaze separately from affect', async () => {
  const preview = [...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent==='경청 미리보기')!
  await act(async()=>preview.click())
  expect(host.querySelector('.idle-avatar-video')!.getAttribute('data-source')).toContain('/idle/2/')
  const select=host.querySelector<HTMLSelectElement>('[aria-label="발화 시선"]')!
  await act(async()=>{ select.value='avert_return';select.dispatchEvent(new Event('change',{bubbles:true})) })
  await send()
  expect(api.sendTurn).toHaveBeenLastCalledWith('s','테스트',undefined,expect.any(String),'speech_safe',expect.any(Object),
    {mode:'pupil',pattern:'avert_return',x:.65,y:-.15})
  expect(host.querySelector('.idle-avatar-video')!.getAttribute('data-source')).toContain('/idle/2/')
})


it('uses microphone speech cues while listening and clears them when capture stops', async()=>{
  class Recognition {lang='';continuous=true;interimResults=true;onend?:()=>void;start(){} stop(){this.onend?.()} }
  vi.stubGlobal('SpeechRecognition',Recognition)
  const stopTrack=vi.fn()
  vi.stubGlobal('navigator',{mediaDevices:{getUserMedia:vi.fn().mockResolvedValue({getTracks:()=>[{stop:stopTrack}]})}})
  class MicAudio extends FakeAudio {
    createMediaStreamSource(){return {connect:vi.fn()}}
    createAnalyser(){return {fftSize:256,frequencyBinCount:128,getByteTimeDomainData:(values:Uint8Array)=>values.fill(136)}}
  }
  vi.stubGlobal('AudioContext',MicAudio)
  vi.stubGlobal('fetch',vi.fn().mockImplementation(()=>Promise.resolve({ok:true,body:new ReadableStream()})))
  await act(async()=>root.render(<LiveRoom key="microphone" avatar={{id:'a',name:'Test',persona:'test',voice:'test',status:'ready',created_at:'',engine:'remote'}} method="ditto_realtime_trt10" sessionInstruction="test" apiOnline onExit={()=>{}}/>))
  await act(async()=>host.querySelector<HTMLButtonElement>('[aria-label="음성 입력 시작"]')!.click())
  await act(async()=>vi.advanceTimersByTimeAsync(1900))
  expect(host.querySelector('.idle-avatar-video')!.getAttribute('data-source')).toContain('/idle/3/')
  await act(async()=>host.querySelector<HTMLButtonElement>('[aria-label="음성 입력 종료 및 전송"]')!.click())
  expect(stopTrack).toHaveBeenCalled()
  expect(host.querySelector('.idle-avatar-video')!.getAttribute('data-source')).not.toContain('/idle/3/')
})

it('ignores delayed recognition callbacks from the previous microphone session', async()=>{
  const sessions: Recognition[]=[]
  class Recognition {lang='';continuous=true;interimResults=true;onend?:()=>void;onresult?:(event:unknown)=>void;start(){sessions.push(this)} stop(){} }
  vi.stubGlobal('SpeechRecognition',Recognition)
  vi.stubGlobal('navigator',{mediaDevices:{getUserMedia:vi.fn().mockRejectedValue(new Error('no device'))}})
  await act(async()=>root.render(<LiveRoom key="stale-mic" avatar={{id:'a',name:'Test',persona:'test',voice:'test',status:'ready',created_at:'',engine:'remote'}} method="ditto_realtime_trt10" sessionInstruction="test" apiOnline onExit={()=>{}}/>))
  await act(async()=>host.querySelector<HTMLButtonElement>('[aria-label="음성 입력 시작"]')!.click())
  await act(async()=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent==='Push to talk')!.click())
  await act(async()=>host.querySelector<HTMLButtonElement>('[aria-label="음성 입력 시작"]')!.click())
  await act(async()=>sessions[0].onend?.())
  // Cancelled recognizer must not change the current state or insert text.
  await act(async()=>sessions[0].onresult?.({results:[{0:{transcript:'stale'},isFinal:true}]}))
  expect(host.querySelector<HTMLTextAreaElement>('.composer textarea')!.value).not.toBe('stale')
  expect(api.sendTurn).not.toHaveBeenCalled()
  expect(host.querySelector('[aria-label="음성 입력 종료 및 전송"]')).not.toBeNull()
})

it('keeps the last speech composite visible briefly when interrupted',async()=>{
  await act(async()=>root.render(null))
  vi.stubGlobal('SpeechRecognition',class {start(){} stop(){}})
  vi.stubGlobal('fetch',vi.fn(()=>Promise.resolve({ok:true,body:new ReadableStream({start(c){c.enqueue(new TextEncoder().encode('--frame\r\nContent-Length: 1\r\n\r\nx\r\n'))}})})))
  vi.stubGlobal('requestAnimationFrame',(cb:FrameRequestCallback)=>window.setTimeout(()=>cb(performance.now()),16))
  vi.stubGlobal('cancelAnimationFrame',(id:number)=>window.clearTimeout(id))
  vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({canvas:{width:512,height:512},drawImage:draw,save:vi.fn(),restore:vi.fn(),translate:vi.fn(),globalAlpha:1} as unknown as CanvasRenderingContext2D)
  await act(async()=>root.render(<LiveRoom key="interrupt" avatar={{id:'a',name:'Test',persona:'test',voice:'test',status:'ready',created_at:'',engine:'remote'}} method="ditto_realtime_trt10" sessionInstruction="test" apiOnline onExit={()=>{}}/>))
  await act(async()=>vi.advanceTimersByTimeAsync(50))
  await send()
  await act(async()=>{socket.onopen?.();packet(2,0);packet(1,1000);packet(2,1000)})
  clock=.21
  await act(async()=>vi.advanceTimersByTimeAsync(250))
  await act(async()=>host.querySelector<HTMLButtonElement>('[aria-label="음성 입력 시작"]')!.click())
  expect(api.interrupt).toHaveBeenCalledWith('s')
  expect(host.querySelector('canvas.rendered-avatar-video.visible')).not.toBeNull()
  await act(async()=>vi.advanceTimersByTimeAsync(400))
  expect(host.querySelector('canvas.rendered-avatar-video')).toBeNull()
})

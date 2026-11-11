import { useCallback, useEffect, useRef, useState } from 'react'
import { Activity, ArrowLeft, AudioLines, Box, Check, Download, FileArchive, Headphones, LoaderCircle, MessageSquare, Mic, Move3d, Pause, Play, RotateCcw, Send, SlidersHorizontal, Sparkles, Square, Upload, X } from 'lucide-react'
import { createLamRenderer, manualFrame, manualSpeechFrame } from './renderer'
import { createOfficialRenderer } from './officialRenderer'
import { AudioPlayout, MotionTimeline, PlaybackCompletion } from './timeline'
import { Microphone } from './microphone'
import { DEFAULT_CONTROLS, type Avatar, type Controls, type Health, type MotionFrame, type RendererStats, type WireEvent } from './types'
import './gaussian.css'
import { NaturalMotion } from './naturalMotion'
import { decodeTestWav, pcmBase64 } from './wavTest'
import { PolicyReadout } from './PolicyReadout'
import { PreviewCapture, type PreviewStatus } from './previewCapture'

type Chat = { id: string; role: string; text: string; final: boolean }
type Trace = { at: string; type: string; detail: string }
type Metrics = { fps: number; queued: number; audio: number; animation: number; underruns: number; syncTimeouts: number; pts: number }
const initialMetrics: Metrics = { fps: 0, queued: 0, audio: 0, animation: 0, underruns: 0, syncTimeouts: 0, pts: 0 }
const stateLabels: Record<string, string> = { idle: '대화 준비', ready: '대화 준비', connecting: '연결 중', listening: '듣고 있어요', thinking: '답변 준비 중', responding: '말하고 있어요', speaking: '말하고 있어요', disconnected: '연결 종료', error: '연결 오류' }
const emotions = [{ id: 'neutral', name: '중립' }, { id: 'happy', name: '기쁨' }, { id: 'sad', name: '슬픔' }, { id: 'angry', name: '화남' }, { id: 'fear', name: '두려움' }, { id: 'surprise', name: '놀람' }, { id: 'disgust', name: '혐오' }, { id: 'contempt', name: '경멸' }]

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/gaussian-api${path}`, options)
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try { const body = await response.json() as { detail?: unknown; error?: string }; detail = typeof body.detail === 'string' ? body.detail : body.error ?? JSON.stringify(body.detail ?? body) } catch { /* retain HTTP status */ }
    throw new Error(detail)
  }
  return await response.json() as T
}
const json = (body: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
const errorMessage = (error: unknown) => error instanceof Error ? error.message : String(error)

export function GaussianStudio() {
  const motion = useRef(new NaturalMotion())
  const [naturalEnabled,setNaturalEnabled] = useState(true)
  const naturalEnabledRef = useRef(true)
  const [vitality,setVitality] = useState(1)
  const vitalityRef = useRef(1)
  const [mode, setMode] = useState<'realtime'|'wav'>('realtime')
  const [wavName, setWavName] = useState('')
  const [wavBusy, setWavBusy] = useState(false)
  const [wavDuration, setWavDuration] = useState(0)
  const wavPcm = useRef<Uint8Array | null>(null)
  const wavInput = useRef<HTMLInputElement>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [avatars, setAvatars] = useState<Avatar[]>([])
  const [avatarId, setAvatarId] = useState('')
  const [error, setError] = useState('')
  const [uploading, setUploading] = useState(false)
  const [loading, setLoading] = useState(0)
  const [renderStatus, setRenderStatus] = useState<'empty'|'loading'|'ready'|'error'>('empty')
  const [renderStats, setRenderStats] = useState<RendererStats | null>(null)
  const [session, setSession] = useState('')
  const [state, setState] = useState('disconnected')
  const [mic, setMic] = useState(false)
  const [micLevel, setMicLevel] = useState(0)
  const [text, setText] = useState('')
  const [chats, setChats] = useState<Chat[]>([])
  const [controls, setControls] = useState<Controls>({ ...DEFAULT_CONTROLS })
  const [automatic, setAutomatic] = useState(true)
  const automaticRef = useRef(true)
  const [perception, setPerception] = useState(false)
  const [perceptionText, setPerceptionText] = useState('사용자 얼굴 분석 꺼짐')
  const [voice, setVoice] = useState('marin')
  const [metrics, setMetrics] = useState<Metrics>(initialMetrics)
  const [lastFrame, setLastFrame] = useState<MotionFrame | null>(null)
  const [turnDiagnostics, setTurnDiagnostics] = useState<WireEvent | null>(null)
  const [behaviorPlan, setBehaviorPlan] = useState('대화 시작 후 결정')
  const [events, setEvents] = useState<Trace[]>([])
  const [debugTab, setDebugTab] = useState<'motion'|'events'>('motion')
  const [feedbackOpen, setFeedbackOpen] = useState(false)
  const [feedback, setFeedback] = useState('')
  const [rating, setRating] = useState(4)
  const [feedbackSaved, setFeedbackSaved] = useState(false)
  const host = useRef<HTMLDivElement>(null)
  const photoInput = useRef<HTMLInputElement>(null)
  const zipInput = useRef<HTMLInputElement>(null)
  const ws = useRef<WebSocket | null>(null)
  const sessionRef = useRef('')
  const controlsRef = useRef(controls)
  const timeline = useRef(new MotionTimeline())
  const audio = useRef(new AudioPlayout())
  const microphone = useRef(new Microphone())
  const renderer = useRef<Awaited<ReturnType<typeof createLamRenderer>> | null>(null)
  const latestFrame = useRef<MotionFrame | null>(null)
  const idleFrame = useRef<MotionFrame | null>(null)
  const lastTurn = useRef('')
  const completedTurns = useRef(new PlaybackCompletion())
  const micRef = useRef(false)
  const [previewStatus,setPreviewStatus]=useState<PreviewStatus|null>(null)
  const [preview]=useState(()=>new PreviewCapture(
    async id=>(await request<{id:string}>('/sessions',json({avatar_id:id,mode:'preview'}))).id,
    async (id,events)=>{const {saved}=await request<{saved:number}>(`/sessions/${id}/preview-events`,{...json({events}),keepalive:true});if(saved!==events.length)throw new Error('저장된 샘플 수가 일치하지 않습니다.')},
    setPreviewStatus))
  const runInfo=useRef({asset_id:'',asset_sha256:'',mode:'realtime'})
  const [logSource,setLogSource]=useState<'session'|'preview'>('session')
  const replyTextTurn=useRef(''),receiptTurn=useRef('')
  const mounted = useRef(true)
  const scroll = useRef<HTMLDivElement>(null)
  const avatar = avatars.find(item => item.id === avatarId)
  const isReference=avatar?.kind==='reference_video'
  const isOfficial=avatar?.kind==='official_live'
  const assetBase = isReference ? '' : isOfficial ? 'official-live-306' : avatar?.asset_url ?? (avatar ? `/gaussian-api/avatars/${avatar.id}/asset.zip` : '')
  const currentAssetUrl = assetBase && avatar?.asset_sha256 ? `${assetBase}${assetBase.includes('?') ? '&' : '?'}v=${avatar.asset_sha256}` : assetBase
  const currentAvatarStatus = avatar?.status
  const currentCameraJson = JSON.stringify(avatar?.source_camera ?? avatar?.generation?.manifest?.source_camera ?? null)
  const connected = !!session && !['disconnected', 'error', 'connecting'].includes(state)
  useEffect(()=>{runInfo.current={asset_id:avatarId,asset_sha256:avatar?.asset_sha256??'',mode}
    latestFrame.current=null
    motion.current.resetPolicy()
    return ()=>{preview.finish()}
  },[avatarId,avatar?.asset_sha256,mode,preview])
  const trace = useCallback((type: string, data?: unknown) => {
    const detail = typeof data === 'string' ? data : JSON.stringify(data ?? {})
    setEvents(previous => [{ at: new Date().toLocaleTimeString('ko-KR', { hour12: false }), type, detail: detail.slice(0, 800) }, ...previous].slice(0, 120))
  }, [])
  const send = useCallback((event: WireEvent) => {
    if (ws.current?.readyState === WebSocket.OPEN) { ws.current.send(JSON.stringify(event)); return true }
    return false
  }, [])
  const recordAction=useCallback((event:string,details:Record<string,unknown>)=>{
    const packet={type:'telemetry',event,client_ms:performance.now(),...details}
    if(!send(packet)&&!sessionRef.current && runInfo.current.asset_id) {
      setLogSource('preview')
      preview.start(runInfo.current.asset_id,performance.now(),packet)
    }
    trace(event,details)
  },[send,trace,preview])
  const publishPolicyEvents=useCallback((turnId:string)=>{
    for(const decision of motion.current.drainPolicyEvents()){
      const event='policy.'+decision.event
      const packet={type:'telemetry',event,details:decision.details,client_ms:performance.now(),turn_id:turnId}
      if(!send(packet))preview.add(packet)
      trace(event,decision.details)
    }
  },[send,trace,preview])
  const getFrame = useCallback((): MotionFrame => {
    const clock = audio.current.clock()
    const frame = timeline.current.sample(clock.turn, clock.ms)
    const manual = manualFrame(automaticRef.current ? {...DEFAULT_CONTROLS,intensity:0} : controlsRef.current, performance.now() / 1000)
    const now=performance.now()/1000
    if(clock.speaking && automaticRef.current && naturalEnabledRef.current && clock.turn && clock.turn===replyTextTurn.current && receiptTurn.current!==clock.turn){
      receiptTurn.current=clock.turn;motion.current.requestNod(now,'spoken_receipt')
    }
    // Idle server policy can arrive without any output audio.
    const selected = !automaticRef.current
      ? (frame ? manualSpeechFrame(frame, controlsRef.current, performance.now() / 1000) : manual)
      : frame ?? (idleFrame.current && sessionRef.current ? idleFrame.current : {...manual,source:'auto-preview'})
    const animated = motion.current.apply(selected, now, clock.speaking, naturalEnabledRef.current, vitalityRef.current)
    publishPolicyEvents(clock.turn||selected.turn_id)
    latestFrame.current = animated
    return animated
  }, [publishPolicyEvents])

  const refresh = useCallback(async () => {
    const results = await Promise.allSettled([request<Health>('/health'), request<Avatar[] | { avatars: Avatar[] }>('/avatars')])
    if (!mounted.current) return
    if (results[0].status === 'fulfilled') setHealth(results[0].value)
    else { setHealth(null); trace('backend.unavailable', errorMessage(results[0].reason)) }
    if (results[1].status === 'fulfilled') {
      const value = results[1].value
      const list = Array.isArray(value) ? value : value.avatars
      setAvatars(list)
      setAvatarId(current => current || list.find(item=>item.kind==='official_live' && item.status==='ready')?.id || list.find(item => item.status === 'ready')?.id || '')
    }
  }, [trace])

  useEffect(() => {
    mounted.current = true
    const capture = microphone.current, playout = audio.current
    // Kick off external HTTP subscriptions asynchronously, also across StrictMode mounts.
    const first = setTimeout(() => void refresh(), 0)
    const timer = setInterval(() => void refresh(), 7000)
    return () => {
      mounted.current = false; clearInterval(timer); clearTimeout(first)
      ws.current?.close(); capture.stop(); playout.close()
    }
  }, [refresh])

  useEffect(() => {
    if (!currentAssetUrl || currentAvatarStatus !== 'ready' || !host.current) {
      const reset = setTimeout(() => {setRenderStatus('empty');setRenderStats(null);setLastFrame(null)}, 0)
      return () => clearTimeout(reset)
    }
    let cancelled = false
    const abort = new AbortController()
    let local: Awaited<ReturnType<typeof createLamRenderer>> | null = null
    const showLoading = setTimeout(() => { setRenderStatus('loading'); setLoading(0); setRenderStats(null) }, 0)
    const container = host.current
    // A dedicated mount avoids the SDK moving its static canvas between stale React effects.
    const mount = document.createElement('div'); mount.className = 'gs-render-mount'; container.appendChild(mount)
    const createRenderer=isOfficial?createOfficialRenderer:createLamRenderer
    void createRenderer(mount, currentAssetUrl, getFrame,
      stats => { if (!cancelled) { setRenderStats(stats); setRenderStatus(stats.error?'error':'ready'); if(stats.error)setError(stats.error); trace(stats.error?'renderer.error':'renderer.ready', stats) } },
      progress => { if (!cancelled) setLoading(Math.round(progress * 100)) }, abort.signal, JSON.parse(currentCameraJson) ?? undefined)
      .then(instance => {
        local = instance
        if (cancelled) { instance.dispose(); mount.remove() }
        else renderer.current = instance
      }).catch(reason => { if (!cancelled) { setError(errorMessage(reason)); setRenderStatus('error'); trace('renderer.error', errorMessage(reason)) } mount.remove() })
    return () => { cancelled = true; clearTimeout(showLoading); abort.abort(); if (local) { local.dispose(); mount.remove() }; renderer.current = null }
  }, [currentAssetUrl, currentAvatarStatus, currentCameraJson, getFrame, trace, isOfficial])

  useEffect(() => {
    const timer = setInterval(() => {
      const stats = renderer.current?.stats()
      const clock = audio.current.clock()
      const current: Metrics = { fps: stats?.fps ?? 0, queued: clock.queuedMs, audio: audio.current.chunks,
        animation: timeline.current.count, underruns: audio.current.underruns, syncTimeouts: audio.current.syncTimeouts, pts: clock.ms }
      setMetrics(current); setLastFrame(stats?.displayedFrame??latestFrame.current)
      if (stats) setRenderStats(stats)
      const completedTurn = completedTurns.current.poll(clock)
      if (completedTurn) {
        send({ type: 'telemetry', event: 'playback.complete', turn_id: completedTurn, played_ms: clock.ms })
        trace('playback.complete', { turn_id: completedTurn, played_ms: clock.ms })
        audio.current.finish(completedTurn); timeline.current.cancel(completedTurn)
      }
    }, 250)
    let lastFull=0
    const telemetry = setInterval(() => {
      if(ws.current?.readyState!==WebSocket.OPEN && !preview.active())return
      const clock = audio.current.clock()
      const now=performance.now(),stats=renderer.current?.stats()
      const displayed=stats?.displayedFrame
      const frame=displayed??latestFrame.current
      const packet={type:'telemetry',event:'motion.sample',client_ms:now,renderSequence:stats?.renderSequence,
        tracking_stage:displayed?'displayed':'requested',fps:stats?.fps,frames:stats?.frames,headMotion:stats?.headMotion,
        roundTripMs:stats?.roundTripMs,renderMs:stats?.renderMs,audio_queue_ms:clock.queuedMs,
        turn_id:clock.turn||frame?.turn_id,audio_pts_ms:clock.ms,underruns:audio.current.underruns,sync_timeouts:audio.current.syncTimeouts,
        animation_frames:timeline.current.count,visibility:document.visibilityState,
        control_mode:automaticRef.current?'auto':'manual',settings:{...runInfo.current,mode:preview.active()?'preview':runInfo.current.mode,natural_enabled:naturalEnabledRef.current,vitality:vitalityRef.current,controls:{...controlsRef.current}},
        rendered_frame:frame ? {source:frame.source,turn_id:frame.turn_id,weights:frame.weights,raw_weights:frame.raw_weights,behavior:frame.behavior,
          head:frame.head,gaze:frame.gaze,natural_motion:frame.natural_motion,pts_ms:frame.pts_ms}:null}
      if(!send(packet))preview.add(packet)
      if(stats?.rig && now-lastFull>=1000){send({type:'telemetry',event:'rig.sample',client_ms:now,rig:stats.rig});lastFull=now}
      preview.tick(now)
    }, 100)
    return () => { clearInterval(timer); clearInterval(telemetry) }
  }, [send, trace,preview])
  useEffect(() => { scroll.current?.scrollTo({ top: scroll.current.scrollHeight, behavior: 'smooth' }) }, [chats])

  const onEvent = useCallback((event: WireEvent) => {
    const type = event.type
    if (!['audio.chunk', 'animation.frame', 'transcript.delta'].includes(type)) trace(type, event)
    if (type === 'session.ready') { setState('ready'); send({ type: 'control', ...controlsRef.current, auto: automaticRef.current }) }
    if (type === 'state') {const next=String(event.state??'ready').toLowerCase();setState(next)
      if(['thinking','responding','speaking'].includes(next))motion.current.endListeningTurn()}
    if (type === 'audio.chunk') {
      const turn = String(event.turn_id)
      lastTurn.current = turn
      audio.current.enqueue(turn, Number(event.seq ?? 0), Number(event.pts_ms ?? 0), String(event.pcm_base64), Number(event.sample_rate ?? 24000))
    }
    if (type === 'animation.frame') {
      const frame = event as unknown as MotionFrame
      if (frame.turn_id && frame.turn_id !== 'idle' && frame.turn_id !== 'manual') {
        timeline.current.add(frame); audio.current.markAnimationReady(frame.turn_id)
      } else idleFrame.current = frame
    }
    if (type === 'transcript.delta' || type === 'transcript.final') {
      const role = String(event.role ?? 'assistant'), id = `${event.turn_id ?? 'current'}:${role}`
      const nextText = String(event.text ?? event.delta ?? '')
      if(role==='assistant' && nextText.trim() && event.turn_id)replyTextTurn.current=String(event.turn_id)
      setChats(previous => {
        const existing = previous.find(chat => chat.id === id)
        // The backend emits the complete partial transcript, not token deltas.
        const item: Chat = { id, role, final: type.endsWith('final'), text: nextText }
        return existing ? previous.map(chat => chat.id === id ? item : chat) : [...previous, item]
      })
    }
    if (type === 'cancelled' || type === 'turn.cancelled') {
      const turn = String(event.turn_id ?? lastTurn.current)
      audio.current.finish(turn); timeline.current.cancel(turn)
      completedTurns.current.cancel(turn)
      motion.current.cancelTurn()
    }
    if (type === 'turn.done') completedTurns.current.mark(String(event.turn_id), Number(event.duration_ms ?? 0))
    if (type === 'diagnostics') setTurnDiagnostics(event)
    if (type === 'behavior') {
      const plan = event.plan as Record<string, unknown> | undefined
      if (plan) setBehaviorPlan(`${plan.source === 'llm_tool_call' ? 'LLM Auto' : plan.source === 'manual_expression' ? '수동' : '대기'} · ${plan.emotion ?? 'neutral'} · ${plan.intent ?? 'manual'} · ${Math.round(Number(plan.intensity ?? 0) * 100)}%`)
    }
    if (type === 'error') { setError(String(event.message ?? event.detail ?? event.error ?? '연결 오류')); trace(type, event) }
    if (type === 'perception') {
      const observation = event.observation as Record<string, unknown> | undefined
      setPerceptionText(observation ? `${observation.emotion ?? observation.label ?? '관찰 중'} · 신뢰도 ${Number(observation.confidence ?? 0).toFixed(2)}` : String(event.detail ?? '분석 대기 중'))
    }
  }, [send, trace])

  useEffect(() => {
    const finish = () => preview.finish()
    window.addEventListener('pagehide', finish)
    return () => window.removeEventListener('pagehide', finish)
  }, [preview])
  const connect = async () => {
    if (!avatar || renderStatus !== 'ready') return
    setError(''); setState('connecting'); setLogSource('session')
    preview.finish();motion.current.resetPolicy();receiptTurn.current='';replyTextTurn.current=''
    try {
      await audio.current.prepare()
      audio.current.chunks = 0; audio.current.underruns = 0; audio.current.syncTimeouts = 0
      setMetrics(initialMetrics); setTurnDiagnostics(null); setBehaviorPlan('대화 시작 후 결정')
      timeline.current.clear(); idleFrame.current = null; completedTurns.current.clear()
      const result = await request<{ id: string; ws_url: string }>('/sessions', json({ avatar_id: avatar.id, voice,mode:mode==='wav'?'wav_test':'realtime',
        instructions: '당신은 따뜻하고 차분한 한국어 대화 파트너입니다. 사용자의 마음을 단정하지 말고 맥락에 맞게 짧게 공감하며 두 문장 이내로 답하세요. 감정에 적절한 비언어 행동을 선택하세요.' }))
      sessionRef.current = result.id; setSession(result.id); setChats([])
      const url = new URL(result.ws_url, location.href); url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
      const socket = new WebSocket(url); ws.current = socket
      socket.onmessage = message => { try { onEvent(JSON.parse(String(message.data)) as WireEvent) } catch (reason) { trace('client.event_error', errorMessage(reason)) } }
      socket.onerror = () => { setError('실시간 연결에 실패했습니다. 서비스 상태와 로그를 확인하세요.'); setState('error') }
      socket.onclose = () => { if (ws.current !== socket) return; setState('disconnected'); sessionRef.current = ''; microphone.current.stop(); audio.current.stop(); setMic(false); micRef.current = false }
      socket.onopen = () => { trace('client.connected', { session: result.id }); if (perception) send({ type: 'perception', enabled: true }) }
    } catch (reason) { setState('error'); setError(errorMessage(reason)); trace('client.connect_error', errorMessage(reason)) }
  }
  const disconnect = () => {
    motion.current.resetPolicy()
    microphone.current.stop(); micRef.current = false; setMic(false); setMicLevel(0)
    send({ type: 'interrupt' }); audio.current.stop(); timeline.current.clear(); idleFrame.current = null; completedTurns.current.clear()
    ws.current?.close(); ws.current = null; sessionRef.current = ''; setState('disconnected')
  }
  const interrupt = () => {
    const clock = audio.current.clock()
    motion.current.cancelTurn(); audio.current.stop(); timeline.current.cancel(lastTurn.current); completedTurns.current.clear()
    send({ type: 'interrupt', turn_id: clock.turn, played_ms: Math.max(0, clock.ms) }); setState('ready'); trace('client.interrupt')
  }
  const toggleMic = async () => {
    if (micRef.current) {
      microphone.current.stop(); micRef.current = false; setMic(false); setMicLevel(0)
      motion.current.endListeningTurn();send({ type: 'input.commit' }); trace('client.mic_commit'); return
    }
    setError('')
    try {
      await audio.current.prepare()
      if(['speaking','responding','thinking'].includes(state) || audio.current.clock().queuedMs > 0) interrupt()
      else motion.current.endListeningTurn()
      send({ type: 'input.start' })
      await microphone.current.start((pcm, rms) => { if(automaticRef.current&&naturalEnabledRef.current)motion.current.observeVoice(performance.now()/1000,.02,rms>.015);send({ type: 'input.audio', pcm_base64: pcm }); setMicLevel(rms) })
      micRef.current = true; setMic(true); setState('listening'); trace('client.mic_started')
    } catch (reason) { setError(`마이크를 시작하지 못했습니다: ${errorMessage(reason)}`); trace('client.mic_error', errorMessage(reason)) }
  }
  const sendText = async (value = text) => {
    if (!value.trim() || !connected) return
    await audio.current.prepare()
    if (['speaking', 'responding', 'thinking'].includes(state) || audio.current.clock().queuedMs > 0) interrupt()
    send({ type: 'input.text', text: value.trim() }); setText('')
  }
  const updateControls = (next: Partial<Controls>, log=true) => {
    const value = { ...controlsRef.current, ...next, nod:false }
    controlsRef.current = value; setControls(value); idleFrame.current = null; setAutomatic(false); automaticRef.current = false
    send({ type: 'control', ...value })
    if(log)recordAction('control.override',{controls:value,request:next,auto:false})
  }
  const previewNod = () => {
    const clock=audio.current.clock()
    const granted=motion.current.requestNod(performance.now()/1000,'manual')
    recordAction('control.nod',{cue:'manual',granted})
    publishPolicyEvents(clock.turn || 'preview')
  }
  const upload = async (file: File | undefined, importing: boolean) => {
    if (!file) return
    setUploading(true); setError('')
    try {
      const body = new FormData(); body.append(importing ? 'file' : 'image', file); body.append('name', file.name.replace(/\.[^.]+$/, ''))
      const result = await request<Avatar>(importing ? '/avatars/import' : '/avatars', { method: 'POST', body })
      await refresh(); setAvatarId(result.id); trace(importing ? 'avatar.imported' : 'avatar.generation_started', { id: result.id })
    } catch (reason) { setError(errorMessage(reason)); trace('avatar.error', errorMessage(reason)) }
    finally { setUploading(false); if (photoInput.current) photoInput.current.value = ''; if (zipInput.current) zipInput.current.value = '' }
  }
  const loadWav = async (file?: File, preset: 'reference' | 'ash-en' = 'reference') => {
    setWavBusy(true); setError('')
    try {
      const response = file ? null : await fetch(`/gaussian-api/test-audio?preset=${preset}`)
      if (response && !response.ok) throw new Error('기본 WAV가 없습니다. WAV 파일을 선택해 주세요.')
      const data = file ? await file.arrayBuffer() : await response!.arrayBuffer()
      const pcm = await decodeTestWav(data)
      const name = file?.name ?? (preset === 'ash-en' ? 'Ash · 영어 남성' : 'Ditto 기본 테스트 WAV')
      wavPcm.current = pcm; setWavDuration(pcm.length/48000); setWavName(name)
      trace('wav.loaded', {name, preset:file ? null : preset, duration_ms:pcm.length/48})
    } catch (reason) { setError(errorMessage(reason)) }
    finally {setWavBusy(false); if(wavInput.current) wavInput.current.value=''}
  }
  const replayWav = async () => {
    if (!connected || !wavPcm.current || wavBusy) return
    setError('')
    try {
      await audio.current.prepare()
      interrupt(); updateControls({})
      send({type:'input.start'})
      for(let offset=0;offset<wavPcm.current.length;offset+=24000) {
        if (!send({type:'input.audio',pcm_base64:pcmBase64(wavPcm.current.subarray(offset,offset+24000))})) throw new Error('테스트 연결이 끊겼습니다.')
      }
      send({type:'test.commit',filename:wavName,control:controlsRef.current})
      setState('thinking'); trace('wav.replay', {name:wavName,emotion:controlsRef.current.emotion,intensity:controlsRef.current.intensity})
    } catch (reason) {setError(errorMessage(reason))}
  }
  const logId = logSource==='preview' ? previewStatus?.id : session
  const logLabel = logSource==='preview' && previewStatus ? `미리보기 · ${previewStatus.state==='error' ? '저장 오류' : previewStatus.state==='saved' ? '저장 완료' : '기록 중'} · 저장 ${previewStatus.saved}건${previewStatus.dropped ? ` · 누락 ${previewStatus.dropped}건` : ''}` : connected ? '세션 기록 중' : session ? '세션 로그' : '테스트 대기'
  const saveFeedback = async () => {
    try {
      await request(`/sessions/${logId}/feedback`, json({ rating, comment: feedback, turn_id: logSource==='preview' ? 'preview' : lastTurn.current }))
      setFeedbackSaved(true); setFeedback(''); trace('feedback.saved', { rating })
    } catch (reason) { setError(errorMessage(reason)) }
  }

  return <div className="gaussian-studio">
    <header className="gs-header">
      <a className="gs-brand" href="/" aria-label="영상 스튜디오로 이동"><span className="gs-logo"><Box size={22}/></span><span>Empathic<span className="gs-brand-light"> Avatar</span><small>GAUSSIAN STUDIO</small></span></a>
      <nav><a href="/"><ArrowLeft size={14}/> 영상 스튜디오</a><span className="gs-mode-badge">3DGS · LIVE LAB</span></nav>
      <div className="gs-header-actions"><span className={`gs-dot ${health ? 'ok' : ''}`}/><span>{health ? '로컬 서비스 연결됨' : '로컬 서비스 확인 중'}</span><button className="gs-icon-button" onClick={() => void refresh()} aria-label="서비스 새로고침"><RotateCcw size={17}/></button></div>
    </header>
    <div className="gs-heading"><div><h1>공감 행동 스튜디오</h1><p>실시간 대화와 WAV 테스트에서 아바타의 표정, 시선, 끄덕임을 비교하세요.</p></div><button className="gs-secondary" disabled={!logId} onClick={() => { setFeedbackOpen(true); setFeedbackSaved(false) }}><MessageSquare size={16}/> 피드백 남기기</button></div>
    {error && <div className="gs-error" role="alert"><span>{error}</span><button onClick={() => setError('')} aria-label="오류 닫기"><X size={16}/></button></div>}
    <div className="gs-test-modes" role="group" aria-label="실행 모드">
      <button className={mode==='realtime'?'active':''} disabled={connected} onClick={()=>setMode('realtime')}>실시간 대화</button>
      <button className={mode==='wav'?'active':''} disabled={connected} onClick={()=>{setMode('wav');setPerception(false);updateControls({emotion:'neutral',intensity:.8}, false);if(!wavPcm.current) void loadWav()}}>WAV 감정 테스트</button>
      <span>{connected ? '모드를 바꾸려면 연결을 종료하세요.' : mode==='wav' ? '같은 음성으로 감정 비교 · LLM 호출 없음' : 'LLM 음성 대화'}</span>
    </div>
    <main className="gs-workspace">
      <aside className="gs-panel gs-setup">
        <div className="gs-panel-title"><span className="gs-step">01</span><h2>아바타 준비</h2></div>
        <p className="gs-caption">정면 사진 한 장으로 움직이는 3DGS 얼굴을 생성합니다.</p>
        <input ref={photoInput} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={event => void upload(event.target.files?.[0], false)}/>
        <input ref={zipInput} type="file" accept=".zip" hidden onChange={event => void upload(event.target.files?.[0], true)}/>
        <button className="gs-upload" disabled={uploading || connected} onClick={() => photoInput.current?.click()}>
          {uploading ? <LoaderCircle className="gs-spin" size={25}/> : <Upload size={25}/>}<strong>{uploading ? '아바타 준비 중…' : '사진으로 아바타 만들기'}</strong><span>JPG · PNG · WEBP</span>
        </button>
        <button className="gs-import" disabled={uploading || connected} onClick={() => zipInput.current?.click()}><FileArchive size={16}/> 생성된 LAM ZIP 가져오기</button>
        {!health?.generator.ready && <p className="gs-hint">사진 생성기: {health?.generator.detail ?? '연결 확인 중'}</p>}
        <div className="gs-section-label">아바타 라이브러리 <span>{avatars.length}</span></div>
        <div className="gs-avatar-list">{avatars.map(item => <button key={item.id} className={`gs-avatar-card ${avatarId === item.id ? 'selected' : ''}`} disabled={connected} onClick={() => setAvatarId(item.id)}>
          <div className="gs-avatar-thumb">{item.image_url ? <img src={item.image_url} alt=""/> : <Box size={24}/>}</div>
          <span><strong>{item.name}</strong><small>{item.status === 'preparing' ? '생성 중…' : item.status === 'error' ? '생성 실패' : item.kind === 'official_live' ? '상단 고정 · 실시간 FLAME 구동' : item.source === 'reference' ? '상단 고정 · 공식 모델 동작 재생' : item.source === 'sample' ? 'LAM 공식 샘플' : item.source === 'photo' ? '내 사진 · 3DGS' : '가져온 3DGS'}</small></span>
          {item.status === 'preparing' ? <LoaderCircle size={15} className="gs-spin"/> : avatarId === item.id ? <Check size={16}/> : null}
        </button>)}</div>
        {avatar?.error && <p className="gs-hint gs-warning">{avatar.error}</p>}
        {!avatars.length && <p className="gs-hint">준비된 아바타가 없습니다. 사진 또는 LAM ZIP을 추가하세요.</p>}
        <div className="gs-divider"/>
        <div className="gs-section-label">대화 설정 <Headphones size={15}/></div>
        <label className="gs-field">목소리<select value={voice} onChange={event => setVoice(event.target.value)} disabled={connected || mode==='wav'}><option value="marin">Marin · 차분하고 따뜻하게</option><option value="cedar">Cedar · 자연스럽고 또렷하게</option><option value="coral">Coral · 밝고 부드럽게</option><option value="sage">Sage · 안정적이고 담백하게</option></select></label>
        <label className="gs-checkbox"><input type="checkbox" disabled={mode==='wav'} checked={perception} onChange={event => { setPerception(event.target.checked); send({ type: 'perception', enabled: event.target.checked }) }}/><span>사용자 얼굴 분석<small>켜면 카메라의 정서 추정값을 반응에 반영</small></span></label>
        {perception && <p className="gs-hint">{perceptionText}</p>}
        <div className="gs-service-box"><Service label="Realtime 음성" ready={health?.openai.ready} detail={health?.openai.model}/><Service label="NVIDIA Audio2Face" ready={health?.a2f.ready} detail={health?.a2f.error}/><Service label="백엔드 세션 로그" ready={health?.logging.enabled}/></div>
      </aside>

      <section className="gs-center">
        <div className="gs-stage">
          <div className="gs-stage-top"><span className="gs-stage-tag"><span className={`gs-dot ${renderStatus === 'ready' ? 'ok' : ''}`}/>{isOfficial ? 'OFFICIAL MODEL · LIVE FLAME' : isReference ? 'OFFICIAL MODEL · RECORDED MOTION' : renderStatus === 'ready' ? 'LIVE 3D GAUSSIAN' : '3D GAUSSIAN VIEWER'}</span><span className="gs-stage-fps">{metrics.fps ? `${metrics.fps.toFixed(0)} FPS` : '— FPS'}</span></div>
          <div ref={host} className="gs-render-host" aria-label="3DGS 아바타 렌더러"/>
          {isReference && <video aria-label="GaussianAvatars 공식 모델 동작" src={avatar.video_url} controls autoPlay muted loop playsInline style={{position:'absolute',inset:0,width:'100%',height:'100%',objectFit:'contain',background:'white'}}/>}
          {!isReference && renderStatus !== 'ready' && <div className="gs-stage-empty">{renderStatus === 'loading' ? <><LoaderCircle size={38} className="gs-spin"/><h3>3D 아바타를 불러오는 중</h3><p>실제 Gaussian · 리그 · 표정 데이터 준비</p><div className="gs-loadbar"><i style={{ width: `${loading}%` }}/></div><small>{loading}%</small></> : <><Box size={48}/><h3>{renderStatus === 'error' ? '아바타 렌더링 확인 필요' : avatar?.status === 'preparing' ? '사진으로 3D 아바타를 만들고 있어요' : '아바타를 선택해 주세요'}</h3><p>{renderStatus === 'error' ? '위 오류 메시지와 서비스 로그를 확인하세요.' : '왼쪽에서 사진을 추가하거나 준비된 아바타를 선택하세요.'}</p></>}</div>}
          <div className="gs-stage-bottom"><div><h3>{avatar?.name ?? '나의 3D 아바타'}</h3><p>{isOfficial ? '공식 체크포인트 · A2F → FLAME 실시간 구동' : isReference ? '공식 체크포인트 · 원본 FLAME 동작 재생' : avatar?.source === 'sample' ? 'LAM 공식 샘플 · 내 사진 생성 결과와 구분됩니다' : '리깅된 Gaussian 얼굴 · WebGL 실시간 렌더링'}</p></div><span className="gs-state"><span className={`gs-dot ${connected ? 'ok' : ''}`}/>{stateLabels[state] ?? state}</span></div>
        </div>
        <div className="gs-transport">
          {!connected ? <button className="gs-primary" disabled={isReference || state === 'connecting' || renderStatus !== 'ready' || (mode === 'wav' ? !health?.a2f.ready : !health?.openai.ready)} onClick={() => void connect()}>{state === 'connecting' ? <LoaderCircle size={17} className="gs-spin"/> : <Play size={17}/>} {mode==='wav'?'테스트 연결':'대화 시작'}</button> : <>{mode==='realtime' && <button className={`gs-mic ${mic ? 'recording' : ''}`} onClick={() => void toggleMic()}><Mic size={18}/>{mic ? '말하기 완료 · 전송' : '눌러서 말하기'}{mic && <span className="gs-level"><i style={{ transform: `scaleX(${Math.min(1, micLevel * 10)})` }}/></span>}</button>}<button className="gs-secondary" onClick={interrupt} aria-label="응답 중단"><Pause size={17}/> 응답 중단</button><button className="gs-icon-button" onClick={disconnect} aria-label="대화 종료"><Square size={17}/></button></>}
          <span className="gs-transport-note">{isReference ? '녹화된 예제입니다. 음성을 연결하려면 라이브 아바타를 선택하세요.' : mode==='wav' ? '감정 선택 → WAV 재생 · 같은 음성으로 반복 비교' : mic ? '마이크 녹음 중 · 다시 누르면 전송' : connected ? '마이크 버튼을 눌러 말하거나 아래에 입력하세요' : '헤드·시선·표정은 연결 전에도 시험할 수 있어요'}</span>
        </div>
        {mode==='wav' ? <div className="gs-panel gs-wav-panel"><h2>WAV 감정 테스트</h2><p>오른쪽에서 감정과 강도를 선택한 뒤 재생하세요. 파일 음성을 그대로 발화하며, 재생 중에도 감정을 바꿀 수 있습니다.</p><input ref={wavInput} type="file" accept=".wav,audio/wav" hidden onChange={e=>void loadWav(e.target.files?.[0])}/><div><button className="gs-secondary" disabled={wavBusy} onClick={()=>wavInput.current?.click()}>WAV 파일 선택</button> <button className="gs-secondary" disabled={wavBusy} onClick={()=>void loadWav()}>Ditto 기본 WAV</button><button className="gs-secondary" disabled={wavBusy} onClick={()=>void loadWav(undefined, 'ash-en')}>Ash · 영어 남성</button></div><p>{wavBusy?'WAV 준비 중…':wavName ? `${wavName} · ${wavDuration.toFixed(1)}초` : 'WAV를 선택하세요.'}</p><button className="gs-primary" disabled={!connected || !wavName || wavBusy} onClick={()=>void replayWav()}>선택한 감정으로 처음부터 재생</button><small>24kHz 모노로 변환 · Audio2Face 립싱크 · 입력 음성 해시와 감정·리그 값 로그 저장</small></div> : <div className="gs-panel gs-conversation"><div className="gs-conversation-title"><h2><MessageSquare size={16}/> 대화</h2><span>한국어 · 실시간 음성</span></div>
          <div className="gs-chat-scroll" ref={scroll}>{chats.length ? chats.map(chat => <div key={chat.id} className={`gs-message ${chat.role === 'user' ? 'user' : 'assistant'}`}><span>{chat.role === 'user' ? '나' : '아바타'}</span><p>{chat.text}{!chat.final && <i className="gs-cursor"/>}</p></div>) : <div className="gs-chat-empty"><AudioLines size={24}/><p>첫 이야기를 들려주세요.</p><div>{['오늘 조금 지쳤어.', '좋은 소식이 있어!', '내 이야기를 들어줄래?'].map(value => <button key={value} disabled={!connected} onClick={() => void sendText(value)}>{value}</button>)}</div></div>}</div>
          <form className="gs-chat-input" onSubmit={event => { event.preventDefault(); void sendText() }}><input value={text} onChange={event => setText(event.target.value)} placeholder={connected ? '이야기를 입력하세요…' : '대화를 시작하면 입력할 수 있어요'} disabled={!connected || mic}/><button type="submit" disabled={!connected || !text.trim() || mic} aria-label="메시지 보내기"><Send size={18}/></button></form>
        </div>}
      </section>

      <aside className="gs-panel gs-controls"><div className="gs-panel-title"><span className="gs-step">02</span><h2>공감 행동 컨트롤</h2><SlidersHorizontal size={17}/></div><p className="gs-caption">{isReference ? '녹화된 동작입니다. 제어하려면 라이브 아바타를 선택하세요.' : 'Auto에서는 대화에 맞춰 반응합니다. 감정을 선택하면 수동 제어로 전환합니다.'}</p>
        {isReference && <a href={avatar.reference_url} target="_blank" rel="noreferrer">GaussianAvatars 공식 저장소</a>}
        {isOfficial && <p className="gs-caption">A2F → FLAME · GPU {renderStats?.renderMs?.toFixed(0) ?? '—'}ms · 왕복 {renderStats?.roundTripMs?.toFixed(0) ?? '—'}ms</p>}
        <fieldset disabled={isReference} style={{border:0,padding:0,margin:0,minWidth:0,opacity:isReference?.45:1}}>
        <label className="gs-checkbox"><input type="checkbox" checked={naturalEnabled} onChange={e=>{const enabled=e.target.checked;setNaturalEnabled(enabled);naturalEnabledRef.current=enabled;motion.current.resetPolicy();recordAction('control.override',{natural_enabled:enabled})}}/><span>SOBIA 기본 움직임<small>대기·발화 표정, 시선, 경청 중 끄덕임</small></span></label>
        <div className="gs-section-label">표현 프리셋 <span>{connected ? '행동정책에 전달' : '로컬 제어 미리보기'}</span></div><div className="gs-emotions">{emotions.map(emotion => <button key={emotion.id} className={!automatic && controls.emotion === emotion.id ? 'active' : ''} onClick={() => updateControls({ emotion: emotion.id })}>{emotion.name}</button>)}</div>
        <Slider label="움직임 생동감" value={vitality} min={0} max={1.5} step={0.05} display={`${Math.round(vitality*100)}%`} onChange={value=>{setVitality(value);vitalityRef.current=value;recordAction('control.override',{vitality:value})}}/>
        <small>표현 강도는 감정의 최대치, 생동감은 강세·쉼에 따른 움직임의 크기입니다.</small>
        <Slider label="표현 강도" value={controls.intensity} min={0} max={1} step={0.01} display={`${Math.round(controls.intensity * 100)}%`} onChange={value => updateControls({ intensity: value })}/>
        <div className="gs-divider"/><div className="gs-section-label">시선과 헤드 <Move3d size={15}/></div>
        <div className="gs-gaze-preview"><i style={{ left: `${50 + controls.gaze_x * 35}%`, top: `${50 - controls.gaze_y * 35}%` }}/><span>GAZE</span></div>
        <Slider label="시선 · 좌우" value={controls.gaze_x} min={-1} max={1} step={0.05} onChange={value => updateControls({ gaze_x: value })}/>
        <Slider label="시선 · 상하" value={controls.gaze_y} min={-1} max={1} step={0.05} onChange={value => updateControls({ gaze_y: value })}/>
        <Slider label="고개 · 좌우" value={controls.head_yaw} min={-12} max={12} step={1} display={`${controls.head_yaw}°`} onChange={value => updateControls({ head_yaw: value })} disabled={renderStatus === 'ready' && !renderStats?.head}/>
        <Slider label="고개 · 상하" value={controls.head_pitch} min={-10} max={10} step={1} display={`${controls.head_pitch}°`} onChange={value => updateControls({ head_pitch: value })} disabled={renderStatus === 'ready' && !renderStats?.head}/>
        <Slider label="고개 · 기울임" value={controls.head_roll} min={-6} max={6} step={1} display={`${controls.head_roll}°`} onChange={value => updateControls({ head_roll: value })} disabled={renderStatus === 'ready' && !renderStats?.head}/>
        <div className="gs-control-actions"><button className="gs-secondary" disabled={!renderStats?.head} onClick={previewNod}>끄덕이기</button><button className="gs-secondary" onClick={() => { motion.current.resetPolicy(); updateControls({ ...DEFAULT_CONTROLS }); renderer.current?.resetView() }}><RotateCcw size={14}/> 초기화</button></div>
        {currentCameraJson !== 'null' && <button className="gs-secondary" onClick={() => { renderer.current?.resetView(); trace('camera.source_view_restored') }}>사진 기준 정면 복원</button>}
        <label className="gs-checkbox"><input type="checkbox" disabled={mode==='wav'} checked={automatic} onChange={event => { const auto=event.target.checked;setAutomatic(auto); automaticRef.current=auto; motion.current.resetPolicy();idleFrame.current=null; send({type:'control',...controlsRef.current,auto});recordAction('control.override',{auto}) }}/><span>Auto · LLM 공감 행동<small>{automatic ? 'LLM 도구 호출로 감정·시선·고개 동작 결정' : '수동 표정 테스트 · 선택한 감정으로 발화'}</small></span></label>
        <div className="gs-control-note"><Sparkles size={14}/><p>Audio2Face가 입 모양을 구동합니다. SOBIA 정책은 전달 상태와 말의 리듬에 맞춰 표정과 고개를 움직입니다.</p></div>
        </fieldset>
      </aside>
    </main>

    <section className="gs-panel gs-diagnostics"><div className="gs-diagnostics-header"><div><Activity size={17}/><h2>실행 진단</h2><span>소리와 움직임의 같은 시간축</span></div><div><span className="gs-log-state"><span className={`gs-dot ${logSource==='preview' && previewStatus?.state==='error' ? 'warning' : logId ? 'ok' : ''}`}/>{logLabel}</span>{logId && <a className="gs-secondary" href={`/gaussian-api/sessions/${logId}/summary`} target="_blank" rel="noreferrer">테스트 요약</a>}<a className={`gs-secondary ${!logId ? 'disabled' : ''}`} href={logId ? `/gaussian-api/sessions/${logId}/logs.zip` : undefined} download><Download size={14}/> 로그 다운로드</a></div></div>
      {logSource==='preview' && previewStatus?.error && <p role="alert" className="gs-diagnostic-warning">미리보기 로그 저장 오류 · {previewStatus.error}</p>}
      <div className="gs-metrics"><Metric label="렌더링" value={metrics.fps.toFixed(0)} unit="FPS"/><Metric label="오디오 버퍼" value={metrics.queued.toFixed(0)} unit="ms"/><Metric label="오디오 청크" value={String(metrics.audio)} unit="개"/><Metric label="모션 프레임" value={String(metrics.animation)} unit="개"/><Metric label="재생 지연" value={String(metrics.underruns)} unit="회"/><Metric label="동기화 대기초과" value={String(metrics.syncTimeouts)} unit="회" warning={metrics.syncTimeouts > 0}/></div>
      <div className="gs-turn-summary"><span>행동 계획 <strong>{behaviorPlan}</strong></span><span>첫 음성 <strong>{turnDiagnostics?.first_audio_ms ? `${Number(turnDiagnostics.first_audio_ms).toFixed(0)} ms` : '—'}</strong></span><span>첫 모션 <strong>{turnDiagnostics?.first_motion_ms ? `${Number(turnDiagnostics.first_motion_ms).toFixed(0)} ms` : '—'}</strong></span><span>응답 길이 <strong>{turnDiagnostics?.duration_ms ? `${(Number(turnDiagnostics.duration_ms)/1000).toFixed(1)} s` : '—'}</strong></span></div>
      {metrics.syncTimeouts > 0 && <p className="gs-diagnostic-warning">모션 도착이 1.8초 이상 지연된 구간은 음성만 먼저 재생됐습니다. 해당 턴의 Audio2Face 로그를 확인하세요.</p>}
      <div className="gs-debug-tabs"><button className={debugTab === 'motion' ? 'active' : ''} onClick={() => setDebugTab('motion')}>현재 제어값</button><button className={debugTab === 'events' ? 'active' : ''} onClick={() => setDebugTab('events')}>이벤트 타임라인 <span>{events.length}</span></button><span className="gs-session-id">{logId ? `SESSION ${logId}` : '테스트 대기'}</span></div>
      {debugTab === 'motion' && !isReference && <PolicyReadout frame={lastFrame} stats={renderStats} official={isOfficial}/> }
        {debugTab === 'motion' && renderStats?.rig && <div className="gs-rig-diagnostics">
        <p>기본 모션: {naturalEnabled ? '켜짐' : '꺼짐'} · 음성 에너지 {(lastFrame?.natural_motion?.energy ?? 0).toFixed(2)} · 고개 Pitch/Yaw/Roll {lastFrame?.head ? [lastFrame.head.pitch,lastFrame.head.yaw,lastFrame.head.roll].map(v=>v.toFixed(2)).join(' / ') : '—'}°</p>
        <p>눈 가림: {renderStats.eyeOcclusionMode ?? '기본'}</p>
        <p>구강 처리: {renderStats.oralVersion ?? '기본 리그'} · 입술 개방 {(renderStats.oralOpen ?? 0).toFixed(2)}</p>
        <strong>표정 전달 진단 · {renderStats.rig.channelCount}개 리그 채널</strong>
        <p>입력 → SDK 적용 → GPU 업로드 버퍼. 버퍼값은 화면상 표정 품질을 보장하지 않습니다.</p>
        <table><thead><tr><th>채널</th><th>입력</th><th>SDK</th><th>업로드</th><th>리그</th></tr></thead><tbody>
          {Object.entries(renderStats.rig.channels).map(([name, d]) => <tr key={name}>
            <td>{name}</td><td>{d.requested.toFixed(3)}</td><td>{d.applied?.toFixed(3) ?? '미확인'}</td><td>{d.uploaded?.toFixed(3) ?? '미확인'}</td>
            <td>{!d.supported ? '가시 변형 없음' : d.maxDeltaMm < .01 ? '변형 없음' : `${d.maxDeltaMm.toFixed(1)} mm / 최대값`}</td>
          </tr>)}
        </tbody></table>
      </div>}
      {debugTab === 'motion' ? <div className="gs-motion-monitor"><div className="gs-coefficients">{['jawOpen','mouthSmileLeft','mouthFrownLeft','browInnerUp','eyeBlinkLeft','eyeLookOutLeft','tongueOut'].map(name => <div key={name}><span>{name}</span><i><b style={{ width: `${Math.max(0, Math.min(1, lastFrame?.weights?.[name] ?? 0)) * 100}%` }}/></i><code>{(lastFrame?.weights?.[name] ?? 0).toFixed(2)}</code></div>)}</div><div className="gs-motion-meta"><p><span>모션 소스</span><strong>{lastFrame?.source ?? '대기'}</strong></p><p><span>Head 리그</span><strong>{renderStats ? renderStats.head ? (isOfficial ? renderStats.headMotion?.driver ?? 'GPU 확인 중' : 'LAM head bone') : '지원되지 않는 리그' : '확인 중'}</strong></p><p><span>Gaussian 수</span><strong>{renderStats?.splats.toLocaleString() ?? '—'}</strong></p><p><span>구강·혀 리그</span><strong>{renderStats?.oralMaterial ? `구강 색 보정 · ${renderStats.oralMaterial.changed_splats} splats · 독립 혀 없음` : renderStats?.oralOcclusion && renderStats.tongue ? '구강 가림 + 혀 채널 활성' : renderStats?.oralVersion==='hybrid-oral-v5' ? '구강 색 보정 · 독립 혀 없음' : '기본 리그'}</strong></p><p><span>음성 재생 시각</span><strong>{Math.max(0, metrics.pts).toFixed(0)} ms</strong></p></div></div> : <div className="gs-event-list">{events.length ? events.map((event, index) => <div key={`${event.at}:${index}`}><time>{event.at}</time><strong>{event.type}</strong><code>{event.detail}</code></div>) : <p>이벤트를 기다리고 있습니다.</p>}</div>}
    </section>
    <footer className="gs-footer"><span>{isOfficial || isReference ? 'GaussianAvatars · FLAME' : 'LAM · 3D Gaussian Splatting'}</span><span>Realtime → Audio2Face + Empathic Controller → ARKit · Head · Gaze</span><a href="/gaussian/rig-check" target="_blank" rel="noreferrer">눈 감김·입 모양 검사</a></footer>
    {feedbackOpen && <div className="gs-modal-backdrop" onClick={() => setFeedbackOpen(false)}><section className="gs-modal" onClick={event => event.stopPropagation()}><button className="gs-modal-close" aria-label="피드백 닫기" onClick={() => setFeedbackOpen(false)}><X size={19}/></button><MessageSquare size={25}/><h2>이번 대화는 어땠나요?</h2><p>피드백에 세션과 최근 턴의 로그가 연결됩니다.</p><label className="gs-field">전체 경험<select value={rating} onChange={event => setRating(Number(event.target.value))}>{[5,4,3,2,1].map(value => <option key={value} value={value}>{value} / 5</option>)}</select></label><textarea value={feedback} onChange={event => setFeedback(event.target.value)} placeholder="예: 슬픈 이야기에 웃는 표정이 나왔어요. 립싱크가 조금 늦어요." rows={4}/>{feedbackSaved ? <p className="gs-feedback-saved"><Check size={16}/> 피드백이 로그와 함께 저장됐어요.</p> : <button className="gs-primary" onClick={() => void saveFeedback()}>피드백 저장</button>}</section></div>}
  </div>
}

function Service({ label, ready, detail }: { label: string; ready?: boolean; detail?: string }) {
  return <div className="gs-service" title={detail}><span className={`gs-dot ${ready ? 'ok' : 'warning'}`}/><span>{label}</span><strong>{ready ? '준비됨' : '확인 필요'}</strong></div>
}
function Slider({ label, value, min, max, step, onChange, display, disabled }: { label: string; value: number; min: number; max: number; step: number; onChange(value: number): void; display?: string; disabled?: boolean }) {
  return <label className="gs-slider"><span>{label}<code>{display ?? value.toFixed(2)}</code></span><input type="range" aria-label={label} min={min} max={max} step={step} value={value} onChange={event => onChange(Number(event.target.value))} disabled={disabled}/></label>
}
function Metric({ label, value, unit, warning }: { label: string; value: string; unit: string; warning?: boolean }) {
  return <div className={`gs-metric ${warning ? 'warning' : ''}`}><span>{label}</span><strong>{value}<small>{unit}</small></strong></div>
}

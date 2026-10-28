import { useEffect, useRef, useState } from 'react'
import { createLamRenderer, manualFrame, neutralWeights, ARKIT_NAMES } from './renderer'
import { createOfficialRenderer } from './officialRenderer'
import { NaturalMotion } from './naturalMotion'
import { DEFAULT_CONTROLS, type Avatar, type RendererStats } from './types'

/** Repeatable visual inspection; no microphone, remote API call or timed blink. */
export function GaussianRigCheck() {
  const [avatars, setAvatars] = useState<Avatar[]>([])
  const [selected, setSelected] = useState('')
  const [nativeOral,setNativeOral]=useState(true)
  const [rawShaders,setRawShaders]=useState(false)
  const [blink, setBlink] = useState(0)
  const [jaw, setJaw] = useState(0)
  const [yaw, setYaw] = useState(0)
  const [emotion, setEmotion] = useState('neutral')
  const [auditMode,setAuditMode] = useState('emotion')
  const [channel,setChannel] = useState('browInnerUp')
  const [channelWeight,setChannelWeight] = useState(1)
  const [dynamic,setDynamic] = useState(false)
  const dynamics = useRef(new NaturalMotion())
  const [tongue, setTongue] = useState(0)
  const [intensity, setIntensity] = useState(1)
  const [message, setMessage] = useState('준비 중')
  const [stats, setStats] = useState<RendererStats | null>(null)
  const host = useRef<HTMLDivElement>(null)
  const values = useRef({ blink, jaw, yaw, emotion, tongue, intensity, auditMode, channel, channelWeight, dynamic })
  useEffect(() => { values.current = { blink, jaw, yaw, emotion, tongue, intensity, auditMode, channel, channelWeight, dynamic } }, [blink, jaw, yaw, emotion, tongue, intensity, auditMode, channel, channelWeight, dynamic])
  useEffect(() => { void fetch('/gaussian-api/avatars').then(r => r.json()).then(list => {
    setAvatars(list); setSelected(list.find((a: { status: string; kind?:string }) => a.status === 'ready' && a.kind !== 'reference_video')?.id ?? '')
  }) }, [])
  const avatar = avatars.find(a => a.id === selected)
  useEffect(() => {
    if (!avatar || !host.current) return
    setStats(null)
    setMessage('선택한 자산·보정 설정 적용 중')
    const abort = new AbortController()
    let dispose: (() => void) | undefined
    let timer: ReturnType<typeof setInterval> | undefined
    const createRenderer=avatar.kind==='official_live'?createOfficialRenderer:createLamRenderer
    void createRenderer(host.current, `${avatar.asset_url}?v=${avatar.asset_sha256}`, () => {
      const v=values.current
      const frame=manualFrame({...DEFAULT_CONTROLS,emotion:v.emotion,intensity:v.intensity},1)
      if(v.auditMode==='single') frame.weights={...neutralWeights(),[v.channel]:v.channelWeight}
      else {
        frame.weights.eyeBlinkLeft=frame.weights.eyeBlinkRight=v.blink
        frame.weights.jawOpen=Math.max(v.jaw,frame.weights.jawOpen)
        frame.weights.tongueOut=v.tongue
        if(v.auditMode==='exclude') frame.weights[v.channel]=0
      }
      frame.turn_id='rig-check';frame.source='manual-rig-check';frame.head={yaw:v.yaw,pitch:0,roll:0}
      return dynamics.current.apply(frame,performance.now()/1000,false,v.dynamic)
    }, () => setMessage('검사 준비됨'), () => {}, abort.signal, avatar.source_camera ?? avatar.generation?.manifest?.source_camera, nativeOral, rawShaders).then(r => { if (abort.signal.aborted) {r.dispose(); return}; dispose = r.dispose; timer = setInterval(()=>setStats(r.stats()),500) }).catch(e => {
      if (!abort.signal.aborted) setMessage(String(e))
    })
    return () => { abort.abort(); clearInterval(timer); dispose?.() }
  }, [avatar,nativeOral,rawShaders])
  return <main style={{ padding: 24, color: '#eaf3f5', background: '#172630', minHeight: '100vh' }}>
    <h1>3DGS 리그 검사</h1><a href="/gaussian" style={{ color: '#8ee4d4' }}>대화 화면으로</a>
    <p>{message} · 정적 최대 표정·개별 채널·채널 제외를 비교하고, dynamics를 따로 켜 볼 수 있습니다.</p>
    <select aria-label="검사 아바타" value={selected} onChange={e => setSelected(e.target.value)}>
      {avatars.filter(a => a.status === 'ready' && a.kind !== 'reference_video').map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
    </select>
    <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', marginTop: 20 }}>
      <div data-testid="rig-canvas" ref={host} style={{ width: 450, height: 450, position: 'relative' }} />
      {avatar?.image_url && <figure style={{margin:0}}><img src={avatar.image_url} alt="입력 사진 · 원본 비율 비교" style={{width:360,height:450,objectFit:'contain'}}/><figcaption>입력 사진 · 원본 비율 비교 (구도 차이 있음)</figcaption></figure>}
      <div style={{ width: 250 }}>
        <p>{avatar?.kind==='official_live' ? '공식 체크포인트 · 실시간 FLAME 변형' : 'LAM 원본 구강 · 화면 색 덧씌우기 제거'}</p>
        {avatar?.kind!=='official_live' && <label><input type="checkbox" checked={nativeOral} onChange={e=>setNativeOral(e.target.checked)}/>기존 보강 구조 숨김</label>}<br/>
        {avatar?.kind!=='official_live' && <label><input type="checkbox" checked={rawShaders} onChange={e=>setRawShaders(e.target.checked)}/>눈·구강 셰이더 보정 해제 (원인 비교)</label>}<br/>
        <label>검사 방식 <select aria-label="검사 방식" value={auditMode} onChange={e=>setAuditMode(e.target.value)}>
          <option value="emotion">감정 조합</option><option value="single">단일 blendshape</option><option value="exclude">선택 채널 제외 비교</option>
        </select></label><br/>
        <label>검사 채널 <select aria-label="검사 채널" value={channel} onChange={e=>setChannel(e.target.value)}>{ARKIT_NAMES.map(n=><option key={n}>{n}</option>)}</select></label>
        {auditMode==='single' && <label>채널값 {channelWeight.toFixed(2)}<input aria-label="채널값" type="range" min="0" max="1" step="0.05" value={channelWeight} onChange={e=>setChannelWeight(Number(e.target.value))}/></label>}
        <label><input type="checkbox" checked={dynamic} onChange={e=>setDynamic(e.target.checked)}/>대기 dynamics 미리보기</label><br/>
        <label>표정 검사 <select aria-label="표정 검사" value={emotion} onChange={e=>setEmotion(e.target.value)}>
          {['neutral','happy','sad','angry','fear','surprise','disgust','contempt'].map(e=><option key={e}>{e}</option>)}
        </select></label><br/>
        <label>표현 강도 {Math.round(intensity*100)}%<input aria-label="표현 강도" type="range" min="0" max="1" step="0.01" value={intensity} onChange={e=>setIntensity(Number(e.target.value))}/></label><br/>
        <label>눈 감김 {blink.toFixed(2)}<input aria-label="눈 감김" type="range" min="0" max="1" step="0.05" value={blink} onChange={e => setBlink(Number(e.target.value))} /></label>
        <p><button onClick={() => setBlink(0)}>눈 뜨기</button> <button onClick={() => setBlink(1)}>눈 완전히 감기</button></p>
        <label>입 벌림 {jaw.toFixed(2)}<input aria-label="입 벌림" type="range" min="0" max="0.6" step="0.05" value={jaw} onChange={e => setJaw(Number(e.target.value))} /></label>
        <label>고개 회전 {yaw}<input aria-label="고개 회전" type="range" min="-20" max="20" step="1" value={yaw} onChange={e => setYaw(Number(e.target.value))} /></label>
        <label>혀 내밀기 {tongue.toFixed(2)}<input disabled={!stats?.tongue} aria-label="혀 내밀기" type="range" min="0" max="1" step="0.05" value={tongue} onChange={e=>setTongue(Number(e.target.value))}/></label>
      </div>
    </div>
    <pre aria-label="리그 적용 진단">{JSON.stringify(stats, null, 2)}</pre>
  </main>
}

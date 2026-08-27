import { useEffect, useMemo, useRef, useState } from 'react'
import './rendered-video.css'
import {
  AlertCircle,
  ArrowRight,
  AudioLines,
  Bot,
  Camera,
  CameraOff,
  Check,
  ChevronRight,
  CircleHelp,
  Clock3,
  Gauge,
  LayoutDashboard,
  LoaderCircle,
  MessageSquareText,
  Mic,
  MicOff,
  MoreHorizontal,
  Pause,
  Play,
  Plus,
  Radio,
  SendHorizontal,
  Settings2,
  ShieldCheck,
  Sparkles,
  Trash2,
  UploadCloud,
  Volume2,
  WandSparkles,
  X,
} from 'lucide-react'
import { ApiError, api } from './api'
import { localTurn } from './localTurn'
import type { Avatar, ExpressionIntent, LiveState, MotionPlan, TranscriptItem, TurnResponse } from './types'

type Page = 'dashboard' | 'avatars' | 'create' | 'live'

interface SpeechRecognitionResultEventLike extends Event {
  results: {
    length: number
    [index: number]: {
      isFinal: boolean
      0: { transcript: string }
    }
  }
}

interface SpeechRecognitionLike {
  continuous: boolean
  interimResults: boolean
  lang: string
  onresult: ((event: SpeechRecognitionResultEventLike) => void) | null
  onend: (() => void) | null
  onerror: ((event: { error: string }) => void) | null
  start(): void
  stop(): void
}

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike

const defaultAvatar: Avatar = {
  id: 'demo-hana',
  name: '하나 · Ditto Live',
  persona: '차분하고 신뢰감 있게 대화하는 AI 생성 한국어 데모 아바타',
  voice: 'Calm Korean',
  status: 'ready',
  created_at: new Date().toISOString(),
  engine: 'remote',
  source_url: '/api/assets/demo-hana',
}

const defaultAvatarIds = new Set(['demo-hana', 'demo-minjun', 'demo-seoyeon', 'demo-doyun'])

const pageMeta: Record<Page, { eyebrow: string; title: string; description: string }> = {
  dashboard: {
    eyebrow: 'YOUR AVATAR WORKSPACE',
    title: '좋은 대화는, 준비된 존재감에서 시작됩니다.',
    description: '한 장의 승인된 사진을 안전한 대화형 AI 아바타로 준비하세요.',
  },
  avatars: {
    eyebrow: 'AVATAR LIBRARY',
    title: '내 아바타',
    description: '준비된 아바타를 선택해 실시간 대화를 시작하거나 설정을 관리하세요.',
  },
  create: {
    eyebrow: 'CREATE PRIVATE AVATAR',
    title: '새 아바타 만들기',
    description: '사진 1장과 명시적 권리 동의로 private 아바타를 준비합니다.',
  },
  live: {
    eyebrow: 'LIVE CONVERSATION',
    title: '라이브 룸',
    description: 'AI 생성 아바타와 실시간으로 대화 중입니다.',
  },
}

function sourceUrl(avatar: Avatar) {
  if (!avatar.source_url) return undefined
  if (/^https?:\/\//.test(avatar.source_url) || avatar.source_url.startsWith('blob:')) return avatar.source_url
  return `${import.meta.env.VITE_API_BASE_URL ?? ''}${avatar.source_url}`
}

function mediaUrl(path: string | undefined) {
  if (!path) return undefined
  if (/^https?:\/\//.test(path) || path.startsWith('blob:')) return path
  return `${import.meta.env.VITE_API_BASE_URL ?? ''}${path}`
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('ko-KR', { month: 'short', day: 'numeric' }).format(new Date(value))
}

function initials(name: string) {
  return name
    .split(' ')
    .map((part) => part[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()
}

export default function App() {
  const [page, setPage] = useState<Page>('dashboard')
  const [avatars, setAvatars] = useState<Avatar[]>([])
  const [selectedAvatarId, setSelectedAvatarId] = useState(defaultAvatar.id)
  const [apiOnline, setApiOnline] = useState(true)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    void Promise.all([api.health(), api.avatars()])
      .then(([, remoteAvatars]) => {
        if (!alive) return
        setApiOnline(true)
        setAvatars(remoteAvatars.length ? remoteAvatars : [defaultAvatar])
        if (remoteAvatars[0]) setSelectedAvatarId(remoteAvatars[0].id)
      })
      .catch(() => {
        if (!alive) return
        setApiOnline(false)
        setAvatars([defaultAvatar])
      })
    return () => {
      alive = false
    }
  }, [])

  const selectedAvatar = useMemo(
    () => avatars.find((avatar) => avatar.id === selectedAvatarId) ?? avatars[0] ?? defaultAvatar,
    [avatars, selectedAvatarId],
  )

  const openLive = (avatar: Avatar) => {
    setSelectedAvatarId(avatar.id)
    setPage('live')
  }

  const addAvatar = (avatar: Avatar) => {
    setAvatars((items) => [avatar, ...items.filter((item) => item.id !== avatar.id)])
    setSelectedAvatarId(avatar.id)
    setPage('avatars')
    setNotice(avatar.status === 'ready' ? `${avatar.name} 아바타 준비가 완료되었습니다.` : `${avatar.name} 아바타 준비 작업을 시작했습니다.`)
  }

  const removeAvatar = async (avatar: Avatar) => {
    if (!window.confirm(`${avatar.name}의 원본과 준비 캐시를 모두 삭제할까요? 이 작업은 되돌릴 수 없습니다.`)) return
    try {
      if (apiOnline && avatar.id !== defaultAvatar.id) await api.deleteAvatar(avatar.id)
      setAvatars((items) => items.filter((item) => item.id !== avatar.id))
      setSelectedAvatarId(defaultAvatar.id)
      setNotice(`${avatar.name} 및 연결된 원본·캐시를 삭제했습니다.`)
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '삭제하지 못했습니다.')
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <button className="brand" onClick={() => setPage('dashboard')} aria-label="Empathic Avatar home">
          <span className="brand-mark"><Sparkles size={17} strokeWidth={2.5} /></span>
          <span>empathic</span>
        </button>

        <nav className="primary-nav" aria-label="Main navigation">
          <NavItem active={page === 'dashboard'} icon={<LayoutDashboard size={18} />} label="개요" onClick={() => setPage('dashboard')} />
          <NavItem active={page === 'avatars'} icon={<Bot size={18} />} label="내 아바타" onClick={() => setPage('avatars')} />
          <NavItem active={page === 'live'} icon={<Radio size={18} />} label="라이브 룸" onClick={() => setPage('live')} />
        </nav>

        <div className="sidebar-bottom">
          <div className="plan-card">
            <div className="plan-icon"><Gauge size={17} /></div>
            <div>
              <strong>Ditto renderer candidate</strong>
              <span>Private avatars only</span>
            </div>
          </div>
          <button className="nav-item" onClick={() => setNotice('설정은 다음 배포 단계에서 계정·팀 단위로 연결됩니다.')}>
            <Settings2 size={18} /> 설정
          </button>
          <div className="profile-row">
            <span className="profile-avatar">JD</span>
            <div><strong>Jason</strong><span>Builder workspace</span></div>
            <MoreHorizontal size={18} />
          </div>
        </div>
      </aside>

      <main className="main-panel">
        <header className="topbar">
          <div className="crumb"><span>Studio</span><ChevronRight size={15} /><strong>{pageMeta[page].eyebrow}</strong></div>
          <div className="topbar-actions">
            {!apiOnline && <span className="offline-pill"><AlertCircle size={14} /> API 연결 전 — 브라우저 데모</span>}
            <button className="icon-button" aria-label="Help" onClick={() => setNotice('아바타는 항상 AI 생성임을 표시하고, 본인 또는 권리 보유 성인의 사진만 사용하세요.')}><CircleHelp size={19} /></button>
            {page !== 'create' && <button className="primary-button compact" onClick={() => setPage('create')}><Plus size={17} /> 새 아바타</button>}
          </div>
        </header>

        {notice && <div className="notice"><Check size={16} /><span>{notice}</span><button aria-label="닫기" onClick={() => setNotice(null)}><X size={16} /></button></div>}

        <section className={`page-content page-${page}`}>
          {page === 'dashboard' && <Dashboard avatars={avatars} onCreate={() => setPage('create')} onLive={openLive} />}
          {page === 'avatars' && <AvatarLibrary avatars={avatars} onCreate={() => setPage('create')} onLive={openLive} onDelete={removeAvatar} />}
          {page === 'create' && <CreateAvatar apiOnline={apiOnline} onComplete={addAvatar} onCancel={() => setPage('avatars')} />}
          {page === 'live' && <LiveRoom avatar={selectedAvatar} apiOnline={apiOnline} onExit={() => setPage('avatars')} />}
        </section>
      </main>
    </div>
  )
}

function NavItem({ active, icon, label, onClick }: { active: boolean; icon: React.ReactNode; label: string; onClick: () => void }) {
  return <button className={`nav-item ${active ? 'active' : ''}`} onClick={onClick}>{icon}<span>{label}</span></button>
}

function Dashboard({ avatars, onCreate, onLive }: { avatars: Avatar[]; onCreate: () => void; onLive: (avatar: Avatar) => void }) {
  const demoAvatars = avatars.filter((avatar) => defaultAvatarIds.has(avatar.id))
  const featured = demoAvatars.find((avatar) => avatar.id === defaultAvatar.id) ?? demoAvatars[0] ?? avatars.find((avatar) => avatar.status === 'ready') ?? avatars[0]
  const featuredReady = featured?.status === 'ready'
  return (
    <>
      <section className="hero-grid">
        <div className="hero-copy">
          <span className="eyebrow"><Sparkles size={15} /> ONE PHOTO, REAL PRESENCE</span>
          <h1>대화할 준비가 된<br /><em>당신만의 아바타.</em></h1>
          <p>한 장의 승인된 사진을 준비하고, 음성으로 자연스럽게 대화하세요. 모든 세션에는 AI 아바타 표시가 유지됩니다.</p>
          <div className="hero-actions">
            <button className="primary-button" onClick={onCreate}><WandSparkles size={18} /> 아바타 만들기 <ArrowRight size={17} /></button>
            {featured && <button className="secondary-button" onClick={() => onLive(featured)}><Radio size={17} /> 데모 대화</button>}
          </div>
          <div className="trust-row"><ShieldCheck size={17} /><span>Private by default</span><i /> <span>삭제 시 원본·캐시 연쇄 삭제</span></div>
        </div>
        <div className="hero-visual">
          <div className="orb orb-one" /><div className="orb orb-two" />
          <div className="hero-avatar-card">
            <AvatarPortrait avatar={featured ?? defaultAvatar} mode="idle" />
            <div className="avatar-card-caption"><span className="live-dot" /> <strong>AI AVATAR</strong><span>Ready to listen</span></div>
          </div>
          <div className="floating-stat stat-latency"><span className="metric-dot mint" /> <div><small>RESPONSE PATH</small><strong>Audio → motion</strong></div></div>
          <div className="floating-stat stat-ready"><Check size={15} /><div><small>AVATAR STATE</small><strong>Prepared once</strong></div></div>
        </div>
      </section>

      <section className="metric-grid">
        <Metric icon={<Bot size={19} />} label="준비된 아바타" value={featuredReady ? '1' : '0'} detail="default demo" />
        <Metric icon={<Clock3 size={19} />} label="세션 기록" value="Opt-in" detail="기본 저장 안 함" />
        <Metric icon={<ShieldCheck size={19} />} label="AI 표시" value="Always" detail="대화·화면 내 고정" />
      </section>

      <section className="section-head"><div><span className="eyebrow subtle">YOUR AVATARS</span><h2>바로 대화 시작</h2></div><button className="text-button" onClick={onCreate}>아바타 라이브러리 <ArrowRight size={15} /></button></section>
      <div className="avatar-card-grid">
        {(demoAvatars.length ? demoAvatars : featured ? [featured] : []).map((avatar) => <AvatarCard key={avatar.id} avatar={avatar} onLive={() => onLive(avatar)} />)}
      </div>
    </>
  )
}

function Metric({ icon, label, value, detail }: { icon: React.ReactNode; label: string; value: string; detail: string }) {
  return <article className="metric-card"><span className="metric-icon">{icon}</span><div><span>{label}</span><strong>{value}</strong><small>{detail}</small></div></article>
}

function AvatarLibrary({ avatars, onCreate, onLive, onDelete }: { avatars: Avatar[]; onCreate: () => void; onLive: (avatar: Avatar) => void; onDelete: (avatar: Avatar) => void }) {
  return (
    <>
      <section className="page-heading"><span className="eyebrow"><Bot size={15} /> AVATAR LIBRARY</span><h1>내 아바타</h1><p>각 아바타는 원본 사진과 분리된 immutable 준비 버전을 사용합니다.</p></section>
      <div className="library-toolbar"><div className="filter-tabs"><button className="active">전체 <span>{avatars.length}</span></button><button>준비 완료 <span>{avatars.filter((item) => item.status === 'ready').length}</span></button></div><button className="primary-button compact" onClick={onCreate}><Plus size={17} /> 새 아바타</button></div>
      <div className="avatar-card-grid library-grid">
        {avatars.map((avatar) => <AvatarCard key={avatar.id} avatar={avatar} onLive={() => onLive(avatar)} onDelete={avatar.id === defaultAvatar.id ? undefined : () => onDelete(avatar)} />)}
        <button className="create-tile library-create" onClick={onCreate}><span><UploadCloud size={23} /></span><strong>사진 업로드</strong><small>새 private 아바타 만들기</small></button>
      </div>
    </>
  )
}

function AvatarCard({ avatar, onLive, onDelete }: { avatar: Avatar; onLive: () => void; onDelete?: () => void }) {
  const statusText = avatar.status === 'ready' ? '준비 완료' : avatar.status === 'preparing' ? '준비 중' : '확인 필요'
  return (
    <article className="avatar-card">
      <div className="avatar-thumb"><AvatarPortrait avatar={avatar} mode="idle" /><span className={`status-chip ${avatar.status}`}><i />{statusText}</span><span className="ai-label">AI</span></div>
      <div className="avatar-card-body"><div><h3>{avatar.name}</h3><p>{avatar.persona}</p></div><button className="icon-button card-menu" aria-label={`${avatar.name} options`}><MoreHorizontal size={18} /></button></div>
      <div className="avatar-card-footer"><span><Volume2 size={14} /> {avatar.voice}</span><span>{formatDate(avatar.created_at)}</span></div>
      <div className="card-actions"><button className="secondary-button compact" disabled={avatar.status !== 'ready'} onClick={onLive}><Radio size={15} /> 대화 시작</button>{onDelete && <button className="danger-quiet" aria-label={`${avatar.name} 삭제`} onClick={onDelete}><Trash2 size={16} /></button>}</div>
    </article>
  )
}

function CreateAvatar({ apiOnline, onComplete, onCancel }: { apiOnline: boolean; onComplete: (avatar: Avatar) => void; onCancel: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [imagePreview, setImagePreview] = useState<string | undefined>()
  const [name, setName] = useState('')
  const [persona, setPersona] = useState('따뜻하고 차분한 대화 파트너')
  const [voice, setVoice] = useState('Calm Korean')
  const [consentLikeness, setConsentLikeness] = useState(false)
  const [consentAdult, setConsentAdult] = useState(false)
  const [consentAiLabel, setConsentAiLabel] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => () => { if (imagePreview?.startsWith('blob:')) URL.revokeObjectURL(imagePreview) }, [imagePreview])

  const chooseFile = (candidate?: File) => {
    if (!candidate) return
    if (!candidate.type.startsWith('image/')) {
      setError('JPG, PNG 또는 WebP 이미지 파일을 선택해 주세요.')
      return
    }
    if (candidate.size > 12 * 1024 * 1024) {
      setError('이미지는 12MB 이하로 업로드해 주세요.')
      return
    }
    setError(null)
    setFile(candidate)
    setImagePreview(URL.createObjectURL(candidate))
  }

  const submit = async () => {
    if (!file || !name.trim()) return setError('사진과 아바타 이름을 입력해 주세요.')
    if (!consentLikeness || !consentAdult || !consentAiLabel) return setError('아래 세 가지 동의를 모두 확인해야 합니다.')
    setSubmitting(true)
    setError(null)
    try {
      let avatar: Avatar
      if (apiOnline) {
        avatar = await api.createAvatar({ image: file, name: name.trim(), persona, voice, consent_likeness: consentLikeness, consent_adult: consentAdult, consent_ai_label: consentAiLabel })
        if (avatar.status === 'preparing') avatar = await waitForAvatar(avatar.id)
      } else {
        await new Promise((resolve) => window.setTimeout(resolve, 850))
        avatar = { id: `local-${Date.now()}`, name: name.trim(), persona, voice, status: 'ready', source_url: imagePreview, created_at: new Date().toISOString(), engine: 'preview' }
      }
      onComplete(avatar)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : '아바타를 준비하지 못했습니다. 이미지를 바꿔 다시 시도해 주세요.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="create-layout">
      <section className="page-heading compact-heading"><span className="eyebrow"><WandSparkles size={15} /> PRIVATE AVATAR SETUP</span><h1>한 장으로, 대화의 표정을 만드세요.</h1><p>원본은 private workspace에 보관되며, 언제든 원본과 준비 캐시를 함께 삭제할 수 있습니다.</p></section>
      <div className="create-progress"><span className="active"><b>1</b> 사진 선택</span><i /><span><b>2</b> 권리 확인</span><i /><span><b>3</b> 준비 완료</span></div>
      <div className="create-columns">
        <div className="form-card photo-form">
          <div className="form-label-row"><label>인물 사진</label><span>JPG · PNG · WebP · 최대 12MB</span></div>
          <input ref={inputRef} type="file" accept="image/jpeg,image/png,image/webp" hidden onChange={(event) => chooseFile(event.target.files?.[0])} />
          <button className={`upload-zone ${imagePreview ? 'has-image' : ''}`} onClick={() => inputRef.current?.click()} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); chooseFile(event.dataTransfer.files[0]) }}>
            {imagePreview ? <img src={imagePreview} alt="업로드한 아바타 사진 미리보기" /> : <><span className="upload-icon"><UploadCloud size={25} /></span><strong>사진을 끌어놓거나 선택하세요</strong><small>정면을 향한 한 명의 성인, 밝고 선명한 얼굴 사진이 가장 좋습니다.</small></>}
            {imagePreview && <span className="replace-image"><UploadCloud size={15} /> 사진 바꾸기</span>}
          </button>
          <div className="image-tips"><div><Check size={15} /> 512px 이상 권장</div><div><Check size={15} /> 얼굴 가림 없음</div><div><Check size={15} /> 정면 또는 15° 이내</div></div>
          {file && <div className="quality-hint"><Sparkles size={16} /><span><strong>{file.name}</strong><small>업로드 후 해상도·선명도 기본 검사를 진행합니다.</small></span></div>}
        </div>

        <div className="form-card details-form">
          <label>아바타 이름<input value={name} onChange={(event) => setName(event.target.value)} placeholder="예: 민지 코치" maxLength={60} /></label>
          <label>대화 성격<textarea value={persona} onChange={(event) => setPersona(event.target.value)} maxLength={240} rows={3} /></label>
          <label>기본 음성<select value={voice} onChange={(event) => setVoice(event.target.value)}><option>Calm Korean</option><option>Warm Korean</option><option>Clear English</option></select></label>
          <div className="consent-box"><div className="consent-title"><ShieldCheck size={18} /><div><strong>권리와 투명성 확인</strong><span>public sharing 및 voice cloning은 이 프로토타입에서 비활성화되어 있습니다.</span></div></div><Consent checked={consentLikeness} onChange={setConsentLikeness}>이 사진의 인물은 본인이거나, 제가 AI 아바타로 사용할 정당한 권리를 보유합니다.</Consent><Consent checked={consentAdult} onChange={setConsentAdult}>인물은 성인이며, 미성년자 또는 공인을 사칭하는 용도가 아닙니다.</Consent><Consent checked={consentAiLabel} onChange={setConsentAiLabel}>대화·화면·향후 내보내기에서 AI 생성 아바타임을 명확히 표시하는 데 동의합니다.</Consent></div>
          {error && <div className="form-error"><AlertCircle size={16} />{error}</div>}
          <div className="form-actions"><button className="secondary-button" onClick={onCancel}>취소</button><button className="primary-button" disabled={submitting} onClick={submit}>{submitting ? <LoaderCircle className="spin" size={17} /> : <WandSparkles size={17} />}{submitting ? '안전하게 준비 중…' : '아바타 준비하기'}<ArrowRight size={16} /></button></div>
        </div>
      </div>
      <div className="privacy-footnote"><ShieldCheck size={16} /><span><strong>개인정보 기본값:</strong> 마이크 오디오와 대화 기록은 저장하지 않습니다. 아바타 삭제 요청은 원본, 파생 이미지, 모델 캐시를 연쇄 삭제합니다.</span></div>
    </div>
  )
}

function Consent({ checked, onChange, children }: { checked: boolean; onChange: (value: boolean) => void; children: React.ReactNode }) {
  return <label className="consent-row"><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} /><span className="fake-checkbox">{checked && <Check size={13} />}</span><span>{children}</span></label>
}

function LiveRoom({ avatar, apiOnline, onExit }: { avatar: Avatar; apiOnline: boolean; onExit: () => void }) {
  const [state, setState] = useState<LiveState>('connecting')
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [captions, setCaptions] = useState<TranscriptItem[]>([])
  const [interim, setInterim] = useState('')
  const [muted, setMuted] = useState(false)
  const [audioLevel, setAudioLevel] = useState(0.16)
  const [renderedVideo, setRenderedVideo] = useState<string | undefined>()
  const [renderedAudio, setRenderedAudio] = useState<string | undefined>()
  const [streamReady, setStreamReady] = useState(false)
  const [realtimeActive, setRealtimeActive] = useState(false)
  const [cameraEnabled, setCameraEnabled] = useState(false)
  const [cameraError, setCameraError] = useState<string | null>(null)
  const [expression, setExpression] = useState<ExpressionIntent>('neutral')
  const [headYaw, setHeadYaw] = useState(0)
  const [nodQueued, setNodQueued] = useState(false)
  const [lastAppliedMotion, setLastAppliedMotion] = useState<MotionPlan | undefined>()
  const [voiceSupported] = useState(() => supportsSpeechRecognition())
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null)
  const mediaRef = useRef<{ stream: MediaStream; context: AudioContext; frame: number } | null>(null)
  const cameraStreamRef = useRef<MediaStream | null>(null)
  const cameraVideoRef = useRef<HTMLVideoElement>(null)
  const renderedAudioRef = useRef<HTMLAudioElement>(null)
  const realtimeCanvasRef = useRef<HTMLCanvasElement>(null)
  const realtimeSocketRef = useRef<WebSocket | null>(null)
  const realtimeAudioRef = useRef<AudioContext | null>(null)
  const sessionRef = useRef<string | null>(null)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    const connect = async () => {
      try {
        const session = apiOnline ? await api.createSession(avatar.id) : { id: `local-room-${Date.now()}`, avatar_id: avatar.id, state: 'active', created_at: new Date().toISOString() }
        if (!mountedRef.current) return
        setSessionId(session.id)
        sessionRef.current = session.id
        setState('ready')
      } catch {
        if (mountedRef.current) setState('error')
      }
    }
    void connect()
    return () => {
      mountedRef.current = false
      window.speechSynthesis?.cancel()
      recognitionRef.current?.stop()
      stopMedia(mediaRef.current)
      stopCamera(cameraStreamRef.current)
      realtimeSocketRef.current?.close()
      void realtimeAudioRef.current?.close()
      if (sessionRef.current && apiOnline) void api.endSession(sessionRef.current).catch(() => undefined)
      sessionRef.current = null
    }
  }, [avatar.id, apiOnline])

  useEffect(() => {
    // Download the WAV while Ditto is producing its first frame, then use the
    // first decoded MJPEG frame as the shared A/V zero point.
    if (!renderedAudio || !streamReady) return
    const audio = renderedAudioRef.current
    if (!audio) return
    audio.currentTime = 0
    void audio.play().catch(() => undefined)
  }, [renderedAudio, streamReady])

  const stopRealtime = () => {
    realtimeSocketRef.current?.close()
    realtimeSocketRef.current = null
    void realtimeAudioRef.current?.close()
    realtimeAudioRef.current = null
    setRealtimeActive(false)
  }

  const startRealtime = (streamPath: string) => {
    stopRealtime()
    const context = new AudioContext()
    realtimeAudioRef.current = context
    // Do not anchor media time when the socket opens: GPU warm-up can take
    // seconds. Build a small playout buffer instead: JPEG decoding and the
    // browser compositor otherwise make the first few live frames visibly
    // late even when the worker PTS values are correct.
    let mediaStart: number | null = null
    let finalAudioAt = 0
    const pendingFrames: Array<[number, ArrayBuffer]> = []
    const pendingAudio: Array<[number, ArrayBuffer]> = []
    let latestVideoPts = -1
    // Ditto's online renderer can have a short GPU/encoder burst after it has
    // started speaking.  Keeping 0.6 s ahead lets the browser absorb that
    // jitter without slowing both audio and video together mid-utterance.
    const initialBufferMs = 600
    let ended = false
    const drawAt = async (ptsMs: number, jpeg: ArrayBuffer) => {
      if (mediaStart === null) {
        pendingFrames.push([ptsMs, jpeg])
        return
      }
      const startAt = mediaStart
      try {
        const bitmap = await createImageBitmap(new Blob([jpeg], { type: 'image/jpeg' }))
        const draw = () => {
          const remaining = startAt + ptsMs / 1000 - context.currentTime
          if (remaining > 0.008) {
            window.setTimeout(draw, Math.min(remaining * 1000, 40))
            return
          }
          const canvas = realtimeCanvasRef.current
          const ctx = canvas?.getContext('2d')
          if (canvas && ctx) {
            if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
              canvas.width = bitmap.width
              canvas.height = bitmap.height
            }
            ctx.drawImage(bitmap, 0, 0)
          }
          bitmap.close()
        }
        draw()
      } catch {
        // A dropped JPEG is preferable to delaying the media clock.
      }
    }
    const scheduleAudio = (ptsMs: number, payload: ArrayBuffer) => {
      if (mediaStart === null) return
      const pcm = new Int16Array(payload)
      const buffer = context.createBuffer(1, pcm.length, 16000)
      const channel = buffer.getChannelData(0)
      for (let index = 0; index < pcm.length; index += 1) channel[index] = pcm[index] / 32768
      const source = context.createBufferSource()
      source.buffer = buffer
      source.connect(context.destination)
      const at = Math.max(mediaStart + ptsMs / 1000, finalAudioAt, context.currentTime + 0.005)
      source.start(at)
      finalAudioAt = at + buffer.duration
    }
    const startWhenBuffered = () => {
      if (mediaStart !== null || latestVideoPts < initialBufferMs || pendingAudio.length === 0) return
      // Keep a little media time in hand. This is a fixed startup latency,
      // not cumulative delay, and gives ImageBitmap decoding a stable lead.
      mediaStart = context.currentTime + 0.16
      finalAudioAt = mediaStart
      for (const [pendingPts, pendingPcm] of pendingAudio.splice(0)) scheduleAudio(pendingPts, pendingPcm)
      for (const [pendingPts, pendingJpeg] of pendingFrames.splice(0)) void drawAt(pendingPts, pendingJpeg)
    }
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const socket = new WebSocket(`${protocol}//${window.location.host}${streamPath}`)
    socket.binaryType = 'arraybuffer'
    realtimeSocketRef.current = socket
    socket.onopen = () => {
      setRealtimeActive(true)
      setAudioLevel(0.5)
      void context.resume()
    }
    socket.onmessage = (event) => {
      const packet = event.data as ArrayBuffer
      const view = new DataView(packet)
      if (packet.byteLength < 5) return
      const kind = view.getUint8(0)
      const ptsMs = view.getUint32(1, false)
      const payload = packet.slice(5)
      if (kind === 1) {
        if (mediaStart === null) {
          pendingAudio.push([ptsMs, payload])
          startWhenBuffered()
          return
        }
        scheduleAudio(ptsMs, payload)
      } else if (kind === 2) {
        latestVideoPts = Math.max(latestVideoPts, ptsMs)
        void drawAt(ptsMs, payload)
        startWhenBuffered()
      } else if (kind === 3) {
        ended = true
        const finishIn = Math.max(0, finalAudioAt - context.currentTime) * 1000 + 80
        window.setTimeout(() => {
          if (ended) {
            stopRealtime()
            setAudioLevel(0.13)
            setState('ready')
          }
        }, finishIn)
      }
    }
    socket.onerror = () => {
      stopRealtime()
      setState('ready')
    }
  }

  const stopListening = () => {
    recognitionRef.current?.stop()
    recognitionRef.current = null
    stopMedia(mediaRef.current)
    mediaRef.current = null
    setAudioLevel(0.14)
  }

  const submitTurn = async (rawText: string) => {
    const text = rawText.trim()
    if (!text || !sessionId) return
    stopListening()
    setInterim('')
    setDraft('')
    const turnId = `user-${Date.now()}`
    setCaptions((items) => [...items, { id: turnId, role: 'user', text, at: new Date() }])
    setState('thinking')
    const motionPlan: MotionPlan = {
      expression,
      head: { yaw_deg: headYaw, pitch_deg: 0, roll_deg: 0 },
      // Ditto v0.1 turns gaze intent into a small head cue. Independent eye
      // gaze is intentionally not advertised until it is calibrated.
      gaze: { x: 0, y: 0 },
      ...(nodQueued ? { nod: { start_ms: 320, duration_ms: 460, amplitude_deg: 5 } } : {}),
    }
    setNodQueued(false)
    try {
      const result = apiOnline ? await api.sendTurn(sessionId, text, motionPlan) : localTurn(text, avatar)
      if (!mountedRef.current) return
      setCaptions((items) => [...items, { id: result.turn_id, role: 'assistant', text: result.assistant_text, at: new Date() }])
      setLastAppliedMotion(result.renderer.applied_motion ?? motionPlan)
      setState('speaking')
      const video = mediaUrl(result.renderer.stream_url)
      if (result.renderer.stream_url?.startsWith('/avatar-stream/')) {
        setRenderedVideo(undefined)
        setRenderedAudio(undefined)
        setStreamReady(false)
        startRealtime(result.renderer.stream_url)
      } else if (video) {
        setRenderedVideo(video)
        setRenderedAudio(mediaUrl(result.renderer.audio_url))
        setStreamReady(!video.includes('/live-media/'))
        setAudioLevel(0.5)
      } else {
        speak(result, avatar.voice, setState, setAudioLevel)
      }
    } catch (error) {
      if (!mountedRef.current) return
      const message = error instanceof Error ? error.message : '응답을 생성하지 못했습니다.'
      setCaptions((items) => [...items, { id: `error-${Date.now()}`, role: 'assistant', text: message, at: new Date() }])
      setState('ready')
    }
  }

  const startListening = async () => {
    if (state === 'speaking' && sessionId) await interrupt()
    if (muted || state === 'thinking' || !sessionId) return
    setState('listening')
    try {
      await beginMedia(mediaRef, setAudioLevel)
    } catch {
      // The text composer remains a complete fallback when microphone permission is denied.
    }
    const Constructor = (window as unknown as { SpeechRecognition?: SpeechRecognitionConstructor; webkitSpeechRecognition?: SpeechRecognitionConstructor }).SpeechRecognition
      ?? (window as unknown as { webkitSpeechRecognition?: SpeechRecognitionConstructor }).webkitSpeechRecognition
    if (!Constructor) {
      stopListening()
      setState('ready')
      return
    }
    const recognition = new Constructor()
    recognition.lang = 'ko-KR'
    recognition.continuous = false
    recognition.interimResults = true
    recognition.onresult = (event) => {
      let finalText = ''
      let partial = ''
      for (let index = 0; index < event.results.length; index += 1) {
        const result = event.results[index]
        if (result.isFinal) finalText += result[0].transcript
        else partial += result[0].transcript
      }
      setInterim(partial)
      if (finalText) void submitTurn(finalText)
    }
    recognition.onerror = () => {
      if (mountedRef.current) setState('ready')
    }
    recognition.onend = () => {
      if (mountedRef.current) {
        stopMedia(mediaRef.current)
        mediaRef.current = null
      }
    }
    recognitionRef.current = recognition
    recognition.start()
  }

  const interrupt = async () => {
    window.speechSynthesis?.cancel()
    stopListening()
    stopRealtime()
    if (sessionId && apiOnline) await api.interrupt(sessionId).catch(() => undefined)
    setState('ready')
  }

  const toggleCamera = async () => {
    if (cameraEnabled) {
      stopCamera(cameraStreamRef.current)
      cameraStreamRef.current = null
      setCameraEnabled(false)
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } }, audio: false })
      cameraStreamRef.current = stream
      if (cameraVideoRef.current) {
        cameraVideoRef.current.srcObject = stream
        await cameraVideoRef.current.play()
      }
      setCameraError(null)
      setCameraEnabled(true)
    } catch {
      setCameraError('카메라 권한을 허용하지 못했습니다. 영상은 이 브라우저에서만 미리보기로 사용됩니다.')
      setCameraEnabled(false)
    }
  }

  const isSpeaking = state === 'speaking'
  const stateLabel: Record<LiveState, string> = { connecting: '연결 중', ready: '대화 준비됨', listening: '듣는 중', transcribing: '음성을 정리 중', thinking: '생각 중', speaking: '말하는 중', reconnecting: '다시 연결 중', error: '연결 문제' }
  const lastAssistant = [...captions].reverse().find((item) => item.role === 'assistant')
  return (
    <div className="live-layout">
      <section className="live-stage">
        <div className="live-stage-top"><div><span className="eyebrow"><Radio size={14} /> LIVE · AI GENERATED</span><h2>{avatar.name}</h2><p className="render-pipeline">Ditto unified motion · lip · head · expression</p></div><div className={`connection-state ${state}`}><i />{stateLabel[state]}</div></div>
        <div className="video-canvas">
          <div className="stage-glow" />
          <AvatarPortrait avatar={avatar} mode={isSpeaking ? 'talking' : state === 'listening' ? 'listening' : 'idle'} level={audioLevel} large />
          {realtimeActive ? <canvas ref={realtimeCanvasRef} className="rendered-avatar-video" aria-label={`${avatar.name} 실시간 아바타 영상`} /> : renderedVideo && (renderedVideo.includes('/live-media/') ? <img className="rendered-avatar-video" src={renderedVideo} alt={`${avatar.name} 실시간 아바타 영상`} onLoad={() => setStreamReady(true)} onError={() => { setRenderedVideo(undefined); setStreamReady(true) }} /> : <video className="rendered-avatar-video" src={renderedVideo} autoPlay playsInline onEnded={() => { setRenderedVideo(undefined); setAudioLevel(0.13); setState('ready') }} onError={() => { setRenderedVideo(undefined); setState('ready') }} />)}
          {renderedAudio && <audio ref={renderedAudioRef} src={renderedAudio} preload="auto" onEnded={() => { setRenderedAudio(undefined); setRenderedVideo(undefined); setStreamReady(false); setAudioLevel(0.13); setState('ready') }} onError={() => { setRenderedAudio(undefined); setRenderedVideo(undefined); setStreamReady(false); setAudioLevel(0.13); setState('ready') }} />}
          <div className={`camera-pip ${cameraEnabled ? 'visible' : ''}`}>
            <video ref={cameraVideoRef} muted playsInline aria-label="내 카메라 로컬 미리보기" />
            <span><Camera size={11} /> 로컬 미리보기</span>
          </div>
          <div className="ai-watermark"><Sparkles size={13} /> AI AVATAR</div>
          <div className="video-bottom"><div className="avatar-nameplate"><span className="avatar-mini">{initials(avatar.name)}</span><div><strong>{avatar.name}</strong><small>{avatar.persona}</small></div></div><div className="engine-badge"><span className="metric-dot mint" /> {avatar.engine === 'remote' ? 'Ditto controlled · GPU' : '브라우저 미리보기'}</div></div>
        </div>
        <div className="stage-controls"><button className="round-control" aria-label={muted ? '마이크 켜기' : '마이크 끄기'} onClick={() => { setMuted((value) => !value); if (!muted) stopListening() }}>{muted ? <MicOff size={19} /> : <Mic size={19} />}</button><button className={`talk-button ${state === 'listening' ? 'active' : ''}`} disabled={state === 'connecting' || state === 'thinking'} onClick={() => { if (state === 'listening') stopListening(); else void startListening() }}>{state === 'listening' ? <><Pause size={17} /> 듣기 중지</> : isSpeaking ? <><Mic size={17} /> 끼어들어 말하기</> : <><Mic size={17} /> 길게 눌러 말하기</>}</button><button className={`round-control ${cameraEnabled ? 'active-camera' : ''}`} aria-label={cameraEnabled ? '카메라 끄기' : '카메라 켜기'} onClick={() => void toggleCamera()}>{cameraEnabled ? <Camera size={19} /> : <CameraOff size={19} />}</button><button className="round-control" aria-label="대화 종료" onClick={onExit}><X size={20} /></button></div>
        <div className="ditto-control-deck" aria-label="Ditto 동작 제어">
          <div className="control-deck-head"><div><span className="eyebrow subtle">DITTO MOTION PLAN</span><strong>다음 응답의 동작</strong></div><small>안전 범위 내에서 worker에 전달</small></div>
          <div className="motion-control-row"><div className="control-group"><span>표정 의도</span><div className="segmented-control">{(['neutral', 'warm', 'concern'] as ExpressionIntent[]).map((item) => <button key={item} className={expression === item ? 'active' : ''} onClick={() => setExpression(item)}>{item === 'neutral' ? '중립' : item === 'warm' ? '따뜻함' : '공감'}</button>)}</div></div><div className="control-group"><span>고개 방향</span><div className="pose-stepper"><button onClick={() => setHeadYaw((value) => Math.max(-12, value - 3))}>←</button><strong>{headYaw > 0 ? `+${headYaw}` : headYaw}°</strong><button onClick={() => setHeadYaw((value) => Math.min(12, value + 3))}>→</button></div></div><div className="control-group nod-control"><span>경청 nod</span><button className={nodQueued ? 'nod-armed' : ''} onClick={() => setNodQueued((value) => !value)}>{nodQueued ? '다음 응답에 적용' : '작은 nod 예약'}</button></div></div>
          <p>카메라 영상은 현재 이 브라우저에서만 미리보기로 사용합니다. 시선은 v0.1에서 작은 head cue로만 반영하며, 독립 eye-gaze 제어는 calibration 뒤 활성화합니다.</p>
        </div>
        <div className="motion-status" aria-label="아바타 렌더링 파이프라인 상태"><span><i /> 음성 → unified motion</span><b>→</b><span><i /> pose · expression · lip</span><b>→</b><span><i /> Ditto online stream</span>{lastAppliedMotion && <span className="motion-applied">적용: {lastAppliedMotion.expression}{lastAppliedMotion.nod ? ' · nod' : ''}</span>}</div>
        {interim && <div className="interim-caption"><AudioLines size={16} /><span>{interim}</span></div>}
        {cameraError && <div className="camera-note"><CameraOff size={14} /> {cameraError}</div>}
      </section>
      <aside className="conversation-panel">
        <div className="conversation-header"><div><span className="eyebrow subtle">LIVE CAPTIONS</span><h3>대화</h3></div><button className="icon-button" aria-label="세션 정보"><CircleHelp size={18} /></button></div>
        <div className="privacy-banner"><ShieldCheck size={15} /><span>오디오와 대화 기록은 이 데모에서 저장하지 않습니다.</span></div>
        <div className="transcript-list">
          {captions.length === 0 ? <div className="empty-transcript"><span><MessageSquareText size={25} /></span><strong>대화를 시작해 보세요</strong><p>마이크 버튼을 누르거나 아래에 메시지를 입력하세요.</p></div> : captions.map((item) => <div key={item.id} className={`message ${item.role}`}><span className="message-avatar">{item.role === 'assistant' ? <Sparkles size={13} /> : 'J'}</span><div><small>{item.role === 'assistant' ? `${avatar.name} · AI Avatar` : '나'}</small><p>{item.text}</p></div></div>)}
          {state === 'thinking' && <div className="message assistant loading-message"><span className="message-avatar"><Sparkles size={13} /></span><div><small>{avatar.name} · AI Avatar</small><p><i /><i /><i /></p></div></div>}
        </div>
        <form className="composer" onSubmit={(event) => { event.preventDefault(); void submitTurn(draft) }}><textarea value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="메시지 입력…" rows={1} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void submitTurn(draft) } }} /><button type="submit" disabled={!draft.trim() || state === 'thinking'} aria-label="메시지 보내기"><SendHorizontal size={17} /></button></form>
        <div className="caption-footnote"><span><span className="keycap">↵</span> 보내기</span>{voiceSupported ? <span><Mic size={13} /> 음성 인식 사용 가능</span> : <span>텍스트 대화 사용 가능</span>}</div>
        {lastAssistant && <button className="replay-button" onClick={() => speak({ turn_id: lastAssistant.id, assistant_text: lastAssistant.text, visemes: [], renderer: { mode: 'preview', status: 'replay' } }, avatar.voice, setState, setAudioLevel)}><Play size={14} /> 마지막 답변 다시 듣기</button>}
      </aside>
    </div>
  )
}

function AvatarPortrait({ avatar, mode, level = 0.15, large = false }: { avatar: Avatar; mode: 'idle' | 'listening' | 'talking'; level?: number; large?: boolean }) {
  const image = sourceUrl(avatar)
  const mouthScale = mode === 'talking' ? 0.75 + Math.min(level, 1) * 1.5 : 0.55
  return <div className={`portrait ${large ? 'large' : ''} ${mode}`} style={{ '--mouth-scale': mouthScale } as React.CSSProperties}>
    {image ? <img src={image} alt={`${avatar.name} 아바타 사진`} /> : <div className="portrait-illustration" aria-label={`${avatar.name} 데모 아바타`}><div className="portrait-halo" /><div className="portrait-hair" /><div className="portrait-neck" /><div className="portrait-face"><i className="brow left" /><i className="brow right" /><i className="eye left" /><i className="eye right" /><i className="nose" /><i className="mouth" /></div><div className="portrait-shirt" /></div>}
    <div className="portrait-sheen" />
  </div>
}

async function waitForAvatar(avatarId: string): Promise<Avatar> {
  const attempts = 20
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    await new Promise((resolve) => window.setTimeout(resolve, 1_000))
    const avatar = await api.avatar(avatarId)
    if (avatar.status !== 'preparing') return avatar
  }
  throw new ApiError('아바타 준비 시간이 초과되었습니다. 라이브러리에서 상태를 다시 확인해 주세요.', 504)
}

function supportsSpeechRecognition() {
  if (typeof window === 'undefined') return false
  const browser = window as unknown as { SpeechRecognition?: SpeechRecognitionConstructor; webkitSpeechRecognition?: SpeechRecognitionConstructor }
  return Boolean(browser.SpeechRecognition ?? browser.webkitSpeechRecognition)
}

function speak(result: TurnResponse, voiceName: string, setState: (value: LiveState) => void, setAudioLevel: (value: number) => void) {
  const utterance = new SpeechSynthesisUtterance(result.assistant_text)
  utterance.lang = voiceName.includes('Korean') ? 'ko-KR' : 'en-US'
  utterance.rate = 1.02
  utterance.pitch = 1
  const voices = window.speechSynthesis?.getVoices?.() ?? []
  utterance.voice = voices.find((voice) => voice.lang.startsWith(utterance.lang.slice(0, 2))) ?? null
  let timer = 0
  const animate = () => {
    setAudioLevel(0.2 + Math.random() * 0.62)
    timer = window.setTimeout(animate, 110)
  }
  utterance.onstart = () => { setState('speaking'); animate() }
  utterance.onend = () => { window.clearTimeout(timer); setAudioLevel(0.13); setState('ready') }
  utterance.onerror = () => { window.clearTimeout(timer); setAudioLevel(0.13); setState('ready') }
  if ('speechSynthesis' in window) window.speechSynthesis.speak(utterance)
  else { setState('ready'); setAudioLevel(0.13) }
}

async function beginMedia(ref: React.MutableRefObject<{ stream: MediaStream; context: AudioContext; frame: number } | null>, setLevel: (value: number) => void) {
  if (ref.current) return
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } })
  const context = new AudioContext()
  const source = context.createMediaStreamSource(stream)
  const analyser = context.createAnalyser()
  analyser.fftSize = 256
  source.connect(analyser)
  const values = new Uint8Array(analyser.frequencyBinCount)
  const update = () => {
    analyser.getByteTimeDomainData(values)
    const level = Math.min(1, Math.sqrt(values.reduce((sum, value) => sum + Math.pow((value - 128) / 128, 2), 0) / values.length) * 3.6)
    setLevel(Math.max(0.1, level))
    if (ref.current) ref.current.frame = requestAnimationFrame(update)
  }
  ref.current = { stream, context, frame: requestAnimationFrame(update) }
}

function stopMedia(media: { stream: MediaStream; context: AudioContext; frame: number } | null) {
  if (!media) return
  cancelAnimationFrame(media.frame)
  media.stream.getTracks().forEach((track) => track.stop())
  void media.context.close()
}

function stopCamera(stream: MediaStream | null) {
  stream?.getTracks().forEach((track) => track.stop())
}

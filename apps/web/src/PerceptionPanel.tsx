import {forwardRef,useEffect,useImperativeHandle,useRef,useState} from 'react'
import {api} from './api'
import type {TurnResponse} from './types'
import {PerceptionResponsiveness} from './perceptionResponsiveness'

export type PerceptionStatus={state:string;error?:string;observation?:Record<string,unknown>;preview_available?:boolean;capture?:{backend:string;device_fps:number};performance?:{cpu_core_percent:number;processing_ms:number;actual_fps:number}}
export type PerceptionHandle={beginSpeech:()=>void;endSpeech:()=>void;turnOptions:()=>{use_observation:boolean;observation_window_ms:number;observation_speaking:boolean;observation_end_age_ms:number};showTurn:(result:TurnResponse)=>void}

export const PerceptionPanel=forwardRef<PerceptionHandle,{sessionId:string;online:boolean}>(function PerceptionPanel({sessionId,online},ref){
  const [enabled,setEnabled]=useState(false),[busy,setBusy]=useState(false)
  const [status,setStatus]=useState<PerceptionStatus>({state:'off'}),[error,setError]=useState('')
  const [preview,setPreview]=useState(''),[lastTurn,setLastTurn]=useState<TurnResponse|null>(null)
  const enabledRef=useRef(false),speechStart=useRef<number|null>(null),speechEnd=useRef<number|null>(null)
  const generation=useRef(0)
  const [uiPerf,setUiPerf]=useState({fps:0,p95:0,max:0,foreground:false})
  useEffect(()=>{
    let frame=0,previous=0,at=0,gaps:number[]=[]
    const tick=(now:number)=>{
      const foreground=!document.hidden&&document.hasFocus()
      if(foreground&&previous)gaps.push(now-previous)
      if(!foreground)gaps=[]
      previous=now
      if(now-at>=2000){
        if(gaps.length){const sorted=[...gaps].sort((a,b)=>a-b);setUiPerf({fps:Math.round(1000/(gaps.reduce((a,b)=>a+b,0)/gaps.length)),p95:Math.round(sorted[Math.floor((sorted.length-1)*.95)]),max:Math.round(sorted.at(-1)!),foreground});gaps=[]}
        else setUiPerf({fps:0,p95:0,max:0,foreground})
        at=now
      }
      frame=requestAnimationFrame(tick)
    }
    frame=requestAnimationFrame(tick)
    return()=>cancelAnimationFrame(frame)
  },[])
  const latestUiPerf=useRef(uiPerf);latestUiPerf.current=uiPerf
  useEffect(()=>{
    if(!enabled||!sessionId)return
    const timer=window.setInterval(()=>{
      const sample=latestUiPerf.current
      if(sample.foreground)void api.telemetry({turn_id:`perception-${sessionId}`,event:'perception_ui_sample',elapsed_ms:Math.round(performance.now()),details:{...sample}}).catch(()=>{})
    },5000)
    return()=>clearInterval(timer)
  },[enabled,sessionId])
  const [expanded,setExpanded]=useState(false),[showPreview,setShowPreview]=useState(false),[showDetails,setShowDetails]=useState(false)
  const previewWanted=useRef(false)
  previewWanted.current=expanded&&showPreview
  useImperativeHandle(ref,()=>({
    beginSpeech(){speechStart.current=performance.now();speechEnd.current=null},
    endSpeech(){if(speechStart.current!==null&&speechEnd.current===null)speechEnd.current=performance.now()},
    turnOptions(){
      const start=speechStart.current,end=speechEnd.current??performance.now()
      // Discard abandoned speech captures rather than attributing them to a later typed turn.
      const speaking=start!==null&&performance.now()-end<5000
      speechStart.current=null;speechEnd.current=null
      return {use_observation:enabledRef.current,observation_window_ms:speaking?Math.min(120000,Math.max(200,Math.round(end-start))):3000,observation_speaking:speaking,observation_end_age_ms:speaking?Math.min(5000,Math.round(performance.now()-end)):0}
    },
    showTurn:setLastTurn,
  }))
  useEffect(()=>{
    generation.current++
    setEnabled(false);enabledRef.current=false;setPreview('');setStatus({state:'off'});setLastTurn(null);setBusy(false);setError('');speechStart.current=null;speechEnd.current=null
    return ()=>{generation.current++;const wasEnabled=enabledRef.current;enabledRef.current=false;if(wasEnabled&&sessionId&&online)void api.perception(sessionId,'stop').catch(()=>{})}
  },[sessionId,online])
  useEffect(()=>{
    if(!enabled||!sessionId)return
    const guard=new PerceptionResponsiveness()
    let frame=0
    const tick=(now:number)=>{
      if(guard.sample(now,!document.hidden&&document.hasFocus())){
        enabledRef.current=false;setEnabled(false)
        setError('화면 갱신 지연이 반복되어 얼굴 분석을 자동으로 중지했습니다. 카메라/드라이버 경로 점검이 필요합니다.')
        void api.perception(sessionId,'stop').catch(()=>{})
        void api.telemetry({turn_id:`perception-${sessionId}`,event:'perception_ui_stall',elapsed_ms:Math.round(now),details:{action:'camera_stopped',reason:'4 frame gaps >250ms within 5s'}}).catch(()=>{})
        return
      }
      frame=requestAnimationFrame(tick)
    }
    frame=requestAnimationFrame(tick)
    const exit=()=>{enabledRef.current=false;setEnabled(false);void api.perceptionStopOnExit(sessionId).catch(()=>{})}
    window.addEventListener('pagehide',exit)
    return()=>{cancelAnimationFrame(frame);window.removeEventListener('pagehide',exit)}
  },[enabled,sessionId])
  useEffect(()=>{
    if(!enabled||!sessionId)return
    let cancelled=false,timer=0,url=''
    const poll=async()=>{
      try{
        const next=await api.perception(sessionId,'status')
        if(cancelled)return
        if(!document.hidden)setStatus(next)
        if(next.error)throw new Error(next.error)
        if(previewWanted.current&&!document.hidden){
          const blob=await api.perceptionPreview(sessionId)
          if(cancelled)return
          if(blob.size){const nextUrl=URL.createObjectURL(blob);if(url)URL.revokeObjectURL(url);url=nextUrl;setPreview(url)}
        }else if(url){
          URL.revokeObjectURL(url);url='';setPreview('')
        }
      }catch(e){if(!cancelled){setError(e instanceof Error?e.message:'얼굴 분석 연결 오류');setEnabled(false);enabledRef.current=false;void api.perception(sessionId,'stop').catch(()=>{})}}
      if(!cancelled)timer=window.setTimeout(()=>void poll(),document.hidden?3000:1000)
    }
    void poll()
    return ()=>{cancelled=true;clearTimeout(timer);if(url)URL.revokeObjectURL(url);setPreview('')}
  },[enabled,sessionId])
  const toggle=async()=>{
    const version=generation.current
    setBusy(true);setError('')
    try{
      if(enabled){enabledRef.current=false;setEnabled(false);setStatus({state:'off'});setLastTurn(null);await api.perception(sessionId,'stop')}
      else{
        const next=await api.perception(sessionId,'start')
        if(version!==generation.current){void api.perception(sessionId,'stop').catch(()=>{});return}
        enabledRef.current=true;setEnabled(true);setStatus(next)
      }
    }catch(e){if(version===generation.current)setError(e instanceof Error?e.message:'카메라 연결 오류')}
    finally{if(version===generation.current)setBusy(false)}
  }
  return <details className="affect-test-panel perception-panel" onToggle={e=>setExpanded(e.currentTarget.open)}>
    <summary>사용자 얼굴 관측 · {enabled?status.state:'OFF'}</summary>
    <p>{uiPerf.foreground?`브라우저 화면 갱신: ${uiPerf.fps} FPS · 프레임 간격 p95 ${uiPerf.p95} ms · 최대 ${uiPerf.max} ms`:'비활성 창 · 브라우저 절전 지연은 성능 진단에서 제외합니다.'}</p>
    <p>사용자 1명 · 켜면 로컬 카메라 분석을 시작합니다. 원본 영상은 저장·외부 전송하지 않으며, Realtime에서는 짧은 얼굴 단서 요약을 응답 모델에 전달합니다.</p>
    <button type="button" className="secondary-button" disabled={!online||!sessionId||busy} onClick={()=>void toggle()}>{busy?'연결 중…':enabled?'얼굴 분석 끄기':'얼굴 분석 켜기'}</button>
    {error&&<p role="alert">{error}</p>}
    {enabled&&expanded&&<>
      <p>로컬 분석 최대 5 FPS · 관측 {String(status.observation?.label??status.observation?.reason??'준비 중')} · 처리 {String(status.observation?.inference_ms??0)} ms</p>
      {status.capture?.backend&&<small>캡처 {status.capture.backend} · 장치 {status.capture.device_fps} FPS · 화면 지연 감지 시 자동 중지</small>}
      {status.performance?.actual_fps!==undefined&&<small>실측 {status.performance.actual_fps} FPS · CPU {status.performance.cpu_core_percent}% (코어 1개 기준) · 프레임 처리 {status.performance.processing_ms} ms</small>}
      <label><input type="checkbox" checked={showPreview} onChange={e=>setShowPreview(e.target.checked)}/> 미리보기 (1 FPS · 선택 사항)</label>
      {showPreview&&preview&&<img src={preview} alt="로컬 사용자 카메라 미리보기" width="240" height="180" style={{display:'block',transform:'scaleX(-1)'}}/>}
      <details onToggle={e=>setShowDetails(e.currentTarget.open)}><summary>관측 상세 수치</summary>{showDetails&&<pre style={{whiteSpace:'pre-wrap',maxHeight:180,overflow:'auto'}}>{JSON.stringify(status.observation,null,2)}</pre>}</details>
    </>}
    {lastTurn&&<details><summary>최근 턴 관측 → 적용 감정 · {lastTurn.turn_id}</summary><pre style={{whiteSpace:'pre-wrap',maxHeight:220,overflow:'auto'}}>{JSON.stringify({observation:lastTurn.user_observation,applied:lastTurn.renderer.applied_motion},null,2)}</pre></details>}
    <small>표정 점수는 실제 감정의 확정값이 아닙니다. WAV Auto는 얼굴 표정 매핑 테스트이며 AI 호출은 없습니다.</small>
  </details>
})

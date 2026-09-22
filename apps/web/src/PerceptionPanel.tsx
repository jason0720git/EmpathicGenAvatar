import {forwardRef,useEffect,useImperativeHandle,useRef,useState} from 'react'
import {api} from './api'
import type {TurnResponse} from './types'

export type PerceptionStatus={state:string;error?:string;observation?:Record<string,unknown>;preview_available?:boolean}
export type PerceptionHandle={beginSpeech:()=>void;endSpeech:()=>void;turnOptions:()=>{use_observation:boolean;observation_window_ms:number;observation_speaking:boolean;observation_end_age_ms:number};showTurn:(result:TurnResponse)=>void}

export const PerceptionPanel=forwardRef<PerceptionHandle,{sessionId:string;online:boolean}>(function PerceptionPanel({sessionId,online},ref){
  const [enabled,setEnabled]=useState(false),[busy,setBusy]=useState(false)
  const [status,setStatus]=useState<PerceptionStatus>({state:'off'}),[error,setError]=useState('')
  const [preview,setPreview]=useState(''),[lastTurn,setLastTurn]=useState<TurnResponse|null>(null)
  const enabledRef=useRef(false),speechStart=useRef<number|null>(null),speechEnd=useRef<number|null>(null)
  const generation=useRef(0)
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
    let cancelled=false,timer=0,url=''
    const poll=async()=>{
      try{
        const next=await api.perception(sessionId,'status')
        if(cancelled)return
        setStatus(next)
        if(next.error)throw new Error(next.error)
        if(next.preview_available){
          const blob=await api.perceptionPreview(sessionId)
          if(cancelled)return
          const nextUrl=URL.createObjectURL(blob);if(url)URL.revokeObjectURL(url);url=nextUrl;setPreview(url)
        }
      }catch(e){if(!cancelled){setError(e instanceof Error?e.message:'얼굴 분석 연결 오류');setEnabled(false);enabledRef.current=false;void api.perception(sessionId,'stop').catch(()=>{})}}
      if(!cancelled)timer=window.setTimeout(()=>void poll(),1000)
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
  return <details className="affect-test-panel perception-panel">
    <summary>사용자 얼굴 관측 · {enabled?status.state:'OFF'}</summary>
    <p>사용자 1명 · 켜면 로컬 카메라 분석을 시작합니다. 원본 영상은 저장·외부 전송하지 않으며, Realtime에서는 짧은 얼굴 단서 요약을 응답 모델에 전달합니다.</p>
    <button type="button" className="secondary-button" disabled={!online||!sessionId||busy} onClick={()=>void toggle()}>{busy?'연결 중…':enabled?'얼굴 분석 끄기':'얼굴 분석 켜기'}</button>
    {error&&<p role="alert">{error}</p>}
    {preview&&<img src={preview} alt="로컬 사용자 카메라 미리보기" width="240" style={{display:'block',transform:'scaleX(-1)'}}/>}
    {enabled&&<pre style={{whiteSpace:'pre-wrap',maxHeight:180,overflow:'auto'}}>{JSON.stringify(status.observation,null,2)}</pre>}
    {lastTurn&&<details><summary>최근 턴 관측 → 적용 감정 · {lastTurn.turn_id}</summary><pre style={{whiteSpace:'pre-wrap',maxHeight:220,overflow:'auto'}}>{JSON.stringify({observation:lastTurn.user_observation,applied:lastTurn.renderer.applied_motion},null,2)}</pre></details>}
    <small>표정 점수는 실제 감정의 확정값이 아닙니다. WAV 모드에서는 관측·로그만 검사하며 AI 호출은 없습니다.</small>
  </details>
})

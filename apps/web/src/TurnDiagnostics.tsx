import {useEffect,useRef,useState} from 'react'
import {api,ApiError} from './api'

type Event=Record<string,unknown>
const names:Record<string,string>={
  'turn.requested':'요청 접수', 'observation.snapshot':'카메라 관측 (로컬)',
  'llm.input':'LLM 전송 정보', 'tool.started':'감정 tool call 요청',
  'tool.completed':'감정 tool call 반환', 'tool.skipped':'tool call 생략',
  'audio.started':'음성 생성 시작', 'llm.completed':'LLM 답변 완료',
  'behavior.decision':'Ditto 표정·동작 파라미터', 'renderer.completed':'렌더러 적용 확인',
  'renderer.failed':'렌더러 오류', 'llm.failed':'LLM 오류', 'turn.failed':'요청 오류',
  'wav_test.input':'고정 WAV 입력', 'caption.final':'최종 발화 텍스트',
}
function summary(e:Event):string{
  if(e.event==='renderer.completed'){
    const r=e.renderer as {applied_motion?:{expression?:string;intensity?:number};status?:string}
    return r.applied_motion?`${r.applied_motion.expression} · ${Math.round((r.applied_motion.intensity??0)*100)}% (worker 응답)`:`${r.status??'완료'} · 실제 적용 값 미제공 (요청 파라미터와 구분)`
  }
  const behavior=e.behavior as {affect?:{emotion:string;intensity:number};source?:string}|undefined
  const affect=(e.arguments??e.affect??behavior?.affect) as {emotion:string;intensity:number}|undefined
  if(affect)return `${affect.emotion} · ${Math.round(affect.intensity*100)}%${behavior?.source?' · '+behavior.source:''}${e.reason?' · '+e.reason:''}`
  if(e.event==='observation.snapshot'){
    const o=e.observation as {status:string;label:string;reason:string;age_ms:number;valid_ratio:number}
    return o.status==='observed'?`${o.label} · 관측 유효율 ${Math.round(o.valid_ratio*100)}% · ${o.age_ms}ms 전`:`사용 안 함 · ${o.reason}`
  }
  if(e.event==='llm.input')return e.facial_context?`얼굴 요약: ${e.facial_context}`:'얼굴 단서 없음 · 대화 텍스트/기존 대화 문맥만 사용'
  return String(e.assistant_text??e.error??e.reason??e.name??e.mode??'')
}

export function TurnDiagnostics({sessionId,turnId,online,active,error}:{sessionId:string;turnId:string;online:boolean;active:boolean;error:string}){
  const [events,setEvents]=useState<Event[]>([]),[status,setStatus]=useState('')
  const activeRef=useRef(active);activeRef.current=active
  useEffect(()=>{
    setEvents([]);setStatus('')
    if(!online||!sessionId||!turnId)return
    let cancelled=false,timer=0,after=0,idlePolls=0
    const started=Date.now()
    const poll=async()=>{
      try{
        if(!document.hidden){
          const packet=await api.liveDiagnostics(sessionId,turnId,after)
          if(cancelled)return
          if(packet.events.length){
            after=Math.max(after,...packet.events.map(e=>Number(e.sequence)))
            setEvents(rows=>[...rows,...packet.events].slice(-64));idlePolls=0
          }else idlePolls++
          setStatus('실시간 · 최대 1초 간격')
        }
      }catch(e){
        if(cancelled)return
        setStatus(e instanceof Error?e.message:'진단 연결 오류')
        if(e instanceof ApiError&&(e.status===403||e.status===404))return
      }
      // Single-flight, bounded polling. No JSONL scan or parent video rerender.
      if(!cancelled&&Date.now()-started<180000&&(activeRef.current||idlePolls<3))timer=window.setTimeout(()=>void poll(),document.hidden?3000:1000)
      else if(!cancelled)setStatus('수집 완료')
    }
    void poll()
    return()=>{cancelled=true;clearTimeout(timer)}
  },[sessionId,turnId,online])
  return <section className="turn-diagnostics" aria-label="실시간 응답 진단">
    <h4>응답 진단 <small>{turnId?status:'대기 중'}</small></h4>
    <p>관측 → LLM 입력 → tool 결과 → Ditto 적용. 내부 사고 과정은 제공되지 않으며, 아래는 실제 입출력입니다.</p>
    {error&&<p role="alert">{error}</p>}
    <div className="diagnostic-events">{events.map((event)=><article key={String(event.sequence)}>
      <strong>{names[String(event.event)]??String(event.event)}</strong><time>{String(event.at).slice(11,19)} UTC</time>
      <p>{summary(event)}</p>
      <details><summary>상세 JSON</summary><pre>{JSON.stringify(event,null,2)}</pre></details>
    </article>)}</div>
    <small>원본 카메라 영상은 LLM에 전송하지 않습니다. WAV는 AI 호출 없음. 과거 전체 로그는 ‘로그 JSON 다운로드’에서 확인하세요.</small>
  </section>
}

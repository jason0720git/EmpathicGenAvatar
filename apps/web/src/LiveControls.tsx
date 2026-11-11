import { useEffect, useRef, useState } from 'react'

type Target = {expression:string;intensity:number;head:{yaw_deg:number;pitch_deg:number;roll_deg:number};gaze:{x:number;y:number}}
const initial:Target={expression:'neutral',intensity:.4,head:{yaw_deg:0,pitch_deg:0,roll_deg:0},gaze:{x:0,y:0}}
type ControlTrace = (phase: string, details: Record<string, string | number>) => void
export function LiveControls({socket,displayedPts,baseline=initial,onTrace}:{socket:WebSocket|null;displayedPts:()=>number;baseline?:Target;onTrace?:ControlTrace}) {
  const [target,setTarget]=useState<Target>(initial)
  const [status,setStatus]=useState('발화가 시작되면 조절할 수 있습니다.')
  const [connected,setConnected]=useState(false)
  const seq=useRef(0), pending=useRef<{seq:number;pts:number}|null>(null)
  const readPts=useRef(displayedPts); readPts.current=displayedPts
  const trace=useRef(onTrace); trace.current=onTrace
  const base=useRef(baseline);base.current={expression:baseline.expression,intensity:baseline.intensity,head:{...baseline.head},gaze:{x:baseline.gaze.x,y:baseline.gaze.y}}
  useEffect(()=>{
    seq.current=0;pending.current=null;setTarget(base.current)
    setConnected(socket?.readyState===1)
    setStatus(socket?.readyState===1?'현재 발화에 적용할 값을 선택하세요.':'발화가 시작되면 조절할 수 있습니다.')
    if(!socket)return
    const receive=(event:MessageEvent)=>{
      if(typeof event.data!=='string')return
      try {
        const data=JSON.parse(event.data)
        if(data.type==='control.received'||data.type==='control.applied'||data.type==='control.error'){
          const detail: Record<string, string | number> = {seq: data.seq ?? 0}
          if (typeof data.pts_ms === 'number') detail.pts_ms = data.pts_ms
          if (data.head_deg) Object.assign(detail, data.head_deg)
          if (typeof data.detail === 'string') detail.error = data.detail
          trace.current?.(data.type, detail)
        }
        if(data.type==='control.error'&&data.seq===undefined){
          pending.current=null;setConnected(false);setStatus(`실시간 제어 종료: ${data.detail}`);return
        }
        if(data.seq!==seq.current)return
        if(data.type==='control.received')setStatus(`명령 ${data.seq} 수신 · 생성 대기`)
        if(data.type==='control.applied'){
          pending.current={seq:data.seq,pts:data.pts_ms}
          setStatus(`명령 ${data.seq} 생성 반영 · ${data.pts_ms}ms · 화면 표시 대기`)
        }
        if(data.type==='control.error'){pending.current=null;setStatus(`적용 안 됨: ${data.detail}`)}
      }catch{ /* Unrelated diagnostic message. */ }
    }
    const close=()=>{setConnected(false);if(!pending.current)setStatus('생성 종료 · 이미 생성된 프레임은 변경할 수 없습니다.')}
    socket.addEventListener('message',receive);socket.addEventListener('close',close)
    const timer=window.setInterval(()=>{
      if(pending.current&&readPts.current()>=pending.current.pts){
        trace.current?.('displayed', {seq: pending.current.seq, pts_ms: pending.current.pts, display_pts_ms: readPts.current()})
        setStatus(`명령 ${pending.current.seq} 화면 반영 · ${pending.current.pts}ms부터 부드럽게 전환`)
        pending.current=null
      }
    },80)
    return()=>{clearInterval(timer);socket.removeEventListener('message',receive);socket.removeEventListener('close',close)}
  },[socket])
  const send=(next:Target,reset=false)=>{
    setTarget(next)
    if(socket?.readyState!==1)return
    pending.current=null
    const id=++seq.current
    const changed=Object.fromEntries(Object.entries(next).filter(([key,value])=>JSON.stringify(value)!==JSON.stringify(target[key as keyof Target])))
    socket.send(JSON.stringify(reset?{type:'control.reset',seq:id}:{type:'control',seq:id,...changed}))
    trace.current?.(reset?'reset':'requested', {seq:id, expression:next.expression, intensity:next.intensity,
      ...next.head, gaze_x:next.gaze.x, gaze_y:next.gaze.y, channels:Object.keys(changed).join(',')})
    setStatus(`명령 ${id} 전송`)
  }
  return <details className="live-controls"><summary>발화 중 얼굴·머리·시선 제어</summary>
    <p>현재 답변의 얼굴 움직임을 조절합니다. 반영에는 생성·재생 버퍼만큼 지연이 있습니다.</p>
    <fieldset disabled={!connected}>
      <label>실시간 표정 <select aria-label="실시간 표정" value={target.expression} onChange={e=>send({...target,expression:e.target.value})}>
        {['neutral','happy','sad','surprise','angry','fear','disgust','contempt'].map(value=><option key={value}>{value}</option>)}
      </select></label>
      <label>표정 강도 {target.intensity.toFixed(2)}<input aria-label="실시간 표정 강도" type="range" min="0" max=".8" step=".05" value={target.intensity} onChange={e=>send({...target,intensity:Number(e.target.value)})}/></label>
      {([['yaw_deg','머리 좌우',-6,6],['pitch_deg','머리 상하',-5,5],['roll_deg','머리 기울기',-3,3]] as const).map(([axis,label,min,max])=><label key={axis}>{label} {target.head[axis].toFixed(1)}°<input aria-label={label} type="range" min={min} max={max} step=".5" value={target.head[axis]} onChange={e=>send({...target,head:{...target.head,[axis]:Number(e.target.value)}})}/></label>)}
      {([['x','시선 좌우'],['y','시선 상하']] as const).map(([axis,label])=><label key={axis}>{label} {target.gaze[axis].toFixed(2)}<input aria-label={label} type="range" min="-.8" max=".8" step=".05" value={target.gaze[axis]} onChange={e=>send({...target,gaze:{...target.gaze,[axis]:Number(e.target.value)}})}/></label>)}
      <button type="button" onClick={()=>send(base.current,true)}>자동 동작으로 복귀</button>
    </fieldset><small role="status" aria-label="실시간 제어 상태">{status}</small>
  </details>
}

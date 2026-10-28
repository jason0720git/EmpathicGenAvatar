import type {MotionFrame,RendererStats} from './types'

/** Demand-driven original GaussianAvatars GPU rendering, no recorded video. */
export function createOfficialRenderer(container:HTMLElement,_asset:string,getFrame:()=>MotionFrame,
  onReady:(stats:RendererStats)=>void,onProgress:(n:number)=>void,signal?:AbortSignal) {
  return new Promise<{dispose():void;stats():RendererStats;resetView():void}>((resolve,reject)=>{
    const canvas=document.createElement('canvas');canvas.width=640;canvas.height=640
    Object.assign(canvas.style,{width:'100%',height:'100%',objectFit:'contain',background:'white'})
    container.appendChild(canvas)
    const ctx=canvas.getContext('2d')!
    const url=new URL('/gaussian-render/ws',location.href);url.protocol=location.protocol==='https:'?'wss:':'ws:'
    const ws=new WebSocket(url);ws.binaryType='arraybuffer'
    let disposed=false,ready=false,frames=0,sequence=0,fps=0,mark=performance.now(),lastCount=0,timer:ReturnType<typeof setTimeout>
    let renderMs=0,roundTripMs=0,sentAt=0,failure:string|undefined
    const stats=():RendererStats=>({fps,frames,head:true,splats:89021,oralVersion:'official-flame-native',tongue:false,
      eyeOcclusionMode:'official-trained-appearance',renderMs,roundTripMs,error:failure})
    const dispose=()=>{disposed=true;clearTimeout(timer);clearTimeout(timeout);ws.close();canvas.remove()}
    const fail=(message:string)=>{failure=message;if(!ready)reject(new Error(message));else onReady(stats());dispose()}
    const timeout=setTimeout(()=>fail('공식 GPU 렌더러에 연결할 수 없습니다. 8041 서비스 로그를 확인하세요.'),15000)
    const next=()=>{
      if(disposed)return
      if(ready && document.hidden){timer=setTimeout(next,250);return}
      if(ws.readyState===WebSocket.OPEN){sentAt=performance.now();ws.send(JSON.stringify({...getFrame(),sequence:sequence++}))}
    }
    signal?.addEventListener('abort',()=>{if(!ready)reject(new DOMException('Aborted','AbortError'));dispose()},{once:true})
    ws.onopen=()=>{onProgress(.5);next()}
    ws.onerror=()=>fail('공식 GPU 렌더러 연결 오류')
    ws.onclose=()=>{if(!disposed)fail('공식 GPU 렌더러 연결이 종료되었습니다.')}
    ws.onmessage=async event=>{
      if(typeof event.data==='string'){const data=JSON.parse(event.data);renderMs=data.render_ms;return}
      try {
        const bitmap=await createImageBitmap(new Blob([event.data],{type:'image/jpeg'}))
        if(disposed){bitmap.close();return}
        ctx.drawImage(bitmap,0,0);bitmap.close();frames++;roundTripMs=performance.now()-sentAt
        if(performance.now()-mark>=1000){fps=(frames-lastCount)*1000/(performance.now()-mark);lastCount=frames;mark=performance.now()}
        if(!ready){ready=true;clearTimeout(timeout);onProgress(1);onReady(stats());resolve({dispose,stats,resetView:()=>{}})}
        // Exactly one frame in flight: slow GPU cannot accumulate stale lip poses.
        timer=setTimeout(next,Math.max(0,33-(performance.now()-sentAt)))
      } catch {fail('공식 모델 프레임 디코딩 실패')}
    }
  })
}

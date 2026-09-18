// Transient, face-local registration. Unlike a full-canvas transform this
// displacement is exactly zero on every image edge. It is NOT a face rig or
// a persistent stabilizer; native Ditto motion is untouched after handoff.
const smooth = (t:number) => {const v=Math.max(0,Math.min(1,t)); return v*v*(3-2*v)}
export function faceWeight(x:number,y:number) {
  return smooth((x-.12)/.20)*smooth((.88-x)/.20)
    *smooth((y-.02)/.18)*smooth((.9-y)/.3)
}
export function warpPoint(x:number,y:number,dx:number,dy:number,weight:number) {
  const amount=faceWeight(x,y)*weight
  return [x+dx*amount,y+dy*amount] as const
}
type Point=readonly[number,number]
function triangle(ctx:CanvasRenderingContext2D,source:CanvasImageSource,s:Point[],d:Point[],w:number,h:number) {
  const ux=s[1][0]-s[0][0],uy=s[1][1]-s[0][1],vx=s[2][0]-s[0][0],vy=s[2][1]-s[0][1]
  const det=ux*vy-vx*uy
  const dux=d[1][0]-d[0][0],duy=d[1][1]-d[0][1],dvx=d[2][0]-d[0][0],dvy=d[2][1]-d[0][1]
  const a=(dux*vy-dvx*uy)/det,b=(duy*vy-dvy*uy)/det,c=(dvx*ux-dux*vx)/det,e=(dvy*ux-duy*vx)/det
  ctx.save();ctx.beginPath();ctx.moveTo(...d[0]);ctx.lineTo(...d[1]);ctx.lineTo(...d[2]);ctx.closePath();ctx.clip()
  ctx.transform(a,b,c,e,d[0][0]-a*s[0][0]-c*s[0][1],d[0][1]-b*s[0][0]-e*s[0][1])
  ctx.drawImage(source,0,0,w,h);ctx.restore()
}
export function drawFaceRegistration(ctx:CanvasRenderingContext2D,source:CanvasImageSource,dx:number,dy:number,weight:number) {
  if(!weight || (!dx && !dy)) return
  const w=ctx.canvas.width,h=ctx.canvas.height
  const xs=[0,.18,.32,.5,.68,.82,1],ys=[0,.08,.2,.4,.6,.78,1]
  for(let j=0;j<ys.length-1;j++) for(let i=0;i<xs.length-1;i++) {
    const normalized:Point[]=[[xs[i],ys[j]],[xs[i+1],ys[j]],[xs[i+1],ys[j+1]],[xs[i],ys[j+1]]]
    const src=normalized.map(([x,y])=>[x*w,y*h] as Point)
    const dst=normalized.map(([x,y])=>{const p=warpPoint(x,y,dx,dy,weight);return [p[0]*w,p[1]*h] as Point})
    for(const ids of [[0,1,2],[0,2,3]]) triangle(ctx,source,ids.map(k=>src[k]),ids.map(k=>dst[k]),w,h)
  }
}

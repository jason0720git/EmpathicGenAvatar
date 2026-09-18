// Boundary-only geometry handoff. Warp both live images to the same geometry
// BEFORE a short continuous appearance transfer. Never hard-cut at midpoint.
// The original-resolution textures, not tracking thumbnails, are sampled.
export const FLOW_W=128, FLOW_H=160, GRID_W=17, GRID_H=21
const clamp=(x:number,a:number,b:number)=>Math.max(a,Math.min(b,x))
const smooth=(x:number)=>{const t=clamp(x,0,1);return t*t*(3-2*t)}
export const appearanceWeight=(t:number)=>smooth((t-.2)/.6)
export function smoothFlow(current:Float32Array,previous:Float32Array) {
  for(let i=0;i<current.length;i++)current[i]=previous[i]+clamp(.7*(current[i]-previous[i]),-.35,.35)
  return boundFlow(current)
}
const at=(a:Float32Array,x:number,y:number)=>a[clamp(y,0,FLOW_H-1)*FLOW_W+clamp(x,0,FLOW_W-1)]

export type FlowField={xy:Float32Array; reliable:number; residual:number; peak:number}
export function boundFlow(xy:Float32Array) {
  let gradient=0
  for(let y=0;y<GRID_H-1;y++)for(let x=0;x<GRID_W-1;x++){
    const k=(y*GRID_W+x)*2
    for(let a=0;a<2;a++)gradient=Math.max(gradient,(Math.abs(xy[k+2+a]-xy[k+a])+Math.abs(xy[k+GRID_W*2+a]-xy[k+a]))/8)
  }
  // Keep the inverse warp contractive: no folded or inverted cells.
  if(gradient>.6)for(let i=0;i<xy.length;i++)xy[i]*=.6/gradient
  return xy
}
// A regularized patch-displacement field, NOT anatomical landmark tracking.
// Forward A->B correspondences; fixed outer border prevents camera movement.
export function matchGeometry(a:Float32Array,b:Float32Array):FlowField {
  if(a.every((v,i)=>v===b[i])) return {xy:new Float32Array(GRID_W*GRID_H*2),reliable:1,residual:0,peak:0}
  const cost=(x:number,y:number,dx:number,dy:number,r=3)=>{
    let s=0
    for(let j=-r;j<=r;j+=2) for(let i=-r;i<=r;i+=2) {
      const d=at(a,x+i,y+j)-at(b,x+i+dx,y+j+dy)
      s+=Math.min(1600,d*d)
    }
    return s/((r+1)*(r+1))
  }
  const globalCost=(dx:number,dy:number)=>{
    let score=0
    for(let y=32;y<100;y+=8) for(let x=32;x<96;x+=8) {
      const d=at(a,x,y)-at(b,x+dx,y+dy); score+=Math.min(1600,d*d)
    }
    return score
  }
  let gx=0,gy=0,best=globalCost(0,0)
  for(let dy=-8;dy<=8;dy++) for(let dx=-8;dx<=8;dx++) {
    const score=globalCost(dx,dy)
    if(score<best){best=score;gx=dx;gy=dy}
  }
  const raw=new Float32Array(GRID_W*GRID_H*2),confidence=new Float32Array(GRID_W*GRID_H)
  let good=0,total=0,residual=0
  for(let j=1;j<GRID_H-1;j++) for(let i=1;i<GRID_W-1;i++) {
    const x=i*8,y=j*8,k=j*GRID_W+i
    let dx=gx,dy=gy,score=cost(x,y,gx,gy)
    for(let sy=gy-3;sy<=gy+3;sy++) for(let sx=gx-3;sx<=gx+3;sx++) {
      const value=cost(x,y,sx,sy)+.8*((sx-gx)**2+(sy-gy)**2)
      if(value<score){score=value;dx=sx;dy=sy}
    }
    // Subpixel parabola avoids integer-step shimmer.
    const c=cost(x,y,dx,dy)
    const refine=(lo:number,hi:number)=>clamp(.5*(lo-hi)/Math.max(1e-5,lo+hi-2*c),-.5,.5)
    const fx=refine(cost(x,y,dx-1,dy),cost(x,y,dx+1,dy))
    const fy=refine(cost(x,y,dx,dy-1),cost(x,y,dx,dy+1))
    let energy=0
    for(let q=-2;q<=2;q++) energy+=Math.abs(at(a,x+q+1,y)-at(a,x+q-1,y))+Math.abs(at(a,x,y+q+1)-at(a,x,y+q-1))
    const valid=energy>35 && c<450
    confidence[k]=valid?1:0
    raw[k*2]=valid?dx+fx:gx;raw[k*2+1]=valid?dy+fy:gy
    if(x>=24 && x<=104 && y>=24 && y<=128){total++;if(valid)good++;residual+=c}
  }
  const xy=new Float32Array(raw.length)
  let peak=0
  for(let j=1;j<GRID_H-1;j++) for(let i=1;i<GRID_W-1;i++) {
    const k=j*GRID_W+i
    // Smooth neighboring matches. Invalid/occluded areas follow surrounding
    // geometry rather than chasing a tooth, blink, or high-contrast mismatch.
    for(let axis=0;axis<2;axis++) {
      let value=0,weight=0
      for(let y=Math.max(1,j-1);y<=Math.min(GRID_H-2,j+1);y++) for(let x=Math.max(1,i-1);x<=Math.min(GRID_W-2,i+1);x++) {
        const n=y*GRID_W+x,w=(n===k?3:1)*(confidence[n]?1:.2)
        value+=raw[n*2+axis]*w;weight+=w
      }
      const edge=smooth(i/2)*smooth((GRID_W-1-i)/2)*smooth(j/2)*smooth((GRID_H-1-j)/2)
      xy[k*2+axis]=clamp(value/weight,-10,10)*edge
      peak=Math.max(peak,Math.abs(xy[k*2+axis]))
    }
  }
  boundFlow(xy)
  return {xy,reliable:good/Math.max(1,total),residual:residual/Math.max(1,total),peak}
}

export const HANDOFF_FRAGMENT=`
precision highp float;
varying vec2 uv;
uniform sampler2D firstImage,secondImage,flowImage;
uniform float progress;
uniform vec2 imageSize;
vec4 sharpSample(sampler2D image,vec2 point) {
  vec2 pixel=point*imageSize-0.5,base=floor(pixel),fraction=pixel-base;
  vec2 f=fraction;
  vec2 w0=f*(-0.5+f*(1.0-0.5*f));
  vec2 w1=1.0+f*f*(-2.5+1.5*f);
  vec2 w2=f*(0.5+f*(2.0-1.5*f));
  vec2 w3=f*f*(-0.5+0.5*f),w12=w1+w2;
  // Exact Catmull-Rom with 9 bilinear fetches rather than 16 point fetches.
  vec2 p0=(base-0.5)/imageSize,p12=(base+0.5+w2/w12)/imageSize,p3=(base+2.5)/imageSize;
  vec4 color=texture2D(image,vec2(p0.x,p0.y))*w0.x*w0.y
    +texture2D(image,vec2(p12.x,p0.y))*w12.x*w0.y
    +texture2D(image,vec2(p3.x,p0.y))*w3.x*w0.y
    +texture2D(image,vec2(p0.x,p12.y))*w0.x*w12.y
    +texture2D(image,p12)*w12.x*w12.y
    +texture2D(image,vec2(p3.x,p12.y))*w3.x*w12.y
    +texture2D(image,vec2(p0.x,p3.y))*w0.x*w3.y
    +texture2D(image,vec2(p12.x,p3.y))*w12.x*w3.y
    +texture2D(image,p3)*w3.x*w3.y;
  return clamp(color,0.0,1.0);
}
vec2 flow(vec2 p) {
  // Grid vertices span [0,1], whereas texture samples address texel centers.
  vec2 grid=(clamp(p,0.0,1.0)*vec2(16.0,20.0)+0.5)/vec2(17.0,21.0);
  vec4 v=texture2D(flowImage,grid)*255.0;
  return ((vec2(v.r*256.0+v.g,v.b*256.0+v.a)/65535.0)*24.0-12.0)/vec2(128.0,160.0);
}
void main() {
  // Invert the intermediate warp with two fixed-point iterations.
  vec2 p=uv-progress*flow(uv);
  p=uv-progress*flow(p);
  vec2 movement=flow(p);
  // These forms are EXACT identity at their respective endpoints, even when
  // the iterative inverse estimate has residual error.
  vec2 fromPoint=uv-progress*movement;
  vec2 toPoint=uv+(1.0-progress)*movement;
  float appearance=smoothstep(0.2,0.8,progress);
  vec4 color;
  if(appearance<=0.0)color=sharpSample(firstImage,clamp(fromPoint,0.0,1.0));
  else if(appearance>=1.0)color=sharpSample(secondImage,clamp(toPoint,0.0,1.0));
  else color=mix(sharpSample(firstImage,clamp(fromPoint,0.0,1.0)),
                 sharpSample(secondImage,clamp(toPoint,0.0,1.0)),appearance);
  gl_FragColor=vec4(color.rgb,1.0);
}`

class GpuWarp {
  canvas=document.createElement('canvas')
  gl:WebGLRenderingContext
  program:WebGLProgram
  textures:WebGLTexture[]=[]
  constructor(){
    const gl=this.canvas.getContext('webgl',{alpha:false,antialias:false,preserveDrawingBuffer:true})
    if(!gl)throw new Error('WebGL unavailable')
    this.gl=gl
    const shader=(type:number,text:string)=>{
      const s=gl.createShader(type)!;gl.shaderSource(s,text);gl.compileShader(s)
      if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw new Error(gl.getShaderInfoLog(s)??'shader')
      return s
    }
    const program=gl.createProgram()!
    gl.attachShader(program,shader(gl.VERTEX_SHADER,'attribute vec2 position; varying vec2 uv; void main(){gl_Position=vec4(position,0.,1.);uv=vec2((position.x+1.)*.5,(1.-position.y)*.5);}'))
    gl.attachShader(program,shader(gl.FRAGMENT_SHADER,HANDOFF_FRAGMENT));gl.linkProgram(program)
    if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw new Error('Handoff shader link failed')
    this.program=program;gl.useProgram(program)
    const buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer)
    gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,1,1]),gl.STATIC_DRAW)
    const loc=gl.getAttribLocation(program,'position');gl.enableVertexAttribArray(loc);gl.vertexAttribPointer(loc,2,gl.FLOAT,false,0,0)
    for(let i=0;i<3;i++){
      this.textures.push(gl.createTexture()!);gl.activeTexture(gl.TEXTURE0+i);gl.bindTexture(gl.TEXTURE_2D,this.textures[i])
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR)
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE)
      gl.uniform1i(gl.getUniformLocation(program,['firstImage','secondImage','flowImage'][i]),i)
    }
  }
  render(a:CanvasImageSource,b:CanvasImageSource,field:Float32Array,t:number,w:number,h:number){
    const gl=this.gl
    if(gl.isContextLost())throw new Error('Handoff GPU context lost')
    if(this.canvas.width!==w || this.canvas.height!==h){this.canvas.width=w;this.canvas.height=h}
    gl.viewport(0,0,w,h);gl.useProgram(this.program)
    for(const [i,source] of [a,b].entries()){
      gl.activeTexture(gl.TEXTURE0+i);gl.bindTexture(gl.TEXTURE_2D,this.textures[i])
      gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,source as TexImageSource)
    }
    const packed=new Uint8Array(GRID_W*GRID_H*4)
    for(let i=0;i<field.length;i++){
      const value=Math.round((clamp(field[i],-12,12)+12)/24*65535)
      packed[i*2]=value>>8;packed[i*2+1]=value&255
    }
    gl.activeTexture(gl.TEXTURE2);gl.bindTexture(gl.TEXTURE_2D,this.textures[2])
    gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,GRID_W,GRID_H,0,gl.RGBA,gl.UNSIGNED_BYTE,packed)
    gl.uniform1f(gl.getUniformLocation(this.program,'progress'),t)
    gl.uniform2f(gl.getUniformLocation(this.program,'imageSize'),w,h)
    gl.drawArrays(gl.TRIANGLE_STRIP,0,4)
    return this.canvas
  }
}
// The presentation canvas is remounted between turns. Share one scratch GPU
// context across those mounts so repeated tests cannot exhaust context limits.
let sharedGpu:GpuWarp|null=null
export function warmGeometryHandoff(source:HTMLCanvasElement) {
  try {
    if(sharedGpu && !sharedGpu.gl.isContextLost())return
    const gpu=sharedGpu=new GpuWarp()
    gpu.render(source,source,new Float32Array(GRID_W*GRID_H*2),.25,source.width,source.height)
    // Pay shader compilation/upload once while idle, not at the first audible
    // frame. No pixels from this scratch warm-up are presented to the user.
    gpu.gl.finish()
    // Warm the CPU matcher too; its first JIT invocation otherwise lands in
    // the first transition even though the shader was already compiled.
    const a=new Float32Array(FLOW_W*FLOW_H),b=new Float32Array(a.length)
    for(let y=0;y<FLOW_H;y++)for(let x=0;x<FLOW_W;x++){
      a[y*FLOW_W+x]=110+40*Math.sin(x*.4)+30*Math.sin(y*.53)
      b[y*FLOW_W+x]=110+40*Math.sin((x-2)*.4)+30*Math.sin((y-1)*.53)
    }
    matchGeometry(a,b);matchGeometry(b,a)
  } catch { sharedGpu=null }
}
export class GeometryHandoff {
  private sampleCanvas:HTMLCanvasElement|null=null
  private previous:Float32Array|null=null
  stats={mode:'pending',frames:0,peak_ms:0,reliable:0,residual:0,peak_displacement:0,fallback_frames:0,last_error:''}
  private sample(image:CanvasImageSource){
    const c=this.sampleCanvas??(this.sampleCanvas=document.createElement('canvas'))
    if(c.width!==FLOW_W){c.width=FLOW_W;c.height=FLOW_H}
    const ctx=c.getContext('2d',{willReadFrequently:true})!
    ctx.drawImage(image,0,0,FLOW_W,FLOW_H)
    const rgba=ctx.getImageData(0,0,FLOW_W,FLOW_H).data,gray=new Float32Array(FLOW_W*FLOW_H)
    for(let i=0;i<gray.length;i++)gray[i]=rgba[i*4]*.299+rgba[i*4+1]*.587+rgba[i*4+2]*.114
    return gray
  }
  draw(ctx:CanvasRenderingContext2D,a:CanvasImageSource,b:CanvasImageSource,t:number){
    const w=ctx.canvas.width,h=ctx.canvas.height
    if(t<=0 || t>=1){ctx.drawImage(t<=0?a:b,0,0,w,h);return}
    const start=performance.now()
    try {
      const field=matchGeometry(this.sample(a),this.sample(b))
      if(field.reliable<.15 || field.residual>800)throw new Error('Unreliable frame correspondence')
      if(this.previous)smoothFlow(field.xy,this.previous)
      this.previous=field.xy
      if(sharedGpu?.gl.isContextLost())sharedGpu=null
      const gpu=sharedGpu??(sharedGpu=new GpuWarp())
      ctx.drawImage(gpu.render(a,b,field.xy,t,w,h),0,0,w,h)
      this.stats={...this.stats,mode:'aligned_continuous_warp',reliable:field.reliable,residual:field.residual,peak_displacement:field.peak}
    } catch(error) {
      // Degraded GPU/readback fallback must also remain continuous, not cut
      // at 50%. This can soften the image and is explicitly logged.
      ctx.drawImage(a,0,0,w,h);ctx.save();ctx.globalAlpha=appearanceWeight(t)
      ctx.drawImage(b,0,0,w,h);ctx.restore();this.stats.mode='unregistered_blend_fallback'
      this.stats.fallback_frames++;this.stats.last_error=error instanceof Error?error.message:'render_failed'
    }
    this.stats.frames++;this.stats.peak_ms=Math.max(this.stats.peak_ms,performance.now()-start)
  }
}

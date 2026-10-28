/** Restrict supplemental oral surfaces to the jaw opening, never the philtrum. */
export function withOralOcclusion(source: string): string {
  const color='vColor = uintToRGBAVec(sampledCenterColor.r);'
  if (!source.includes(color)) throw new Error('LAM oral shader contract changed')
  return `uniform vec4 gsMouth;
uniform float gsJaw;
`+source.replace(color,color+`
  float gsOralTop = gsMouth.y - 0.0007 + 0.002 * gsJaw;
  float gsOralBottom = gsMouth.y - 0.001 - 0.033 * gsJaw;
  vec2 gsOralUV = vec2((gsMovedCenter.x-gsMouth.x)/(gsMouth.w*0.95),
    (gsMovedCenter.y-(gsOralTop+gsOralBottom)*0.5)/max(0.001,(gsOralTop-gsOralBottom)*0.5));
  float gsOralOval = 1.0-smoothstep(0.72,1.0,dot(gsOralUV,gsOralUV));
  // Supplemental points have zero learned offset; their neutral positions
  // lie inside this explicitly generated volume. Skin remains untouched.
  if (splatIndex >= uint(20018)) {
    float top = gsMouth.y - 0.0007 + 0.002 * gsJaw;
    float bottom = gsMouth.y - 0.001 - 0.033 * gsJaw;
    float visible = smoothstep(bottom, bottom+0.0015, gsMovedCenter.y)
      * (1.0-smoothstep(top-0.001, top+0.0003, gsMovedCenter.y));
    visible *= 1.0-smoothstep(gsMouth.w*0.82,gsMouth.w,abs(gsMovedCenter.x-gsMouth.x));
    vColor.a *= visible * gsOralOval * smoothstep(0.025,0.12,gsJaw);
  } else {
    float recessed = (1.0-smoothstep(gsMouth.z-0.006,gsMouth.z-0.003,gsNeutralCenter.z))
      * smoothstep(gsMouth.z-0.04,gsMouth.z-0.03,gsNeutralCenter.z);
    float inside = (1.0-smoothstep(gsMouth.w*0.7,gsMouth.w*0.9,abs(gsMovedCenter.x-gsMouth.x)))
      * smoothstep(gsMouth.y-0.030*gsJaw,gsMouth.y-0.027*gsJaw,gsMovedCenter.y)
      * (1.0-smoothstep(gsMouth.y-0.001,gsMouth.y+0.001,gsMovedCenter.y));
    float bright = smoothstep(0.48,0.7,dot(vColor.rgb,vec3(0.333)));
    vColor.rgb = mix(vColor.rgb,vec3(0.16,0.055,0.05),recessed*inside*gsOralOval*bright*smoothstep(0.08,0.25,gsJaw));
  }
`)
}

/** V2 clips fragments, not whole splat centres, against the animated lip aperture. */
export function withOralSurfaceVertex(source:string, nativeTeeth=false):string {
  const end='gl_Position = quadPos;'
  const color='vColor = uintToRGBAVec(sampledCenterColor.r);'
  if(!source.includes(end)||!source.includes(color)) throw new Error('LAM oral v2 vertex contract changed')
  return `uniform vec4 gsAperture;
uniform vec4 gsMouth;
uniform float gsOralOpen;
varying vec2 gsOralUv;
varying float gsOralKind;
`+source.replace(color,color+`
    gsOralKind = splatIndex >= uint(20018) ? 1.0 : 0.0;
    ${nativeTeeth ? 'if(splatIndex >= uint(20018)) vColor.a=0.0; else gsOralKind=2.0;' : ''}
    // Remove only recessed legacy interior splats, never paint them as tissue.
    if(gsOralKind==0.0 && gsNeutralCenter.z < gsMouth.z+0.030 && gsNeutralCenter.z > gsMouth.z-0.04
       && abs(gsNeutralCenter.x-gsMouth.x)<gsMouth.w && abs(gsNeutralCenter.y-gsMouth.y)<0.018) gsOralKind=2.0;
` ).replace(end,end+`
    mat4 gsPose=mat4(1.0);
    #ifdef USE_SKINNING
      if(headBoneIndex>=0.0) gsPose=getBoneMatrix0(headBoneIndex);
    #endif
    mat4 gsProject=projectionMatrix*transformModelViewMatrix*gsPose;
    vec4 gsC=gsProject*vec4(gsAperture.xy,gsMouth.z,1.0);
    vec4 gsX=gsProject*vec4(gsAperture.x+gsAperture.z,gsAperture.y,gsMouth.z,1.0);
    vec4 gsY=gsProject*vec4(gsAperture.x,gsAperture.y+gsAperture.w,gsMouth.z,1.0);
    vec2 gsDx=gsX.xy/gsX.w-gsC.xy/gsC.w;
    vec2 gsDy=gsY.xy/gsY.w-gsC.xy/gsC.w;
    vec2 gsP=quadPos.xy-gsC.xy/gsC.w;
    float gsDet=gsDx.x*gsDy.y-gsDx.y*gsDy.x;
    gsOralUv=abs(gsDet)>1e-12 ? vec2(gsP.x*gsDy.y-gsP.y*gsDy.x,gsDx.x*gsP.y-gsDx.y*gsP.x)/gsDet : vec2(100.0);
`)
}
export function withOralSurfaceFragment(source:string, nativeTeeth=false):string {
  const opacity='float opacity = exp( -0.5*A) * vColor.a;'
  if(!source.includes(opacity)) throw new Error('LAM oral v2 fragment contract changed')
  return `uniform float gsOralOpen;
varying vec2 gsOralUv;
varying float gsOralKind;
`+source.replace(opacity,`
    vec3 gsTissueColor=vColor.rgb;
    ${nativeTeeth ? `if(gsOralKind>1.5) {
      float tissue=(1.0-smoothstep(-0.20,0.25,gsOralUv.y))
        *(1.0-smoothstep(0.60,0.95,dot(gsOralUv,gsOralUv)))*gsOralOpen;
      float luminance=dot(vColor.rgb,vec3(0.299,0.587,0.114));
      gsTissueColor=mix(vColor.rgb,vec3(0.48,0.22,0.25)*(0.55+0.70*luminance),tissue);
    }` : ''}
`+opacity+`
    float gsMask=(1.0-smoothstep(0.80,1.0,dot(gsOralUv,gsOralUv)))*gsOralOpen;
    if(gsOralKind>0.5 && gsOralKind<1.5) opacity*=gsMask;
    ${nativeTeeth ? '' : 'if(gsOralKind>1.5) opacity*=1.0-gsMask;'}
`).replace('vec4(color, opacity)', 'vec4(gsTissueColor, opacity)')
}
export type LipAnchor={position:number[];deltas:Record<string,number[]>}
export function lipAperture(anchors:Record<string,LipAnchor>,weights:Record<string,number>):number[] {
  const moved=(name:string)=>{
    const anchor=anchors[name];const p=[...anchor.position]
    for(const [key,delta] of Object.entries(anchor.deltas)) for(let i=0;i<3;i++) p[i]+=delta[i]*(weights[key]??0)
    return p
  }
  const upper=moved('upper'),lower=moved('lower'),left=moved('left'),right=moved('right')
  const restGap=anchors.upper.position[1]-anchors.lower.position[1]
  const top=upper[1]-restGap/2,bottom=lower[1]+restGap/2
  return [(left[0]+right[0])/2,(top+bottom)/2,Math.max(.005,Math.abs(right[0]-left[0])/2),Math.max(.00015,(top-bottom)/2)]
}

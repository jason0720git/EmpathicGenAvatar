/** Visibility correction for fixed-color Gaussians crossing a closing eyelid. */
export function withBlinkOcclusion(source: string, channels?: Record<string,number>): string {
  const center = 'vec3 splatCenter = uintBitsToFloat(uvec3(sampledCenter));'
  const skin = 'vec3 transformed = vec3(splatCenter.xyz);'
  const color = 'vColor = uintToRGBAVec(sampledCenterColor.r);'
  if (![center, skin, color].every(marker => source.includes(marker))) throw new Error('LAM blink shader contract changed')
  if(channels && ['eyeLookOutLeft','eyeLookOutRight','eyeBlinkLeft','eyeBlinkRight'].every(k=>channels[k]!==undefined)) {
    const loop='for(int i = 0; i < bsCount; ++i) {'
    const sample='uvec3 sampledBSPos = texture(flameModelTexture, flameBSTextureUV).rgb;'
    if(!source.includes(loop)||!source.includes(sample)) throw new Error('LAM anatomical eye shader contract changed')
    return `uniform vec2 gsBlink;
uniform vec3 gsEyeSkinLeft;
uniform vec3 gsEyeSkinRight;
uniform vec3 gsEyeSeamLeft;
uniform vec3 gsEyeSeamRight;
`+source
      .replace(center,center+'\n vec3 gsNeutralCenter = splatCenter;')
      .replace(skin,'vec3 gsMovedCenter = splatCenter;\n'+skin)
      .replace(loop,'float gsEyeL=0.0; float gsEyeR=0.0; float gsLidL=0.0; float gsLidR=0.0;\n'+loop)
      .replace(sample,sample+`
        float gsDelta=length(uintBitsToFloat(sampledBSPos));
        if(i==${channels.eyeLookOutLeft}) gsEyeL=gsDelta;
        if(i==${channels.eyeLookOutRight}) gsEyeR=gsDelta;
        if(i==${channels.eyeBlinkLeft}) gsLidL=gsDelta;
        if(i==${channels.eyeBlinkRight}) gsLidR=gsDelta;
      `)
      .replace(color,color+`
        // Eye-globe points rotate with gaze but do not deform with the eyelid.
        // Classify in the rig, independent of gaze, head pose, and photo offsets.
        float gsGlobeL=step(0.0005,gsEyeL)*(1.0-step(0.00035,gsLidL));
        float gsGlobeR=step(0.0005,gsEyeR)*(1.0-step(0.00035,gsLidR));
        float gsClosedL=step(.0005,gsEyeL)*smoothstep(.45,.95,gsBlink.x);
        float gsClosedR=step(.0005,gsEyeR)*smoothstep(.45,.95,gsBlink.y);
        vec3 gsSkin=gsClosedL>gsClosedR?gsEyeSkinLeft:gsEyeSkinRight;
        vec3 gsSeam=gsClosedL>gsClosedR?gsEyeSeamLeft:gsEyeSeamRight;
        float gsLash=1.0-smoothstep(.0003,.0012,abs(gsMovedCenter.y-gsSeam.y));
        vColor.rgb=mix(vColor.rgb,mix(gsSkin,gsSkin*.30,gsLash),max(gsClosedL,gsClosedR));
        vColor.a*=1.0-max(gsGlobeL*smoothstep(0.25,0.85,gsBlink.x),gsGlobeR*smoothstep(0.25,0.85,gsBlink.y));
      `)
  }
  return `uniform vec2 gsBlink;
uniform vec4 gsEyeLeft;
uniform vec4 gsEyeRight;
float gsEyeOcclusion(vec3 neutral, vec3 moved, vec4 eye, float blink) {
  float horizontal = 1.0 - smoothstep(eye.y * 0.75, eye.y, abs(neutral.x-eye.x));
  float vertical = smoothstep(eye.z-0.008, eye.z-0.005, neutral.y)
    * (1.0-smoothstep(eye.z+0.010, eye.z+0.014, neutral.y));
  float front = smoothstep(eye.w-0.004, eye.w, neutral.z);
  // A closed eyelid should occlude iris fragments above its seam. Opacity,
  // rather than painting skin color over the eye, preserves original colors.
  float aboveLid = smoothstep(eye.z+0.0005, eye.z+0.0025, moved.y);
  return horizontal * vertical * front * aboveLid * smoothstep(0.15,0.60,blink);
}
` + source.replace(center, center+'\n vec3 gsNeutralCenter = splatCenter;')
    .replace(skin, 'vec3 gsMovedCenter = splatCenter;\n'+skin)
    .replace(color, color+`\n vColor.a *= 1.0 - max(
      gsEyeOcclusion(gsNeutralCenter,gsMovedCenter,gsEyeLeft,gsBlink.x),
      gsEyeOcclusion(gsNeutralCenter,gsMovedCenter,gsEyeRight,gsBlink.y));`)
}

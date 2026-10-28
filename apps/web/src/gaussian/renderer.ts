import type { MotionFrame, RendererStats, SourceCamera } from './types'
import { sanitizeWeights } from './timeline'
import { withBlinkOcclusion } from './blinkOcclusion'
import { withOralOcclusion, withOralSurfaceVertex, withOralSurfaceFragment, lipAperture, type LipAnchor } from './oralOcclusion'

// SDK 0.0.9-alpha.1 stores the actual Three.js bone and mixer on the renderer.
// This isolated adapter is the only code depending on that pinned internal contract.
type Quaternion = { clone(): Quaternion; copy(other: Quaternion): Quaternion; multiply(other: Quaternion): Quaternion; set(x: number, y: number, z: number, w: number): Quaternion }
type Bone = { name: string; isBone?: boolean; quaternion: Quaternion; updateMatrixWorld(force: boolean): void }
type Vector = { x: number; y: number; z: number; set(x: number, y: number, z: number): Vector }
type Position = { count: number; getX(index: number): number; getY(index: number): number; getZ(index: number): number }
type SkinMesh = { userData?: { oralMaterial?: {version:string;changed_splats:number}; eyeSurface?:Record<string,{skin:number[];seam:number[]}>; oral?: { version: string; base_count: number; added: number; anchor?:number[]; halfwidth?:number; lip_anchors?:Record<string,LipAnchor> } }; morphTargetDictionary?: Record<string, number>; skeleton?: { bones: Bone[] }; geometry?: { attributes?: { position?: Position }; morphAttributes?: { position?: Position[] } } }
type Lam = {
  motioncfg?: {scale:Record<string,number>;offset:Record<string,number>};
  dispose(): void; mixer?: { update(delta: number): unknown; stopAllAction(): unknown };
  animManager?: { update(state: string): void };
  viewer?: { avatarMesh?: SkinMesh & { traverse(callback: (node: Bone) => void): void }; skinModel?: SkinMesh; gaussianSplatCount?: number;
    splatMesh?: { bsWeight?: Record<string, number>; morphTargetDictionary?: Record<string, number>; bonesNum?: number; splatDataTextures?: { baseData?: { boneMatrix?: Uint32Array } }; material: { vertexShader: string; fragmentShader:string; uniforms: Record<string, {value: unknown}>; needsUpdate: boolean } };
    camera?: { position: Vector; up: Vector; fov?: number; lookAt(x: number, y: number, z: number): void; updateProjectionMatrix(): void };
    controls?: { target: Vector; update(): void } };
}

import { neutralWeights, ARKIT_NAMES } from './expression'
export { manualFrame, manualSpeechFrame, neutralWeights, ARKIT_NAMES } from './expression'

let initialization = Promise.resolve()
export async function createLamRenderer(container: HTMLElement, assetUrl: string,
  getFrame: () => MotionFrame, onReady: (stats: RendererStats) => void,
  onProgress: (value: number) => void, signal?: AbortSignal, sourceCamera?: SourceCamera, nativeOral = true, rawShaders = false): Promise<{ dispose(): void; stats(): RendererStats; resetView(): void }> {
  // SDK uses one static canvas: serialize initialization, including React strict mode.
  const previous = initialization
  let release!: () => void
  initialization = new Promise(resolve => { release = resolve })
  await previous
  let frames = 0, lastFrames = 0, fps = 0, lastTime = performance.now()
  let renderer: Lam | undefined
  let head: Bone | undefined
  let alive = true
  const blinkUniform = { value: [0, 0] }
  const jawUniform = { value: 0 }
  const apertureUniform = {value:[0,0,.02,.00015]}
  const oralOpenUniform = {value:0}
  let lipAnchors:Record<string,LipAnchor>|undefined
  let requestedWeights: Record<string, number> = {}
  try {
    if (signal?.aborted) throw new DOMException('Renderer load cancelled', 'AbortError')
    const { GaussianSplatRenderer } = await import('gaussian-splat-renderer-for-lam')
    if (signal?.aborted) throw new DOMException('Renderer load cancelled', 'AbortError')
    let loaded = false
    let done!: () => void
    const complete = new Promise<void>(resolve => { done = resolve })
    renderer = await GaussianSplatRenderer.getInstance(container, assetUrl, {
      // The SDK's random state clips would otherwise override our explicit policy.
      getChatState: () => 'Idle',
      getExpressionData: () => {
        frames++
        const time = performance.now()
        if (time - lastTime > 1000) { fps = (frames - lastFrames) * 1000 / (time - lastTime); lastFrames = frames; lastTime = time }
        const weights = { ...neutralWeights(), ...sanitizeWeights(getFrame().weights) }
        // Closing lids take priority over eye widening and gaze deformation.
        for(const side of ['Left','Right']) {
          const closure=weights['eyeBlink'+side]??0
          for(const channel of ['eyeWide','eyeLookUp','eyeLookDown','eyeLookIn','eyeLookOut']) weights[channel+side]*=1-closure
        }
        requestedWeights = {...weights}
        blinkUniform.value = [weights.eyeBlinkLeft ?? 0, weights.eyeBlinkRight ?? 0]
        const calibrated = Object.fromEntries(Object.entries(weights).map(([k,v])=>[k,v*(renderer?.motioncfg?.scale[k]??1)+(renderer?.motioncfg?.offset[k]??0)]))
        jawUniform.value = Math.max(0, (calibrated.jawOpen ?? 0) - .65*(calibrated.mouthClose ?? 0))
        if(lipAnchors) {
          apertureUniform.value=lipAperture(lipAnchors,calibrated)
          oralOpenUniform.value=Math.max(0,Math.min(1,(apertureUniform.value[3]-.0002)/.0012))
        }
        return weights
      }, backgroundColor: '0x121E2B', alpha: 0,
      loadProgress: value => { onProgress(value); if (value >= 1) { loaded = true; done() } },
    }) as Lam | undefined
    if (!renderer) throw new Error('LAM 아바타를 불러오지 못했습니다. ZIP 구조와 WebGL 지원을 확인하세요.')
    // SDK speech-demo defaults silently scale mouthClose to .2, shrugUpper to
    // .1, and many lips to 1.3. Our controller owns composition; use a real
    // nominal 0..1 range for every channel, including single-channel inspection.
    if (renderer.motioncfg) {
      for (const name of ARKIT_NAMES) {
        renderer.motioncfg.scale[name] = 1
        renderer.motioncfg.offset[name] = 0
      }
    }
    // "Idle" still plays an upstream canned body/neck pose. Stop that clip;
    // otherwise its parent-bone rotation silently changes neutral face framing.
    if (renderer.animManager) renderer.animManager.update = () => {}
    renderer.mixer?.stopAllAction()
    // updateMorphTarget replaces avatarMesh with the skinned head mesh; its
    // bones are siblings in the GLTF scene, so traverse(mesh) cannot find them.
    head = (renderer.viewer?.skinModel?.skeleton?.bones ?? renderer.viewer?.avatarMesh?.skeleton?.bones)
      ?.find(node => node.name.toLowerCase() === 'head')
    renderer.viewer?.avatarMesh?.traverse(node => {
      if (node.isBone && node.name.toLowerCase() === 'head') head = node
    })
    if (head && renderer.mixer) {
      const bone = head
      const rest = bone.quaternion.clone(), delta = rest.clone()
      const mixer = renderer.mixer
      const original = mixer.update.bind(mixer)
      mixer.update = (seconds: number) => {
        // Reset before each mixer tick: repeated manual frames must never accumulate rotation.
        bone.quaternion.copy(rest)
        const result = original(seconds)
        const pose = getFrame().head ?? { pitch: 0, yaw: 0, roll: 0 }
        const radians = (value: number) => Math.max(-35, Math.min(35, value)) * Math.PI / 180 / 2
        const x = radians(pose.pitch), y = radians(pose.yaw), z = radians(pose.roll)
        const c1 = Math.cos(x), c2 = Math.cos(y), c3 = Math.cos(z)
        const s1 = Math.sin(x), s2 = Math.sin(y), s3 = Math.sin(z)
        delta.set(s1*c2*c3+c1*s2*s3, c1*s2*c3-s1*c2*s3, c1*c2*s3+s1*s2*c3, c1*c2*c3-s1*s2*s3)
        bone.quaternion.multiply(delta); bone.updateMatrixWorld(true)
        return result
      }
    }
    let timeout: ReturnType<typeof setTimeout> | undefined
    if (!loaded) await Promise.race([complete, new Promise<never>((_, reject) => {
      timeout = setTimeout(() => reject(new Error('LAM 렌더러 초기화 제한시간 초과')), 90000)
    })]).finally(() => clearTimeout(timeout))
    const skinMesh = renderer.viewer?.skinModel
    const material = renderer.viewer?.splatMesh?.material
    if (!rawShaders && material && skinMesh?.geometry?.attributes?.position && skinMesh.morphTargetDictionary) {
      const base = skinMesh.geometry.attributes.position
      const eye = (side: string) => {
        const target = skinMesh.geometry?.morphAttributes?.position?.[skinMesh.morphTargetDictionary!['eyeBlink'+side]]
        if (!target) throw new Error('Avatar is missing eyelid deformation')
        const closed: number[] = [], xs: number[] = [], zs: number[] = []
        for (let i=0;i<base.count;i++) {
          if (Math.abs(target.getY(i)) > .003) { closed.push(base.getY(i)+target.getY(i)); xs.push(base.getX(i)); zs.push(base.getZ(i)) }
        }
        if (!closed.length) throw new Error('Avatar has no usable eyelid deformation')
        closed.sort((a,b)=>a-b); xs.sort((a,b)=>a-b); zs.sort((a,b)=>a-b)
        return [xs[Math.floor(xs.length/2)], (xs[xs.length-1]-xs[0])*.48, closed[Math.floor(closed.length*.5)], zs[Math.floor(zs.length*.1)]]
      }
      material.uniforms.gsBlink = blinkUniform
      for(const side of ['Left','Right']) {
        const surface=skinMesh.userData?.eyeSurface?.[side]
        material.uniforms['gsEyeSkin'+side]={value:surface?.skin??[.74,.58,.52]}
        material.uniforms['gsEyeSeam'+side]={value:surface?.seam??[side==='Left'?.032:-.032,1.69,.08]}
      }
      material.uniforms.gsEyeLeft = { value: eye('Left') }
      material.uniforms.gsEyeRight = { value: eye('Right') }
      material.vertexShader = withBlinkOcclusion(material.vertexShader, skinMesh.userData?.eyeSurface ? skinMesh.morphTargetDictionary : undefined)
      // A projected colour patch cannot reconstruct oral anatomy; v5 created a
      // visible boundary. Keep native LAM appearance and remove added surfaces.
      if ((nativeOral || skinMesh.userData?.oral?.version==='hybrid-oral-v5') && skinMesh.userData?.oral) {
        lipAnchors=skinMesh.userData.oral.lip_anchors
        material.vertexShader=material.vertexShader.replace('vColor = uintToRGBAVec(sampledCenterColor.r);','vColor = uintToRGBAVec(sampledCenterColor.r); if(splatIndex >= uint(20018)) vColor.a=0.0;')
      } else if (['explicit-oral-gaussians-v2','explicit-oral-gaussians-v3'].includes(skinMesh.userData?.oral?.version ?? '') && skinMesh.userData?.oral?.lip_anchors) {
        const oral=skinMesh.userData.oral
        lipAnchors=oral.lip_anchors
        material.uniforms.gsMouth={value:[...oral.anchor!,oral.halfwidth!]}
        material.uniforms.gsAperture=apertureUniform
        material.uniforms.gsOralOpen=oralOpenUniform
        material.vertexShader=withOralSurfaceVertex(material.vertexShader)
        material.fragmentShader=withOralSurfaceFragment(material.fragmentShader)
      } else if (skinMesh.userData?.oral?.version === 'explicit-oral-gaussians-v1' && base.count === 20908) {
        // Contract of explicit-oral-gaussians-v1: 375 cavity points first.
        const mouthX=(base.getX(20018)+base.getX(20018+374))/2
        const mouthWidth=(base.getX(20018+374)-base.getX(20018))/2
        material.uniforms.gsMouth={value:[mouthX,base.getY(20018)-.007,base.getZ(20018)+.019,mouthWidth]}
        material.uniforms.gsJaw=jawUniform
        material.vertexShader=withOralOcclusion(material.vertexShader)
      }
      material.needsUpdate = true
    }
    const positions = renderer.viewer?.skinModel?.geometry?.attributes?.position
    const camera = renderer.viewer?.camera
    if (positions?.count && camera) {
      // BufferGeometry.computeBoundingBox includes all ARKit morph extrema.
      // Those envelopes can be much larger than the resting face. Fit only the
      // neutral POSITION attribute so a portrait actually fills the viewport.
      const min = { x: Infinity, y: Infinity, z: Infinity }
      const max = { x: -Infinity, y: -Infinity, z: -Infinity }
      for (let index = 0; index < positions.count; index++) {
        const x = positions.getX(index), y = positions.getY(index), z = positions.getZ(index)
        min.x = Math.min(min.x, x); min.y = Math.min(min.y, y); min.z = Math.min(min.z, z)
        max.x = Math.max(max.x, x); max.y = Math.max(max.y, y); max.z = Math.max(max.z, z)
      }
      // LAM exports Gaussian positions in the same metric frame as head vertices.
      const center = { x: (min.x + max.x)/2, y: (min.y + max.y)/2, z: (min.z + max.z)/2 }
      // A close wide-angle camera exaggerates the nose/chin relative to a
      // portrait input. Keep the same framing with a longer portrait lens.
      camera.fov = 22
      const fov = camera.fov * Math.PI / 180
      const distance = Math.max(0.35, (max.y - min.y) / (2 * Math.tan(fov / 2) * 0.70))
      camera.position.set(center.x, center.y + (max.y - min.y)*0.03, center.z + distance)
      renderer.viewer?.controls?.target.set(center.x, center.y, center.z)
      camera.lookAt(center.x, center.y, center.z); camera.updateProjectionMatrix(); renderer.viewer?.controls?.update()
    }
    const resetView = () => {
      if (!camera || !sourceCamera) return
      const {position, target, up, fov} = sourceCamera
      if (![...position, ...target, ...up, fov].every(Number.isFinite) || fov < 5 || fov > 100) throw new Error('Invalid source camera')
      camera.fov = fov
      camera.position.set(position[0],position[1],position[2])
      camera.up.set(up[0],up[1],up[2])
      renderer?.viewer?.controls?.target.set(target[0],target[1],target[2])
      camera.lookAt(target[0],target[1],target[2]); camera.updateProjectionMatrix(); renderer?.viewer?.controls?.update()
    }
    resetView()
    const diagnosticNames = ARKIT_NAMES
    const maxDeltas = Object.fromEntries(diagnosticNames.map(name => {
      const target = skinMesh?.geometry?.morphAttributes?.position?.[skinMesh.morphTargetDictionary?.[name] ?? -1]
      let maxDelta = 0
      const visibleCount = nativeOral ? skinMesh?.userData?.oral?.base_count ?? target?.count ?? 0 : target?.count ?? 0
      if (target) for (let i=0;i<visibleCount;i++) maxDelta = Math.max(maxDelta, Math.hypot(target.getX(i),target.getY(i),target.getZ(i)))
      return [name, maxDelta*1000]
    }))
    const rigDiagnostics = () => {
      const splat = renderer?.viewer?.splatMesh
      const dictionary = splat?.morphTargetDictionary ?? {}
      const buffer = splat?.splatDataTextures?.baseData?.boneMatrix
      const decoded = buffer ? new Float32Array(buffer.buffer, buffer.byteOffset, buffer.length) : undefined
      return { channelCount: Object.keys(dictionary).length, channels: Object.fromEntries(diagnosticNames.map(name => {
        const index = dictionary[name]
        const uploaded = index !== undefined && decoded && splat?.bonesNum !== undefined ? decoded[index+splat.bonesNum*16] : null
        return [name, {requested: requestedWeights[name] ?? 0, applied: splat?.bsWeight?.[name] ?? null,
          uploaded, supported: index !== undefined && maxDeltas[name] > 0, maxDeltaMm: maxDeltas[name]}]
      })) }
    }
    const stats = () => ({ fps, frames, head: !!head, splats: renderer?.viewer?.gaussianSplatCount ?? 0,
      rig: rigDiagnostics(), oralMaterial:skinMesh?.userData?.oralMaterial, oralAperture: apertureUniform.value, oralOpen:oralOpenUniform.value, oralVersion:(nativeOral || skinMesh?.userData?.oral?.version==='hybrid-oral-v5')?'native-lam-no-overlay':skinMesh?.userData?.oral?.version,
      eyeOcclusion: !!material?.uniforms.gsBlink, eyeOcclusionMode:rawShaders?'disabled-baseline':skinMesh?.userData?.eyeSurface?'rig-globe-and-lid-appearance':'legacy-spatial-mask', portraitFov: camera?.fov,
      oralOcclusion: !!material?.uniforms.gsMouth, tongue: (!nativeOral && skinMesh?.userData?.oral?.version!=='hybrid-oral-v5') && skinMesh?.morphTargetDictionary?.tongueOut !== undefined })
    if (signal?.aborted) { alive = false; renderer.dispose() }
    else onReady(stats())
    return { stats, resetView, dispose() { if (alive) { alive = false; renderer?.dispose() } } }
  } catch (error) { renderer?.dispose(); throw error }
  finally { release() }
}

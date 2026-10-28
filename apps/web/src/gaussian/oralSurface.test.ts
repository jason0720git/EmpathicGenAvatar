import {expect,it} from 'vitest'
import {lipAperture,withOralSurfaceFragment,withOralSurfaceVertex} from './oralOcclusion'
it('tracks lip morphs and removes the neutral lip thickness from the aperture',()=>{
 const anchors={upper:{position:[0,.002,0],deltas:{jawOpen:[0,0,0]}},lower:{position:[0,-.002,0],deltas:{jawOpen:[0,-.03,0]}},left:{position:[-.02,0,0],deltas:{}},right:{position:[.02,0,0],deltas:{}}}
 expect(lipAperture(anchors,{} )[3]).toBeCloseTo(.00015)
 expect(lipAperture(anchors,{jawOpen:.4})[3]).toBeCloseTo(.006)
})
it('fails loudly if pinned shader contracts change',()=>{
 expect(()=>withOralSurfaceFragment('invalid')).toThrow()
 expect(()=>withOralSurfaceVertex('invalid')).toThrow()
})

export type SourceCamera = { version: string; position: number[]; target: number[]; up: number[]; fov: number; aspect: number }
export type Avatar = {
  id: string; name: string; status: 'ready' | 'preparing' | 'error'; asset_url?: string;
  image_url?: string; asset_sha256?: string; kind?: 'reference_video'|'official_live'; video_url?:string; reference_url?:string; pinned?:boolean; source: 'photo' | 'import' | 'sample' | 'reference'; error?: string; created_at?: string;
  source_camera?: SourceCamera;
  generation?: { manifest?: { source_camera?: SourceCamera } };
}
export type Health = {
  openai: { ready: boolean; model?: string; error?: string };
  a2f: { ready: boolean; endpoint?: string; error?: string };
  generator: { ready: boolean; detail?: string };
  logging: { enabled: boolean; path?: string }; renderer?: string;
}
export type MotionFrame = {
  turn_id: string; pts_ms: number; weights: Record<string, number>;
  raw_weights?: Record<string, number>;
  behavior?: {emotion?:string;intensity?:number};
  head?: { pitch: number; yaw: number; roll: number }; gaze?: { x: number; y: number };
  source?: string; speech_energy?: number; natural_motion?: {speaking:boolean;energy:number;head_offset:{pitch:number;yaw:number;roll:number};blink:number;version?:string;gain?:number;emotion?:string;accent?:number;boundary?:number;accent_count?:number;face_envelopes?:Record<string,number>;raw_residual_peak?:number};
}
export type Controls = {
  emotion: string; intensity: number; gaze_x: number; gaze_y: number;
  head_yaw: number; head_pitch: number; head_roll: number; nod: boolean;
}
export const DEFAULT_CONTROLS: Controls = { emotion: 'neutral', intensity: 0.65,
  gaze_x: 0, gaze_y: 0, head_yaw: 0, head_pitch: 0, head_roll: 0, nod: false }
export type WireEvent = { type: string; [key: string]: unknown }
export type RendererStats = { oralMaterial?: {version:string;changed_splats:number}; fps: number; head: boolean; splats: number; frames: number; eyeOcclusion?: boolean; eyeOcclusionMode?: string; portraitFov?: number; oralOcclusion?: boolean; tongue?: boolean;
  oralVersion?:string; oralOpen?:number; oralAperture?:number[]; renderMs?:number;roundTripMs?:number;error?:string;
  rig?: { channelCount: number; channels: Record<string, { requested: number; applied: number|null; uploaded: number|null; supported: boolean; maxDeltaMm: number }> } }

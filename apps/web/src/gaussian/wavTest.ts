/** WAV replay uses the file as avatar speech, never as a prompt to an LLM. */
export function floatToPcm16(samples: Float32Array): Uint8Array {
  const bytes = new Uint8Array(samples.length * 2)
  const view = new DataView(bytes.buffer)
  for (let i=0; i<samples.length; i++) {
    const v = Math.max(-1, Math.min(1, Number.isFinite(samples[i]) ? samples[i] : 0))
    view.setInt16(i*2, Math.round(v * (v < 0 ? 32768 : 32767)), true)
  }
  return bytes
}
export async function decodeTestWav(data: ArrayBuffer): Promise<Uint8Array> {
  const header = new Uint8Array(data, 0, Math.min(12, data.byteLength))
  const text = String.fromCharCode(...header)
  if (data.byteLength > 32*1024*1024 || !text.startsWith('RIFF') || text.slice(8,12) !== 'WAVE') throw new Error('32MB 이하의 WAV 파일을 선택해 주세요.')
  const context = new AudioContext()
  try {
    const decoded = await context.decodeAudioData(data.slice(0))
    if (decoded.duration < .1 || decoded.duration > 90) throw new Error('WAV 길이는 0.1초~90초여야 합니다.')
    const offline = new OfflineAudioContext(1, Math.round(decoded.duration*24000), 24000)
    const source = offline.createBufferSource(); source.buffer = decoded; source.connect(offline.destination); source.start()
    return floatToPcm16((await offline.startRendering()).getChannelData(0))
  } finally { await context.close() }
}
export function pcmBase64(bytes: Uint8Array): string {
  let value = ''
  for (const byte of bytes) value += String.fromCharCode(byte)
  return btoa(value)
}

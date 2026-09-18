import { useEffect, type RefObject } from 'react'

// Explicitly decode the same JPEGs as speech. Native <img> MJPEG presentation
// has no exposed frame clock; its canvas snapshot need not be the displayed
// frame. Here the transition source is exactly the canvas we just painted.
export class MjpegParser {
  private buffer = new Uint8Array(0)
  push(chunk: Uint8Array): Uint8Array[] {
    const joined = new Uint8Array(this.buffer.length + chunk.length)
    joined.set(this.buffer); joined.set(chunk, this.buffer.length)
    this.buffer = joined
    const frames: Uint8Array[] = []
    while (this.buffer.length) {
      let end = -1
      for (let i = 0; i + 3 < this.buffer.length; i++) {
        if (this.buffer[i] === 13 && this.buffer[i+1] === 10 && this.buffer[i+2] === 13 && this.buffer[i+3] === 10) { end = i; break }
      }
      if (end < 0) {
        if (this.buffer.length > 4096) throw new Error('Invalid idle frame header')
        break
      }
      const header = new TextDecoder().decode(this.buffer.subarray(0, end))
      const length = Number(/Content-Length:\s*(\d+)/i.exec(header)?.[1])
      if (!Number.isInteger(length) || length <= 0 || length > 4_000_000) throw new Error('Invalid idle frame size')
      const start = end + 4
      if (this.buffer.length < start + length) break
      frames.push(this.buffer.slice(start, start + length))
      this.buffer = this.buffer.slice(start + length)
    }
    return frames
  }
}

export function IdleCanvas({ source, canvasRef, className, label, onReady, parked=false }: {
  source: string; canvasRef: RefObject<HTMLCanvasElement | null>; className: string
  label: string; onReady: (ready: boolean) => void; parked?: boolean
}) {
  useEffect(() => {
    const controller = new AbortController()
    let pending: ImageBitmap | null = null
    let paintId = 0
    let ready = false
    // Retain the painted image while reconnecting. During speech fetch only
    // frame zero (the shared source-pose anchor), not an arbitrary idle phase.
    if (!canvasRef.current?.dataset.painted) onReady(false)
    const paint = () => {
      paintId = 0
      const bitmap = pending; pending = null
      const canvas = canvasRef.current
      if (!bitmap) return
      if (!controller.signal.aborted && canvas) {
        if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
          canvas.width = bitmap.width; canvas.height = bitmap.height
        }
        canvas.getContext('2d')?.drawImage(bitmap, 0, 0)
        canvas.dataset.painted = 'true'
        canvas.dataset.parked = String(parked)
        if (!ready) { ready = true; onReady(true) }
      }
      bitmap.close()
    }
    const run = async () => {
      const response = await fetch(source, { signal: controller.signal })
      if (!response.ok || !response.body) throw new Error('Idle stream unavailable')
      const reader = response.body.getReader()
      const parser = new MjpegParser()
      try {
        while (!controller.signal.aborted) {
          const { value, done } = await reader.read()
          if (done) throw new Error('Idle stream ended')
          const frames = parser.push(value)
          if (!frames.length) continue
          // Decode serially and retain only the newest frame after a network
          // burst. Never replay a backlog as a fast head movement.
          const bitmap = await createImageBitmap(new Blob([frames[parked ? 0 : frames.length-1] as BlobPart], { type: 'image/jpeg' }))
          if (controller.signal.aborted) { bitmap.close(); break }
          pending?.close(); pending = bitmap
          if (!paintId) paintId = requestAnimationFrame(paint)
          // Cancel rather than leave 16 seconds of network frames queued.
          // Unparking opens a fresh stream from frame zero at normal 25 fps.
          if (parked) break
        }
      } finally { await reader.cancel().catch(() => undefined); reader.releaseLock() }
    }
    void run().catch(() => {
      // Retain a painted frame on transient failure instead of flashing the
      // source portrait. The next preparation revision reconnects the stream.
      if (!controller.signal.aborted && !ready) onReady(false)
    })
    return () => { controller.abort(); cancelAnimationFrame(paintId); pending?.close() }
  }, [source, canvasRef, onReady, parked])
  return <canvas ref={canvasRef} className={className} aria-label={label} data-source={source} />
}

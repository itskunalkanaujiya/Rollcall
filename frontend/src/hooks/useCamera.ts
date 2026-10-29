import { useCallback, useEffect, useRef, useState } from 'react'

export type CameraState = 'off' | 'starting' | 'on' | 'error' | 'disconnected'

export function describeCameraError(e: unknown): string {
  const name = e instanceof DOMException ? e.name : ''
  switch (name) {
    case 'NotAllowedError': case 'SecurityError':
      return 'Camera access is blocked. Allow the camera for this site in your browser settings, then press Start again.'
    case 'NotFoundError': case 'OverconstrainedError':
      return 'No camera was found. Connect a camera or pick another one from the list.'
    case 'NotReadableError': case 'AbortError':
      return 'The camera is in use by another app. Close it (Teams, Zoom, another tab) and try again.'
    default:
      return e instanceof Error ? `Camera error: ${e.message}` : 'The camera could not be started.'
  }
}

/** Camera access with device selection, automatic reconnect after a disconnect, and full release on stop. */
export function useCamera(size = { width: 1280, height: 720 }) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const wantRef = useRef(false)
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const [state, setState] = useState<CameraState>('off')
  const [error, setError] = useState<string | null>(null)
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([])
  const [deviceId, setDeviceId] = useState('')
  const [aspect, setAspect] = useState(16 / 9)

  const refreshDevices = useCallback(async () => {
    try {
      const all = await navigator.mediaDevices.enumerateDevices()
      setDevices(all.filter((d) => d.kind === 'videoinput'))
    } catch { /* enumerating is optional */ }
  }, [])

  const release = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => { t.onended = null; t.stop() })
    streamRef.current = null
    if (videoRef.current) videoRef.current.srcObject = null
  }, [])

  const open = useCallback(async (id: string, silent: boolean) => {
    if (!navigator.mediaDevices?.getUserMedia) {
      setState('error'); setError('This browser cannot access cameras here. Use localhost or HTTPS in a current browser.'); wantRef.current = false
      return
    }
    release()
    if (!silent) setState('starting')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { ...(id ? { deviceId: { exact: id } } : { facingMode: 'user' }), width: { ideal: size.width }, height: { ideal: size.height } },
      })
      if (!wantRef.current) { stream.getTracks().forEach((t) => t.stop()); return }   // stopped while the permission prompt was open
      streamRef.current = stream
      const track = stream.getVideoTracks()[0]
      track.onended = () => {                       // unplugged, or taken by another app
        release()
        if (!wantRef.current) return
        setState('disconnected')
        retryRef.current = setTimeout(() => { void open(id, true) }, 2500)
      }
      const v = videoRef.current
      if (v) {
        v.srcObject = stream
        await v.play().catch(() => undefined)
        if (v.videoWidth) setAspect(v.videoWidth / v.videoHeight)
      }
      setDeviceId(track.getSettings().deviceId ?? id)
      setError(null); setState('on')
      void refreshDevices()                         // labels are only available after permission
    } catch (e) {
      if (!wantRef.current) return
      if (silent) { retryRef.current = setTimeout(() => { void open(id, true) }, 2500); return }   // keep trying to reconnect
      wantRef.current = false
      setState('error'); setError(describeCameraError(e))
    }
  }, [release, refreshDevices, size.width, size.height])

  const start = useCallback(async (id?: string) => { wantRef.current = true; if (retryRef.current) clearTimeout(retryRef.current); await open(id ?? deviceId, false) }, [open, deviceId])
  const stop = useCallback(() => {
    wantRef.current = false
    if (retryRef.current) clearTimeout(retryRef.current)
    release(); setState('off')
  }, [release])
  const select = useCallback(async (id: string) => { setDeviceId(id); if (wantRef.current) await open(id, false) }, [open])

  useEffect(() => {
    const md = navigator.mediaDevices
    md?.addEventListener?.('devicechange', refreshDevices)
    return () => { md?.removeEventListener?.('devicechange', refreshDevices); wantRef.current = false; if (retryRef.current) clearTimeout(retryRef.current); release() }
  }, [refreshDevices, release])

  /** Grab the current frame as a JPEG (downscaled) plus a tiny luminance signature used to skip unchanged frames. */
  const capture = useCallback(async (maxWidth = 640, quality = 0.8): Promise<{ blob: Blob; signature: number[] } | null> => {
    const v = videoRef.current
    if (!v || v.readyState < 2 || !v.videoWidth) return null
    const scale = Math.min(1, maxWidth / v.videoWidth)
    const c = (canvasRef.current ??= document.createElement('canvas'))
    c.width = Math.round(v.videoWidth * scale); c.height = Math.round(v.videoHeight * scale)
    const ctx = c.getContext('2d', { willReadFrequently: true })
    if (!ctx) return null
    ctx.drawImage(v, 0, 0, c.width, c.height)
    const tiny = document.createElement('canvas'); tiny.width = 16; tiny.height = 9
    const tctx = tiny.getContext('2d', { willReadFrequently: true })
    tctx?.drawImage(c, 0, 0, 16, 9)
    const px = tctx?.getImageData(0, 0, 16, 9).data
    const signature: number[] = []
    if (px) for (let i = 0; i < px.length; i += 4) signature.push((px[i] + px[i + 1] + px[i + 2]) / 3)
    const blob = await new Promise<Blob | null>((res) => c.toBlob(res, 'image/jpeg', quality))
    return blob ? { blob, signature } : null
  }, [])

  return { videoRef, state, error, devices, deviceId, aspect, start, stop, select, capture }
}

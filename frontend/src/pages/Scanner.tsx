import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Camera, CameraOff, Pause, Play, Square, Wifi, WifiOff } from 'lucide-react'
import * as svc from '../services/endpoints'
import { useAsync } from '../hooks/useAsync'
import { useAuth } from '../hooks/useAuth'
import { useCamera } from '../hooks/useCamera'
import { Badge, Button, Card, ErrorNote, Notice, PageHeader, Select, StatusBadge, cx } from '../components/ui'
import { ScanTicket } from '../components/ScanTicket'
import { describeScan, frameChanged, holdSeconds, TERMINAL, type Phase } from '../utils/scanState'
import type { ScanResult } from '../types'

type Socket = 'connecting' | 'open' | 'closed' | 'unauthorized'
const WS_URL = () => `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/v1/recognition/ws`
const RESPONSE_TIMEOUT_MS = 12000

interface Recent { key: number; result: ScanResult; at: string }

export default function Scanner() {
  const { can } = useAuth()
  const status = useAsync(() => svc.recognition.status(), [])
  const cfg = status.data
  const camera = useCamera(cfg?.camera)

  const [phase, setPhase] = useState<Phase>('idle')
  const [socket, setSocket] = useState<Socket>('closed')
  const [result, setResult] = useState<ScanResult | null>(null)
  const [recognizing, setRecognizing] = useState(false)
  const [bbox, setBbox] = useState<ScanResult['bbox'] | null>(null)
  const [recent, setRecent] = useState<Recent[]>([])

  const wsRef = useRef<WebSocket | null>(null)
  const phaseRef = useRef<Phase>('idle')
  const inflight = useRef(false)
  const lockUntil = useRef(0)            // no frames are sent until then (cooldown after a result)
  const holdUntil = useRef(0)            // a terminal result stays on screen until then
  const lastSig = useRef<number[] | null>(null)
  const lastWasNoFace = useRef(false)
  const bboxTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const watchdog = useRef<ReturnType<typeof setTimeout> | null>(null)
  const clearTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const attempts = useRef(0)
  const cooldownRef = useRef(10)
  cooldownRef.current = cfg?.cooldown_seconds ?? 10
  phaseRef.current = phase

  // ---- socket ---------------------------------------------------------------------------------
  const closeSocket = useCallback(() => {
    if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
    const ws = wsRef.current
    wsRef.current = null
    if (ws) { ws.onclose = null; ws.onmessage = null; ws.close() }
    inflight.current = false
    setSocket('closed')
  }, [])

  const handleResult = useCallback((r: ScanResult) => {
    inflight.current = false
    setRecognizing(false)
    if (watchdog.current) clearTimeout(watchdog.current)
    lastWasNoFace.current = r.status === 'no_face'
    if (r.status === 'cooldown') return                           // server is still locked after a result; keep what is on screen
    const now = Date.now()
    if (now < holdUntil.current && !TERMINAL.includes(r.status)) return   // do not overwrite a result being shown

    if (r.bbox) {
      setBbox(r.bbox)
      if (bboxTimer.current) clearTimeout(bboxTimer.current)
      bboxTimer.current = setTimeout(() => setBbox(null), 1500)
    } else setBbox(null)
    setResult(r.status === 'no_face' ? null : r)

    const secs = holdSeconds(r.status, cooldownRef.current)
    if (secs > 0) {
      lockUntil.current = now + secs * 1000
      holdUntil.current = now + secs * 1000
      if (clearTimer.current) clearTimeout(clearTimer.current)
      clearTimer.current = setTimeout(() => { setResult(null); setBbox(null); lastSig.current = null }, secs * 1000)
    }
    if (r.status === 'marked' || r.status === 'already_marked') {
      setRecent((x) => [{ key: now, result: r, at: new Date().toLocaleTimeString() }, ...x].slice(0, 8))
    }
  }, [])

  const openSocket = useCallback(() => {
    if (wsRef.current) return
    setSocket('connecting')
    const ws = new WebSocket(WS_URL())
    wsRef.current = ws
    ws.onopen = () => { attempts.current = 0; setSocket('open') }
    ws.onmessage = (ev) => {
      let msg: Omit<Partial<ScanResult>, 'type'> & { type?: string }
      try { msg = JSON.parse(String(ev.data)) } catch { return }
      if (msg.type === 'result' && msg.status) handleResult(msg as ScanResult)
      else if (msg.type === 'error') { inflight.current = false; setRecognizing(false) }
    }
    ws.onclose = (ev) => {
      wsRef.current = null
      inflight.current = false
      setRecognizing(false)
      if (ev.code === 4401) { setSocket('unauthorized'); return }          // not signed in / not allowed: do not loop
      setSocket('closed')
      if (phaseRef.current !== 'idle') {                                    // reconnect with backoff while scanning
        attempts.current += 1
        reconnectTimer.current = setTimeout(openSocket, Math.min(10000, 1000 * attempts.current))
      }
    }
  }, [handleResult])

  const capture = camera.capture
  // ---- frame loop: one frame in flight at a time, throttled, skips unchanged frames -------------
  useEffect(() => {
    if (phase !== 'scanning' || socket !== 'open' || camera.state !== 'on') return
    let stop = false
    let timer: ReturnType<typeof setTimeout>
    const interval = cfg?.frame_interval_ms ?? 700
    const tick = async () => {
      if (stop) return
      const ws = wsRef.current
      const ready = ws && ws.readyState === WebSocket.OPEN && !inflight.current && Date.now() >= lockUntil.current && document.visibilityState === 'visible'
      if (ready) {
        inflight.current = true                                              // claim before awaiting: prevents overlapping sends
        const cap = await capture(640, 0.8)
        if (stop || !cap) { inflight.current = false }
        else if (lastWasNoFace.current && !frameChanged(lastSig.current, cap.signature)) { inflight.current = false }   // empty scene unchanged: skip
        else {
          lastSig.current = cap.signature
          ws.send(cap.blob)
          setRecognizing(true)
          watchdog.current = setTimeout(() => { inflight.current = false; setRecognizing(false) }, RESPONSE_TIMEOUT_MS)
        }
      }
      timer = setTimeout(() => { void tick() }, interval)
    }
    void tick()
    return () => { stop = true; clearTimeout(timer) }
  }, [phase, socket, camera.state, capture, cfg?.frame_interval_ms])

  // ---- controls -------------------------------------------------------------------------------
  const reset = useCallback(() => {
    lockUntil.current = 0; holdUntil.current = 0; lastSig.current = null
    setResult(null); setBbox(null); setRecognizing(false)
    wsRef.current?.readyState === WebSocket.OPEN && wsRef.current.send(JSON.stringify({ type: 'reset' }))
  }, [])

  const start = async () => {
    setPhase('starting'); phaseRef.current = 'starting'
    reset()
    await camera.start()
    openSocket()
    setPhase('scanning')
  }
  const pause = () => { setPhase('paused'); reset() }
  const resume = () => { reset(); setPhase('scanning'); openSocket() }
  const stop = useCallback(() => {
    setPhase('idle'); phaseRef.current = 'idle'
    camera.stop(); closeSocket(); reset()
    if (clearTimer.current) clearTimeout(clearTimer.current)
  }, [camera, closeSocket, reset])

  // If the camera could not start, drop back to idle (the error is shown below).
  useEffect(() => { if (camera.state === 'error' && phaseRef.current !== 'idle') { setPhase('idle'); closeSocket() } }, [camera.state, closeSocket])
  useEffect(() => () => {                                                    // release everything when leaving the page
    phaseRef.current = 'idle'
    ;[bboxTimer, watchdog, clearTimer, reconnectTimer].forEach((t) => t.current && clearTimeout(t.current))
    const ws = wsRef.current; if (ws) { ws.onclose = null; ws.close() }
  }, [])

  const backendOnline = socket === 'open'
  const view = useMemo(
    () => describeScan({ phase: camera.state === 'disconnected' ? 'starting' : phase, recognizing, faceDetected: !!bbox, result, backendOnline }),
    [phase, camera.state, recognizing, bbox, result, backendOnline],
  )
  const tone = view.tone === 'ok' ? 'ok' : view.tone === 'warn' ? 'warn' : view.tone === 'bad' ? 'bad' : bbox || view.tone === 'busy' ? 'busy' : 'idle'
  const active = phase === 'scanning' || phase === 'paused'
  const modelDown = cfg && !cfg.model_loaded

  return (
    <>
      <PageHeader title="Live scanner" subtitle="Stand in front of the camera. Attendance is recorded automatically once the server confirms who you are."
        actions={<div className="flex flex-wrap items-center gap-2">
          <Badge tone={camera.state === 'on' ? 'present' : camera.state === 'disconnected' || camera.state === 'error' ? 'absent' : 'neutral'}>{camera.state === 'on' ? <Camera className="h-3 w-3" /> : <CameraOff className="h-3 w-3" />}Camera {camera.state === 'disconnected' ? 'disconnected' : camera.state === 'on' ? 'on' : camera.state === 'error' ? 'error' : 'off'}</Badge>
          <Badge tone={socket === 'open' ? 'present' : active ? 'absent' : 'neutral'}>{socket === 'open' ? <Wifi className="h-3 w-3" /> : <WifiOff className="h-3 w-3" />}Server {socket === 'open' ? 'connected' : socket === 'connecting' ? 'connecting' : 'not connected'}</Badge>
        </div>} />

      <div className="mb-4 space-y-3">
        {status.error && <ErrorNote error={status.error} onRetry={status.reload} />}
        {modelDown && <ErrorNote error={`Face model not loaded. ${cfg.model_error ?? ''}`} onRetry={status.reload} />}
        {cfg && cfg.liveness_policy === 'off' && (
          <Notice tone="warn">Liveness check is <b>off</b>: a printed photo or a face on a phone screen could be accepted. Use this only where someone supervises the camera.{can('admin') && <> Turn it on in <Link className="underline" to="/settings">Settings</Link>.</>}</Notice>
        )}
        {cfg && cfg.liveness_policy === 'challenge' && <Notice tone="info">Liveness challenge is on (experimental). You will be asked to turn your head. It deters casual photo-holding but does not stop video replays or masks.</Notice>}
        {cfg && cfg.enrolled_people === 0 && <Notice tone="warn">No faces are enrolled yet, so every scan will be “not recognized”. <Link className="underline" to="/people">Register and enroll people</Link> first.</Notice>}
        {socket === 'unauthorized' && <ErrorNote error="The scanner connection was refused. Sign in again with an administrator or operator account." />}
        {camera.error && <ErrorNote error={camera.error} />}
        {camera.state === 'disconnected' && <Notice tone="warn">Camera disconnected. Reconnecting automatically…</Notice>}
      </div>

      <div className="grid gap-6 lg:grid-cols-5">
        <div className="space-y-4 lg:col-span-3">
          <div className="relative overflow-hidden rounded-2xl bg-black" style={{ aspectRatio: camera.aspect }}>
            <video ref={camera.videoRef} muted playsInline aria-label="Camera preview" className="absolute inset-0 h-full w-full -scale-x-100 object-cover" />
            {camera.state !== 'on' && (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-center text-white/70">
                <CameraOff className="h-10 w-10" /><p className="text-sm">{camera.state === 'starting' ? 'Starting camera…' : 'Camera is off'}</p>
              </div>
            )}
            {camera.state === 'on' && (
              <div className="reticle absolute inset-0" data-tone={tone} aria-hidden>
                <i /><i /><i /><i />
                {recognizing && bbox && <span className="sweep absolute left-[14%] right-[14%] h-0.5 rounded bg-white/80" />}
                {bbox && <span className={cx('absolute rounded-lg border-2', tone === 'ok' ? 'border-present' : tone === 'bad' ? 'border-absent' : tone === 'warn' ? 'border-late' : 'border-white/80')}
                  style={{ left: `${(1 - bbox.x - bbox.w) * 100}%`, top: `${bbox.y * 100}%`, width: `${bbox.w * 100}%`, height: `${bbox.h * 100}%` }} />}
              </div>
            )}
            {camera.state === 'on' && (
              <div className="absolute left-3 top-3 flex items-center gap-1.5 rounded-full bg-black/55 px-2.5 py-1 text-xs text-white">
                <span className={cx('h-2 w-2 rounded-full', bbox ? 'bg-present' : 'bg-white/50')} />{bbox ? 'Face detected' : 'No face'}
              </div>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {!active && <Button onClick={() => void start()} loading={phase === 'starting'} disabled={!!modelDown}><Play className="h-4 w-4" />Start scanning</Button>}
            {phase === 'scanning' && <Button variant="secondary" onClick={pause}><Pause className="h-4 w-4" />Pause</Button>}
            {phase === 'paused' && <Button onClick={resume}><Play className="h-4 w-4" />Resume</Button>}
            {active && <Button variant="secondary" onClick={stop}><Square className="h-4 w-4" />Stop and release camera</Button>}
            {camera.devices.length > 1 && (
              <Select aria-label="Camera" className="ml-auto w-auto max-w-[16rem]" value={camera.deviceId} onChange={(e) => void camera.select(e.target.value)}>
                {camera.devices.map((d, i) => <option key={d.deviceId} value={d.deviceId}>{d.label || `Camera ${i + 1}`}</option>)}
              </Select>
            )}
          </div>
          <p className="text-xs text-muted">Frames are sent to the server about every {((cfg?.frame_interval_ms ?? 700) / 1000).toFixed(1)} s, one at a time. Nothing is recorded or stored from the video; only the attendance result is saved.</p>
        </div>

        <div className="space-y-4 lg:col-span-2">
          <ScanTicket view={view} result={result} />
          <Card>
            <h2 className="border-b border-line px-4 py-3 text-base font-semibold">Confirmed this session</h2>
            {recent.length === 0 ? <p className="px-4 py-6 text-sm text-muted">Check-ins confirmed by the server appear here.</p> : (
              <ul className="divide-y divide-line">
                {recent.map(({ key, result: r, at }) => (
                  <li key={key} className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm">
                    <div className="min-w-0"><p className="truncate font-medium">{r.person?.full_name}</p><p className="text-xs text-muted">{r.person?.person_code} · {at}</p></div>
                    {r.status === 'marked' && r.attendance ? <StatusBadge status={r.attendance.status} /> : <Badge>Already marked</Badge>}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </>
  )
}

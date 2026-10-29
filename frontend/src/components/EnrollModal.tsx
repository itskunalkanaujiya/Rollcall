import { useEffect, useRef, useState } from 'react'
import { Camera, ImagePlus, Trash2 } from 'lucide-react'
import * as svc from '../services/endpoints'
import { toApiError } from '../services/api'
import { useCamera } from '../hooks/useCamera'
import type { EnrollmentResult, Person } from '../types'
import { Button, ErrorNote, Modal, Notice, cx } from './ui'

const PROMPTS = ['Look straight at the camera', 'Turn your head slightly to the left', 'Turn your head slightly to the right', 'Neutral expression, chin level', 'Smile', 'Look straight again']
const MAX = 8

interface Shot { id: number; blob: Blob; url: string }

export function EnrollModal({ person, minSamples, onClose, onDone }: { person: Person; minSamples: number; onClose: () => void; onDone: () => void }) {
  const camera = useCamera({ width: 1280, height: 720 })
  const [mode, setMode] = useState<'webcam' | 'upload'>('webcam')
  const [shots, setShots] = useState<Shot[]>([])
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<EnrollmentResult | null>(null)
  const [duplicate, setDuplicate] = useState<EnrollmentResult | null>(null)
  const seq = useRef(0)
  const shotsRef = useRef<Shot[]>([])
  shotsRef.current = shots

  useEffect(() => () => shotsRef.current.forEach((s) => URL.revokeObjectURL(s.url)), [])
  useEffect(() => { if (mode === 'webcam') void camera.start(); else camera.stop() }, [mode]) // eslint-disable-line react-hooks/exhaustive-deps

  const add = (blob: Blob) => setShots((x) => x.length >= MAX ? x : [...x, { id: ++seq.current, blob, url: URL.createObjectURL(blob) }])
  const remove = (id: number) => setShots((x) => { x.filter((s) => s.id === id).forEach((s) => URL.revokeObjectURL(s.url)); return x.filter((s) => s.id !== id) })

  async function snap() { const c = await camera.capture(1280, 0.92); if (c) add(c.blob) }
  function onFiles(files: FileList | null) {
    if (!files) return
    for (const f of Array.from(files)) { if (f.type.startsWith('image/')) add(f) }
  }

  async function submit(confirmDuplicate = false) {
    setBusy(true); setError(null)
    try {
      const r = await svc.people.enroll(person.id, shots.map((s) => s.blob), { source: mode, confirmDuplicate })
      setResult(r); setDuplicate(null); camera.stop()
      onDone()
    } catch (e) {
      const info = toApiError(e)
      const d = info.details as EnrollmentResult | undefined
      if (info.code === 'possible_duplicate' && d) setDuplicate(d)
      else if (info.code === 'no_usable_images' && d) { setResult(d); setError('None of these photos could be used. Fix the issues below and try again.') }
      else setError(info.message)
    } finally { setBusy(false) }
  }

  const ready = consent && shots.length >= 1
  const prompt = PROMPTS[shots.length % PROMPTS.length]

  return (
    <Modal wide title={`Enroll face - ${person.full_name}`} onClose={() => { camera.stop(); onClose() }}
      footer={result?.accepted ? <Button onClick={() => { camera.stop(); onClose() }}>Done</Button> : <>
        <Button variant="secondary" onClick={() => { camera.stop(); onClose() }}>Cancel</Button>
        <Button loading={busy} disabled={!ready} onClick={() => void submit(false)}>Save {shots.length || ''} photo{shots.length === 1 ? '' : 's'}</Button>
      </>}>
      <div className="space-y-4">
        {result?.accepted ? (
          <Notice tone="ok">Saved {result.accepted} face sample{result.accepted === 1 ? '' : 's'}. {result.enrollment_status === 'enrolled' ? 'Enrollment is complete.' : `Add at least ${minSamples - result.total_samples} more to finish enrollment.`}</Notice>
        ) : (
          <>
            <div className="flex gap-2" role="tablist">
              {(['webcam', 'upload'] as const).map((m) => (
                <button key={m} role="tab" aria-selected={mode === m} onClick={() => setMode(m)}
                  className={cx('flex items-center gap-2 rounded-lg border px-3 py-1.5 text-sm font-medium', mode === m ? 'border-brand bg-brand text-on-brand' : 'border-line hover:bg-surface-2')}>
                  {m === 'webcam' ? <Camera className="h-4 w-4" /> : <ImagePlus className="h-4 w-4" />}{m === 'webcam' ? 'Use webcam' : 'Upload photos'}
                </button>
              ))}
            </div>
            <p className="text-sm text-muted">Take or add {minSamples}–{MAX} clear photos with different head angles and expressions. One person per photo, good light, no sunglasses or masks.</p>

            {mode === 'webcam' ? (
              <div>
                <div className="relative overflow-hidden rounded-xl bg-black" style={{ aspectRatio: camera.aspect }}>
                  <video ref={camera.videoRef} muted playsInline aria-label="Camera preview" className="absolute inset-0 h-full w-full -scale-x-100 object-cover" />
                  {camera.state === 'on' && <p className="absolute inset-x-0 bottom-0 bg-black/60 px-3 py-2 text-center text-sm text-white">{prompt}</p>}
                  {camera.state !== 'on' && <div className="absolute inset-0 flex items-center justify-center text-sm text-white/70">{camera.state === 'starting' ? 'Starting camera…' : 'Camera is off'}</div>}
                </div>
                {camera.error && <div className="mt-2"><ErrorNote error={camera.error} /></div>}
                <Button className="mt-3" onClick={() => void snap()} disabled={camera.state !== 'on' || shots.length >= MAX}><Camera className="h-4 w-4" />Capture photo ({shots.length}/{MAX})</Button>
              </div>
            ) : (
              <label className="flex cursor-pointer flex-col items-center gap-1 rounded-xl border-2 border-dashed border-line p-6 text-center text-sm hover:bg-surface-2">
                <ImagePlus className="h-6 w-6 text-muted" /><span className="font-medium">Choose photos</span><span className="text-xs text-muted">JPEG, PNG or WEBP, up to 5 MB each</span>
                <input type="file" accept="image/jpeg,image/png,image/webp" multiple className="sr-only" onChange={(e) => { onFiles(e.target.files); e.target.value = '' }} />
              </label>
            )}

            {shots.length > 0 && (
              <ul className="flex flex-wrap gap-2" aria-label="Selected photos">
                {shots.map((s, i) => (
                  <li key={s.id} className="relative">
                    <img src={s.url} alt={`Photo ${i + 1}`} className="h-20 w-20 rounded-lg object-cover" />
                    <button onClick={() => remove(s.id)} aria-label={`Remove photo ${i + 1}`} className="absolute -right-1.5 -top-1.5 rounded-full bg-surface p-1 shadow ring-1 ring-line"><Trash2 className="h-3 w-3" /></button>
                  </li>
                ))}
              </ul>
            )}

            <label className="flex items-start gap-2.5 rounded-lg bg-surface-2 p-3 text-sm">
              <input type="checkbox" className="mt-0.5 h-4 w-4" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
              <span><b>{person.full_name}</b> has been told how their face data is used for attendance and has agreed to be enrolled. Only an encrypted face template is stored; the photos are discarded after processing. The person can ask for their data to be deleted at any time.</span>
            </label>
          </>
        )}

        {error && <ErrorNote error={error} />}
        {duplicate && (
          <Notice tone="warn">
            <p className="font-medium">These photos closely match someone already enrolled. Nothing was saved.</p>
            <ul className="mt-1 list-disc pl-5">{duplicate.possible_duplicates.map((d) => <li key={d.person_id}>{d.full_name} ({d.person_code}) - similarity {d.similarity.toFixed(2)}</li>)}</ul>
            <p className="mt-2">A high match may be a duplicate registration of the same person, or a look-alike. It is a warning, not proof of identity. Check before continuing.</p>
            <Button variant="secondary" className="mt-2" loading={busy} onClick={() => void submit(true)}>This is a different person - enroll anyway</Button>
          </Notice>
        )}
        {result && result.rejected.length > 0 && (
          <div className="text-sm">
            <p className="mb-1 font-medium">Photos that were not used</p>
            <ul className="space-y-0.5 text-muted">{result.rejected.map((r) => <li key={r.index}>Photo {r.index + 1}: {r.reason}</li>)}</ul>
          </div>
        )}
        {result?.warnings.map((w) => <Notice key={w} tone="warn">{w}</Notice>)}
      </div>
    </Modal>
  )
}

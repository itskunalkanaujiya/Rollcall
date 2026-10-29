import { describeScan, frameChanged, holdSeconds } from '../utils/scanState'
import type { ScanResult } from '../types'

const base = { phase: 'scanning' as const, recognizing: false, faceDetected: false, result: null, backendOnline: true }
const person = { id: 1, person_code: 'E1', full_name: 'Rahul Sharma', department: 'CS' }
const attendance = { id: 5, session: 'Morning', session_date: '2026-01-05', marked_at: '2026-01-05T03:42:00Z', local_time: '09:12:00', status: 'present' as const, method: 'face' }
const res = (status: ScanResult['status'], extra: Partial<ScanResult> = {}): ScanResult => ({ status, message: 'server message', ...extra })

describe('describeScan', () => {
  it('walks through the waiting → detected → recognizing states', () => {
    expect(describeScan(base)).toMatchObject({ key: 'waiting', message: 'Please look at the camera.' })
    expect(describeScan({ ...base, faceDetected: true })).toMatchObject({ key: 'detected', message: 'Keep your face within the frame.' })
    expect(describeScan({ ...base, faceDetected: true, recognizing: true })).toMatchObject({ key: 'recognizing', message: 'Verifying identity…' })
  })
  it('shows success only for a backend-confirmed "marked" result', () => {
    const marked = describeScan({ ...base, result: res('marked', { person, attendance, message: 'Welcome, Rahul Sharma. Attendance recorded at 9:12 AM.' }) })
    expect(marked).toMatchObject({ key: 'marked', tone: 'ok', message: 'Welcome, Rahul Sharma. Attendance recorded at 9:12 AM.' })
    // every other status must never produce the success view
    for (const s of ['unknown', 'already_marked', 'no_face', 'poor_quality', 'liveness_failed', 'no_active_session', 'person_disabled', 'multiple_faces', 'model_unavailable', 'cooldown'] as const) {
      expect(describeScan({ ...base, faceDetected: true, recognizing: true, result: res(s) }).key).not.toBe('marked')
    }
    expect(describeScan({ ...base, faceDetected: true, recognizing: true }).tone).not.toBe('ok')   // a face in view is not a success
  })
  it('uses the required wording for duplicate, unknown and liveness failure', () => {
    expect(describeScan({ ...base, result: res('already_marked', { message: '' }) }).message).toBe('Your attendance has already been recorded.')
    expect(describeScan({ ...base, result: res('unknown') })).toMatchObject({ tone: 'bad', message: 'Person not recognized. No attendance recorded.' })
    expect(describeScan({ ...base, result: res('liveness_failed') }).message).toBe('Verification failed. Please try again.')
  })
  it('reports camera, scanner and backend problems', () => {
    expect(describeScan({ ...base, phase: 'idle' }).key).toBe('idle')
    expect(describeScan({ ...base, phase: 'paused' }).key).toBe('paused')
    expect(describeScan({ ...base, backendOnline: false })).toMatchObject({ key: 'offline', tone: 'bad' })
  })
})

describe('frame throttling helpers', () => {
  it('detects unchanged frames', () => {
    const a = Array(144).fill(100)
    expect(frameChanged(null, a)).toBe(true)
    expect(frameChanged(a, a.map((v) => v + 0.5))).toBe(false)
    expect(frameChanged(a, a.map((v) => v + 20))).toBe(true)
  })
  it('locks the scanner after a result for the configured cooldown', () => {
    expect(holdSeconds('marked', 10)).toBe(10)
    expect(holdSeconds('already_marked', 7)).toBe(7)
    expect(holdSeconds('unknown', 10)).toBe(3)
    expect(holdSeconds('no_face', 10)).toBe(0)
  })
})

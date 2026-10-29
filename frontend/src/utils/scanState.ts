import type { ScanResult } from '../types'

export type Tone = 'idle' | 'ok' | 'warn' | 'bad' | 'busy'
export type Phase = 'idle' | 'starting' | 'scanning' | 'paused'

export interface ScanView { key: string; tone: Tone; title: string; message: string }

interface Input { phase: Phase; recognizing: boolean; faceDetected: boolean; result: ScanResult | null; backendOnline: boolean }

/**
 * Maps scanner state to what the person at the camera sees.
 * A success view ("Attendance marked") is produced ONLY from a backend result with status === 'marked',
 * i.e. after the database record was created - never from a local guess.
 */
export function describeScan({ phase, recognizing, faceDetected, result, backendOnline }: Input): ScanView {
  if (phase === 'idle') return { key: 'idle', tone: 'idle', title: 'Scanner is off', message: 'Press Start scanning to turn on the camera.' }
  if (phase === 'starting') return { key: 'starting', tone: 'busy', title: 'Starting camera', message: 'Allow camera access if your browser asks.' }
  if (phase === 'paused') return { key: 'paused', tone: 'idle', title: 'Scanning paused', message: 'Press Resume to continue. The camera is still on.' }
  if (!backendOnline) return { key: 'offline', tone: 'bad', title: 'Server not connected', message: 'Reconnecting to the recognition service…' }

  if (result) {
    const name = result.person?.full_name
    switch (result.status) {
      case 'marked': return { key: 'marked', tone: 'ok', title: 'Attendance marked', message: result.message || `Welcome, ${name}.` }
      case 'already_marked': return { key: 'already', tone: 'warn', title: 'Already marked', message: result.message || 'Your attendance has already been recorded.' }
      case 'unknown': return { key: 'unknown', tone: 'bad', title: 'Person not recognized', message: 'Person not recognized. No attendance recorded.' }
      case 'person_disabled': return { key: 'disabled', tone: 'bad', title: 'Account disabled', message: result.message }
      case 'no_active_session': return { key: 'nosession', tone: 'warn', title: 'No open session', message: result.message }
      case 'multiple_faces': return { key: 'multi', tone: 'warn', title: 'More than one face', message: result.message }
      case 'liveness_failed': return { key: 'live-fail', tone: 'bad', title: 'Liveness check failed', message: 'Verification failed. Please try again.' }
      case 'liveness_unsupported': return { key: 'live-unsupported', tone: 'bad', title: 'Liveness not available', message: result.message }
      case 'liveness_challenge': return { key: 'live', tone: 'busy', title: 'Liveness check', message: result.message }
      case 'model_unavailable': return { key: 'model', tone: 'bad', title: 'Recognition unavailable', message: result.message }
      case 'poor_quality': return { key: 'quality', tone: 'warn', title: 'Adjust your position', message: result.message }
      case 'bad_image': return { key: 'bad-image', tone: 'warn', title: 'Camera frame unreadable', message: result.message }
      default: break
    }
  }
  if (recognizing && faceDetected) return { key: 'recognizing', tone: 'busy', title: 'Verifying identity', message: 'Verifying identity…' }
  if (faceDetected) return { key: 'detected', tone: 'busy', title: 'Face detected', message: 'Keep your face within the frame.' }
  return { key: 'waiting', tone: 'idle', title: 'Waiting for a face', message: 'Please look at the camera.' }
}

/** Statuses after which the scanner holds the result on screen and stops submitting frames for a while. */
export const TERMINAL: ScanResult['status'][] = ['marked', 'already_marked', 'unknown', 'person_disabled', 'no_active_session', 'liveness_failed', 'multiple_faces']

export function holdSeconds(status: ScanResult['status'], cooldown: number): number {
  if (status === 'marked' || status === 'already_marked' || status === 'person_disabled' || status === 'no_active_session') return cooldown
  if (status === 'unknown' || status === 'liveness_failed' || status === 'multiple_faces') return 3
  return 0
}

export function frameChanged(prev: number[] | null, next: number[], threshold = 2): boolean {
  if (!prev || prev.length !== next.length) return true
  let sum = 0
  for (let i = 0; i < next.length; i++) sum += Math.abs(prev[i] - next[i])
  return sum / next.length > threshold
}

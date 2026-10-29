import { AlertTriangle, CheckCircle2, Clock, Loader2, ScanFace, ShieldAlert, UserX, WifiOff } from 'lucide-react'
import type { ScanResult } from '../types'
import type { ScanView, Tone } from '../utils/scanState'
import { StatusBadge, cx } from './ui'

const TONE: Record<Tone, string> = {
  idle: 'border-line bg-surface-2 text-ink', ok: 'border-present/50 bg-present-bg text-present',
  warn: 'border-late/50 bg-late-bg text-late', bad: 'border-absent/50 bg-absent-bg text-absent', busy: 'border-info/40 bg-info-bg text-info',
}
function Icon({ view }: { view: ScanView }) {
  const c = 'h-7 w-7'
  if (view.key === 'marked') return <CheckCircle2 className={c} />
  if (view.key === 'already') return <Clock className={c} />
  if (view.key === 'unknown') return <UserX className={c} />
  if (view.key === 'offline') return <WifiOff className={c} />
  if (view.key.startsWith('live') || view.key === 'disabled') return <ShieldAlert className={c} />
  if (view.tone === 'busy') return <Loader2 className={cx(c, 'animate-spin')} />
  if (view.tone === 'warn' || view.tone === 'bad') return <AlertTriangle className={c} />
  return <ScanFace className={c} />
}

/** The result panel. Person details are only rendered for a backend-confirmed marked / already-marked result. */
export function ScanTicket({ view, result }: { view: ScanView; result: ScanResult | null }) {
  const confirmed = result && (view.key === 'marked' || view.key === 'already')   // only when the view itself reflects the confirmed result
  return (
    <div role="status" aria-live="polite" data-testid="scan-ticket" data-state={view.key} className={cx('rounded-xl border-2 p-5', TONE[view.tone])}>
      <div className="flex items-start gap-3">
        <Icon view={view} />
        <div className="min-w-0">
          <p className="font-display text-xl font-semibold leading-tight">{view.title}</p>
          <p className="mt-1 text-sm text-ink">{view.message}</p>
        </div>
      </div>
      {confirmed && result.person && result.attendance && (
        <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 rounded-lg bg-surface/80 p-3 text-sm text-ink">
          <div><dt className="text-xs text-muted">Name</dt><dd className="font-medium">{result.person.full_name}</dd></div>
          <div><dt className="text-xs text-muted">Person ID</dt><dd className="font-medium">{result.person.person_code}</dd></div>
          <div><dt className="text-xs text-muted">Session</dt><dd>{result.attendance.session}</dd></div>
          <div><dt className="text-xs text-muted">{result.status === 'marked' ? 'Recorded at' : 'First recorded at'}</dt><dd className="tabular-nums">{result.attendance.session_date} {result.attendance.local_time}</dd></div>
          <div><dt className="text-xs text-muted">Status</dt><dd><StatusBadge status={result.attendance.status} /></dd></div>
          {result.similarity !== undefined && (
            <div><dt className="text-xs text-muted">Match score</dt><dd title="Cosine similarity between face templates. It is a score, not a probability of being correct." className="tabular-nums">{result.similarity.toFixed(2)}</dd></div>
          )}
        </dl>
      )}
      {result?.status === 'liveness_challenge' && result.challenge && (
        <p className="mt-3 text-xs text-muted">Experimental check: it deters casual photo-holding but is not strong spoof protection.</p>
      )}
    </div>
  )
}

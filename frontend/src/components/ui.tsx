import { createContext, useCallback, useContext, useEffect, useId, useRef, useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from 'react'
import { AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight, Info, Loader2, X } from 'lucide-react'
import type { ApiErrorInfo } from '../services/api'
import { STATUS_LABEL } from '../utils/format'

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(' ')

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost'
const VARIANTS: Record<Variant, string> = {
  primary: 'bg-brand text-on-brand hover:bg-brand-strong disabled:opacity-50',
  secondary: 'bg-surface text-ink border border-line hover:bg-surface-2 disabled:opacity-50',
  danger: 'bg-absent text-white hover:opacity-90 disabled:opacity-50',
  ghost: 'text-ink hover:bg-surface-2 disabled:opacity-50',
}
export function Button({ variant = 'primary', loading, className, children, disabled, ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; loading?: boolean }) {
  return (
    <button {...rest} disabled={disabled || loading}
      className={cx('inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition-colors', VARIANTS[variant], className)}>
      {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
      {children}
    </button>
  )
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <section className={cx('rounded-xl border border-line bg-surface', className)}>{children}</section>
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold">{title}</h1>
        {subtitle && <p className="mt-1 max-w-prose text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  )
}

const TONES: Record<string, string> = {
  present: 'bg-present-bg text-present', corrected: 'bg-info-bg text-info', late: 'bg-late-bg text-late',
  absent: 'bg-absent-bg text-absent', neutral: 'bg-surface-2 text-muted', info: 'bg-info-bg text-info',
}
export function Badge({ tone = 'neutral', children }: { tone?: string; children: ReactNode }) {
  return <span className={cx('inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium', TONES[tone] ?? TONES.neutral)}>{children}</span>
}
export const StatusBadge = ({ status }: { status: string }) => <Badge tone={status}>{STATUS_LABEL[status] ?? status}</Badge>

export function Field({ label, error, hint, children }: { label: string; error?: string; hint?: string; children: (id: string, invalid: boolean) => ReactNode }) {
  const id = useId()
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-medium">{label}</label>
      {children(id, !!error)}
      {hint && !error && <p className="mt-1 text-xs text-muted">{hint}</p>}
      {error && <p role="alert" className="mt-1 text-xs text-absent">{error}</p>}
    </div>
  )
}
const inputCls = (invalid?: boolean) => cx('w-full rounded-lg border bg-surface-2 px-3 py-2 text-sm text-ink placeholder:text-muted/70', invalid ? 'border-absent' : 'border-line')
export const Input = ({ invalid, className, ...p }: InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean }) => <input {...p} aria-invalid={invalid || undefined} className={cx(inputCls(invalid), className)} />
export const Select = ({ invalid, className, ...p }: SelectHTMLAttributes<HTMLSelectElement> & { invalid?: boolean }) => <select {...p} aria-invalid={invalid || undefined} className={cx(inputCls(invalid), className)} />

const TIME_HOURS = Array.from({ length: 12 }, (_, i) => String(i + 1))
const TIME_MINUTES = Array.from({ length: 60 }, (_, i) => String(i).padStart(2, '0'))

/** Dropdown list rendered and styled by us, not the browser: native <select> popups don't
 * reliably follow the app's dark theme (some browsers/webviews always render the open listbox
 * in the OS light theme), which made the time picker flash white mid-interaction. */
function MiniSelect({ id, value, placeholder, options, onChange, ariaLabel, className }:
  { id?: string; value: string; placeholder?: string; options: string[]; onChange: (v: string) => void; ariaLabel: string; className?: string }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const listRef = useRef<HTMLUListElement>(null)
  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDoc); document.addEventListener('keydown', onKey)
    listRef.current?.querySelector<HTMLElement>('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' })
    return () => { document.removeEventListener('mousedown', onDoc); document.removeEventListener('keydown', onKey) }
  }, [open])
  const move = (dir: 1 | -1) => {
    const i = options.indexOf(value)
    const next = options[Math.min(options.length - 1, Math.max(0, (i < 0 ? (dir === 1 ? -1 : options.length) : i) + dir))]
    if (next !== undefined) onChange(next)
  }
  return (
    <div ref={ref} className="relative">
      <button id={id} type="button" aria-haspopup="listbox" aria-expanded={open} aria-label={ariaLabel}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') { e.preventDefault(); setOpen(true); move(1) }
          else if (e.key === 'ArrowUp') { e.preventDefault(); setOpen(true); move(-1) }
          else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpen((v) => !v) }
        }}
        className={cx('appearance-none bg-transparent py-2 text-sm text-ink focus:outline-none disabled:opacity-50', className, !value && 'text-muted')}>
        {value || placeholder}
      </button>
      {open && (
        <ul ref={listRef} role="listbox" aria-label={ariaLabel} tabIndex={-1}
          className="absolute left-0 top-full z-50 mt-1 max-h-48 min-w-full overflow-auto rounded-lg border border-line bg-surface-2 py-1 text-sm shadow-xl">
          {options.map((o) => (
            <li key={o} role="option" aria-selected={o === value}
              onClick={() => { onChange(o); setOpen(false) }}
              className={cx('cursor-pointer px-3 py-1.5 text-center', o === value ? 'bg-brand text-on-brand' : 'text-ink hover:bg-surface')}>
              {o}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** 12-hour hour/minute/AM-PM picker. Value and onChange use 24-hour "HH:MM" so the
 * app's native <input type="time"> browser rendering (locale-dependent, sometimes 24h-only
 * on Windows) never leaks into the UI. */
export function TimeInput({ id, value, onChange, invalid, clearable }:
  { id?: string; value: string; onChange: (v: string | null) => void; invalid?: boolean; clearable?: boolean }) {
  const [hStr, mStr] = value ? value.split(':') : [undefined, undefined]
  const h24 = hStr !== undefined ? Number(hStr) : undefined
  const period: 'AM' | 'PM' = h24 === undefined || h24 < 12 ? 'AM' : 'PM'
  const h12 = h24 === undefined ? '' : String(h24 % 12 === 0 ? 12 : h24 % 12)
  const minute = mStr ?? ''

  const emit = (h12v: string, minv: string, per: 'AM' | 'PM') => {
    if (!h12v || !minv) return
    let h = Number(h12v) % 12
    if (per === 'PM') h += 12
    onChange(`${String(h).padStart(2, '0')}:${minv}`)
  }

  return (
    <div className="flex items-center gap-2">
      <div className={cx('flex items-center rounded-lg border bg-surface-2', invalid ? 'border-absent' : 'border-line')} aria-invalid={invalid || undefined}>
        <MiniSelect id={id} ariaLabel="Hour" placeholder="HH" value={h12} options={TIME_HOURS} onChange={(v) => emit(v, minute || '00', period)} className="w-11 pl-2.5 pr-0.5 text-right" />
        <span className="text-muted" aria-hidden>:</span>
        <MiniSelect ariaLabel="Minute" placeholder="MM" value={minute} options={TIME_MINUTES} onChange={(v) => emit(h12 || '12', v, period)} className="w-10 pl-0.5 pr-1" />
        <span className={cx('h-5 w-px', invalid ? 'bg-absent/40' : 'bg-line')} aria-hidden />
        <MiniSelect ariaLabel="AM or PM" value={period} options={['AM', 'PM']} onChange={(v) => emit(h12 || '12', minute || '00', v as 'AM' | 'PM')} className="w-[4.1rem] pl-1.5 pr-2.5 font-medium" />
      </div>
      {clearable && value && <button type="button" onClick={() => onChange(null)} className="text-xs text-muted underline">Clear</button>}
    </div>
  )
}

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return <div role="status" className="flex items-center justify-center gap-2 py-10 text-sm text-muted"><Loader2 className="h-4 w-4 animate-spin" aria-hidden />{label}…</div>
}

export function EmptyState({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      {icon && <div className="mb-3 text-muted">{icon}</div>}
      <p className="font-medium">{title}</p>
      {children && <p className="mt-1 max-w-sm text-sm text-muted">{children}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function ErrorNote({ error, onRetry }: { error: ApiErrorInfo | string; onRetry?: () => void }) {
  const msg = typeof error === 'string' ? error : error.message
  return (
    <div role="alert" className="flex items-start gap-3 rounded-lg border border-absent/40 bg-absent-bg p-3 text-sm text-absent">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="flex-1">{msg}</div>
      {onRetry && <button onClick={onRetry} className="font-medium underline">Retry</button>}
    </div>
  )
}

export function Notice({ tone = 'info', children }: { tone?: 'info' | 'warn' | 'bad' | 'ok'; children: ReactNode }) {
  const cls = { info: 'bg-info-bg text-info', warn: 'bg-late-bg text-late', bad: 'bg-absent-bg text-absent', ok: 'bg-present-bg text-present' }[tone]
  const Icon = tone === 'ok' ? CheckCircle2 : tone === 'info' ? Info : AlertTriangle
  return <div className={cx('flex items-start gap-2.5 rounded-lg p-3 text-sm', cls)}><Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden /><div>{children}</div></div>
}

export function Modal({ title, onClose, children, wide, footer }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean; footer?: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null
    ref.current?.focus()
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', key)
    return () => { document.removeEventListener('keydown', key); prev?.focus() }
  }, [onClose])
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/50 p-4 sm:p-8" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title}
        className={cx('w-full rounded-xl border border-line bg-surface shadow-2xl outline-none', wide ? 'max-w-3xl' : 'max-w-lg')}>
        <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="rounded p-1 text-muted hover:bg-surface-2"><X className="h-5 w-5" /></button>
        </div>
        <div className="p-5">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-line px-5 py-3.5">{footer}</div>}
      </div>
    </div>
  )
}

export function Pagination({ page, pages, total, onPage, label = 'results' }: { page: number; pages: number; total: number; onPage: (p: number) => void; label?: string }) {
  return (
    <div className="flex items-center justify-between border-t border-line px-4 py-3 text-sm text-muted">
      <span>{total.toLocaleString()} {label}</span>
      <div className="flex items-center gap-1">
        <button className="rounded p-1.5 hover:bg-surface-2 disabled:opacity-40" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page"><ChevronLeft className="h-4 w-4" /></button>
        <span className="px-2">Page {page} of {pages}</span>
        <button className="rounded p-1.5 hover:bg-surface-2 disabled:opacity-40" disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="Next page"><ChevronRight className="h-4 w-4" /></button>
      </div>
    </div>
  )
}

/** Confirm dialog for destructive actions. */
export function Confirm({ title, children, confirmLabel, onConfirm, onCancel, busy }: { title: string; children: ReactNode; confirmLabel: string; onConfirm: () => void; onCancel: () => void; busy?: boolean }) {
  return (
    <Modal title={title} onClose={onCancel} footer={<><Button variant="secondary" onClick={onCancel}>Cancel</Button><Button variant="danger" loading={busy} onClick={onConfirm}>{confirmLabel}</Button></>}>
      <div className="text-sm">{children}</div>
    </Modal>
  )
}

// ---- toasts -------------------------------------------------------------------------------------
interface Toast { id: number; tone: 'ok' | 'bad'; text: string }
const ToastCtx = createContext<(tone: 'ok' | 'bad', text: string) => void>(() => undefined)
export const useToast = () => useContext(ToastCtx)
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([])
  const push = useCallback((tone: 'ok' | 'bad', text: string) => {
    const id = Date.now() + Math.random()
    setItems((x) => [...x, { id, tone, text }])
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), 4500)
  }, [])
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="fixed bottom-4 right-4 z-[60] flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2" aria-live="polite">
        {items.map((t) => <Notice key={t.id} tone={t.tone}>{t.text}</Notice>)}
      </div>
    </ToastCtx.Provider>
  )
}

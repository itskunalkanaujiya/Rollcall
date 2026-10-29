import { useMemo, useState, type FormEvent } from 'react'
import { ArrowDown, ArrowUp, ClipboardList, Download, PenLine, Plus, Search } from 'lucide-react'
import * as svc from '../services/endpoints'
import { fieldErrors, toApiError } from '../services/api'
import { useAsync } from '../hooks/useAsync'
import { useAuth } from '../hooks/useAuth'
import { useDebounce } from '../hooks/useDebounce'
import { Badge, Button, Card, EmptyState, ErrorNote, Field, Input, Modal, Notice, PageHeader, Pagination, Select, Spinner, StatusBadge, useToast } from '../components/ui'
import { daysAgo, download, fmtDate, isoDay } from '../utils/format'
import type { AttendanceRow } from '../types'

type SortKey = 'date' | 'name' | 'status' | 'session'

function Details({ row, onClose, onCorrect }: { row: AttendanceRow; onClose: () => void; onCorrect?: () => void }) {
  const items: [string, string][] = [['Person', `${row.person_name} (${row.person_code})`], ['Department', row.department ?? '-'], ['Session', row.session_name], ['Date', fmtDate(row.session_date)],
    ['Time', row.local_time ?? '-'], ['Method', row.method === 'face' ? 'Face recognition' : row.method === 'manual' ? 'Manual entry' : 'Not recorded'],
    ['Match score', row.similarity === null ? '-' : `${row.similarity.toFixed(2)} (cosine similarity, not a probability)`], ['Note', row.note ?? '-']]
  return (
    <Modal title="Attendance details" onClose={onClose} footer={onCorrect && row.id !== null ? <Button onClick={onCorrect}><PenLine className="h-4 w-4" />Correct status</Button> : undefined}>
      <div className="mb-4 flex items-center gap-2"><StatusBadge status={row.status} />{row.corrected && <Badge tone="info">Corrected by an administrator</Badge>}{row.is_computed && <Badge>Computed: no check-in found</Badge>}</div>
      <dl className="space-y-2.5">{items.map(([k, v]) => <div key={k} className="grid grid-cols-3 gap-2 text-sm"><dt className="text-muted">{k}</dt><dd className="col-span-2">{v}</dd></div>)}</dl>
    </Modal>
  )
}

function CorrectModal({ row, onClose, onSaved }: { row: AttendanceRow; onClose: () => void; onSaved: () => void }) {
  const toast = useToast()
  const [status, setStatus] = useState<'present' | 'late' | 'corrected'>(row.status === 'absent' ? 'present' : row.status)
  const [note, setNote] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  async function submit(e: FormEvent) {
    e.preventDefault()
    if (note.trim().length < 3) { setErr('Give a reason (at least 3 characters).'); return }
    setBusy(true)
    try { await svc.attendance.correct(row.id as number, { status, note: note.trim() }); toast('ok', 'Attendance corrected.'); onSaved() }
    catch (e2) { setErr(toApiError(e2).message) } finally { setBusy(false) }
  }
  return (
    <Modal title={`Correct attendance - ${row.person_name}`} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4" noValidate>
        <Notice>Corrections are logged with your name and the original status.</Notice>
        <Field label="New status">{(id) => <Select id={id} value={status} onChange={(e) => setStatus(e.target.value as 'present' | 'late' | 'corrected')}><option value="present">Present</option><option value="late">Late</option><option value="corrected">Corrected (counts as attended)</option></Select>}</Field>
        <Field label="Reason" error={err ?? undefined}>{(id, bad) => <Input id={id} invalid={bad} value={note} onChange={(e) => setNote(e.target.value)} autoFocus />}</Field>
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" loading={busy}>Save correction</Button></div>
      </form>
    </Modal>
  )
}

function ManualModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const toast = useToast()
  const people = useAsync(() => svc.people.list({ page_size: 100, status: 'active' }), [])
  const sessions = useAsync(() => svc.sessions.list(), [])
  const [f, setF] = useState({ person_id: '', session_id: '', session_date: isoDay(new Date()), status: 'present', note: '' })
  const [errs, setErrs] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  async function submit(e: FormEvent) {
    e.preventDefault()
    const v: Record<string, string> = {}
    if (!f.person_id) v.person_id = 'Choose a person.'
    if (!f.session_id) v.session_id = 'Choose a session.'
    if (f.note.trim().length < 3) v.note = 'Give a reason (at least 3 characters).'
    setErrs(v); if (Object.keys(v).length) return
    setBusy(true)
    try { await svc.attendance.manual({ person_id: +f.person_id, session_id: +f.session_id, session_date: f.session_date, status: f.status, note: f.note.trim() }); toast('ok', 'Manual entry added.'); onSaved() }
    catch (e2) { const i = toApiError(e2); setErrs(i.status === 422 ? fieldErrors(i) : { note: i.message }) } finally { setBusy(false) }
  }
  const set = (k: string) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }))
  return (
    <Modal title="Add manual entry" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4" noValidate>
        <Notice>Manual entries are labelled “Manual” everywhere and are not face-verified.</Notice>
        <Field label="Person" error={errs.person_id}>{(id, bad) => <Select id={id} invalid={bad} value={f.person_id} onChange={set('person_id')}><option value="">Select…</option>{people.data?.items.map((p) => <option key={p.id} value={p.id}>{p.full_name} ({p.person_code})</option>)}</Select>}</Field>
        <Field label="Session" error={errs.session_id}>{(id, bad) => <Select id={id} invalid={bad} value={f.session_id} onChange={set('session_id')}><option value="">Select…</option>{sessions.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select>}</Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Date">{(id) => <Input id={id} type="date" max={isoDay(new Date())} value={f.session_date} onChange={set('session_date')} />}</Field>
          <Field label="Status">{(id) => <Select id={id} value={f.status} onChange={set('status')}><option value="present">Present</option><option value="late">Late</option><option value="corrected">Corrected</option></Select>}</Field>
        </div>
        <Field label="Reason" error={errs.note}>{(id, bad) => <Input id={id} invalid={bad} value={f.note} onChange={set('note')} />}</Field>
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" loading={busy}>Add entry</Button></div>
      </form>
    </Modal>
  )
}

export default function Attendance() {
  const { can } = useAuth()
  const toast = useToast()
  const [q, setQ] = useState(''); const [from, setFrom] = useState(daysAgo(29)); const [to, setTo] = useState(isoDay(new Date()))
  const [sessionId, setSessionId] = useState(''); const [dept, setDept] = useState(''); const [status, setStatus] = useState('')
  const [sort, setSort] = useState<SortKey>('date'); const [order, setOrder] = useState<'asc' | 'desc'>('desc'); const [page, setPage] = useState(1)
  const dq = useDebounce(q)
  const params = useMemo(() => ({ q: dq, date_from: from, date_to: to, session_id: sessionId, department: dept, status }), [dq, from, to, sessionId, dept, status])
  const list = useAsync(() => svc.attendance.list({ ...params, sort, order, page, page_size: 20 }), [params, sort, order, page])
  const sessions = useAsync(() => svc.sessions.list(), [])
  const depts = useAsync(() => svc.people.departments(), [])
  const [detail, setDetail] = useState<AttendanceRow | null>(null)
  const [correct, setCorrect] = useState<AttendanceRow | null>(null)
  const [manual, setManual] = useState(false)
  const [exporting, setExporting] = useState(false)

  const setF = (fn: (v: string) => void) => (e: { target: { value: string } }) => { fn(e.target.value); setPage(1) }
  const sortBy = (k: SortKey) => { if (sort === k) setOrder((o) => (o === 'asc' ? 'desc' : 'asc')); else { setSort(k); setOrder(k === 'date' ? 'desc' : 'asc') } setPage(1) }
  const Th = ({ k, children }: { k: SortKey; children: string }) => (
    <th className="px-4 py-2.5 font-medium" aria-sort={sort === k ? (order === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button onClick={() => sortBy(k)} className="inline-flex items-center gap-1 hover:text-ink">{children}{sort === k && (order === 'asc' ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}</button>
    </th>
  )
  async function exportCsv() {
    setExporting(true)
    try { download(await svc.attendance.exportCsv(params), `attendance_${from}_to_${to}.csv`); toast('ok', 'Export downloaded (uses the current filters).') }
    catch (e) { toast('bad', toApiError(e).message) } finally { setExporting(false) }
  }
  const data = list.data
  const refresh = () => { list.reload(); setDetail(null); setCorrect(null); setManual(false) }

  return (
    <>
      <PageHeader title="Attendance records" subtitle="Every check-in, with who recorded it and how. Absences appear only after a session has ended."
        actions={<>
          {can('admin') && <Button variant="secondary" onClick={() => setManual(true)}><Plus className="h-4 w-4" />Manual entry</Button>}
          {can('admin', 'operator') && <Button variant="secondary" onClick={() => void exportCsv()} loading={exporting}><Download className="h-4 w-4" />Export CSV</Button>}
        </>} />
      <Card>
        <div className="grid gap-3 border-b border-line p-4 sm:grid-cols-2 lg:grid-cols-6">
          <div className="relative lg:col-span-2"><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted" aria-hidden /><Input aria-label="Search by name or ID" placeholder="Search by name or ID" className="pl-9" value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} /></div>
          <Input aria-label="From date" type="date" value={from} max={to} onChange={setF(setFrom)} />
          <Input aria-label="To date" type="date" value={to} min={from} onChange={setF(setTo)} />
          <Select aria-label="Session" value={sessionId} onChange={setF(setSessionId)}><option value="">All sessions</option>{sessions.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select>
          <div className="grid grid-cols-2 gap-3">
            <Select aria-label="Department" value={dept} onChange={setF(setDept)}><option value="">All depts</option>{depts.data?.map((d) => <option key={d}>{d}</option>)}</Select>
            <Select aria-label="Status" value={status} onChange={setF(setStatus)}><option value="">Any status</option><option value="present">Present</option><option value="late">Late</option><option value="absent">Absent</option><option value="corrected">Corrected</option></Select>
          </div>
        </div>
        {list.error && <div className="p-4"><ErrorNote error={list.error} onRetry={list.reload} /></div>}
        {list.loading && !data ? <Spinner /> : data && (data.items.length === 0 ? (
          <EmptyState icon={<ClipboardList className="h-8 w-8" />} title="No records for these filters">Widen the date range or clear a filter. Check-ins appear here as soon as the scanner records them.</EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-line text-xs text-muted"><tr><Th k="date">Date</Th><th className="px-4 py-2.5 font-medium">Time</th><Th k="name">Person</Th><Th k="session">Session</Th><Th k="status">Status</Th><th className="px-4 py-2.5 font-medium">Method</th></tr></thead>
              <tbody className="divide-y divide-line">
                {data.items.map((r, i) => (
                  <tr key={r.id ?? `c${r.person_id}-${r.session_id}-${r.session_date}-${i}`} onClick={() => setDetail(r)} className="cursor-pointer hover:bg-surface-2/60">
                    <td className="whitespace-nowrap px-4 py-3">{fmtDate(r.session_date)}</td>
                    <td className="px-4 py-3 tabular-nums">{r.local_time?.slice(0, 5) ?? <span className="text-muted">-</span>}</td>
                    <td className="px-4 py-3"><button className="text-left" onClick={(e) => { e.stopPropagation(); setDetail(r) }}><span className="font-medium">{r.person_name}</span><span className="block text-xs text-muted">{r.person_code}{r.department ? ` · ${r.department}` : ''}</span></button></td>
                    <td className="px-4 py-3">{r.session_name}</td>
                    <td className="px-4 py-3"><StatusBadge status={r.status} />{r.corrected && <span className="ml-1.5 text-xs text-muted">edited</span>}</td>
                    <td className="px-4 py-3 text-muted">{r.method === 'face' ? 'Face' : r.method === 'manual' ? 'Manual' : 'No check-in'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pagination page={data.page} pages={data.pages} total={data.total} onPage={setPage} label="records" />
          </div>
        ))}
      </Card>
      {detail && <Details row={detail} onClose={() => setDetail(null)} onCorrect={can('admin') ? () => { setCorrect(detail); setDetail(null) } : undefined} />}
      {correct && <CorrectModal row={correct} onClose={() => setCorrect(null)} onSaved={refresh} />}
      {manual && <ManualModal onClose={() => setManual(false)} onSaved={refresh} />}
    </>
  )
}

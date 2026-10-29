import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { CalendarClock, Pencil, Plus, Trash2 } from 'lucide-react'
import * as svc from '../services/endpoints'
import { fieldErrors, toApiError } from '../services/api'
import { useAsync } from '../hooks/useAsync'
import { useAuth } from '../hooks/useAuth'
import { Badge, Button, Card, Confirm, EmptyState, ErrorNote, Field, Input, Modal, Notice, PageHeader, Pagination, Select, Spinner, TimeInput, useToast, cx } from '../components/ui'
import { DAYS, fmtDate, hhmm } from '../utils/format'
import type { SessionInput, SessionItem, SettingsPayload } from '../types'

type Tab = 'sessions' | 'recognition' | 'camera' | 'retention' | 'users' | 'audit'

// ---- sessions ------------------------------------------------------------------------------------
function SessionForm({ item, departments, onClose, onSaved }: { item?: SessionItem; departments: string[]; onClose: () => void; onSaved: () => void }) {
  const toast = useToast()
  const [f, setF] = useState<SessionInput>(item ? { ...item } : { name: '', start_time: '09:00:00', end_time: '17:00:00', late_cutoff: '09:15:00', days_of_week: [0, 1, 2, 3, 4], early_checkin_minutes: 15, department: null, is_active: true })
  const [errs, setErrs] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [general, setGeneral] = useState<string | null>(null)
  const t = (v: string | null) => (v ? v.slice(0, 5) : '')
  const toTime = (v: string | null) => (v ? `${v}:00` : null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    const v: Record<string, string> = {}
    if (f.name.trim().length < 2) v.name = 'Enter a session name.'
    if (!f.start_time || !f.end_time) v.start_time = 'Set a start and end time.'
    else if (f.end_time <= f.start_time) v.end_time = 'End must be after start (sessions cannot cross midnight).'
    if (f.late_cutoff && (f.late_cutoff < f.start_time || f.late_cutoff > f.end_time)) v.late_cutoff = 'The late cut-off must fall between start and end.'
    if (!f.days_of_week.length) v.days_of_week = 'Choose at least one day.'
    setErrs(v); setGeneral(null)
    if (Object.keys(v).length) return
    setBusy(true)
    try {
      const body = { ...f, name: f.name.trim(), department: f.department || null }
      if (item) await svc.sessions.update(item.id, body); else await svc.sessions.create(body)
      toast('ok', item ? 'Session updated.' : 'Session created.'); onSaved()
    } catch (err) {
      const info = toApiError(err)
      if (info.code === 'duplicate_session') setErrs({ name: 'A session with this name already exists.' })
      else if (info.status === 422) setErrs(fieldErrors(info)); else setGeneral(info.message)
    } finally { setBusy(false) }
  }
  const toggleDay = (d: number) => setF((x) => ({ ...x, days_of_week: x.days_of_week.includes(d) ? x.days_of_week.filter((y) => y !== d) : [...x.days_of_week, d].sort() }))
  return (
    <Modal title={item ? 'Edit session' : 'New session'} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4" noValidate>
        {general && <ErrorNote error={general} />}
        <Field label="Name" error={errs.name}>{(id, bad) => <Input id={id} invalid={bad} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} autoFocus />}</Field>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Starts" error={errs.start_time}>{(id, bad) => <TimeInput id={id} invalid={bad} value={t(f.start_time)} onChange={(v) => setF({ ...f, start_time: toTime(v) ?? f.start_time })} />}</Field>
          <Field label="Ends" error={errs.end_time}>{(id, bad) => <TimeInput id={id} invalid={bad} value={t(f.end_time)} onChange={(v) => setF({ ...f, end_time: toTime(v) ?? f.end_time })} />}</Field>
          <Field label="Late after" error={errs.late_cutoff} hint="Leave empty for no late rule.">{(id, bad) => <TimeInput id={id} invalid={bad} value={t(f.late_cutoff)} clearable onChange={(v) => setF({ ...f, late_cutoff: toTime(v) })} />}</Field>
        </div>
        <fieldset><legend className="mb-1 text-sm font-medium">Runs on</legend>
          <div className="flex flex-wrap gap-1.5">{DAYS.map((d, i) => <button type="button" key={d} aria-pressed={f.days_of_week.includes(i)} onClick={() => toggleDay(i)} className={cx('rounded-lg border px-3 py-1.5 text-sm', f.days_of_week.includes(i) ? 'border-brand bg-brand text-on-brand' : 'border-line hover:bg-surface-2')}>{d}</button>)}</div>
          {errs.days_of_week && <p role="alert" className="mt-1 text-xs text-absent">{errs.days_of_week}</p>}
        </fieldset>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Check-in opens (minutes before start)" error={errs.early_checkin_minutes}>{(id) => <Input id={id} type="number" min={0} max={240} value={f.early_checkin_minutes} onChange={(e) => setF({ ...f, early_checkin_minutes: Math.max(0, Math.min(240, +e.target.value || 0)) })} />}</Field>
          <Field label="Only for (optional)" hint="Department, class or team.">{(id) => <><Input id={id} list="s-depts" value={f.department ?? ''} onChange={(e) => setF({ ...f, department: e.target.value || null })} /><datalist id="s-depts">{departments.map((d) => <option key={d} value={d} />)}</datalist></>}</Field>
        </div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.is_active} onChange={(e) => setF({ ...f, is_active: e.target.checked })} />Active (accepts check-ins)</label>
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" loading={busy}>{item ? 'Save changes' : 'Create session'}</Button></div>
      </form>
    </Modal>
  )
}

function SessionsTab({ isAdmin }: { isAdmin: boolean }) {
  const toast = useToast()
  const list = useAsync(() => svc.sessions.list(), [])
  const depts = useAsync(() => svc.people.departments(), [])
  const [form, setForm] = useState<{ item?: SessionItem } | null>(null)
  const [del, setDel] = useState<SessionItem | null>(null)
  async function remove() {
    if (!del) return
    try { await svc.sessions.remove(del.id); toast('ok', 'Session deleted.'); setDel(null); list.reload() }
    catch (e) { const i = toApiError(e); toast('bad', i.message); setDel(null) }
  }
  return (
    <Card>
      <div className="flex items-center justify-between px-5 py-4"><div><h2 className="text-base font-semibold">Sessions</h2><p className="text-sm text-muted">A session is a daily window in which people can check in.</p></div>{isAdmin && <Button onClick={() => setForm({})}><Plus className="h-4 w-4" />New session</Button>}</div>
      {list.error && <div className="px-5 pb-4"><ErrorNote error={list.error} onRetry={list.reload} /></div>}
      {list.loading && !list.data ? <Spinner /> : list.data && (list.data.length === 0 ? (
        <div className="border-t border-line"><EmptyState icon={<CalendarClock className="h-8 w-8" />} title="No sessions yet" action={isAdmin ? <Button onClick={() => setForm({})}><Plus className="h-4 w-4" />Create a session</Button> : undefined}>Nobody can be marked present until a session is open. Add one, for example “Morning 09:00 to 17:00”.</EmptyState></div>
      ) : (
        <ul className="divide-y divide-line border-t border-line">
          {list.data.map((s) => (
            <li key={s.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3.5">
              <div><p className="font-medium">{s.name} {!s.is_active && <Badge>Inactive</Badge>}</p>
                <p className="text-sm text-muted">{hhmm(s.start_time)}–{hhmm(s.end_time)} · late after {s.late_cutoff ? hhmm(s.late_cutoff) : 'never'} · opens {s.early_checkin_minutes} min early · {s.days_of_week.map((d) => DAYS[d]).join(', ')}{s.department ? ` · ${s.department} only` : ''}</p></div>
              {isAdmin && <div className="flex gap-1"><Button variant="ghost" className="!px-2" aria-label={`Edit ${s.name}`} onClick={() => setForm({ item: s })}><Pencil className="h-4 w-4" /></Button><Button variant="ghost" className="!px-2 text-absent" aria-label={`Delete ${s.name}`} onClick={() => setDel(s)}><Trash2 className="h-4 w-4" /></Button></div>}
            </li>
          ))}
        </ul>
      ))}
      {form && <SessionForm item={form.item} departments={depts.data ?? []} onClose={() => setForm(null)} onSaved={() => { setForm(null); list.reload() }} />}
      {del && <Confirm title="Delete session" confirmLabel="Delete" onConfirm={() => void remove()} onCancel={() => setDel(null)}>Delete “{del.name}”? Sessions that already have attendance records cannot be deleted; deactivate them instead.</Confirm>}
    </Card>
  )
}

// ---- runtime settings -------------------------------------------------------------------------------
interface FieldDef { key: string; label: string; type: 'number' | 'text' | 'select'; min?: number; max?: number; step?: number; unit?: string; options?: [string, string][]; hint?: string }
const GROUPS: Record<'recognition' | 'camera' | 'retention', { title: string; intro: string; fields: FieldDef[] }> = {
  recognition: { title: 'Recognition and security', intro: 'These settings decide who gets marked present. Change them carefully.', fields: [
    { key: 'recognition_threshold', label: 'Match threshold', type: 'number', min: 0.2, max: 0.9, step: 0.01, hint: 'Minimum cosine similarity between faces. Higher = fewer wrong matches but more people rejected. It is a score, not a probability.' },
    { key: 'recognition_margin', label: 'Ambiguity margin', type: 'number', min: 0, max: 0.3, step: 0.01, hint: 'If two people score almost the same, the scan is refused. This is the minimum gap.' },
    { key: 'min_face_size_px', label: 'Smallest accepted face', type: 'number', min: 40, max: 400, unit: 'px' },
    { key: 'min_det_score', label: 'Detector confidence', type: 'number', min: 0.3, max: 0.99, step: 0.01 },
    { key: 'liveness_policy', label: 'Liveness check', type: 'select', options: [['off', 'Off - no spoof protection'], ['challenge', 'Head-turn challenge (experimental)']], hint: 'The challenge deters casual photo-holding only. It is not strong anti-spoofing.' },
    { key: 'timezone', label: 'Attendance timezone', type: 'text', hint: 'IANA name, for example Asia/Kolkata. Sets session dates and late rules.' },
  ] },
  camera: { title: 'Camera and scanner', intro: 'How often the scanner sends frames and how long it pauses after a result.', fields: [
    { key: 'frame_interval_ms', label: 'Frame interval', type: 'number', min: 200, max: 5000, step: 50, unit: 'ms', hint: 'Longer is lighter on the server.' },
    { key: 'cooldown_seconds', label: 'Pause after a result', type: 'number', min: 3, max: 300, unit: 's', hint: 'Prevents the same person being processed repeatedly while they stand there.' },
    { key: 'camera_width', label: 'Camera width', type: 'number', min: 320, max: 1920, unit: 'px' },
    { key: 'camera_height', label: 'Camera height', type: 'number', min: 240, max: 1080, unit: 'px' },
  ] },
  retention: { title: 'Data retention', intro: 'Applied when you press “Apply retention now”.', fields: [
    { key: 'retention_audit_days', label: 'Keep audit log for', type: 'number', min: 30, max: 3650, unit: 'days' },
    { key: 'retention_attendance_days', label: 'Keep attendance for', type: 'number', min: 0, max: 3650, unit: 'days', hint: '0 keeps attendance forever.' },
  ] },
}

function SettingsTab({ group, isAdmin }: { group: keyof typeof GROUPS; isAdmin: boolean }) {
  const toast = useToast()
  const data = useAsync(() => svc.settings.get(), [])
  const [vals, setVals] = useState<SettingsPayload['values']>({})
  const [errs, setErrs] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const def = GROUPS[group]
  useEffect(() => { if (data.data) setVals(data.data.values) }, [data.data])
  const dirty = useMemo(() => def.fields.filter((f) => data.data && String(vals[f.key]) !== String(data.data.values[f.key])), [def, vals, data.data])
  const zones = useMemo(() => { try { return (Intl as unknown as { supportedValuesOf: (k: string) => string[] }).supportedValuesOf('timeZone') } catch { return [] } }, [])

  async function save(e: FormEvent) {
    e.preventDefault()
    const v: Record<string, string> = {}
    for (const f of dirty) if (f.type === 'number') { const n = Number(vals[f.key]); if (Number.isNaN(n) || (f.min !== undefined && n < f.min) || (f.max !== undefined && n > f.max)) v[f.key] = `Enter a number from ${f.min} to ${f.max}.` }
    setErrs(v); if (Object.keys(v).length) return
    setBusy(true)
    try {
      const patch = Object.fromEntries(dirty.map((f) => [f.key, f.type === 'number' ? Number(vals[f.key]) : vals[f.key]]))
      const res = await svc.settings.put(patch)
      setVals(res.values); data.reload(); toast('ok', 'Settings saved.')
    } catch (err) { const i = toApiError(err); if (i.status === 422) setErrs(fieldErrors(i)); else toast('bad', i.message) } finally { setBusy(false) }
  }
  async function retention() {
    try { const r = await svc.admin.retention(); toast('ok', `Removed ${r.audit_removed} audit entries and ${r.attendance_removed} attendance records.`) } catch (e) { toast('bad', toApiError(e).message) }
  }
  if (data.loading && !data.data) return <Spinner />
  if (data.error) return <ErrorNote error={data.error} onRetry={data.reload} />
  return (
    <Card className="p-5">
      <h2 className="text-base font-semibold">{def.title}</h2><p className="mb-4 text-sm text-muted">{def.intro}</p>
      {!isAdmin && <div className="mb-4"><Notice>Only administrators can change settings. You are viewing them read-only.</Notice></div>}
      {group === 'recognition' && vals.liveness_policy === 'off' && <div className="mb-4"><Notice tone="warn">Liveness is off. Photos and screens may be accepted. Use only under supervision.</Notice></div>}
      <form onSubmit={save} className="grid gap-4 sm:grid-cols-2" noValidate>
        {def.fields.map((f) => (
          <Field key={f.key} label={f.unit ? `${f.label} (${f.unit})` : f.label} error={errs[f.key]} hint={f.hint}>
            {(id, bad) => f.type === 'select'
              ? <Select id={id} disabled={!isAdmin} value={String(vals[f.key] ?? '')} onChange={(e) => setVals({ ...vals, [f.key]: e.target.value })}>{f.options?.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>
              : <><Input id={id} invalid={bad} disabled={!isAdmin} type={f.type} min={f.min} max={f.max} step={f.step} list={f.key === 'timezone' ? 'tz-list' : undefined} value={String(vals[f.key] ?? '')} onChange={(e) => setVals({ ...vals, [f.key]: e.target.value })} />{f.key === 'timezone' && <datalist id="tz-list">{zones.map((z) => <option key={z} value={z} />)}</datalist>}</>}
          </Field>
        ))}
        {isAdmin && <div className="flex gap-2 sm:col-span-2"><Button type="submit" loading={busy} disabled={!dirty.length}>Save settings</Button>{group === 'retention' && <Button type="button" variant="secondary" onClick={() => void retention()}>Apply retention now</Button>}</div>}
      </form>
    </Card>
  )
}

// ---- users and audit (admin) ------------------------------------------------------------------------
function UsersTab() {
  const toast = useToast()
  const { user: me } = useAuth()
  const users = useAsync(() => svc.admin.users(), [])
  const [open, setOpen] = useState(false)
  const [f, setF] = useState({ username: '', password: '', email: '', role: 'operator' })
  const [errs, setErrs] = useState<Record<string, string>>({})
  async function create(e: FormEvent) {
    e.preventDefault()
    const v: Record<string, string> = {}
    if (!/^[A-Za-z0-9_.-]{3,64}$/.test(f.username)) v.username = '3-64 characters: letters, digits, "_", ".", "-".'
    if (f.password.length < 10) v.password = 'Use at least 10 characters.'
    setErrs(v); if (Object.keys(v).length) return
    try { await svc.admin.createUser({ ...f, email: f.email || undefined }); toast('ok', 'User created.'); setOpen(false); setF({ username: '', password: '', email: '', role: 'operator' }); users.reload() }
    catch (err) { const i = toApiError(err); setErrs(i.status === 422 && Array.isArray(i.details) ? fieldErrors(i) : { username: i.message }) }
  }
  async function patch(id: number, body: Record<string, unknown>) { try { await svc.admin.updateUser(id, body); users.reload() } catch (e) { toast('bad', toApiError(e).message) } }
  return (
    <Card>
      <div className="flex items-center justify-between px-5 py-4"><div><h2 className="text-base font-semibold">Users</h2><p className="text-sm text-muted">Administrators change data, operators run the scanner, viewers read only.</p></div><Button onClick={() => setOpen(true)}><Plus className="h-4 w-4" />Add user</Button></div>
      {users.loading && !users.data ? <Spinner /> : users.error ? <div className="px-5 pb-4"><ErrorNote error={users.error} onRetry={users.reload} /></div> : (
        <ul className="divide-y divide-line border-t border-line">{users.data?.map((u) => (
          <li key={u.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3"><div><p className="font-medium">{u.username} {u.id === me?.id && <Badge tone="info">You</Badge>} {!u.is_active && <Badge>Disabled</Badge>}</p><p className="text-xs text-muted">{u.email ?? 'no email'} · last sign-in {u.last_login_at ? fmtDate(u.last_login_at) : 'never'}</p></div>
            <div className="flex items-center gap-2"><Select aria-label={`Role for ${u.username}`} className="w-auto" value={u.role} disabled={u.id === me?.id} onChange={(e) => void patch(u.id, { role: e.target.value })}><option value="admin">Administrator</option><option value="operator">Operator</option><option value="viewer">Viewer</option></Select>
              <Button variant="secondary" disabled={u.id === me?.id} onClick={() => void patch(u.id, { is_active: !u.is_active })}>{u.is_active ? 'Disable' : 'Enable'}</Button></div></li>))}</ul>
      )}
      {open && <Modal title="Add user" onClose={() => setOpen(false)}><form onSubmit={create} className="space-y-4" noValidate>
        <Field label="Username" error={errs.username}>{(id, bad) => <Input id={id} invalid={bad} autoFocus value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} />}</Field>
        <Field label="Temporary password" error={errs.password} hint="At least 10 characters.">{(id, bad) => <Input id={id} type="password" autoComplete="new-password" invalid={bad} value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />}</Field>
        <Field label="Email (optional)" error={errs.email}>{(id) => <Input id={id} type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />}</Field>
        <Field label="Role">{(id) => <Select id={id} value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}><option value="operator">Operator</option><option value="viewer">Viewer</option><option value="admin">Administrator</option></Select>}</Field>
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setOpen(false)}>Cancel</Button><Button type="submit">Create user</Button></div></form></Modal>}
    </Card>
  )
}

function AuditTab() {
  const [page, setPage] = useState(1)
  const log = useAsync(() => svc.admin.audit({ page, page_size: 25 }), [page])
  return (
    <Card>
      <div className="px-5 py-4"><h2 className="text-base font-semibold">Audit log</h2><p className="text-sm text-muted">Sign-ins, enrollments, deletions, corrections, exports and setting changes. It never contains face data.</p></div>
      {log.loading && !log.data ? <Spinner /> : log.error ? <div className="px-5 pb-4"><ErrorNote error={log.error} onRetry={log.reload} /></div> : log.data && (
        <div className="overflow-x-auto border-t border-line"><table className="w-full text-left text-sm"><thead className="text-xs text-muted"><tr><th className="px-5 py-2 font-medium">When</th><th className="px-3 py-2 font-medium">Who</th><th className="px-3 py-2 font-medium">Action</th><th className="px-3 py-2 font-medium">Target</th></tr></thead>
          <tbody className="divide-y divide-line">{log.data.items.map((a) => <tr key={a.id}><td className="whitespace-nowrap px-5 py-2 tabular-nums">{new Date(a.created_at).toLocaleString()}</td><td className="px-3 py-2">{a.username ?? '-'}</td><td className="px-3 py-2 font-medium">{a.action.replace(/_/g, ' ')}</td><td className="px-3 py-2 text-muted">{a.entity_type ?? ''} {a.entity_id ?? ''}</td></tr>)}</tbody></table>
          <Pagination page={log.data.page} pages={log.data.pages} total={log.data.total} onPage={setPage} label="entries" /></div>
      )}
    </Card>
  )
}

export default function SettingsPage() {
  const { can } = useAuth()
  const isAdmin = can('admin')
  const canSee = can('admin', 'operator')
  const tabs: [Tab, string, boolean][] = [['sessions', 'Sessions', true], ['recognition', 'Recognition & security', canSee], ['camera', 'Camera', canSee], ['retention', 'Retention', canSee], ['users', 'Users', isAdmin], ['audit', 'Audit log', isAdmin]]
  const [tab, setTab] = useState<Tab>('sessions')
  return (
    <>
      <PageHeader title="Sessions and settings" />
      <div role="tablist" className="mb-5 flex flex-wrap gap-1 border-b border-line">
        {tabs.filter(([, , show]) => show).map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)} className={cx('-mb-px border-b-2 px-4 py-2.5 text-sm font-medium', tab === k ? 'border-brand text-brand' : 'border-transparent text-muted hover:text-ink')}>{l}</button>)}
      </div>
      {tab === 'sessions' && <SessionsTab isAdmin={isAdmin} />}
      {(tab === 'recognition' || tab === 'camera' || tab === 'retention') && <SettingsTab key={tab} group={tab} isAdmin={isAdmin} />}
      {tab === 'users' && isAdmin && <UsersTab />}
      {tab === 'audit' && isAdmin && <AuditTab />}
    </>
  )
}

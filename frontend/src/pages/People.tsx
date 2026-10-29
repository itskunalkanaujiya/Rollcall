import { useState, type FormEvent } from 'react'
import { Ban, CheckCircle, Pencil, ScanFace, Search, Trash2, UserPlus, Users } from 'lucide-react'
import * as svc from '../services/endpoints'
import { fieldErrors, toApiError } from '../services/api'
import { useAsync } from '../hooks/useAsync'
import { useAuth } from '../hooks/useAuth'
import { useDebounce } from '../hooks/useDebounce'
import { Badge, Button, Card, Confirm, EmptyState, ErrorNote, Field, Input, Modal, Notice, PageHeader, Pagination, Select, Spinner, StatusBadge, useToast } from '../components/ui'
import { EnrollModal } from '../components/EnrollModal'
import { fmtDate, fmtPct } from '../utils/format'
import type { Person, PersonRole } from '../types'

const ENROLL_TONE = { enrolled: 'present', partial: 'late', not_enrolled: 'absent' } as const
const ENROLL_LABEL = { enrolled: 'Enrolled', partial: 'Needs more photos', not_enrolled: 'Not enrolled' } as const
const MIN_SAMPLES = 3

function PersonForm({ person, departments, onClose, onSaved }: { person?: Person; departments: string[]; onClose: () => void; onSaved: () => void }) {
  const toast = useToast()
  const [f, setF] = useState({ person_code: person?.person_code ?? '', full_name: person?.full_name ?? '', email: person?.email ?? '', department: person?.department ?? '', role: (person?.role ?? 'student') as PersonRole })
  const [errs, setErrs] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [general, setGeneral] = useState<string | null>(null)

  function validate() {
    const e: Record<string, string> = {}
    if (!person && !/^[A-Za-z0-9][A-Za-z0-9_.\-/]{0,63}$/.test(f.person_code.trim())) e.person_code = 'Use 1-64 letters, digits, "_", ".", "-" or "/".'
    if (f.full_name.trim().length < 2) e.full_name = 'Enter the full name.'
    if (f.email && !/^\S+@\S+\.\S+$/.test(f.email)) e.email = 'Enter a valid email address.'
    return e
  }
  async function submit(ev: FormEvent) {
    ev.preventDefault()
    const e = validate(); setErrs(e); setGeneral(null)
    if (Object.keys(e).length) return
    setBusy(true)
    try {
      if (person) {
        await svc.people.update(person.id, { full_name: f.full_name, role: f.role, email: f.email || undefined, clear_email: !f.email && !!person.email, department: f.department || undefined, clear_department: !f.department && !!person.department })
      } else {
        await svc.people.create({ person_code: f.person_code.trim(), full_name: f.full_name, email: f.email || null, department: f.department || null, role: f.role })
      }
      toast('ok', person ? 'Details saved.' : `${f.full_name} registered. Enroll their face next.`)
      onSaved()
    } catch (err) {
      const info = toApiError(err)
      if (info.code === 'duplicate_person_id') setErrs({ person_code: 'This ID is already registered.' })
      else if (info.code === 'duplicate_email') setErrs({ email: 'This email is already registered.' })
      else if (info.status === 422) setErrs(fieldErrors(info))
      else setGeneral(info.message)
    } finally { setBusy(false) }
  }
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }))
  return (
    <Modal title={person ? 'Edit person' : 'Register person'} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4" noValidate>
        {general && <ErrorNote error={general} />}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Person ID" error={errs.person_code} hint={person ? 'IDs cannot be changed.' : 'Student or employee number. Must be unique.'}>{(id, bad) => <Input id={id} invalid={bad} value={f.person_code} onChange={set('person_code')} disabled={!!person} autoFocus={!person} />}</Field>
          <Field label="Full name" error={errs.full_name}>{(id, bad) => <Input id={id} invalid={bad} value={f.full_name} onChange={set('full_name')} />}</Field>
          <Field label="Department, class or team" error={errs.department}>{(id) => <><Input id={id} list="dept-list" value={f.department} onChange={set('department')} /><datalist id="dept-list">{departments.map((d) => <option key={d} value={d} />)}</datalist></>}</Field>
          <Field label="Role">{(id) => <Select id={id} value={f.role} onChange={set('role')}><option value="student">Student</option><option value="employee">Employee</option><option value="other">Other</option></Select>}</Field>
          <div className="sm:col-span-2"><Field label="Email (optional)" error={errs.email}>{(id, bad) => <Input id={id} type="email" invalid={bad} value={f.email} onChange={set('email')} />}</Field></div>
        </div>
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" loading={busy}>{person ? 'Save changes' : 'Register'}</Button></div>
      </form>
    </Modal>
  )
}

function Profile({ person, onClose }: { person: Person; onClose: () => void }) {
  const hist = useAsync(() => svc.attendance.person(person.id), [person.id])
  const rows: [string, string][] = [['Person ID', person.person_code], ['Department', person.department ?? '-'], ['Role', person.role], ['Email', person.email ?? '-'], ['Registered', fmtDate(person.registered_at)], ['Consent recorded', person.consent_at ? fmtDate(person.consent_at) : 'Not yet'], ['Face samples', `${person.enrolled_samples} (${ENROLL_LABEL[person.enrollment_status]})`]]
  return (
    <Modal title={person.full_name} onClose={onClose} wide>
      <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">{rows.map(([k, v]) => <div key={k}><dt className="text-xs text-muted">{k}</dt><dd className="text-sm font-medium">{v}</dd></div>)}</dl>
      <h3 className="mb-2 mt-6 text-base font-semibold">Last 30 days</h3>
      {hist.loading ? <Spinner /> : hist.error ? <ErrorNote error={hist.error} onRetry={hist.reload} /> : hist.data && (
        <>
          <p className="mb-3 text-sm text-muted">Attendance {fmtPct(hist.data.attendance_percentage)} · {hist.data.summary.present} present · {hist.data.summary.late} late · {hist.data.summary.absent} absent</p>
          {hist.data.items.length === 0 ? <p className="text-sm text-muted">No attendance in this period.</p> : (
            <ul className="max-h-60 divide-y divide-line overflow-y-auto rounded-lg border border-line">
              {hist.data.items.map((r, i) => <li key={`${r.session_id}-${r.session_date}-${i}`} className="flex items-center justify-between px-3 py-2 text-sm"><span>{fmtDate(r.session_date)} · {r.session_name}</span><span className="flex items-center gap-3"><span className="tabular-nums text-muted">{r.local_time?.slice(0, 5)}</span><StatusBadge status={r.status} /></span></li>)}
            </ul>
          )}
        </>
      )}
    </Modal>
  )
}

export default function People() {
  const { can } = useAuth()
  const toast = useToast()
  const isAdmin = can('admin')
  const [q, setQ] = useState(''); const [dept, setDept] = useState(''); const [role, setRole] = useState(''); const [status, setStatus] = useState(''); const [enrollment, setEnrollment] = useState('')
  const [page, setPage] = useState(1)
  const dq = useDebounce(q)
  const list = useAsync(() => svc.people.list({ q: dq, department: dept, role, status, enrollment, page, page_size: 15 }), [dq, dept, role, status, enrollment, page])
  const depts = useAsync(() => svc.people.departments(), [])
  const [form, setForm] = useState<{ person?: Person } | null>(null)
  const [enroll, setEnroll] = useState<Person | null>(null)
  const [profile, setProfile] = useState<Person | null>(null)
  const [del, setDel] = useState<Person | null>(null)
  const [delMode, setDelMode] = useState<'anonymise' | 'purge' | 'biometrics'>('anonymise')
  const [busy, setBusy] = useState(false)

  const refresh = () => { list.reload(); depts.reload() }
  const filter = (set: (v: string) => void) => (e: { target: { value: string } }) => { set(e.target.value); setPage(1) }

  async function toggle(p: Person) {
    try { await svc.people.update(p.id, { status: p.status === 'active' ? 'disabled' : 'active' }); toast('ok', p.status === 'active' ? `${p.full_name} disabled. They will no longer be recognized.` : `${p.full_name} reactivated.`); refresh() }
    catch (e) { toast('bad', toApiError(e).message) }
  }
  async function confirmDelete() {
    if (!del) return
    setBusy(true)
    try {
      if (delMode === 'biometrics') await svc.people.deleteBiometrics(del.id)
      else await svc.people.remove(del.id, delMode === 'purge')
      toast('ok', delMode === 'biometrics' ? 'Face data deleted.' : 'Person deleted.')
      setDel(null); refresh()
    } catch (e) { toast('bad', toApiError(e).message) } finally { setBusy(false) }
  }

  const data = list.data
  return (
    <>
      <PageHeader title="People" subtitle="Register people, enroll their faces, and manage their accounts."
        actions={isAdmin && <Button onClick={() => setForm({})}><UserPlus className="h-4 w-4" />Register person</Button>} />
      <Card>
        <div className="grid gap-3 border-b border-line p-4 sm:grid-cols-2 lg:grid-cols-5">
          <div className="relative lg:col-span-2"><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted" aria-hidden /><Input aria-label="Search by name or ID" placeholder="Search by name or ID" className="pl-9" value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} /></div>
          <Select aria-label="Department" value={dept} onChange={filter(setDept)}><option value="">All departments</option>{depts.data?.map((d) => <option key={d}>{d}</option>)}</Select>
          <Select aria-label="Role" value={role} onChange={filter(setRole)}><option value="">All roles</option><option value="student">Student</option><option value="employee">Employee</option><option value="other">Other</option></Select>
          <div className="grid grid-cols-2 gap-3">
            <Select aria-label="Account status" value={status} onChange={filter(setStatus)}><option value="">Any status</option><option value="active">Active</option><option value="disabled">Disabled</option></Select>
            <Select aria-label="Enrollment" value={enrollment} onChange={filter(setEnrollment)}><option value="">Any enrollment</option><option value="enrolled">Enrolled</option><option value="partial">Partial</option><option value="not_enrolled">Not enrolled</option></Select>
          </div>
        </div>
        {list.error && <div className="p-4"><ErrorNote error={list.error} onRetry={list.reload} /></div>}
        {list.loading && !data ? <Spinner /> : data && (data.items.length === 0 ? (
          <EmptyState icon={<Users className="h-8 w-8" />} title={dq || dept || role || status || enrollment ? 'No one matches these filters' : 'No people registered yet'}
            action={isAdmin && !dq && !dept && !role && !status && !enrollment ? <Button onClick={() => setForm({})}><UserPlus className="h-4 w-4" />Register the first person</Button> : undefined}>
            {dq || dept || role || status || enrollment ? 'Try clearing a filter.' : 'Register someone, then enroll their face so the scanner can recognize them.'}</EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-line text-xs text-muted"><tr><th className="px-4 py-2.5 font-medium">Person</th><th className="px-4 py-2.5 font-medium">Department</th><th className="px-4 py-2.5 font-medium">Account</th><th className="px-4 py-2.5 font-medium">Face enrollment</th>{isAdmin && <th className="px-4 py-2.5 text-right font-medium">Actions</th>}</tr></thead>
              <tbody className="divide-y divide-line">
                {data.items.map((p) => (
                  <tr key={p.id} className="hover:bg-surface-2/60">
                    <td className="px-4 py-3"><button onClick={() => setProfile(p)} className="text-left"><span className="font-medium hover:underline">{p.full_name}</span><span className="block text-xs text-muted">{p.person_code} · {p.role}</span></button></td>
                    <td className="px-4 py-3">{p.department ?? <span className="text-muted">-</span>}</td>
                    <td className="px-4 py-3"><Badge tone={p.status === 'active' ? 'present' : 'neutral'}>{p.status === 'active' ? 'Active' : 'Disabled'}</Badge></td>
                    <td className="px-4 py-3"><Badge tone={ENROLL_TONE[p.enrollment_status]}>{ENROLL_LABEL[p.enrollment_status]}</Badge><span className="ml-2 text-xs text-muted">{p.enrolled_samples} sample{p.enrolled_samples === 1 ? '' : 's'}</span></td>
                    {isAdmin && (
                      <td className="px-4 py-3"><div className="flex justify-end gap-1">
                        <Button variant="ghost" className="!px-2" onClick={() => setEnroll(p)} aria-label={`Enroll face for ${p.full_name}`} title="Enroll face"><ScanFace className="h-4 w-4" /></Button>
                        <Button variant="ghost" className="!px-2" onClick={() => setForm({ person: p })} aria-label={`Edit ${p.full_name}`} title="Edit"><Pencil className="h-4 w-4" /></Button>
                        <Button variant="ghost" className="!px-2" onClick={() => void toggle(p)} aria-label={`${p.status === 'active' ? 'Disable' : 'Reactivate'} ${p.full_name}`} title={p.status === 'active' ? 'Disable' : 'Reactivate'}>{p.status === 'active' ? <Ban className="h-4 w-4" /> : <CheckCircle className="h-4 w-4" />}</Button>
                        <Button variant="ghost" className="!px-2 text-absent" onClick={() => { setDel(p); setDelMode('anonymise') }} aria-label={`Delete ${p.full_name}`} title="Delete"><Trash2 className="h-4 w-4" /></Button>
                      </div></td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
            <Pagination page={data.page} pages={data.pages} total={data.total} onPage={setPage} label="people" />
          </div>
        ))}
      </Card>

      {form && <PersonForm person={form.person} departments={depts.data ?? []} onClose={() => setForm(null)} onSaved={() => { setForm(null); refresh() }} />}
      {enroll && <EnrollModal person={enroll} minSamples={MIN_SAMPLES} onClose={() => setEnroll(null)} onDone={refresh} />}
      {profile && <Profile person={profile} onClose={() => setProfile(null)} />}
      {del && (
        <Confirm title={`Delete ${del.full_name}`} confirmLabel="Delete" busy={busy} onConfirm={() => void confirmDelete()} onCancel={() => setDel(null)}>
          <div className="space-y-3">
            <Notice tone="warn">Face data is always permanently deleted. This cannot be undone.</Notice>
            {([['anonymise', 'Delete face data and anonymize the person', 'Name, ID and email are removed. Past attendance stays in the totals without identifying anyone.'],
               ['purge', 'Delete the person and all attendance history', 'Removes every record for this person.'],
               ['biometrics', 'Delete face data only', 'Keeps the account and history. The person will need to enroll again.']] as const).map(([v, t, d]) => (
              <label key={v} className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-line p-3"><input type="radio" name="del" className="mt-1" checked={delMode === v} onChange={() => setDelMode(v)} /><span><span className="block font-medium">{t}</span><span className="text-muted">{d}</span></span></label>
            ))}
          </div>
        </Confirm>
      )}
    </>
  )
}

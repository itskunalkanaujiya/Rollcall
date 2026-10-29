import { Link } from 'react-router-dom'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ClipboardList, ScanFace, UserPlus } from 'lucide-react'
import * as svc from '../services/endpoints'
import { useAsync } from '../hooks/useAsync'
import { useAuth } from '../hooks/useAuth'
import { Card, EmptyState, ErrorNote, PageHeader, Spinner, StatusBadge } from '../components/ui'
import { fmtDate, fmtPct, fmtShortDate } from '../utils/format'

export const SERIES = [
  { key: 'present', label: 'Present', color: 'var(--present)' },
  { key: 'late', label: 'Late', color: 'var(--late)' },
  { key: 'absent', label: 'Absent', color: 'var(--absent)' },
]
export const chartTip = { contentStyle: { background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 8, color: 'var(--ink)', fontSize: 13 }, cursor: { fill: 'var(--surface-2)' } }
export const axisProps = { stroke: 'var(--muted)', fontSize: 12, tickLine: false, axisLine: false } as const

function Stat({ label, value, note, tone }: { label: string; value: string | number; note?: string; tone?: string }) {
  return (
    <div className="px-5 py-4">
      <p className="text-sm text-muted">{label}</p>
      <p className={`mt-1 font-display text-3xl font-semibold ${tone ?? ''}`}>{value}</p>
      {note && <p className="mt-0.5 text-xs text-muted">{note}</p>}
    </div>
  )
}

export default function Dashboard() {
  const { can } = useAuth()
  const summary = useAsync(() => svc.dashboard.summary(), [])
  const trends = useAsync(() => svc.dashboard.trends(14), [])
  const s = summary.data

  return (
    <>
      <PageHeader title="Dashboard" subtitle={s ? `${fmtDate(s.date)} · ${s.timezone}` : undefined}
        actions={<>
          {can('admin', 'operator') && <Link to="/scanner" className="inline-flex items-center gap-2 rounded-lg bg-brand px-3.5 py-2 text-sm font-medium text-on-brand hover:bg-brand-strong"><ScanFace className="h-4 w-4" />Open scanner</Link>}
          {can('admin') && <Link to="/people" className="inline-flex items-center gap-2 rounded-lg border border-line bg-surface px-3.5 py-2 text-sm font-medium hover:bg-surface-2"><UserPlus className="h-4 w-4" />Register person</Link>}
          <Link to="/attendance" className="inline-flex items-center gap-2 rounded-lg border border-line bg-surface px-3.5 py-2 text-sm font-medium hover:bg-surface-2"><ClipboardList className="h-4 w-4" />View records</Link>
        </>} />
      {summary.error && <ErrorNote error={summary.error} onRetry={summary.reload} />}
      {summary.loading && !s && <Spinner />}
      {s && (
        <div className="space-y-6">
          <Card className="grid grid-cols-2 divide-line sm:grid-cols-3 lg:grid-cols-6 lg:divide-x [&>*]:border-b [&>*]:border-line lg:[&>*]:border-b-0">
            <Stat label="Registered" value={s.total_people} note={`${s.sessions_today} session${s.sessions_today === 1 ? '' : 's'} today`} />
            <Stat label="Present" value={s.present} tone="text-present" />
            <Stat label="Late" value={s.late} tone="text-late" />
            <Stat label="Absent" value={s.absent} tone="text-absent" note="after a session ends" />
            <Stat label="Still expected" value={s.pending} />
            <Stat label="Attendance" value={fmtPct(s.attendance_percentage)} note={s.expected ? `${s.attended} of ${s.expected} expected` : 'no session today'} />
          </Card>

          <div className="grid gap-6 lg:grid-cols-5">
            <Card className="p-5 lg:col-span-3">
              <h2 className="mb-4 text-base font-semibold">Last 14 days</h2>
              {trends.loading && !trends.data ? <Spinner /> : trends.error ? <ErrorNote error={trends.error} onRetry={trends.reload} /> :
                trends.data && trends.data.some((t) => t.expected > 0) ? (
                  <div className="h-64"><ResponsiveContainer width="100%" height="100%">
                    <BarChart data={trends.data.map((t) => ({ ...t, label: fmtShortDate(t.date) }))}>
                      <CartesianGrid stroke="var(--line)" vertical={false} />
                      <XAxis dataKey="label" {...axisProps} /><YAxis allowDecimals={false} {...axisProps} width={28} />
                      <Tooltip {...chartTip} /><Legend />
                      {SERIES.map((x) => <Bar key={x.key} dataKey={x.key} name={x.label} stackId="a" fill={x.color} />)}
                    </BarChart>
                  </ResponsiveContainer></div>
                ) : <EmptyState title="No attendance yet">Trends appear after the first scan or session day.</EmptyState>}
            </Card>
            <Card className="p-5 lg:col-span-2">
              <h2 className="mb-4 text-base font-semibold">By department today</h2>
              {s.departments.length ? (
                <ul className="space-y-3">
                  {s.departments.map((d) => {
                    const total = d.present + d.late + d.absent || 1
                    return (
                      <li key={d.department}>
                        <div className="mb-1 flex justify-between text-sm"><span>{d.department}</span><span className="text-muted">{d.present + d.late}/{d.present + d.late + d.absent}</span></div>
                        <div className="flex h-2 overflow-hidden rounded-full bg-surface-2" role="img" aria-label={`${d.department}: ${d.present} present, ${d.late} late, ${d.absent} absent`}>
                          <span style={{ width: `${(d.present / total) * 100}%`, background: 'var(--present)' }} />
                          <span style={{ width: `${(d.late / total) * 100}%`, background: 'var(--late)' }} />
                          <span style={{ width: `${(d.absent / total) * 100}%`, background: 'var(--absent)' }} />
                        </div>
                      </li>
                    )
                  })}
                </ul>
              ) : <EmptyState title="Nobody has checked in today" />}
            </Card>
          </div>

          <Card>
            <div className="flex items-center justify-between px-5 py-4"><h2 className="text-base font-semibold">Recent check-ins</h2><Link to="/attendance" className="text-sm text-brand hover:underline">All records</Link></div>
            {s.recent.length ? (
              <ul className="divide-y divide-line border-t border-line">
                {s.recent.map((r) => (
                  <li key={r.id} className="flex items-center justify-between gap-3 px-5 py-3">
                    <div className="min-w-0"><p className="truncate font-medium">{r.person_name}</p><p className="truncate text-xs text-muted">{r.person_code} · {r.session_name}</p></div>
                    <div className="flex shrink-0 items-center gap-3"><span className="text-sm tabular-nums text-muted">{r.local_time?.slice(0, 5)}</span><StatusBadge status={r.status} /></div>
                  </li>
                ))}
              </ul>
            ) : <div className="border-t border-line"><EmptyState title="No check-ins yet today">Open the live scanner to start recording attendance.</EmptyState></div>}
          </Card>
        </div>
      )}
    </>
  )
}

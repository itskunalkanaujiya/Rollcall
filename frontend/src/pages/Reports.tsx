import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { BarChart3 } from 'lucide-react'
import * as svc from '../services/endpoints'
import { useAsync } from '../hooks/useAsync'
import { Card, EmptyState, ErrorNote, Input, PageHeader, Select, Spinner, cx } from '../components/ui'
import { SERIES, axisProps, chartTip } from './Dashboard'
import { daysAgo, fmtPct, fmtShortDate, isoDay } from '../utils/format'

const PERIODS = { day: 'Daily', week: 'Weekly', month: 'Monthly' } as const
type Group = keyof typeof PERIODS
const PRESET: Record<Group, number> = { day: 13, week: 83, month: 364 }

const label = (period: string, g: Group) => (g === 'month' ? period : g === 'week' ? `Wk ${fmtShortDate(period)}` : fmtShortDate(period))

function ChartCard({ title, note, empty, children }: { title: string; note?: string; empty: boolean; children: React.ReactNode }) {
  return (
    <Card className="p-5">
      <h2 className="text-base font-semibold">{title}</h2>
      {note && <p className="mb-3 text-xs text-muted">{note}</p>}
      {empty ? <EmptyState icon={<BarChart3 className="h-7 w-7" />} title="No data in this range">Pick a wider date range, or wait for attendance to be recorded.</EmptyState> : <div className="mt-3 h-64">{children}</div>}
    </Card>
  )
}

export default function Reports() {
  const [group, setGroup] = useState<Group>('day')
  const [from, setFrom] = useState(daysAgo(PRESET.day)); const [to, setTo] = useState(isoDay(new Date()))
  const [dept, setDept] = useState('')
  const depts = useAsync(() => svc.people.departments(), [])
  const rep = useAsync(() => svc.reports.attendance({ date_from: from, date_to: to, group_by: group, department: dept }), [from, to, group, dept])
  const r = rep.data
  const changeGroup = (g: Group) => { setGroup(g); setFrom(daysAgo(PRESET[g])) }
  const series = (r?.series ?? []).map((s) => ({ ...s, label: label(s.period, group), lateRate: s.expected ? +((s.late / s.expected) * 100).toFixed(1) : 0, absentRate: s.expected ? +((s.absent / s.expected) * 100).toFixed(1) : 0 }))
  const people = r?.people ?? []

  return (
    <>
      <PageHeader title="Reports and analytics" subtitle="Percentages count only sessions that have ended, using today's list of active people." />
      <Card className="mb-6 flex flex-wrap items-end gap-3 p-4">
        <div role="tablist" aria-label="Grouping" className="flex overflow-hidden rounded-lg border border-line">
          {(Object.keys(PERIODS) as Group[]).map((g) => <button key={g} role="tab" aria-selected={group === g} onClick={() => changeGroup(g)} className={cx('px-3.5 py-2 text-sm font-medium', group === g ? 'bg-brand text-on-brand' : 'hover:bg-surface-2')}>{PERIODS[g]}</button>)}
        </div>
        <label className="text-sm"><span className="mb-1 block text-xs text-muted">From</span><Input type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} /></label>
        <label className="text-sm"><span className="mb-1 block text-xs text-muted">To</span><Input type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} /></label>
        <label className="text-sm"><span className="mb-1 block text-xs text-muted">Department</span><Select value={dept} onChange={(e) => setDept(e.target.value)}><option value="">All departments</option>{depts.data?.map((d) => <option key={d}>{d}</option>)}</Select></label>
        {r && <p className="ml-auto text-sm text-muted">Overall: <b className="text-ink">{fmtPct(r.totals.attendance_percentage)}</b> attendance · {r.totals.present + r.totals.late} attended · {r.totals.absent} absent</p>}
      </Card>

      {rep.error && <ErrorNote error={rep.error} onRetry={rep.reload} />}
      {rep.loading && !r ? <Spinner /> : r && (
        <div className="grid gap-6 lg:grid-cols-2">
          <ChartCard title={`${PERIODS[group]} attendance`} empty={!series.length}>
            <ResponsiveContainer width="100%" height="100%"><BarChart data={series}><CartesianGrid stroke="var(--line)" vertical={false} /><XAxis dataKey="label" {...axisProps} /><YAxis allowDecimals={false} {...axisProps} width={28} /><Tooltip {...chartTip} /><Legend />{SERIES.map((x) => <Bar key={x.key} dataKey={x.key} name={x.label} stackId="a" fill={x.color} />)}</BarChart></ResponsiveContainer>
          </ChartCard>
          <ChartCard title="Attendance rate" note="Share of expected people who attended." empty={!series.length}>
            <ResponsiveContainer width="100%" height="100%"><LineChart data={series}><CartesianGrid stroke="var(--line)" vertical={false} /><XAxis dataKey="label" {...axisProps} /><YAxis domain={[0, 100]} unit="%" {...axisProps} width={40} /><Tooltip {...chartTip} formatter={(v) => `${v}%`} /><Line type="monotone" dataKey="attendance_percentage" name="Attendance" stroke="var(--brand)" strokeWidth={2.5} dot={{ r: 3 }} connectNulls /></LineChart></ResponsiveContainer>
          </ChartCard>
          <ChartCard title="Late arrivals" note="Late check-ins as a share of expected." empty={!series.length}>
            <ResponsiveContainer width="100%" height="100%"><LineChart data={series}><CartesianGrid stroke="var(--line)" vertical={false} /><XAxis dataKey="label" {...axisProps} /><YAxis unit="%" {...axisProps} width={40} /><Tooltip {...chartTip} formatter={(v) => `${v}%`} /><Line type="monotone" dataKey="lateRate" name="Late" stroke="var(--late)" strokeWidth={2.5} dot={{ r: 3 }} /></LineChart></ResponsiveContainer>
          </ChartCard>
          <ChartCard title="Absences" note="Absent as a share of expected." empty={!series.length}>
            <ResponsiveContainer width="100%" height="100%"><LineChart data={series}><CartesianGrid stroke="var(--line)" vertical={false} /><XAxis dataKey="label" {...axisProps} /><YAxis unit="%" {...axisProps} width={40} /><Tooltip {...chartTip} formatter={(v) => `${v}%`} /><Line type="monotone" dataKey="absentRate" name="Absent" stroke="var(--absent)" strokeWidth={2.5} dot={{ r: 3 }} /></LineChart></ResponsiveContainer>
          </ChartCard>
          <ChartCard title="Department comparison" empty={!r.departments.length}>
            <ResponsiveContainer width="100%" height="100%"><BarChart data={r.departments} layout="vertical"><CartesianGrid stroke="var(--line)" horizontal={false} /><XAxis type="number" domain={[0, 100]} unit="%" {...axisProps} /><YAxis type="category" dataKey="department" {...axisProps} width={90} /><Tooltip {...chartTip} formatter={(v) => `${v}%`} /><Bar dataKey="attendance_percentage" name="Attendance" fill="var(--brand)" radius={[0, 4, 4, 0]} /></BarChart></ResponsiveContainer>
          </ChartCard>
          <Card>
            <h2 className="px-5 pt-5 text-base font-semibold">Attendance per person</h2>
            <p className="px-5 text-xs text-muted">Lowest attendance first.</p>
            {people.length === 0 ? <EmptyState title="No data in this range" /> : (
              <div className="mt-3 max-h-72 overflow-y-auto">
                <table className="w-full text-left text-sm"><thead className="sticky top-0 bg-surface text-xs text-muted"><tr><th className="px-5 py-2 font-medium">Person</th><th className="px-2 py-2 font-medium">Attended</th><th className="px-2 py-2 font-medium">Late</th><th className="px-2 py-2 font-medium">Absent</th><th className="px-5 py-2 text-right font-medium">Rate</th></tr></thead>
                  <tbody className="divide-y divide-line">{people.map((p) => <tr key={p.person_id}><td className="px-5 py-2"><span className="font-medium">{p.full_name}</span><span className="ml-2 text-xs text-muted">{p.person_code}</span></td><td className="px-2 py-2 tabular-nums">{p.present + p.late}</td><td className="px-2 py-2 tabular-nums">{p.late}</td><td className="px-2 py-2 tabular-nums">{p.absent}</td><td className="px-5 py-2 text-right font-medium tabular-nums">{fmtPct(p.attendance_percentage)}</td></tr>)}</tbody></table>
              </div>
            )}
          </Card>
        </div>
      )}
    </>
  )
}

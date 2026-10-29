import { api } from './api'
import type {
  AttendanceRow, AuditItem, DashboardSummary, EnrollmentResult, Page, Person, PersonInput, RecognitionStatus,
  Report, SessionInput, SessionItem, SettingsPayload, TrendPoint, User,
} from '../types'

type Params = Record<string, string | number | boolean | undefined | null>
const clean = (p: Params = {}) => Object.fromEntries(Object.entries(p).filter(([, v]) => v !== undefined && v !== null && v !== ''))

export const auth = {
  login: (username: string, password: string) => api.post<User>('/auth/login', { username, password }).then((r) => r.data),
  logout: () => api.post('/auth/logout'),
  me: () => api.get<User>('/auth/me').then((r) => r.data),
}

export const people = {
  list: (p: Params) => api.get<Page<Person>>('/people', { params: clean(p) }).then((r) => r.data),
  get: (id: number) => api.get<Person>(`/people/${id}`).then((r) => r.data),
  create: (b: PersonInput) => api.post<Person>('/people', b).then((r) => r.data),
  update: (id: number, b: Record<string, unknown>) => api.put<Person>(`/people/${id}`, b).then((r) => r.data),
  remove: (id: number, purgeAttendance: boolean) => api.delete(`/people/${id}`, { params: { purge_attendance: purgeAttendance } }).then((r) => r.data),
  deleteBiometrics: (id: number) => api.delete(`/people/${id}/biometrics`).then((r) => r.data),
  departments: () => api.get<string[]>('/departments').then((r) => r.data),
  enroll: (id: number, files: Blob[], opts: { source: 'webcam' | 'upload'; confirmDuplicate?: boolean }) => {
    const form = new FormData()
    files.forEach((f, i) => form.append('files', f, f instanceof File ? f.name : `capture-${i}.jpg`))
    form.append('consent', 'true')
    if (opts.confirmDuplicate) form.append('confirm_duplicate', 'true')
    const path = opts.source === 'webcam' ? 'enroll' : 'enroll-images'
    return api.post<EnrollmentResult>(`/people/${id}/${path}`, form, { timeout: 120000 }).then((r) => r.data)
  },
}

export const attendance = {
  list: (p: Params) => api.get<Page<AttendanceRow>>('/attendance', { params: clean(p) }).then((r) => r.data),
  manual: (b: { person_id: number; session_id: number; session_date: string; status: string; note: string }) =>
    api.post<AttendanceRow>('/attendance/manual', b).then((r) => r.data),
  correct: (id: number, b: { status: string; note: string }) => api.put<AttendanceRow>(`/attendance/${id}`, b).then((r) => r.data),
  person: (id: number) => api.get<{ summary: Record<string, number>; attendance_percentage: number | null; items: AttendanceRow[] }>(`/attendance/person/${id}`).then((r) => r.data),
  exportCsv: (p: Params) => api.get<Blob>('/reports/export', { params: clean(p), responseType: 'blob' }).then((r) => r.data),
}

export const sessions = {
  list: () => api.get<SessionItem[]>('/sessions').then((r) => r.data),
  create: (b: SessionInput) => api.post<SessionItem>('/sessions', b).then((r) => r.data),
  update: (id: number, b: SessionInput) => api.put<SessionItem>(`/sessions/${id}`, b).then((r) => r.data),
  remove: (id: number) => api.delete(`/sessions/${id}`),
}

export const dashboard = {
  summary: () => api.get<DashboardSummary>('/dashboard/summary').then((r) => r.data),
  trends: (days: number) => api.get<TrendPoint[]>('/dashboard/trends', { params: { days } }).then((r) => r.data),
}
export const reports = {
  attendance: (p: Params) => api.get<Report>('/reports/attendance', { params: clean(p) }).then((r) => r.data),
}
export const recognition = { status: () => api.get<RecognitionStatus>('/recognition/status').then((r) => r.data) }

export const settings = {
  get: () => api.get<SettingsPayload>('/settings').then((r) => r.data),
  put: (patch: Record<string, unknown>) => api.put<{ values: SettingsPayload['values'] }>('/settings', patch).then((r) => r.data),
}
export const admin = {
  audit: (p: Params) => api.get<Page<AuditItem>>('/audit-logs', { params: clean(p) }).then((r) => r.data),
  retention: () => api.post<{ audit_removed: number; attendance_removed: number }>('/maintenance/retention').then((r) => r.data),
  users: () => api.get<User[]>('/users').then((r) => r.data),
  createUser: (b: { username: string; password: string; email?: string; role: string }) => api.post<User>('/users', b).then((r) => r.data),
  updateUser: (id: number, b: Record<string, unknown>) => api.put<User>(`/users/${id}`, b).then((r) => r.data),
}

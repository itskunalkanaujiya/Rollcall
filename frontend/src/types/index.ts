export type Role = 'admin' | 'operator' | 'viewer'
export type AttendanceStatus = 'present' | 'late' | 'absent' | 'corrected'
export type PersonStatus = 'active' | 'disabled'
export type PersonRole = 'student' | 'employee' | 'other'
export type EnrollmentStatus = 'not_enrolled' | 'partial' | 'enrolled'

export interface User { id: number; username: string; email: string | null; role: Role; is_active: boolean; created_at: string; last_login_at: string | null }
export interface Page<T> { items: T[]; total: number; page: number; page_size: number; pages: number }

export interface Person {
  id: number; person_code: string; full_name: string; email: string | null; department: string | null
  role: PersonRole; status: PersonStatus; registered_at: string; consent_at: string | null
  anonymized: boolean; enrolled_samples: number; enrollment_status: EnrollmentStatus
}
export interface PersonInput { person_code: string; full_name: string; email?: string | null; department?: string | null; role: PersonRole }

export interface Rejection { index: number; reason: string; code: string }
export interface EnrollmentResult {
  person_id: number; accepted: number; rejected: Rejection[]; total_samples: number
  enrollment_status: EnrollmentStatus; possible_duplicates: { person_id: number; person_code: string; full_name: string; similarity: number }[]; warnings: string[]
}

export interface AttendanceRow {
  id: number | null; person_id: number; person_code: string; person_name: string; department: string | null
  session_id: number; session_name: string; session_date: string; marked_at: string | null; local_time: string | null
  status: AttendanceStatus; method: 'face' | 'manual' | null; similarity: number | null; note: string | null
  is_computed: boolean; corrected: boolean
}

export interface SessionItem {
  id: number; name: string; start_time: string; end_time: string; late_cutoff: string | null
  days_of_week: number[]; early_checkin_minutes: number; department: string | null; is_active: boolean
}
export type SessionInput = Omit<SessionItem, 'id'>

export interface DeptCount { department: string; present: number; late: number; absent: number }
export interface DashboardSummary {
  date: string; timezone: string; total_people: number; sessions_today: number; expected: number
  present: number; late: number; absent: number; pending: number; attended: number
  attendance_percentage: number | null; departments: DeptCount[]; recent: AttendanceRow[]
}
export interface TrendPoint { date: string; present: number; late: number; absent: number; expected: number; attendance_percentage: number | null }

export interface ReportBucket { present: number; late: number; absent: number; expected: number; attendance_percentage: number | null }
export interface Report {
  from: string; to: string; group_by: string
  series: (ReportBucket & { period: string })[]
  people: (ReportBucket & { person_id: number; person_code: string; full_name: string })[]
  departments: (ReportBucket & { department: string })[]
  totals: ReportBucket
}

export interface RecognitionStatus {
  model_loaded: boolean; model_name: string; providers_active: string[]; model_error: string | null; notes: string[]
  enrolled_people: number; templates: number; recognition_threshold: number; similarity_note: string
  liveness_policy: 'off' | 'challenge'; liveness_note: string; frame_interval_ms: number; cooldown_seconds: number
  camera: { width: number; height: number }
}

export type ScanStatus =
  | 'no_face' | 'multiple_faces' | 'poor_quality' | 'liveness_challenge' | 'liveness_failed' | 'liveness_unsupported'
  | 'unknown' | 'marked' | 'already_marked' | 'no_active_session' | 'person_disabled' | 'model_unavailable'
  | 'bad_image' | 'cooldown'

export interface ScanResult {
  type?: 'result'; status: ScanStatus; message: string
  person?: { id: number; person_code: string; full_name: string; department: string | null }
  attendance?: { id: number; session: string; session_date: string; marked_at: string; local_time: string; status: AttendanceStatus; method: string }
  similarity?: number; bbox?: { x: number; y: number; w: number; h: number }; challenge?: 'left' | 'right'
  retry_after?: number; detail?: string; reason?: string; timings?: Record<string, number>
}

export interface SettingsPayload { values: Record<string, string | number | boolean>; descriptions: Record<string, string>; sensitive: string[] }
export interface AuditItem { id: number; created_at: string; username: string | null; action: string; entity_type: string | null; entity_id: string | null; details: Record<string, unknown> | null; ip: string | null }

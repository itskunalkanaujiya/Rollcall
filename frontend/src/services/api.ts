import axios, { AxiosError } from 'axios'

/** Same-origin in dev (Vite proxies /api) and in production behind a reverse proxy. */
export const api = axios.create({ baseURL: '/api/v1', withCredentials: true, timeout: 30000 })

export interface ApiErrorInfo { status: number; code: string; message: string; details?: unknown }

export function toApiError(err: unknown): ApiErrorInfo {
  if (axios.isAxiosError(err)) {
    const e = err as AxiosError<{ error?: { code: string; message: string; details?: unknown } }>
    if (e.response?.data?.error) {
      const { code, message, details } = e.response.data.error
      return { status: e.response.status, code, message, details }
    }
    if (e.code === 'ECONNABORTED') return { status: 0, code: 'timeout', message: 'The server took too long to respond.' }
    if (!e.response) return { status: 0, code: 'network', message: 'Cannot reach the server. Check that the backend is running.' }
    return { status: e.response.status, code: 'http_error', message: `Request failed (${e.response.status}).` }
  }
  return { status: 0, code: 'unknown', message: err instanceof Error ? err.message : 'Something went wrong.' }
}

export function fieldErrors(err: ApiErrorInfo): Record<string, string> {
  const out: Record<string, string> = {}
  if (Array.isArray(err.details)) for (const d of err.details as { field: string; message: string }[]) out[d.field] = d.message
  else if (err.details && typeof err.details === 'object') Object.assign(out, err.details)
  return out
}

let onUnauthorized: (() => void) | null = null
export const setUnauthorizedHandler = (fn: (() => void) | null) => { onUnauthorized = fn }

api.interceptors.response.use(
  (r) => r,
  (error) => {
    const url: string = error?.config?.url ?? ''
    if (error?.response?.status === 401 && !url.includes('/auth/login') && !url.includes('/auth/me')) onUnauthorized?.()
    return Promise.reject(error)
  },
)

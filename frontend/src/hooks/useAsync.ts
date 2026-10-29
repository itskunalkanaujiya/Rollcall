import { useCallback, useEffect, useRef, useState } from 'react'
import { toApiError, type ApiErrorInfo } from '../services/api'

/** Loads data with loading/error state; ignores stale responses when deps change. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<ApiErrorInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const seq = useRef(0)
  const run = useCallback(() => {
    const id = ++seq.current
    setLoading(true)
    fn().then((d) => { if (id === seq.current) { setData(d); setError(null) } })
      .catch((e) => { if (id === seq.current) setError(toApiError(e)) })
      .finally(() => { if (id === seq.current) setLoading(false) })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  useEffect(() => { run() }, [run])
  return { data, error, loading, reload: run, setData }
}

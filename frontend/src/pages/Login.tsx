import { useState, type FormEvent } from 'react'
import { Eye, EyeOff, ScanFace } from 'lucide-react'
import { useAuth } from '../hooks/useAuth'
import { toApiError } from '../services/api'
import { Button, Field, Input, Notice } from '../components/ui'

export default function Login() {
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [show, setShow] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [touched, setTouched] = useState(false)

  const userErr = touched && !username.trim() ? 'Enter your username or email.' : undefined
  const passErr = touched && !password ? 'Enter your password.' : undefined

  async function submit(e: FormEvent) {
    e.preventDefault()
    setTouched(true)
    if (!username.trim() || !password) return
    setBusy(true); setError(null)
    try { await login(username.trim(), password) }
    catch (err) {
      const info = toApiError(err)
      setError(info.status === 401 ? 'Wrong username or password.' : info.message)
    } finally { setBusy(false) }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      <div className="relative hidden overflow-hidden bg-rail p-12 text-rail-ink lg:flex lg:flex-col lg:justify-between">
        <div className="flex items-center gap-3"><img src="/favicon.svg" alt="" className="h-9 w-9" /><span className="font-display text-xl font-semibold text-white">Rollcall</span></div>
        <div className="max-w-md">
          <div className="reticle relative mb-8 aspect-[4/3] w-full rounded-2xl border border-white/10 bg-white/5" data-tone="ok" aria-hidden>
            <i /><i /><i /><i />
            <ScanFace className="absolute left-1/2 top-1/2 h-20 w-20 -translate-x-1/2 -translate-y-1/2 text-white/30" />
          </div>
          <h2 className="text-3xl font-semibold leading-tight text-white">Attendance that records itself.</h2>
          <p className="mt-3 text-sm opacity-80">Register people once. After that, anyone who steps up to the camera is verified and logged for the open session.</p>
        </div>
        <p className="text-xs opacity-60">Face data is stored as encrypted templates. No photos are kept.</p>
      </div>
      <div className="flex items-center justify-center p-6">
        <form onSubmit={submit} className="w-full max-w-sm space-y-5" noValidate>
          <div>
            <h1 className="text-2xl font-semibold">Sign in</h1>
            <p className="mt-1 text-sm text-muted">Use the account your administrator created.</p>
          </div>
          {error && <Notice tone="bad">{error}</Notice>}
          <Field label="Username or email" error={userErr}>{(id, bad) => <Input id={id} invalid={bad} autoComplete="username" autoFocus value={username} onChange={(e) => setUsername(e.target.value)} />}</Field>
          <Field label="Password" error={passErr}>
            {(id, bad) => (
              <div className="relative">
                <Input id={id} invalid={bad} type={show ? 'text' : 'password'} autoComplete="current-password" className="pr-10" value={password} onChange={(e) => setPassword(e.target.value)} />
                <button type="button" onClick={() => setShow((s) => !s)} aria-label={show ? 'Hide password' : 'Show password'} className="absolute inset-y-0 right-2 my-auto h-8 rounded p-1.5 text-muted hover:text-ink">
                  {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            )}
          </Field>
          <Button type="submit" loading={busy} className="w-full">Sign in</Button>
        </form>
      </div>
    </div>
  )
}

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { setUnauthorizedHandler } from '../services/api'
import * as svc from '../services/endpoints'
import type { Role, User } from '../types'

interface AuthState {
  user: User | null; loading: boolean
  login: (u: string, p: string) => Promise<void>
  logout: () => Promise<void>
  can: (...roles: Role[]) => boolean
}
const Ctx = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    svc.auth.me().then(setUser).catch(() => setUser(null)).finally(() => setLoading(false))
    setUnauthorizedHandler(() => setUser(null))   // any 401 from the API signs the user out of the UI
    return () => setUnauthorizedHandler(null)
  }, [])

  const login = useCallback(async (u: string, p: string) => { setUser(await svc.auth.login(u, p)) }, [])
  const logout = useCallback(async () => { try { await svc.auth.logout() } finally { setUser(null) } }, [])
  const can = useCallback((...roles: Role[]) => !!user && roles.includes(user.role), [user])
  const value = useMemo(() => ({ user, loading, login, logout, can }), [user, loading, login, logout, can])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useAuth(): AuthState {
  const v = useContext(Ctx)
  if (!v) throw new Error('useAuth must be used inside AuthProvider')
  return v
}

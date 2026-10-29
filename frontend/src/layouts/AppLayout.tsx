import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { BarChart3, CalendarClock, ClipboardList, LayoutDashboard, LogOut, Menu, Moon, ScanFace, Settings, Sun, Users } from 'lucide-react'
import { useAuth } from '../hooks/useAuth'
import { useTheme } from '../hooks/useTheme'
import { cx } from '../components/ui'

const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true, roles: ['admin', 'operator', 'viewer'] },
  { to: '/scanner', label: 'Live scanner', icon: ScanFace, roles: ['admin', 'operator'] },
  { to: '/people', label: 'People', icon: Users, roles: ['admin', 'operator', 'viewer'] },
  { to: '/attendance', label: 'Attendance', icon: ClipboardList, roles: ['admin', 'operator', 'viewer'] },
  { to: '/reports', label: 'Reports', icon: BarChart3, roles: ['admin', 'operator', 'viewer'] },
  { to: '/settings', label: 'Sessions & settings', icon: Settings, roles: ['admin', 'operator', 'viewer'] },
]

export function AppLayout() {
  const { user, logout } = useAuth()
  const { theme, toggle } = useTheme()
  const [open, setOpen] = useState(false)
  const items = NAV.filter((n) => user && n.roles.includes(user.role))
  return (
    <div className="min-h-screen lg:flex">
      <aside className={cx('fixed inset-y-0 left-0 z-40 flex w-64 flex-col bg-rail text-rail-ink transition-transform lg:static lg:translate-x-0', open ? 'translate-x-0' : '-translate-x-full')}>
        <div className="flex items-center gap-2.5 px-5 py-5">
          <img src="/favicon.svg" alt="" className="h-8 w-8" />
          <div><p className="font-display text-lg font-semibold leading-none text-white">Rollcall</p><p className="mt-1 text-xs opacity-70">Face attendance</p></div>
        </div>
        <nav className="flex-1 space-y-0.5 px-3" aria-label="Main">
          {items.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} onClick={() => setOpen(false)}
              className={({ isActive }) => cx('flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors', isActive ? 'bg-rail-active text-white' : 'hover:bg-rail-active/60')}>
              <Icon className="h-[18px] w-[18px]" aria-hidden />{label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-white/10 p-3">
          <div className="mb-2 flex items-center gap-2 px-2 text-xs"><CalendarClock className="h-4 w-4 opacity-70" aria-hidden /><span className="truncate">{user?.username} · {user?.role}</span></div>
          <div className="flex gap-2">
            <button onClick={toggle} className="flex flex-1 items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm hover:bg-rail-active/60" aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}>
              {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}{theme === 'dark' ? 'Light' : 'Dark'}
            </button>
            <button onClick={() => void logout()} className="flex flex-1 items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm hover:bg-rail-active/60"><LogOut className="h-4 w-4" />Sign out</button>
          </div>
        </div>
      </aside>
      {open && <div className="fixed inset-0 z-30 bg-black/40 lg:hidden" onClick={() => setOpen(false)} aria-hidden />}
      <div className="min-w-0 flex-1">
        <header className="flex items-center gap-3 border-b border-line bg-surface px-4 py-3 lg:hidden">
          <button onClick={() => setOpen(true)} aria-label="Open menu" className="rounded p-1.5 hover:bg-surface-2"><Menu className="h-5 w-5" /></button>
          <span className="font-display font-semibold">Rollcall</span>
        </header>
        <main className="mx-auto max-w-7xl px-4 py-6 sm:px-8 sm:py-8"><Outlet /></main>
      </div>
    </div>
  )
}

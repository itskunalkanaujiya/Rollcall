import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './hooks/useAuth'
import { AppLayout } from './layouts/AppLayout'
import { Spinner } from './components/ui'
import Login from './pages/Login'
const Dashboard = lazy(() => import('./pages/Dashboard'))
const Scanner = lazy(() => import('./pages/Scanner'))
const People = lazy(() => import('./pages/People'))
const Attendance = lazy(() => import('./pages/Attendance'))
const Reports = lazy(() => import('./pages/Reports'))
const SettingsPage = lazy(() => import('./pages/Settings'))

export default function App() {
  const { user, loading, can } = useAuth()
  if (loading) return <div className="flex min-h-screen items-center justify-center"><Spinner label="Starting" /></div>
  if (!user) return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  )
  return (
    <Suspense fallback={<Spinner />}>
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<Dashboard />} />
        <Route path="scanner" element={can('admin', 'operator') ? <Scanner /> : <Navigate to="/" replace />} />
        <Route path="people" element={<People />} />
        <Route path="attendance" element={<Attendance />} />
        <Route path="reports" element={<Reports />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="login" element={<Navigate to="/" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
    </Suspense>
  )
}

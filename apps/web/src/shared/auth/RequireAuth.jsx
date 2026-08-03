/**
 * RequireAuth — route gate. Used as a layout route wrapping every protected page.
 *   loading         -> a minimal splash
 *   unauthenticated -> redirect to /login
 *   authenticated   -> render the matched child route (<Outlet/>)
 */
import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useTheme } from '../theme/ThemeContext'

export default function RequireAuth() {
  const { status } = useAuth()
  const { isDark } = useTheme()

  if (status === 'loading') {
    return (
      <div className={`min-h-screen w-full grid place-items-center ${isDark ? 'bg-[#020817] text-slate-500' : 'bg-slate-100 text-slate-400'}`}>
        <div className="flex items-center gap-3 text-sm">
          <span className="inline-block w-4 h-4 rounded-full border-2 border-violet-500 border-t-transparent animate-spin" />
          Checking your session…
        </div>
      </div>
    )
  }

  if (status === 'unauthenticated') {
    return <Navigate to="/login" replace />
  }

  return <Outlet />
}

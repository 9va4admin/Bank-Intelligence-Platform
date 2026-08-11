/**
 * Logout — actually ends the session. The "Sign Out" nav item links here.
 * Calls AuthContext.logout() (which clears the httpOnly cookie server-side and
 * resets auth state), then sends the user to /login. Without this, "Sign Out"
 * was a dead link and the session cookie survived, auto-admitting the last user.
 */
import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../../shared/context/AuthContext'
import { useTheme } from '../../../shared/theme/ThemeContext'

export default function Logout() {
  const { logout } = useAuth()
  const { isDark } = useTheme()
  const navigate = useNavigate()

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      await logout()
      if (!cancelled) navigate('/login', { replace: true })
    })()
    return () => { cancelled = true }
  }, [logout, navigate])

  return (
    <div className={`min-h-screen w-full grid place-items-center ${isDark ? 'bg-[#020817] text-slate-500' : 'bg-slate-100 text-slate-400'}`}>
      <div className="text-sm">Signing out…</div>
    </div>
  )
}

/**
 * AuthContext — resolves the real ASTRA session and gates the app.
 *
 * On mount (and on demand via refresh) it calls GET /v1/auth/session with the
 * httpOnly cookie. 200 -> authenticated (+ user); anything else, or the backend
 * being down -> unauthenticated. RequireAuth uses `status` to gate every route.
 *
 * The session token lives in an httpOnly cookie, so this never sees it — it only
 * ever learns "am I signed in" and the non-secret identity fields.
 */
import { createContext, useCallback, useContext, useEffect, useState } from 'react'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [status, setStatus] = useState('loading') // 'loading' | 'authenticated' | 'unauthenticated'
  const [user, setUser] = useState(null)

  const refresh = useCallback(async () => {
    try {
      const res = await fetch('/v1/auth/session', { credentials: 'include' })
      if (res.ok) {
        const u = await res.json()
        setUser(u)
        setStatus('authenticated')
        return 'authenticated'
      }
    } catch {
      /* backend unreachable — treat as signed out */
    }
    setUser(null)
    setStatus('unauthenticated')
    return 'unauthenticated'
  }, [])

  const logout = useCallback(async () => {
    try {
      await fetch('/v1/auth/logout', { method: 'POST', credentials: 'include' })
    } catch {
      /* ignore — we clear local state regardless */
    }
    sessionStorage.removeItem('astra-csrf')
    setUser(null)
    setStatus('unauthenticated')
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  return (
    <AuthContext.Provider value={{ status, user, refresh, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}

// Non-throwing variant for providers that may render outside AuthProvider
// (e.g. BankContext in standalone tests). Returns null when unavailable.
export function useAuthOptional() {
  return useContext(AuthContext)
}

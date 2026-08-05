import { createContext, useContext } from 'react'
const AuthContext = createContext(null)

// In web-sb-only there is no real auth — return a minimal stub so pages that
// call useAuth() don't crash. Provides the same shape as the real AuthContext.
const AUTH_STUB = {
  status: 'authenticated',
  user: { name: 'Demo User', role: 'ops_manager', bank_id: 'kbl' },
  refresh: () => {},
  logout: () => {},
}

export function useAuth() { return AUTH_STUB }
export function useAuthOptional() { return useContext(AuthContext) }
export function AuthProvider({ children }) {
  return <AuthContext.Provider value={AUTH_STUB}>{children}</AuthContext.Provider>
}

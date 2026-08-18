/**
 * RequirePermission — route-level authorisation guard.
 *
 * Used as a layout route wrapping pages that require a specific permission.
 * RequireAuth (authentication check) must wrap this in the route tree —
 * this component only handles authorisation, not authentication.
 *
 * Usage in App.jsx:
 *   <Route element={<RequirePermission permission="ai:model_metrics" />}>
 *     <Route path="/ops/model-health" element={<ModelHealth />} />
 *     <Route path="/ops/ocr-feedback" element={<CTSOCRFeedback />} />
 *   </Route>
 *
 * On permission denied: redirects to /access-denied (never shows the page shell).
 */
import { Navigate, Outlet } from 'react-router-dom'
import { useBankContext } from '../context/BankContext'

export default function RequirePermission({ permission }) {
  const { hasPermission } = useBankContext()

  if (!hasPermission(permission)) {
    return <Navigate to="/access-denied" replace />
  }

  return <Outlet />
}

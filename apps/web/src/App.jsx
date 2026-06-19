import { HashRouter as BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import LandingPage from './pages/LandingPage'
import CTSWorkstation from './modules/cts/pages/CTSWorkstation'
import CTSVaultStatus from './modules/cts/pages/CTSVaultStatus'
import CTSDecisionsLog from './modules/cts/pages/CTSDecisionsLog'
import CTSAnalytics from './modules/cts/pages/CTSAnalytics'
import CTSConfig from './modules/cts/pages/CTSConfig'
import CTSPresentment from './modules/cts/pages/CTSPresentment'
import { EJDashboard } from './modules/ej'
import IncidentManagement from './modules/ej/pages/IncidentManagement'
import ManagerPortal from './modules/ej/pages/ManagerPortal'
import BREPolicyManager from './modules/ej/pages/BREPolicyManager'
import NotificationCenter from './modules/ej/pages/NotificationCenter'
import './index.css'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        {/* CTS module */}
        <Route path="/cts" element={<CTSWorkstation />} />
        <Route path="/cts/outward" element={<CTSPresentment />} />
        <Route path="/cts/vault" element={<CTSVaultStatus />} />
        <Route path="/cts/decisions" element={<CTSDecisionsLog />} />
        <Route path="/cts/analytics" element={<CTSAnalytics />} />
        <Route path="/cts/config" element={<CTSConfig />} />
        {/* EJ module — own routes, no overlap with CTS */}
        <Route path="/ej" element={<EJDashboard />} />
        <Route path="/ej/incidents" element={<IncidentManagement />} />
        <Route path="/ej/portal" element={<ManagerPortal />} />
        <Route path="/ej/bre" element={<BREPolicyManager />} />
        <Route path="/ej/notifications" element={<NotificationCenter />} />
        {/* EJ deep-links from landing page cards */}
        <Route path="/fleet" element={<EJDashboard defaultTab="fleet" />} />
        <Route path="/disputes" element={<EJDashboard defaultTab="disputes" />} />
        <Route path="/audit" element={<ManagerPortal />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

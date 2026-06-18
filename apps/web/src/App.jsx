import { HashRouter as BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import LandingPage from './pages/LandingPage'
import CTSWorkstation from './modules/cts/pages/CTSWorkstation'
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
        <Route path="/cts" element={<CTSWorkstation />} />
        <Route path="/ej" element={<EJDashboard />} />
        <Route path="/ej/incidents" element={<IncidentManagement />} />
        <Route path="/ej/portal" element={<ManagerPortal />} />
        <Route path="/ej/bre" element={<BREPolicyManager />} />
        <Route path="/ej/notifications" element={<NotificationCenter />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

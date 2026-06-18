import { HashRouter as BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import LandingPage from './pages/LandingPage'
import CTSWorkstation from './modules/cts/pages/CTSWorkstation'
import { EJDashboard } from './modules/ej'
import './index.css'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/cts" element={<CTSWorkstation />} />
        <Route path="/ej" element={<EJDashboard />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

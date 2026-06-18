import { useState } from 'react'
import { useEJCommandCenter } from './hooks/useEJCommandCenter'
import CommandHeader from './components/CommandHeader'
import KPIStrip from './components/KPIStrip'
import FleetFilter from './components/FleetFilter'
import AlarmFeed from './components/AlarmFeed'
import ATMGrid from './components/ATMGrid'
import EJViewer from './components/EJViewer'
import TxnVelocityChart from './components/TxnVelocityChart'
import RiskPanel from './components/RiskPanel'
import { Link } from 'react-router-dom'

export default function EJCommandCenter() {
  const ctx = useEJCommandCenter()
  const [ejViewerOpen, setEJViewerOpen] = useState(false)

  return (
    <div className="min-h-screen bg-[#020817] text-slate-100 font-sans">
      {/* Top nav strip */}
      <div className="border-b border-slate-800 px-6 py-2 flex items-center justify-between">
        <Link to="/" className="text-xs text-slate-500 hover:text-cyan-400 transition-colors">← ASTRA Platform</Link>
        <span className="text-xs font-mono text-slate-600">EJ INTELLIGENCE · COMMAND CENTER</span>
        <Link to="/cts" className="text-xs text-slate-500 hover:text-cyan-400 transition-colors">CTS Workstation →</Link>
      </div>

      <div className="px-4 py-3 space-y-3">
        <CommandHeader kpis={ctx.kpis} tick={ctx.tick} />
        <KPIStrip kpis={ctx.kpis} tick={ctx.tick} />
        <FleetFilter filters={ctx.filters} setFilters={ctx.setFilters} states={ctx.states} cities={ctx.cities} />

        {/* Main 3-panel layout */}
        <div className="grid grid-cols-12 gap-3" style={{minHeight:'520px'}}>
          {/* Left: Alarm Feed */}
          <div className="col-span-3">
            <AlarmFeed alarms={ctx.alarms} ackAlarm={ctx.ackAlarm} />
          </div>

          {/* Center: ATM Grid */}
          <div className="col-span-6">
            <ATMGrid
              atms={ctx.filteredAtms}
              selectedAtm={ctx.selectedAtm}
              setSelectedAtm={ctx.setSelectedAtm}
              onOpenEJ={() => setEJViewerOpen(true)}
              tick={ctx.tick}
            />
          </div>

          {/* Right: Risk + Top Volume */}
          <div className="col-span-3 space-y-3">
            <RiskPanel atms={ctx.atms} />
            <TxnVelocityChart data={ctx.velocityData} />
          </div>
        </div>

        {/* EJ Viewer - collapsible */}
        {ejViewerOpen && (
          <EJViewer
            atm={ctx.selectedAtm}
            onClose={() => setEJViewerOpen(false)}
          />
        )}
        {!ejViewerOpen && ctx.selectedAtm && (
          <button
            onClick={() => setEJViewerOpen(true)}
            className="w-full py-2 border border-cyan-800 rounded-lg text-xs text-cyan-400 hover:bg-cyan-900/20 transition-colors font-mono"
          >
            ▼ VIEW EJ LOGS FOR {ctx.selectedAtm.atm_id} — RAW vs OPTIMIZED
          </button>
        )}
      </div>
    </div>
  )
}

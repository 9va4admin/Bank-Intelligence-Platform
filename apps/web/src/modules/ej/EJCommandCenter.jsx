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

const TIME_RANGES = ['Live', '2h', '6h', '24h', '7d', '30d']

export default function EJCommandCenter() {
  const ctx = useEJCommandCenter()
  const [ejViewerOpen, setEJViewerOpen] = useState(false)
  const [timeRange, setTimeRange] = useState('Live')

  return (
    <div className="min-h-screen bg-[#020817] text-slate-100 font-sans">
      {/* Top nav strip */}
      <div className="border-b border-slate-800 px-6 py-2 flex items-center justify-between">
        <Link to="/" className="text-xs text-slate-500 hover:text-cyan-400 transition-colors">← ASTRA Platform</Link>
        <div className="flex items-center gap-1 text-xs">
          <span className="px-3 py-1.5 rounded bg-cyan-600/20 text-cyan-300 font-medium border border-cyan-500/30">Command Center</span>
          <Link to="/ej/incidents" className="px-3 py-1.5 rounded text-slate-400 hover:text-white transition-colors">Incident Management</Link>
          <Link to="/ej/portal" className="px-3 py-1.5 rounded text-slate-400 hover:text-white transition-colors">Manager Portal</Link>
        </div>
        <Link to="/cts" className="text-xs text-slate-500 hover:text-cyan-400 transition-colors">CTS Workstation →</Link>
      </div>

      <div className="px-4 py-3 space-y-3">
        <CommandHeader kpis={ctx.kpis} tick={ctx.tick} />
        <div className="flex items-center justify-between gap-4">
          <KPIStrip kpis={ctx.kpis} tick={ctx.tick} />
          {/* Time range selector */}
          <div className="flex items-center gap-1 bg-white/5 rounded-lg p-1 border border-white/5 flex-shrink-0">
            {TIME_RANGES.map(t => (
              <button
                key={t}
                onClick={() => setTimeRange(t)}
                className={`px-2.5 py-1 rounded text-xs font-mono transition-colors ${
                  timeRange === t
                    ? 'bg-cyan-600/40 text-cyan-300 border border-cyan-500/40'
                    : 'text-slate-500 hover:text-slate-200'
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        </div>
        {timeRange !== 'Live' && (
          <div className="bg-amber-500/10 border border-amber-500/20 rounded-lg px-4 py-2 text-xs text-amber-300 flex items-center gap-2">
            <span className="font-mono">HISTORICAL</span> — Showing alarm and incident data from the last {timeRange}. Live updates paused.
          </div>
        )}
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

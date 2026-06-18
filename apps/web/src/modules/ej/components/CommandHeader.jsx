import { useState, useEffect } from 'react'

export default function CommandHeader({ kpis, tick }) {
  const [now, setNow] = useState(new Date())

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])

  const systemHealth = kpis.critical > 0 ? 'CRITICAL' : kpis.high > 0 ? 'HIGH ALERT' : kpis.degraded > 0 ? 'DEGRADED' : 'NOMINAL'
  const healthColor = kpis.critical > 0 ? 'text-red-400' : kpis.high > 0 ? 'text-amber-400' : kpis.degraded > 0 ? 'text-yellow-400' : 'text-emerald-400'

  return (
    <div className="flex items-center justify-between border border-slate-800 rounded-xl bg-slate-900/60 px-5 py-3 backdrop-blur">
      <div>
        <div className="flex items-center gap-3">
          <div className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse" />
          <span className="text-sm font-semibold text-cyan-300 tracking-widest uppercase">ATM EJ Intelligence</span>
        </div>
        <p className="text-xs text-slate-500 mt-0.5">ASTRA Command Center · Live Fleet Surveillance</p>
      </div>

      <div className="flex items-center gap-8">
        <div className="text-center">
          <div className="text-xs text-slate-500 uppercase tracking-wider">System Status</div>
          <div className={`text-sm font-bold font-mono ${healthColor}`}>{systemHealth}</div>
        </div>
        <div className="text-center">
          <div className="text-xs text-slate-500 uppercase tracking-wider">Active Alarms</div>
          <div className={`text-xl font-bold font-mono ${kpis.unackedAlarms > 0 ? 'text-red-400 animate-pulse' : 'text-slate-400'}`}>
            {kpis.unackedAlarms}
          </div>
        </div>
        <div className="text-right">
          <div className="text-xl font-mono font-bold text-slate-100 tabular-nums">
            {now.toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false})}
          </div>
          <div className="text-xs text-slate-500 font-mono">
            {now.toLocaleDateString('en-IN',{day:'2-digit',month:'short',year:'numeric'})} IST
          </div>
        </div>
      </div>
    </div>
  )
}

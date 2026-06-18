const RISK_STYLES = {
  CRITICAL: { border: 'border-red-500/70',    bg: 'bg-red-950/30',   label: 'text-red-400',    badge: 'bg-red-900/60 text-red-300',   pulse: true  },
  HIGH:     { border: 'border-amber-500/50',  bg: 'bg-amber-950/20', label: 'text-amber-400',  badge: 'bg-amber-900/50 text-amber-300', pulse: false },
  DEGRADED: { border: 'border-yellow-600/40', bg: 'bg-yellow-950/10',label: 'text-yellow-400', badge: 'bg-yellow-900/40 text-yellow-300', pulse: false },
  HEALTHY:  { border: 'border-slate-700',     bg: 'bg-slate-900/40', label: 'text-emerald-400',badge: 'bg-emerald-900/30 text-emerald-300', pulse: false },
  OFFLINE:  { border: 'border-slate-700/30',  bg: 'bg-slate-900/20', label: 'text-slate-600',  badge: 'bg-slate-800 text-slate-500',   pulse: false },
}

function CashBar({ pct }) {
  const color = pct < 10 ? 'bg-red-500' : pct < 30 ? 'bg-amber-500' : pct < 50 ? 'bg-yellow-500' : 'bg-emerald-500'
  return (
    <div className="mt-2">
      <div className="flex justify-between text-xs text-slate-500 mb-0.5">
        <span>Cash</span><span className={pct < 20 ? 'text-red-400 font-bold' : 'text-slate-400'}>{pct}%</span>
      </div>
      <div className="h-1 rounded-full bg-slate-800 overflow-hidden">
        <div className={`h-full rounded-full transition-all duration-1000 ${color}`} style={{width:`${pct}%`}} />
      </div>
    </div>
  )
}

export default function ATMGrid({ atms, selectedAtm, setSelectedAtm, onOpenEJ, tick }) {
  return (
    <div className="border border-slate-800 rounded-xl bg-slate-900/20 p-3 h-full">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">ATM Fleet · {atms.length} ATMs</span>
        <div className="flex items-center gap-2 text-xs">
          {['CRITICAL','HIGH','DEGRADED','HEALTHY','OFFLINE'].map(r => (
            <span key={r} className={`font-mono text-[10px] ${RISK_STYLES[r].label}`}>● {r}</span>
          ))}
        </div>
      </div>
      <div className="grid grid-cols-3 gap-2 overflow-y-auto" style={{maxHeight:'460px'}}>
        {atms.map(atm => {
          const s = RISK_STYLES[atm.status === 'OFFLINE' ? 'OFFLINE' : atm.risk] || RISK_STYLES.HEALTHY
          const isSelected = selectedAtm?.atm_id === atm.atm_id
          return (
            <div
              key={atm.atm_id}
              onClick={() => { setSelectedAtm(atm); if(atm.status !== 'OFFLINE') onOpenEJ() }}
              className={`
                border rounded-lg p-3 cursor-pointer transition-all duration-300
                ${s.border} ${s.bg}
                ${isSelected ? 'ring-1 ring-cyan-500/60 shadow-lg shadow-cyan-500/10' : 'hover:border-slate-600'}
                ${s.pulse ? 'animate-pulse' : ''}
                ${atm.status === 'OFFLINE' ? 'opacity-40' : ''}
              `}
            >
              <div className="flex items-start justify-between mb-1">
                <div className="font-mono text-[11px] font-bold text-slate-200">{atm.atm_id}</div>
                <span className={`text-[9px] font-semibold px-1.5 py-0.5 rounded-full ${s.badge}`}>
                  {atm.risk}
                </span>
              </div>
              <div className="text-[10px] text-slate-500 truncate">{atm.branch}, {atm.city}</div>
              <div className="text-[10px] text-slate-600 font-mono">{atm.oem}</div>

              <CashBar pct={atm.cash_pct} />

              <div className="flex justify-between mt-2 text-[10px]">
                <div>
                  <span className="text-slate-600">VEL </span>
                  <span className={`font-mono font-bold ${atm.txn_velocity > 30 ? 'text-amber-400' : 'text-cyan-400'}`}>
                    {atm.txn_velocity}/hr
                  </span>
                </div>
                <div>
                  <span className="text-slate-600">TXN </span>
                  <span className="font-mono text-slate-300">{atm.txn_today.toLocaleString()}</span>
                </div>
              </div>

              {atm.pending_alarms > 0 && (
                <div className="mt-1.5 text-[10px] font-semibold text-red-400 font-mono">
                  ⚠ {atm.pending_alarms} active alarm{atm.pending_alarms > 1 ? 's' : ''}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

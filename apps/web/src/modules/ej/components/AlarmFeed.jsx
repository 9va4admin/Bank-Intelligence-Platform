const SEV_STYLES = {
  CRITICAL: { bg: 'bg-red-950/50 border-red-700/50',   dot: 'bg-red-500', label: 'text-red-400',    badge: 'bg-red-900/60 text-red-300' },
  HIGH:     { bg: 'bg-amber-950/40 border-amber-700/40', dot: 'bg-amber-400', label: 'text-amber-400', badge: 'bg-amber-900/50 text-amber-300' },
  MEDIUM:   { bg: 'bg-yellow-950/30 border-yellow-700/30',dot:'bg-yellow-400',label:'text-yellow-400',badge:'bg-yellow-900/40 text-yellow-300' },
  LOW:      { bg: 'bg-slate-900/40 border-slate-700',   dot: 'bg-slate-400', label: 'text-slate-400', badge: 'bg-slate-800 text-slate-400' },
}

export default function AlarmFeed({ alarms, ackAlarm }) {
  const unacked = alarms.filter(a => !a.ack)

  return (
    <div className="border border-slate-800 rounded-xl bg-slate-900/20 p-3 h-full flex flex-col">
      <div className="flex items-center justify-between mb-3 shrink-0">
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${unacked.length > 0 ? 'bg-red-500 animate-pulse' : 'bg-slate-600'}`} />
          <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Live Alarms</span>
        </div>
        <span className={`text-xs font-mono font-bold ${unacked.length > 0 ? 'text-red-400' : 'text-slate-500'}`}>
          {unacked.length} unacked
        </span>
      </div>

      <div className="space-y-1.5 overflow-y-auto flex-1 pr-0.5">
        {alarms.slice(0, 25).map(alarm => {
          const s = SEV_STYLES[alarm.severity] || SEV_STYLES.LOW
          return (
            <div
              key={alarm.id}
              className={`border rounded-lg p-2 transition-all duration-300 ${alarm.ack ? 'opacity-40 ' : ''}${s.bg}`}
            >
              <div className="flex items-start justify-between gap-1">
                <div className="flex items-center gap-1.5 min-w-0">
                  <div className={`w-1.5 h-1.5 rounded-full shrink-0 mt-0.5 ${s.dot}`} />
                  <span className="text-[10px] font-mono font-bold text-slate-300 truncate">{alarm.atm_id}</span>
                </div>
                <span className={`text-[9px] font-semibold shrink-0 px-1.5 py-0.5 rounded-full ${s.badge}`}>
                  {alarm.severity}
                </span>
              </div>
              <div className={`text-[10px] font-semibold mt-1 ${s.label}`}>{alarm.name}</div>
              <div className="text-[10px] text-slate-500 mt-0.5 leading-tight">{alarm.message}</div>
              <div className="flex items-center justify-between mt-1.5">
                <span className="text-[9px] font-mono text-slate-600">{alarm.ts} · {alarm.city}</span>
                {!alarm.ack && (
                  <button
                    onClick={() => ackAlarm(alarm.id)}
                    className="text-[9px] text-cyan-500 hover:text-cyan-300 transition-colors font-mono"
                  >
                    ACK
                  </button>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default function BatchStats({ stats, isDark }) {
  const pctDone = Math.round(((stats.stp_confirmed + stats.stp_returned + stats.human_review) / stats.total_inward) * 100)

  const heading = isDark ? 'text-white'     : 'text-slate-900'
  const meta    = isDark ? 'text-slate-500' : 'text-slate-400'
  const bar     = isDark ? 'bg-white/5'     : 'bg-slate-100'
  const lbl     = isDark ? 'text-slate-600' : 'text-slate-400'
  const wrapper = isDark ? 'border-white/8 bg-navy-900/60' : 'border-slate-200 bg-white'

  const tiles = [
    { label: 'Total Inward',  value: stats.total_inward,   color: heading },
    { label: 'STP Confirmed', value: stats.stp_confirmed,  color: 'text-emerald-400' },
    { label: 'STP Returned',  value: stats.stp_returned,   color: 'text-red-400' },
    { label: 'Human Review',  value: stats.human_review,   color: 'text-amber-400' },
    { label: 'STP Rate',      value: `${stats.stp_rate}%`, color: 'text-gold-400' },
    { label: 'Avg Decision',  value: `${stats.avg_decision_ms}ms`, color: 'text-blue-400' },
  ]

  return (
    <div className={`border-b backdrop-blur px-6 py-4 ${wrapper}`}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <div className={`text-xs font-semibold ${heading}`}>Mumbai Clearing · {stats.date}</div>
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-400/10 border border-emerald-400/20 text-emerald-400">
            ● Live
          </span>
        </div>
        <div className={`text-[11px] ${meta}`}>
          Session: {stats.processing_start} – {stats.cutoff}
        </div>
      </div>

      <div className={`h-1.5 ${bar} rounded-full mb-4 overflow-hidden`}>
        <div
          className="h-full bg-gradient-to-r from-gold-400 to-gold-500 rounded-full transition-all"
          style={{ width: `${pctDone}%` }}
        />
      </div>

      <div className="grid grid-cols-6 gap-3">
        {tiles.map((t) => (
          <div key={t.label} className="text-center">
            <div className={`text-xl font-bold font-mono ${t.color}`}>{t.value}</div>
            <div className={`text-[10px] ${lbl} mt-0.5`}>{t.label}</div>
          </div>
        ))}
      </div>

      {stats.iet_risk > 0 && (
        <div className="mt-3 flex items-center gap-2 text-[11px] text-red-400 animate-pulse">
          <span>⚠</span>
          <span>{stats.iet_risk} cheque{stats.iet_risk > 1 ? 's' : ''} approaching IET deadline — review immediately</span>
        </div>
      )}
    </div>
  )
}

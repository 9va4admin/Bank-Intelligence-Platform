export default function BatchStats({ stats, isDark }) {
  const pctDone = Math.round(((stats.stp_confirmed + stats.stp_returned + stats.human_review) / stats.total_inward) * 100)

  const heading = isDark ? 'text-white' : 'text-slate-900'
  const meta    = isDark ? 'text-slate-500' : 'text-slate-400'
  const bar     = isDark ? 'bg-white/5' : 'bg-slate-100'
  const lbl     = isDark ? 'text-slate-500' : 'text-slate-400'
  const wrapper = isDark ? 'border-white/10 bg-navy-900/60' : 'border-slate-200 bg-white'

  const tiles = [
    { label: 'Inward',    value: stats.total_inward,          color: heading },
    { label: 'Confirmed', value: stats.stp_confirmed,         color: 'text-emerald-500' },
    { label: 'Returned',  value: stats.stp_returned,          color: 'text-red-400' },
    { label: 'Review',    value: stats.human_review,          color: 'text-amber-400' },
    { label: 'STP Rate',  value: `${stats.stp_rate}%`,        color: 'text-gold-400' },
    { label: 'Avg',       value: `${stats.avg_decision_ms}ms`,color: 'text-blue-400' },
  ]

  return (
    <div className={`border-b ${wrapper} shrink-0`}>
      {/* Single compact row */}
      <div className="flex items-center gap-4 px-5 py-1.5">
        {/* Branding + live pill */}
        <div className="flex items-center gap-2 shrink-0">
          <span className={`text-[11px] font-semibold ${heading}`}>Mumbai Clearing · {stats.date}</span>
          <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-emerald-400/10 border border-emerald-400/20 text-emerald-400">● Live</span>
        </div>

        {/* Progress bar — slim, takes remaining space */}
        <div className={`flex-1 h-1 ${bar} rounded-full overflow-hidden`}>
          <div
            className="h-full bg-gradient-to-r from-gold-400 to-gold-500 rounded-full transition-all"
            style={{ width: `${pctDone}%` }}
          />
        </div>

        {/* Tiles — inline */}
        <div className="flex items-center gap-5 shrink-0">
          {tiles.map((t) => (
            <div key={t.label} className="flex items-baseline gap-1">
              <span className={`text-sm font-bold font-mono ${t.color}`}>{t.value}</span>
              <span className={`text-[9px] ${lbl}`}>{t.label}</span>
            </div>
          ))}
        </div>

        {/* Session time */}
        <span className={`text-[10px] ${meta} shrink-0`}>{stats.processing_start}–{stats.cutoff}</span>
      </div>

      {/* IET risk alert — only shown when needed, slim */}
      {stats.iet_risk > 0 && (
        <div className="flex items-center gap-1.5 px-5 pb-1 text-[10px] text-red-400 animate-pulse">
          <span>⚠</span>
          <span>{stats.iet_risk} cheque{stats.iet_risk > 1 ? 's' : ''} approaching IET deadline — review immediately</span>
        </div>
      )}
    </div>
  )
}

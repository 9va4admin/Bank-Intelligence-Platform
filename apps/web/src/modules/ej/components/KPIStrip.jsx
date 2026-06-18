export default function KPIStrip({ kpis }) {
  const items = [
    { label:'Total ATMs',       value: kpis.total,                    color:'text-cyan-300',   sub:'in network' },
    { label:'Online',           value: kpis.online,                   color:'text-emerald-400', sub:`${kpis.offline} offline` },
    { label:'Critical',         value: kpis.critical,                 color: kpis.critical > 0 ? 'text-red-400' : 'text-slate-500', sub:'need action now', pulse: kpis.critical > 0 },
    { label:'High Risk',        value: kpis.high,                     color: kpis.high > 0 ? 'text-amber-400' : 'text-slate-500', sub:'elevated threat' },
    { label:'TXN Today',        value: kpis.totalTxnToday.toLocaleString('en-IN'), color:'text-violet-300', sub:'across all ATMs' },
    { label:'Avg Cash',         value: `${kpis.avgCash}%`,            color: kpis.avgCash < 20 ? 'text-red-400' : kpis.avgCash < 40 ? 'text-amber-400' : 'text-emerald-400', sub:'fleet average' },
  ]

  return (
    <div className="grid grid-cols-6 gap-2">
      {items.map(({ label, value, color, sub, pulse }) => (
        <div key={label} className="border border-slate-800 rounded-lg bg-slate-900/40 px-3 py-2 text-center">
          <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">{label}</div>
          <div className={`text-2xl font-bold font-mono tabular-nums ${color} ${pulse ? 'animate-pulse' : ''}`}>
            {value}
          </div>
          <div className="text-xs text-slate-600 mt-0.5">{sub}</div>
        </div>
      ))}
    </div>
  )
}

export default function RiskPanel({ atms }) {
  const critical = atms.filter(a => a.risk === 'CRITICAL')
  const high = atms.filter(a => a.risk === 'HIGH')
  const topVolume = [...atms].sort((a,b) => b.txn_today - a.txn_today).slice(0, 5)

  return (
    <div className="border border-slate-800 rounded-xl bg-slate-900/20 p-3">
      <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Risk & Volume</span>

      {critical.length > 0 && (
        <div className="mt-2">
          <div className="text-[10px] text-red-400 font-semibold uppercase mb-1">● Critical ({critical.length})</div>
          {critical.map(a => (
            <div key={a.atm_id} className="flex justify-between text-[10px] py-0.5 border-b border-slate-800">
              <span className="font-mono text-red-300">{a.atm_id}</span>
              <span className="text-slate-500">{a.city}</span>
            </div>
          ))}
        </div>
      )}

      {high.length > 0 && (
        <div className="mt-2">
          <div className="text-[10px] text-amber-400 font-semibold uppercase mb-1">● High Risk ({high.length})</div>
          {high.map(a => (
            <div key={a.atm_id} className="flex justify-between text-[10px] py-0.5 border-b border-slate-800">
              <span className="font-mono text-amber-300">{a.atm_id}</span>
              <span className="text-slate-500">{a.city}</span>
            </div>
          ))}
        </div>
      )}

      <div className="mt-3">
        <div className="text-[10px] text-violet-400 font-semibold uppercase mb-1">▲ Top Volume Today</div>
        {topVolume.map((a, i) => (
          <div key={a.atm_id} className="flex justify-between items-center text-[10px] py-0.5 border-b border-slate-800">
            <div className="flex items-center gap-1.5">
              <span className="text-slate-600 font-mono">{i+1}</span>
              <span className="font-mono text-slate-300">{a.atm_id}</span>
            </div>
            <span className="text-violet-300 font-mono font-bold">{a.txn_today.toLocaleString()}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

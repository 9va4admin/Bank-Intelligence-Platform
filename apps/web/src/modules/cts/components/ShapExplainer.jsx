export default function ShapExplainer({ shapValues }) {
  const maxAbs = Math.max(...shapValues.map((s) => Math.abs(s.value)))

  return (
    <div className="space-y-2">
      <div className="text-[10px] text-slate-500 uppercase tracking-widest mb-3">
        AI Decision Factors (SHAP)
      </div>
      {shapValues.map((item) => {
        const width = Math.abs(item.value) / maxAbs
        const isRisk = item.direction === 'risk'
        return (
          <div key={item.feature} className="flex items-center gap-3">
            <div className="w-40 text-xs text-slate-400 text-right shrink-0 truncate" title={item.feature}>
              {item.feature}
            </div>
            <div className="flex-1 flex items-center">
              {isRisk ? (
                <div className="flex items-center w-full justify-start">
                  <div
                    className="h-4 rounded bg-red-500/70 transition-all"
                    style={{ width: `${width * 100}%`, minWidth: '4px' }}
                  />
                  <span className="ml-2 text-[11px] font-mono text-red-400">
                    -{Math.abs(item.value).toFixed(2)}
                  </span>
                </div>
              ) : (
                <div className="flex items-center w-full justify-start">
                  <div
                    className="h-4 rounded bg-emerald-500/70 transition-all"
                    style={{ width: `${width * 100}%`, minWidth: '4px' }}
                  />
                  <span className="ml-2 text-[11px] font-mono text-emerald-400">
                    +{item.value.toFixed(2)}
                  </span>
                </div>
              )}
            </div>
          </div>
        )
      })}
      <div className="flex justify-between text-[10px] text-slate-600 pt-1 border-t border-white/5 mt-2">
        <span className="text-red-400/60">← increases risk</span>
        <span className="text-emerald-400/60">reduces risk →</span>
      </div>
    </div>
  )
}

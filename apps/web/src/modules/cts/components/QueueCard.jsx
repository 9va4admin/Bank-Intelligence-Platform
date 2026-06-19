import IETTimer from './IETTimer'

const REASON_COLORS = {
  SIGNATURE_LOW_CONFIDENCE: 'text-amber-400 bg-amber-400/10 border-amber-400/20',
  FRAUD_SCORE_HIGH:         'text-red-400 bg-red-400/10 border-red-400/20',
  OCR_LOW_CONFIDENCE:       'text-orange-400 bg-orange-400/10 border-orange-400/20',
  VAULT_MISS:               'text-purple-400 bg-purple-400/10 border-purple-400/20',
}

function fraudColor(score) {
  if (score >= 0.80) return 'text-red-400'
  if (score >= 0.72) return 'text-amber-400'
  return 'text-emerald-400'
}

export default function QueueCard({ item, selected, onClick, isDark }) {
  const minsLeft = Math.floor((new Date(item.iet_deadline) - Date.now()) / 60000)
  const urgent = minsLeft < 30

  const idleCls = isDark
    ? 'border-white/8 bg-white/2 hover:border-white/15 hover:bg-white/4'
    : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50'

  const idText  = isDark ? 'text-slate-500'  : 'text-slate-400'
  const name    = isDark ? 'text-white'       : 'text-slate-900'
  const amt     = isDark ? 'text-slate-500'   : 'text-slate-400'
  const fallback= isDark ? 'text-slate-400 bg-white/5 border-white/10' : 'text-slate-500 bg-slate-100 border-slate-200'

  return (
    <button
      onClick={onClick}
      className={`w-full text-left rounded-xl border p-4 transition-all duration-200 ${
        selected
          ? 'border-gold-400/40 bg-gold-400/5'
          : urgent
          ? 'border-red-400/20 bg-red-400/5 hover:border-red-400/40'
          : idleCls
      }`}
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <div>
          <div className={`text-[11px] font-mono ${idText}`}>{item.instrument_id}</div>
          <div className={`text-sm font-semibold ${name} mt-0.5`}>
            {item.account_display} · {item.payee_display}
          </div>
        </div>
        <IETTimer deadline={item.iet_deadline} compact />
      </div>

      <div className="flex items-center gap-2 flex-wrap mt-2">
        <span className={`text-[10px] font-mono px-2 py-0.5 rounded border ${REASON_COLORS[item.reason] || fallback}`}>
          {item.reason_label}
        </span>
        <span className={`text-[10px] ${amt}`}>{item.amount_range}</span>
        <span className={`text-[10px] font-mono font-bold ml-auto ${fraudColor(item.fraud_score)}`}>
          {Math.round(item.fraud_score * 100)}%
        </span>
      </div>
    </button>
  )
}

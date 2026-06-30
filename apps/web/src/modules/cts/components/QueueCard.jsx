import IETTimer from './IETTimer'

const REASON_COLORS_D = {
  SIGNATURE_LOW_CONFIDENCE: 'text-amber-300 bg-amber-400/10 border-amber-400/20',
  FRAUD_SCORE_HIGH:         'text-red-300 bg-red-400/10 border-red-400/20',
  OCR_LOW_CONFIDENCE:       'text-orange-300 bg-orange-400/10 border-orange-400/20',
  VAULT_MISS:               'text-purple-300 bg-purple-400/10 border-purple-400/20',
}
const REASON_COLORS_L = {
  SIGNATURE_LOW_CONFIDENCE: 'text-amber-700 bg-amber-100 border-amber-400',
  FRAUD_SCORE_HIGH:         'text-red-700 bg-red-100 border-red-400',
  OCR_LOW_CONFIDENCE:       'text-orange-700 bg-orange-100 border-orange-400',
  VAULT_MISS:               'text-purple-700 bg-purple-100 border-purple-400',
}

function fraudColor(score) {
  if (score >= 0.80) return 'text-red-400'
  if (score >= 0.72) return 'text-amber-400'
  return 'text-emerald-400'
}

function returnPrediction(item) {
  let score = item.fraud_score * 0.40
  if (item.sig_match_score === null) score += 0.35
  else score += (1 - item.sig_match_score) * 0.35
  const reasonBonus = { VAULT_MISS: 0.20, SIGNATURE_LOW_CONFIDENCE: 0.18, FRAUD_SCORE_HIGH: 0.12, OCR_LOW_CONFIDENCE: 0.08, HIGH_VALUE_DUAL_APPROVAL: 0.04 }
  score += reasonBonus[item.reason] ?? 0
  return Math.min(score, 0.99)
}

export default function QueueCard({ item, selected, onClick, isDark = true }) {
  const minsLeft = Math.floor((new Date(item.iet_deadline) - Date.now()) / 60000)
  const urgent = minsLeft < 30
  const retPct = Math.round(returnPrediction(item) * 100)
  const retColor = retPct >= 75 ? 'text-red-400 border-red-400/30 bg-red-400/8' : retPct >= 55 ? 'text-amber-400 border-amber-400/30 bg-amber-400/8' : 'text-slate-400 border-slate-400/20 bg-transparent'

  const REASON_COLORS = isDark ? REASON_COLORS_D : REASON_COLORS_L
  const fallback = isDark ? 'text-slate-300 bg-white/5 border-white/10' : 'text-slate-600 bg-slate-100 border-slate-300'

  const idleCls = isDark
    ? 'border-white/8 bg-white/5 hover:border-white/15 hover:bg-white/8'
    : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50'

  const idText = isDark ? 'text-slate-500' : 'text-slate-400'
  const nameC  = isDark ? 'text-white'     : 'text-slate-900'
  const amtC   = isDark ? 'text-slate-500' : 'text-slate-400'

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
          <div className={`text-sm font-semibold ${nameC} mt-0.5`}>
            {item.account_display} · {item.payee_display}
          </div>
        </div>
        <IETTimer deadline={item.iet_deadline} compact />
      </div>

      <div className="flex items-center gap-2 flex-wrap mt-2">
        <span className={`text-[10px] font-mono px-2 py-0.5 rounded border ${REASON_COLORS[item.reason] || fallback}`}>
          {item.reason_label}
        </span>
        {item.principal_tag === 'SUB_MEMBER' && (
          <span className={`text-[10px] font-semibold px-2 py-0.5 rounded border ${isDark ? 'text-amber-300 bg-amber-400/10 border-amber-400/30' : 'text-amber-700 bg-amber-100 border-amber-400'}`}>
            SUB-MEMBER
          </span>
        )}
        <span className={`text-[10px] ${amtC}`}>{item.amount_range}</span>
        <span className={`text-[10px] font-mono font-bold ${fraudColor(item.fraud_score)}`}>
          {Math.round(item.fraud_score * 100)}%
        </span>
        <span className={`text-[9px] font-semibold px-1.5 py-0.5 rounded border ml-auto ${retColor}`}>
          ↩ {retPct}%
        </span>
      </div>
    </button>
  )
}

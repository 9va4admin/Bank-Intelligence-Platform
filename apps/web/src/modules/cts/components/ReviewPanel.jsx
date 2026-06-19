import { useState, useRef, useEffect } from 'react'
import IETTimer from './IETTimer'
import FraudGauge from './FraudGauge'
import ShapExplainer from './ShapExplainer'
import ChequeMockImage from './ChequeMockImage'

const RETURN_REASONS = [
  'Signature mismatch confirmed',
  'Amount alteration detected',
  'Insufficient funds',
  'Account dormant / frozen',
  'Post-dated cheque',
  'Mutilated / damaged cheque',
  'Words and figures differ',
  'No specimen on file — cannot verify',
  'Payee name discrepancy',
]

const REASON_COLORS_D = {
  SIGNATURE_LOW_CONFIDENCE: 'bg-amber-400/10 border-amber-400/30 text-amber-300',
  FRAUD_SCORE_HIGH:         'bg-red-400/10 border-red-400/30 text-red-300',
  OCR_LOW_CONFIDENCE:       'bg-orange-400/10 border-orange-400/30 text-orange-300',
  VAULT_MISS:               'bg-purple-400/10 border-purple-400/30 text-purple-300',
  HIGH_VALUE_DUAL_APPROVAL: 'bg-sky-400/10 border-sky-400/30 text-sky-300',
}
const REASON_COLORS_L = {
  SIGNATURE_LOW_CONFIDENCE: 'bg-amber-100 border-amber-400 text-amber-700',
  FRAUD_SCORE_HIGH:         'bg-red-100 border-red-400 text-red-700',
  OCR_LOW_CONFIDENCE:       'bg-orange-100 border-orange-400 text-orange-700',
  VAULT_MISS:               'bg-purple-100 border-purple-400 text-purple-700',
  HIGH_VALUE_DUAL_APPROVAL: 'bg-sky-100 border-sky-400 text-sky-700',
}

function SigPanel({ item, isDark }) {
  const muted  = isDark ? 'text-slate-400'  : 'text-slate-500'
  const note   = isDark ? 'text-slate-500'  : 'text-slate-500'
  const noteBg = isDark ? 'bg-white/3'      : 'bg-slate-50'
  const barBg  = isDark ? 'bg-white/5'      : 'bg-slate-100'
  const tick   = isDark ? 'text-slate-600'  : 'text-slate-400'

  if (!item.sig_specimen_available) {
    return (
      <div className="rounded-xl border border-purple-400/30 bg-purple-400/5 p-4">
        <div className="text-[10px] text-slate-500 uppercase tracking-widest mb-3">Signature Verification</div>
        <div className="flex items-center gap-3 mb-3">
          <span className="text-2xl">🔍</span>
          <div>
            <div className="text-sm font-semibold text-purple-300">No Specimen On File</div>
            <div className={`text-xs ${muted} mt-0.5`}>{item.sig_specimen_label}</div>
          </div>
        </div>
        <div className={`text-xs ${note} leading-relaxed ${noteBg} rounded-lg p-3`}>
          Vault miss — no signature specimen found for account {item.account_display} in the Signature Vault.
          Routed to human review per policy. Auto-return is <span className="text-purple-300 font-medium">never</span> permitted on vault miss.
        </div>
      </div>
    )
  }

  const matchPct = Math.round((item.sig_match_score ?? 0) * 100)
  const color = matchPct < 70 ? 'text-red-400' : matchPct < 85 ? 'text-amber-400' : 'text-emerald-400'
  const borderColor = matchPct < 70 ? 'border-red-400/30 bg-red-400/5' : matchPct < 85 ? 'border-amber-400/30 bg-amber-400/5' : 'border-emerald-400/30 bg-emerald-400/5'

  return (
    <div className={`rounded-xl border p-4 ${borderColor}`}>
      <div className="text-[10px] text-slate-500 uppercase tracking-widest mb-3">Signature Verification · Siamese SNN</div>
      <div className="flex items-center gap-4 mb-3">
        <div className="text-center">
          <div className={`text-3xl font-bold font-mono ${color}`}>{matchPct}%</div>
          <div className="text-[10px] text-slate-500">match score</div>
        </div>
        <div className="flex-1 space-y-1.5">
          <div className={`h-2 ${barBg} rounded-full overflow-hidden`}>
            <div className={`h-full rounded-full transition-all ${matchPct >= 85 ? 'bg-emerald-400' : matchPct >= 70 ? 'bg-amber-400' : 'bg-red-400'}`}
              style={{ width: `${matchPct}%` }} />
          </div>
          <div className={`flex justify-between text-[10px] ${tick}`}>
            <span>0%</span>
            <span className="text-slate-500">threshold: 85%</span>
            <span>100%</span>
          </div>
        </div>
      </div>
      <div className="text-[10px] text-slate-500">{item.sig_specimen_label} · Compared against CBS stored specimen</div>
    </div>
  )
}

export default function ReviewPanel({ item, onDecision, isDark }) {
  const [tab, setTab] = useState('overview')
  const [returnReason, setReturnReason] = useState('')
  const [confirming, setConfirming] = useState(null)

  const REASON_COLORS = isDark ? REASON_COLORS_D : REASON_COLORS_L

  const th = {
    border:   isDark ? 'border-white/8'    : 'border-slate-200',
    id:       isDark ? 'text-slate-500'    : 'text-slate-400',
    heading:  isDark ? 'text-white'        : 'text-slate-900',
    dot:      isDark ? 'text-slate-500'    : 'text-slate-400',
    meta:     isDark ? 'text-slate-500'    : 'text-slate-400',
    tabActive: isDark
      ? 'bg-white/6 text-white border-t border-l border-r border-white/10'
      : 'bg-slate-100 text-slate-900 border-t border-l border-r border-slate-200',
    tabIdle:  isDark ? 'text-slate-500 hover:text-slate-300' : 'text-slate-400 hover:text-slate-700',
    glass:    isDark ? 'bg-white/5 border border-white/8'    : 'bg-slate-50 border border-slate-200',
    lbl:      isDark ? 'text-slate-500'    : 'text-slate-400',
    val:      isDark ? 'text-slate-200'    : 'text-slate-800',
    barBg:    isDark ? 'bg-white/5'        : 'bg-slate-100',
    foot:     isDark ? 'bg-navy-950/80'    : 'bg-white',
    sel:      isDark ? 'bg-white/4 border-white/8 text-slate-300 focus:border-gold-400/40' : 'bg-white border-slate-300 text-slate-700 focus:border-amber-400',
    selOpt:   isDark ? 'bg-navy-900'       : 'bg-white',
    footNote: isDark ? 'text-slate-600'    : 'text-slate-400',
  }

  if (!item) {
    return (
      <div className={`flex-1 flex items-center justify-center text-sm ${th.lbl}`}>
        <div className="text-center">
          <div className="text-4xl mb-3">📋</div>
          <div>Select a cheque from the queue to review</div>
        </div>
      </div>
    )
  }

  const handleAction = (action) => {
    if (action === 'RETURN' && !returnReason) return
    setConfirming(action)
    setTimeout(() => {
      onDecision(item.instrument_id, action, returnReason)
      setConfirming(null)
      setReturnReason('')
      setTab('overview')
    }, 800)
  }

  const [chequeHover, setChequeHover] = useState(false)
  const hoverTimeout = useRef(null)

  const showCheque = () => {
    clearTimeout(hoverTimeout.current)
    setChequeHover(true)
  }
  const hideCheque = () => {
    hoverTimeout.current = setTimeout(() => setChequeHover(false), 120)
  }

  const tabs = ['overview', 'cheque', 'ai analysis']
  const reasonColor = REASON_COLORS[item.reason] || (isDark ? 'bg-slate-400/10 border-slate-400/20 text-slate-300' : 'bg-slate-100 border-slate-300 text-slate-600')

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      {/* Header */}
      <div className={`px-6 pt-4 pb-0 border-b ${th.border} shrink-0`}>
        <div className="flex items-start justify-between mb-3">
          <div>
            <div className={`text-[11px] font-mono mb-0.5 ${th.id}`}>{item.instrument_id} · {item.clearing_zone}</div>
            <div className={`text-base font-bold ${th.heading}`}>
              {item.account_display} <span className={th.dot}>·</span> {item.payee_display}
            </div>
            <div className="flex items-center gap-2 mt-1">
              <span className={`text-[10px] font-semibold px-2 py-0.5 rounded border ${reasonColor}`}>
                {item.reason_label}
              </span>
              <span className={`text-[10px] ${th.meta}`}>{item.amount_range}</span>
              <span className={`text-[10px] ${th.lbl}`}>·</span>
              <span className={`text-[10px] ${th.meta}`}>{item.amount_label}</span>
              {item.opa_rule && <span className="text-[10px] text-sky-400/70 font-mono">OPA</span>}
            </div>
          </div>
          <IETTimer deadline={item.iet_deadline} />
        </div>

        <div className="flex gap-1">
          {tabs.map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-4 py-1.5 text-xs font-medium rounded-t-lg capitalize transition-colors ${tab === t ? th.tabActive : th.tabIdle}`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {/* Content — fills remaining height */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-3">

        {tab === 'overview' && (
          <>
            <div className={`flex items-start gap-3 rounded-xl border px-4 py-2.5 ${reasonColor}`}>
              <span className="text-base mt-0.5">⚠</span>
              <div>
                <div className="text-xs font-semibold">Flagged: {item.reason_label}</div>
                <div className="text-[11px] opacity-70 mt-0.5">
                  {item.reason === 'VAULT_MISS'
                    ? 'Signature vault returned no specimen — auto-return is never permitted. Human must decide.'
                    : item.reason === 'HIGH_VALUE_DUAL_APPROVAL'
                    ? `OPA policy: ${item.opa_rule} — cheque >₹1Cr requires dual reviewer approval.`
                    : 'AI confidence below threshold — decision required before IET deadline.'}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-3 gap-2">
              {[
                { label: 'OCR', val: `${Math.round(item.ocr_confidence * 100)}%`, sub: 'confidence', color: th.heading },
                {
                  label: 'Signature',
                  val: item.sig_match_score != null ? `${Math.round(item.sig_match_score * 100)}%` : 'N/A',
                  sub: item.sig_match_score != null ? 'match score' : 'vault miss',
                  color: item.sig_match_score == null ? 'text-purple-400' : item.sig_match_score < 0.70 ? 'text-red-400' : item.sig_match_score < 0.85 ? 'text-amber-400' : 'text-emerald-400',
                },
                { label: 'Fraud', val: `${Math.round(item.fraud_score * 100)}%`, sub: 'XGBoost score', color: item.fraud_score >= 0.80 ? 'text-red-400' : 'text-amber-400' },
              ].map(({ label, val, sub, color }) => (
                <div key={label} className={`rounded-xl p-3 text-center ${th.glass}`}>
                  <div className={`text-[10px] ${th.lbl} uppercase tracking-wide mb-0.5`}>{label}</div>
                  <div className={`text-xl font-mono font-bold ${color}`}>{val}</div>
                  <div className={`text-[10px] ${th.lbl}`}>{sub}</div>
                </div>
              ))}
            </div>

            {/* OCR fields with cheque hover preview */}
            <div className={`rounded-xl p-4 ${th.glass} relative`}>
              <div className="flex items-center justify-between mb-3">
                <div className={`text-[10px] ${th.lbl} uppercase tracking-widest`}>OCR Extracted Fields · GOT-OCR2.0</div>
                {/* Cheque preview icon */}
                <div className="relative" onMouseEnter={showCheque} onMouseLeave={hideCheque}>
                  <button
                    className={`flex items-center gap-1 text-[10px] px-2 py-1 rounded-lg border transition-all ${
                      isDark
                        ? 'border-white/10 text-slate-400 hover:text-gold-400 hover:border-gold-400/30 hover:bg-gold-400/5'
                        : 'border-slate-200 text-slate-400 hover:text-amber-600 hover:border-amber-300 hover:bg-amber-50'
                    }`}
                    title="Preview cheque image"
                  >
                    <span>🧾</span>
                    <span>View Cheque</span>
                  </button>

                  {/* Floating cheque popover */}
                  {chequeHover && (
                    <div
                      className={`absolute right-0 top-8 z-50 w-[480px] rounded-xl shadow-2xl border p-3 ${
                        isDark ? 'bg-navy-900 border-white/10' : 'bg-white border-slate-200'
                      }`}
                      onMouseEnter={showCheque}
                      onMouseLeave={hideCheque}
                    >
                      <div className={`text-[9px] ${th.lbl} uppercase tracking-widest mb-2`}>Cheque Image — compare with extracted fields</div>
                      <ChequeMockImage fields={item.ocr_fields} alterations={item.ocr_fields.alterations} accountDisplay={item.account_display} isDark={isDark} />
                    </div>
                  )}
                </div>
              </div>
              <div className="grid grid-cols-2 gap-x-6 gap-y-2">
                {[
                  ['Date', item.ocr_fields.date],
                  ['Payee', item.ocr_fields.payee],
                  ['Amount (figures)', item.ocr_fields.amount_figures],
                  ['Amount (words)', item.ocr_fields.amount_words],
                  ['MICR Code', item.ocr_fields.micr],
                  ['Alterations', item.ocr_fields.alterations ? '⚠ DETECTED' : '✓ None'],
                ].map(([k, v]) => (
                  <div key={k} className="flex flex-col">
                    <span className={`text-[10px] ${th.lbl}`}>{k}</span>
                    <span className={`text-xs font-mono mt-0.5 ${k === 'Alterations' && item.ocr_fields.alterations ? 'text-red-400 font-semibold' : th.val}`}>{v}</span>
                  </div>
                ))}
              </div>
            </div>

            <SigPanel item={item} isDark={isDark} />
          </>
        )}

        {tab === 'cheque' && (
          <ChequeMockImage fields={item.ocr_fields} alterations={item.ocr_fields.alterations} accountDisplay={item.account_display} isDark={isDark} />
        )}

        {tab === 'ai analysis' && (
          <div className="space-y-3">
            <div className="flex items-center gap-4">
              <FraudGauge score={item.fraud_score} />
              <div className={`flex-1 rounded-xl p-4 space-y-2 ${th.glass}`}>
                <div className={`text-[10px] ${th.lbl} uppercase tracking-widest mb-2`}>Model Stack</div>
                {[
                  ['OCR', 'GOT-OCR2.0', item.ocr_confidence],
                  ['Vision', 'Qwen2-VL 72B', 0.94],
                  ['Signature', 'Siamese SNN', item.sig_match_score ?? 0],
                  ['Fraud', 'XGBoost', item.fraud_score],
                ].map(([label, model, score]) => (
                  <div key={label} className="flex items-center gap-3">
                    <span className={`text-[10px] ${th.lbl} w-16`}>{label}</span>
                    <div className={`flex-1 h-1.5 ${th.barBg} rounded-full overflow-hidden`}>
                      <div className="h-full bg-gold-400/60 rounded-full" style={{ width: `${score * 100}%` }} />
                    </div>
                    <span className={`text-[10px] font-mono ${th.meta} w-8 text-right`}>{Math.round(score * 100)}%</span>
                    <span className={`text-[10px] ${th.lbl} w-28 truncate`}>{model}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className={`rounded-xl p-4 ${th.glass}`}>
              <ShapExplainer shapValues={item.shap_values} isDark={isDark} />
            </div>
          </div>
        )}
      </div>

      {/* Action footer */}
      <div className={`shrink-0 border-t ${th.border} px-6 py-4 ${th.foot} backdrop-blur space-y-3`}>
        <select
          value={returnReason}
          onChange={(e) => setReturnReason(e.target.value)}
          className={`w-full border rounded-xl px-3 py-2.5 text-xs focus:outline-none appearance-none cursor-pointer ${th.sel}`}
        >
          <option value="" className={th.selOpt}>Select return reason (required to Return)</option>
          {RETURN_REASONS.map((r) => (
            <option key={r} value={r} className={th.selOpt}>{r}</option>
          ))}
        </select>
        <div className="flex gap-3">
          <button
            onClick={() => handleAction('RETURN')}
            disabled={!returnReason || !!confirming}
            className="flex-1 py-3 rounded-xl border border-red-500/40 bg-red-500/10 text-red-400 text-sm font-semibold hover:bg-red-500/20 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {confirming === 'RETURN' ? 'Filing Return to NGCH…' : '✕  Return Cheque'}
          </button>
          <button
            onClick={() => handleAction('CONFIRM')}
            disabled={!!confirming}
            className="flex-1 py-3 rounded-xl bg-emerald-500/20 border border-emerald-500/40 text-emerald-400 text-sm font-semibold hover:bg-emerald-500/30 transition-all disabled:opacity-40"
          >
            {confirming === 'CONFIRM' ? 'Filing Confirm to NGCH…' : '✓  Confirm Cheque'}
          </button>
        </div>
        <div className={`text-center text-[10px] ${th.footNote}`}>
          Decision filed to NGCH immediately · Logged to Immudb · HSM-signed audit record
        </div>
      </div>
    </div>
  )
}

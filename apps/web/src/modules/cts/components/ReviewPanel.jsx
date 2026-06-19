import { useState } from 'react'
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

const REASON_COLORS = {
  SIGNATURE_LOW_CONFIDENCE: 'bg-amber-400/10 border-amber-400/30 text-amber-300',
  FRAUD_SCORE_HIGH: 'bg-red-400/10 border-red-400/30 text-red-300',
  OCR_LOW_CONFIDENCE: 'bg-orange-400/10 border-orange-400/30 text-orange-300',
  VAULT_MISS: 'bg-purple-400/10 border-purple-400/30 text-purple-300',
  HIGH_VALUE_DUAL_APPROVAL: 'bg-sky-400/10 border-sky-400/30 text-sky-300',
}

function SigPanel({ item }) {
  if (!item.sig_specimen_available) {
    return (
      <div className="rounded-xl border border-purple-400/30 bg-purple-400/5 p-4">
        <div className="text-[10px] text-slate-500 uppercase tracking-widest mb-3">Signature Verification</div>
        <div className="flex items-center gap-3 mb-3">
          <span className="text-2xl">🔍</span>
          <div>
            <div className="text-sm font-semibold text-purple-300">No Specimen On File</div>
            <div className="text-xs text-slate-400 mt-0.5">{item.sig_specimen_label}</div>
          </div>
        </div>
        <div className="text-xs text-slate-500 leading-relaxed bg-white/3 rounded-lg p-3">
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
          <div className="h-2 bg-white/5 rounded-full overflow-hidden">
            <div className={`h-full rounded-full transition-all ${matchPct >= 85 ? 'bg-emerald-400' : matchPct >= 70 ? 'bg-amber-400' : 'bg-red-400'}`}
              style={{ width: `${matchPct}%` }} />
          </div>
          <div className="flex justify-between text-[10px] text-slate-600">
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

export default function ReviewPanel({ item, onDecision }) {
  const [tab, setTab] = useState('overview')
  const [returnReason, setReturnReason] = useState('')
  const [confirming, setConfirming] = useState(null)

  if (!item) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-600 text-sm">
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

  const tabs = ['overview', 'cheque', 'ai analysis']
  const reasonColor = REASON_COLORS[item.reason] || 'bg-slate-400/10 border-slate-400/20 text-slate-300'

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      {/* Header */}
      <div className="px-6 pt-5 pb-0 border-b border-white/8 shrink-0">
        <div className="flex items-start justify-between mb-4">
          <div>
            <div className="text-[11px] text-slate-500 font-mono mb-0.5">{item.instrument_id} · {item.clearing_zone}</div>
            <div className="text-lg font-bold text-white">
              {item.account_display} <span className="text-slate-500">·</span> {item.payee_display}
            </div>
            <div className="flex items-center gap-2 mt-1.5">
              <span className={`text-[10px] font-semibold px-2 py-0.5 rounded border ${reasonColor}`}>
                {item.reason_label}
              </span>
              <span className="text-[10px] text-slate-500">{item.amount_range}</span>
              <span className="text-[10px] text-slate-600">·</span>
              <span className="text-[10px] text-slate-500">{item.amount_label}</span>
              {item.opa_rule && (
                <span className="text-[10px] text-sky-400/70 font-mono">OPA</span>
              )}
            </div>
          </div>
          <IETTimer deadline={item.iet_deadline} />
        </div>

        <div className="flex gap-1">
          {tabs.map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-4 py-2 text-xs font-medium rounded-t-lg capitalize transition-colors ${
                tab === t
                  ? 'bg-white/6 text-white border-t border-l border-r border-white/10'
                  : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">

        {tab === 'overview' && (
          <>
            {/* Alert */}
            <div className={`flex items-start gap-3 rounded-xl border px-4 py-3 ${reasonColor}`}>
              <span className="text-lg mt-0.5">⚠</span>
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

            {/* Score tiles */}
            <div className="grid grid-cols-3 gap-3">
              <div className="glass rounded-xl p-3 text-center">
                <div className="text-[10px] text-slate-500 uppercase tracking-wide mb-1">OCR</div>
                <div className="text-xl font-mono font-bold text-white">{Math.round(item.ocr_confidence * 100)}%</div>
                <div className="text-[10px] text-slate-600">confidence</div>
              </div>
              <div className="glass rounded-xl p-3 text-center">
                <div className="text-[10px] text-slate-500 uppercase tracking-wide mb-1">Signature</div>
                {item.sig_match_score != null ? (
                  <div className={`text-xl font-mono font-bold ${item.sig_match_score < 0.70 ? 'text-red-400' : item.sig_match_score < 0.85 ? 'text-amber-400' : 'text-emerald-400'}`}>
                    {Math.round(item.sig_match_score * 100)}%
                  </div>
                ) : (
                  <div className="text-xl font-mono font-bold text-purple-400">N/A</div>
                )}
                <div className="text-[10px] text-slate-600">{item.sig_match_score != null ? 'match score' : 'vault miss'}</div>
              </div>
              <div className="glass rounded-xl p-3 text-center">
                <div className="text-[10px] text-slate-500 uppercase tracking-wide mb-1">Fraud</div>
                <div className={`text-xl font-mono font-bold ${item.fraud_score >= 0.80 ? 'text-red-400' : 'text-amber-400'}`}>
                  {Math.round(item.fraud_score * 100)}%
                </div>
                <div className="text-[10px] text-slate-600">XGBoost score</div>
              </div>
            </div>

            {/* OCR fields */}
            <div className="glass rounded-xl p-4">
              <div className="text-[10px] text-slate-500 uppercase tracking-widest mb-3">OCR Extracted Fields · GOT-OCR2.0</div>
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
                    <span className="text-[10px] text-slate-600">{k}</span>
                    <span className={`text-xs font-mono mt-0.5 ${k === 'Alterations' && item.ocr_fields.alterations ? 'text-red-400 font-semibold' : 'text-slate-200'}`}>{v}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Signature panel */}
            <SigPanel item={item} />
          </>
        )}

        {tab === 'cheque' && (
          <ChequeMockImage fields={item.ocr_fields} alterations={item.ocr_fields.alterations} accountDisplay={item.account_display} />
        )}

        {tab === 'ai analysis' && (
          <div className="space-y-4">
            <div className="flex items-center gap-5">
              <FraudGauge score={item.fraud_score} />
              <div className="flex-1 glass rounded-xl p-4 space-y-2">
                <div className="text-[10px] text-slate-500 uppercase tracking-widest mb-2">Model Stack</div>
                {[
                  ['OCR', 'GOT-OCR2.0', item.ocr_confidence],
                  ['Vision', 'Qwen2-VL 72B', 0.94],
                  ['Signature', 'Siamese SNN', item.sig_match_score ?? 0],
                  ['Fraud', 'XGBoost', item.fraud_score],
                ].map(([label, model, score]) => (
                  <div key={label} className="flex items-center gap-3">
                    <span className="text-[10px] text-slate-500 w-16">{label}</span>
                    <div className="flex-1 h-1.5 bg-white/5 rounded-full overflow-hidden">
                      <div className="h-full bg-gold-400/60 rounded-full" style={{ width: `${score * 100}%` }} />
                    </div>
                    <span className="text-[10px] font-mono text-slate-400 w-8 text-right">{Math.round(score * 100)}%</span>
                    <span className="text-[10px] text-slate-600 w-28 truncate">{model}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="glass rounded-xl p-4">
              <ShapExplainer shapValues={item.shap_values} />
            </div>
          </div>
        )}
      </div>

      {/* Action footer */}
      <div className="shrink-0 border-t border-white/8 px-6 py-4 bg-navy-950/80 backdrop-blur space-y-3">
        <select
          value={returnReason}
          onChange={(e) => setReturnReason(e.target.value)}
          className="w-full bg-white/4 border border-white/8 rounded-xl px-3 py-2.5 text-xs text-slate-300 focus:outline-none focus:border-gold-400/40 appearance-none cursor-pointer"
        >
          <option value="">Select return reason (required to Return)</option>
          {RETURN_REASONS.map((r) => (
            <option key={r} value={r} className="bg-navy-900">{r}</option>
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
        <div className="text-center text-[10px] text-slate-600">
          Decision filed to NGCH immediately · Logged to Immudb · HSM-signed audit record
        </div>
      </div>
    </div>
  )
}

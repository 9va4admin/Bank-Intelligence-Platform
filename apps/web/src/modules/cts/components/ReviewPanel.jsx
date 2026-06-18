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
  'Drawer signature differs',
  'Words and figures differ',
]

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
    }, 800)
  }

  const tabs = ['overview', 'cheque', 'ai analysis']

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      {/* Panel header */}
      <div className="px-6 pt-5 pb-0 border-b border-white/8 shrink-0">
        <div className="flex items-start justify-between mb-4">
          <div>
            <div className="text-[11px] text-slate-500 font-mono">{item.instrument_id}</div>
            <div className="text-lg font-bold text-white mt-0.5">
              {item.account_display} &nbsp;·&nbsp; {item.payee_display}
            </div>
            <div className="text-sm text-slate-400 mt-0.5">{item.amount_range} · {item.clearing_zone}</div>
          </div>
          <IETTimer deadline={item.iet_deadline} />
        </div>

        {/* Tabs */}
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

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">

        {tab === 'overview' && (
          <>
            {/* Alert banner */}
            <div className="flex items-center gap-3 rounded-xl border border-amber-400/20 bg-amber-400/8 px-4 py-3">
              <span className="text-amber-400 text-lg">⚠</span>
              <div>
                <div className="text-xs font-semibold text-amber-400">Flagged: {item.reason_label}</div>
                <div className="text-[11px] text-slate-400 mt-0.5">AI routed to human review — decision required before IET deadline</div>
              </div>
            </div>

            {/* Stats row */}
            <div className="grid grid-cols-3 gap-3">
              <div className="glass rounded-xl p-3 text-center">
                <div className="text-[10px] text-slate-500 uppercase tracking-wide mb-1">OCR</div>
                <div className="text-lg font-mono font-bold text-white">{Math.round(item.ocr_confidence * 100)}%</div>
                <div className="text-[10px] text-slate-600">confidence</div>
              </div>
              <div className="glass rounded-xl p-3 text-center">
                <div className="text-[10px] text-slate-500 uppercase tracking-wide mb-1">Signature</div>
                <div className={`text-lg font-mono font-bold ${item.sig_match_score < 0.70 ? 'text-red-400' : 'text-amber-400'}`}>
                  {Math.round(item.sig_match_score * 100)}%
                </div>
                <div className="text-[10px] text-slate-600">match score</div>
              </div>
              <div className="glass rounded-xl p-3 text-center">
                <div className="text-[10px] text-slate-500 uppercase tracking-wide mb-1">Amount</div>
                <div className="text-sm font-bold text-white">{item.amount_range}</div>
                <div className="text-[10px] text-slate-600">{item.amount_label}</div>
              </div>
            </div>

            {/* OCR Fields */}
            <div className="glass rounded-xl p-4">
              <div className="text-[10px] text-slate-500 uppercase tracking-widest mb-3">OCR Extracted Fields</div>
              <div className="grid grid-cols-2 gap-2">
                {Object.entries(item.ocr_fields).map(([k, v]) => (
                  k !== 'alterations' && (
                    <div key={k} className="flex flex-col">
                      <span className="text-[10px] text-slate-600 capitalize">{k.replace('_', ' ')}</span>
                      <span className="text-xs text-slate-200 font-mono">{v}</span>
                    </div>
                  )
                ))}
                <div className="flex flex-col">
                  <span className="text-[10px] text-slate-600">Alterations</span>
                  <span className={`text-xs font-semibold ${item.ocr_fields.alterations ? 'text-red-400' : 'text-emerald-400'}`}>
                    {item.ocr_fields.alterations ? '⚠ Detected' : '✓ None detected'}
                  </span>
                </div>
              </div>
            </div>
          </>
        )}

        {tab === 'cheque' && (
          <ChequeMockImage fields={item.ocr_fields} alterations={item.ocr_fields.alterations} />
        )}

        {tab === 'ai analysis' && (
          <div className="space-y-5">
            <div className="flex items-center gap-6">
              <FraudGauge score={item.fraud_score} />
              <div className="flex-1 glass rounded-xl p-4 text-xs text-slate-400 space-y-2">
                <div className="text-[10px] text-slate-500 uppercase tracking-widest">Model Info</div>
                <div><span className="text-slate-600">OCR: </span>GOT-OCR2.0</div>
                <div><span className="text-slate-600">Vision: </span>Qwen2-VL 72B</div>
                <div><span className="text-slate-600">Fraud: </span>XGBoost + SHAP</div>
                <div><span className="text-slate-600">Sig: </span>PyTorch Siamese SNN</div>
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
        <div>
          <select
            value={returnReason}
            onChange={(e) => setReturnReason(e.target.value)}
            className="w-full bg-white/4 border border-white/8 rounded-xl px-3 py-2.5 text-xs text-slate-300 focus:outline-none focus:border-gold-400/40 appearance-none"
          >
            <option value="">Select return reason (required to Return)</option>
            {RETURN_REASONS.map((r) => (
              <option key={r} value={r} className="bg-navy-900">{r}</option>
            ))}
          </select>
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => handleAction('RETURN')}
            disabled={!returnReason || confirming}
            className="flex-1 py-3 rounded-xl border border-red-500/40 bg-red-500/10 text-red-400 text-sm font-semibold hover:bg-red-500/20 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {confirming === 'RETURN' ? 'Filing Return…' : '✕  Return Cheque'}
          </button>
          <button
            onClick={() => handleAction('CONFIRM')}
            disabled={confirming}
            className="flex-1 py-3 rounded-xl bg-emerald-500/20 border border-emerald-500/40 text-emerald-400 text-sm font-semibold hover:bg-emerald-500/30 transition-all disabled:opacity-40"
          >
            {confirming === 'CONFIRM' ? 'Filing Confirm…' : '✓  Confirm Cheque'}
          </button>
        </div>
        <div className="text-center text-[10px] text-slate-600">
          Decision will be filed to NGCH immediately · Logged to Immudb audit trail
        </div>
      </div>
    </div>
  )
}

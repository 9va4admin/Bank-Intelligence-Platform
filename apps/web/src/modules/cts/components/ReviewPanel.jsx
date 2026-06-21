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

const REASON_COLORS = {
  SIGNATURE_LOW_CONFIDENCE: 'bg-amber-100 border-amber-400 text-amber-700 dark:bg-amber-400/10 dark:border-amber-400/30 dark:text-amber-300',
  FRAUD_SCORE_HIGH:         'bg-red-100 border-red-400 text-red-700 dark:bg-red-400/10 dark:border-red-400/30 dark:text-red-300',
  OCR_LOW_CONFIDENCE:       'bg-orange-100 border-orange-400 text-orange-700 dark:bg-orange-400/10 dark:border-orange-400/30 dark:text-orange-300',
  VAULT_MISS:               'bg-purple-100 border-purple-400 text-purple-700 dark:bg-purple-400/10 dark:border-purple-400/30 dark:text-purple-300',
  HIGH_VALUE_DUAL_APPROVAL: 'bg-sky-100 border-sky-400 text-sky-700 dark:bg-sky-400/10 dark:border-sky-400/30 dark:text-sky-300'
}


function SigPanel({ item }) {
  const muted  = 'text-slate-500 dark:text-slate-400'
  const note   = 'text-slate-500 dark:text-slate-500'
  const noteBg = 'bg-slate-50 dark:bg-white/3'
  const barBg  = 'bg-slate-100 dark:bg-white/5'
  const tick   = 'text-slate-400 dark:text-slate-600'

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
    <div className={`rounded-xl border px-4 py-3 ${borderColor}`}>
      <div className="flex items-center gap-4">
        {/* Score */}
        <div className="shrink-0 flex items-baseline gap-1">
          <span className={`text-2xl font-bold font-mono ${color}`}>{matchPct}%</span>
          <span className="text-[10px] text-slate-500">match</span>
        </div>
        {/* Bar + labels */}
        <div className="flex-1 space-y-1">
          <div className={`h-1.5 ${barBg} rounded-full overflow-hidden`}>
            <div className={`h-full rounded-full transition-all ${matchPct >= 85 ? 'bg-emerald-400' : matchPct >= 70 ? 'bg-amber-400' : 'bg-red-400'}`}
              style={{ width: `${matchPct}%` }} />
          </div>
          <div className={`flex justify-between text-[10px] ${tick}`}>
            <span>0%</span>
            <span>threshold: 85%</span>
            <span>100%</span>
          </div>
        </div>
        {/* Meta */}
        <div className="shrink-0 text-right">
          <div className="text-[10px] text-slate-500 uppercase tracking-widest">Siamese SNN</div>
          <div className="text-[10px] text-slate-500">{item.sig_specimen_label}</div>
        </div>
      </div>
    </div>
  )
}

export default function ReviewPanel({ item, onDecision }) {
  const [tab, setTab] = useState('overview')
  const [returnReason, setReturnReason] = useState('')
  const [confirming, setConfirming] = useState(null)

  const th = {
    border:   'border-slate-200 dark:border-white/8',
    id:       'text-slate-400 dark:text-slate-500',
    heading:  'text-slate-900 dark:text-white',
    dot:      'text-slate-400 dark:text-slate-500',
    meta:     'text-slate-400 dark:text-slate-500',
    tabActive: 'bg-slate-100 text-slate-900 border-t border-l border-r border-slate-200 dark:bg-white/6 dark:text-white dark:border-white/10',
    tabIdle:  'text-slate-400 hover:text-slate-700 dark:text-slate-500 dark:hover:text-slate-300',
    glass:    'bg-slate-50 border border-slate-200 dark:bg-white/5 dark:border dark:border-white/8',
    lbl:      'text-slate-400 dark:text-slate-500',
    val:      'text-slate-800 dark:text-slate-200',
    barBg:    'bg-slate-100 dark:bg-white/5',
    foot:     'bg-white dark:bg-navy-950/80',
    sel:      'bg-white border-slate-300 text-slate-700 focus:border-amber-400 dark:bg-white/4 dark:border-white/8 dark:text-slate-300 dark:focus:border-gold-400/40',
    selOpt:   'bg-white dark:bg-navy-900',
    footNote: 'text-slate-400 dark:text-slate-600',
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

  const tabs = ['overview', 'cheque', 'ai analysis', 'passport']
  const reasonColor = REASON_COLORS[item.reason] || ('bg-slate-100 border-slate-300 text-slate-600 dark:bg-slate-400/10 dark:border-slate-400/20 dark:text-slate-300')

  // D1: Trust Score strip calculations
  const totalIetMs = new Date(item.iet_deadline) - new Date(item.received_at)
  const remainingMs = new Date(item.iet_deadline) - Date.now()
  const ietPct = Math.max(0, Math.min(1, remainingMs / totalIetMs))
  const minsLeft = Math.max(0, Math.round(remainingMs / 60000))

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      {/* Sub-member context banner */}
      {item.principal_tag === 'SUB_MEMBER' && (
        <div className={`px-6 py-2 flex items-center gap-2 border-b text-[11px] font-medium ${'bg-amber-50 border-amber-300 text-amber-700 dark:bg-amber-400/5 dark:border-amber-400/20 dark:text-amber-300'}`}>
          <span className="font-semibold">SUB-MEMBER CHEQUE</span>
          <span className="opacity-60">·</span>
          <span>{item.sub_member_name}</span>
          <span className="opacity-60">·</span>
          <span className="font-mono opacity-70">{item.sub_member_id}</span>
          <span className="ml-auto opacity-60">Sponsor bank notified on return</span>
        </div>
      )}
      {/* Header — single compact row */}
      <div className={`px-6 pt-2 pb-0 border-b ${th.border} shrink-0`}>
        {/* Single row: cheque no (hover → image) · zone · account · payee · badges · IET */}
        <div className="flex items-center gap-2 mb-2 flex-wrap">
          {/* Cheque number — hover shows cheque image */}
          <div className="relative" onMouseEnter={showCheque} onMouseLeave={hideCheque}>
            <span className={`text-[11px] font-mono cursor-default underline decoration-dotted ${'text-amber-600 decoration-amber-400/60 dark:text-gold-400 dark:decoration-gold-400/40'}`}>
              {item.instrument_id}
            </span>
            {chequeHover && (
              <div
                className={`absolute left-0 top-6 z-50 w-[480px] rounded-xl shadow-2xl border p-3 ${'bg-white border-slate-200 dark:bg-navy-900 dark:border-white/10'}`}
                onMouseEnter={showCheque} onMouseLeave={hideCheque}
              >
                <div className={`text-[9px] ${th.lbl} uppercase tracking-widest mb-2`}>Cheque Image — compare with extracted fields</div>
                <ChequeMockImage fields={item.ocr_fields} alterations={item.ocr_fields.alterations} />
              </div>
            )}
          </div>
          <span className={`text-[10px] ${th.lbl}`}>·</span>
          <span className={`text-[10px] font-mono ${th.id}`}>{item.clearing_zone}</span>
          <span className={`text-[10px] ${th.lbl}`}>·</span>
          <span className={`text-sm font-bold ${th.heading}`}>
            {item.account_display}
          </span>
          <span className={`text-[10px] ${th.dot}`}>·</span>
          <span className={`text-sm font-bold ${th.heading}`}>{item.payee_display}</span>
          <span className={`text-[10px] font-semibold px-2 py-0.5 rounded border ${reasonColor}`}>
            {item.reason_label}
          </span>
          <span className={`text-[10px] ${th.meta}`}>{item.amount_range}</span>
          <span className={`text-[10px] ${th.lbl}`}>·</span>
          <span className={`text-[10px] ${th.meta}`}>{item.amount_label}</span>
          {item.opa_rule && <span className="text-[10px] text-sky-400/70 font-mono">OPA</span>}
          <div className="ml-auto">
            <IETTimer deadline={item.iet_deadline} compact bright />
          </div>
        </div>

        {/* D1: Trust Score strip */}
        <div className="flex items-center gap-3 py-2">
          {[
            {
              label: 'OCR',
              pct: item.ocr_confidence,
              display: `${Math.round(item.ocr_confidence * 100)}%`,
              bar: item.ocr_confidence >= 0.92 ? 'bg-emerald-500' : item.ocr_confidence >= 0.80 ? 'bg-amber-400' : 'bg-red-400',
            },
            {
              label: 'Sig',
              pct: item.sig_match_score ?? 0,
              display: item.sig_match_score != null ? `${Math.round(item.sig_match_score * 100)}%` : 'N/A',
              bar: item.sig_match_score == null ? 'bg-purple-400' : item.sig_match_score >= 0.85 ? 'bg-emerald-500' : item.sig_match_score >= 0.70 ? 'bg-amber-400' : 'bg-red-400',
            },
            {
              label: 'Fraud',
              pct: item.fraud_score,
              display: `${Math.round(item.fraud_score * 100)}%`,
              bar: item.fraud_score >= 0.80 ? 'bg-red-400' : item.fraud_score >= 0.72 ? 'bg-amber-400' : 'bg-emerald-500',
              invert: true,
            },
            {
              label: 'IET',
              pct: ietPct,
              display: `${minsLeft}m`,
              bar: ietPct <= 0.20 ? 'bg-red-400 animate-pulse' : ietPct <= 0.40 ? 'bg-amber-400' : 'bg-sky-400',
            },
          ].map(({ label, pct, display, bar, invert }) => (
            <div key={label} className="flex items-center gap-1.5 min-w-0">
              <span className={`text-[9px] font-semibold uppercase tracking-wider ${th.lbl} w-6 shrink-0`}>{label}</span>
              <div className={`w-16 h-1 ${th.barBg} rounded-full overflow-hidden`}>
                <div className={`h-full rounded-full ${bar}`} style={{ width: `${(invert ? pct : pct) * 100}%` }} />
              </div>
              <span className={`text-[10px] font-mono ${th.lbl}`}>{display}</span>
            </div>
          ))}
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
                  <div className={`text-3xl font-mono font-bold ${color}`}>{val}</div>
                  <div className={`text-[10px] ${th.lbl}`}>{sub}</div>
                </div>
              ))}
            </div>

            {/* OCR fields */}
            <div className={`rounded-xl p-4 ${th.glass} relative`}>
              <div className="mb-3">
                <div className={`text-[10px] ${th.lbl} uppercase tracking-widest`}>OCR Extracted Fields · GOT-OCR2.0</div>
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

            <SigPanel item={item} />
          </>
        )}

        {tab === 'cheque' && (
          <ChequeMockImage fields={item.ocr_fields} alterations={item.ocr_fields.alterations} accountDisplay={item.account_display} />
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
              <ShapExplainer shapValues={item.shap_values} />
            </div>
          </div>
        )}

        {/* D2: Cheque Digital Passport */}
        {tab === 'passport' && (() => {
          const base = new Date(item.received_at).getTime()
          const steps = [
            { label: 'Received from NGCH', ts: base,          icon: '📥', note: `Zone: ${item.clearing_zone} · ${item.cbs_type}`, status: 'done' },
            { label: 'MICR Line Parsed',   ts: base + 2400,   icon: '🔢', note: `GOT-OCR2.0 · MICR: ${item.ocr_fields.micr}`, status: 'done' },
            { label: 'OCR Extraction',     ts: base + 46000,  icon: '📄', note: `Confidence: ${Math.round(item.ocr_confidence * 100)}% · ${item.ocr_fields.alterations ? '⚠ Alteration flag' : '✓ No alteration'}`, status: item.ocr_confidence < 0.88 ? 'warn' : 'done' },
            { label: 'Vision Analysis',    ts: base + 89000,  icon: '🔍', note: 'Qwen2-VL 72B · Tamper risk: low', status: 'done' },
            { label: 'Signature Check',    ts: base + 134000, icon: '✍', note: item.sig_match_score != null ? `Siamese SNN · ${Math.round(item.sig_match_score * 100)}% match · ${item.sig_specimen_label}` : 'Vault miss — no specimen on file', status: item.sig_match_score == null ? 'warn' : item.sig_match_score < 0.80 ? 'warn' : 'done' },
            { label: 'Fraud Scored',       ts: base + 178000, icon: '🛡', note: `XGBoost · Score: ${Math.round(item.fraud_score * 100)}% · ${item.shap_values[0].feature}: top SHAP driver`, status: item.fraud_score >= 0.80 ? 'risk' : 'warn' },
            { label: 'Routed to Review',   ts: base + 241000, icon: '👤', note: `Reason: ${item.reason_label}`, status: 'review' },
            { label: 'Awaiting Decision',  ts: Date.now(),    icon: '⏳', note: `IET deadline in ${minsLeft} min`, status: 'pending' },
          ]
          const stC = { done: 'bg-emerald-500', warn: 'bg-amber-400', risk: 'bg-red-400', review: 'bg-sky-400', pending: 'bg-slate-400 animate-pulse' }
          const stT = { done: 'text-emerald-400', warn: 'text-amber-400', risk: 'text-red-400', review: 'text-sky-400', pending: 'text-slate-400' }
          return (
            <div className="space-y-3">
              <div className={`rounded-xl p-4 ${th.glass}`}>
                <div className={`text-[10px] ${th.lbl} uppercase tracking-widest mb-4`}>Processing Timeline · {item.instrument_id}</div>
                <div className="relative">
                  <div className={`absolute left-3 top-3 bottom-3 w-px ${th.barBg}`} />
                  <div className="space-y-4">
                    {steps.map((s, i) => (
                      <div key={i} className="flex items-start gap-3 relative">
                        <div className={`shrink-0 w-7 h-7 rounded-full flex items-center justify-center z-10 ${stC[s.status]} text-white text-[11px]`}>
                          {s.icon}
                        </div>
                        <div className="flex-1 min-w-0 pt-0.5">
                          <div className="flex items-baseline gap-2 flex-wrap">
                            <span className={`text-xs font-semibold ${th.heading}`}>{s.label}</span>
                            <span className={`text-[9px] font-mono ${th.lbl}`}>
                              {new Date(s.ts).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                            </span>
                            {i > 0 && <span className={`text-[9px] ${th.lbl}`}>+{((s.ts - base) / 1000).toFixed(0)}s</span>}
                          </div>
                          <div className={`text-[11px] ${th.lbl} mt-0.5`}>{s.note}</div>
                        </div>
                        <span className={`text-[9px] font-semibold uppercase ${stT[s.status]} shrink-0`}>{s.status}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
              <div className={`rounded-xl p-4 ${th.glass}`}>
                <div className={`text-[10px] ${th.lbl} uppercase tracking-widest mb-3`}>Instrument Metadata</div>
                <div className="grid grid-cols-2 gap-x-6 gap-y-2">
                  {[
                    ['Instrument ID', item.instrument_id],
                    ['Clearing Zone', item.clearing_zone],
                    ['CBS Type', item.cbs_type],
                    ['Received', new Date(item.received_at).toLocaleTimeString('en-IN')],
                    ['IET Deadline', new Date(item.iet_deadline).toLocaleTimeString('en-IN')],
                    ['Amount Range', item.amount_range],
                    ...(item.principal_tag === 'SUB_MEMBER' ? [['Sub-Member', item.sub_member_name], ['SMB ID', item.sub_member_id]] : []),
                    ...(item.opa_rule ? [['OPA Rule', item.opa_rule]] : []),
                  ].map(([k, v]) => (
                    <div key={k} className="flex flex-col">
                      <span className={`text-[10px] ${th.lbl}`}>{k}</span>
                      <span className={`text-xs font-mono mt-0.5 ${th.val} truncate`}>{v}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )
        })()}
      </div>

      {/* Action footer — single row: dropdown + two buttons */}
      <div className={`shrink-0 border-t ${th.border} px-6 py-3 ${th.foot} backdrop-blur`}>
        <div className="flex items-center gap-2">
          <select
            value={returnReason}
            onChange={(e) => setReturnReason(e.target.value)}
            className={`flex-1 border rounded-xl px-3 py-2 text-xs focus:outline-none appearance-none cursor-pointer ${th.sel}`}
          >
            <option value="" className={th.selOpt}>Select return reason (required to Return)</option>
            {RETURN_REASONS.map((r) => (
              <option key={r} value={r} className={th.selOpt}>{r}</option>
            ))}
          </select>
          <button
            onClick={() => handleAction('RETURN')}
            disabled={!returnReason || !!confirming}
            className="shrink-0 px-5 py-2 rounded-xl border border-red-500/40 bg-red-500/10 text-red-400 text-xs font-semibold hover:bg-red-500/20 transition-all disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
          >
            {confirming === 'RETURN' ? 'Filing…' : '✕ Return'}
          </button>
          <button
            onClick={() => handleAction('CONFIRM')}
            disabled={!!confirming}
            className="shrink-0 px-5 py-2 rounded-xl bg-emerald-500/20 border border-emerald-500/40 text-emerald-400 text-xs font-semibold hover:bg-emerald-500/30 transition-all disabled:opacity-40 whitespace-nowrap"
          >
            {confirming === 'CONFIRM' ? 'Filing…' : '✓ Confirm'}
          </button>
        </div>
      </div>
    </div>
  )
}

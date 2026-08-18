/**
 * CTSInwardReviewQueue — Human review working queue for inward instruments.
 *
 * Route: /cts/inward/review-queue  (permission: cts:view_queue)
 * Tier filter: All / Standard / High Value / Very High
 * IET countdown live-ticks every second, turns red ≤ 30 min
 *
 * Claim — locks instrument to this reviewer (demo: local state)
 * Hold  — pauses for branch consultation (IET clock never pauses)
 * Confirm (PAY) — STP confirm
 * Return — return to drawer with CTS reason code
 *
 * Click any card to expand: cheque image + full AI analysis panel
 */
import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'
import { MockChequeFront } from '../components/MockCheque'

// ─── Mock data ────────────────────────────────────────────────────────────────

const TIERS = ['all', 'standard', 'high_value', 'very_high']
const TIER_LABEL = { all: 'All', standard: 'Standard', high_value: 'High Value', very_high: 'Very High' }

const _T = (offsetMins) => Math.floor(Date.now() / 1000) + offsetMins * 60

const MOCK_REVIEW_ITEMS = [
  {
    instrument_id: 'INS-20260812-00142', queue_tier: 'high_value', status: 'PENDING',
    claimed_by: null, claimed_by_me: false,
    iet_deadline: _T(38),
    account_display: '0531010123456789',
    amount_display: '₹2,50,000', amount_words: 'Two Lakh Fifty Thousand Only',
    payee_display: 'Mahesh Kumar Sharma', payee_name: 'Mahesh Kumar Sharma',
    drawer_name: 'Rajan Industries Pvt. Ltd.',
    cheque_number: '000142', micr_code: '400026001',
    cheque_date: '10-Aug-2026', branch_ifsc: 'UBIN0530001',
    branch_name: 'Fort Branch, Mumbai',
    drawee_bank: 'Union Bank of India', drawee_branch: 'Fort Branch, Mumbai',
    date: '10-Aug-2026', payee: 'Mahesh Kumar Sharma',
    amount_figures: '2,50,000', micr: '400026001',
    risk_flags: ['HIGH_VALUE', 'ALTERATION_SUSPECTED'],
    ai_summary: 'Ink inconsistency detected in payee name field. Possible overwriting between "Kumar" and "Sharma". Confidence 0.71. Manual verification recommended.',
    ai: {
      ocr_confidence: 0.71, ocr_model: 'GOT-OCR2.0',
      signature_score: 0.84, signature_model: 'Siamese-SigNet',
      fraud_score: 0.61, fraud_model: 'XGBoost + LLM',
      alteration_risk: 0.68,
      shap: [
        { feature: 'Ink inconsistency in payee field', contribution: +0.18 },
        { feature: 'High value (₹2.5L)', contribution: +0.12 },
        { feature: 'Signature match 84%', contribution: -0.06 },
        { feature: 'Account active, no stop payment', contribution: -0.09 },
        { feature: 'Cheque printed > 60 days ago', contribution: +0.04 },
      ],
    },
  },
  {
    instrument_id: 'INS-20260812-00143', queue_tier: 'standard', status: 'PENDING',
    claimed_by: null, claimed_by_me: false,
    iet_deadline: _T(102),
    account_display: '0532020987654321',
    amount_display: '₹45,000', amount_words: 'Forty Five Thousand Only',
    payee_display: 'Priya Nair', payee_name: 'Priya Nair',
    drawer_name: 'Suresh Menon',
    cheque_number: '000143', micr_code: '400026001',
    cheque_date: '11-Aug-2026', branch_ifsc: 'UBIN0530001',
    branch_name: 'Fort Branch, Mumbai',
    drawee_bank: 'Union Bank of India', drawee_branch: 'Fort Branch, Mumbai',
    date: '11-Aug-2026', payee: 'Priya Nair',
    amount_figures: '45,000', micr: '400026001',
    risk_flags: [],
    ai_summary: null,
    ai: {
      ocr_confidence: 0.97, ocr_model: 'GOT-OCR2.0',
      signature_score: 0.93, signature_model: 'Siamese-SigNet',
      fraud_score: 0.08, fraud_model: 'XGBoost + LLM',
      alteration_risk: 0.04,
      shap: [
        { feature: 'Signature match 93%', contribution: -0.14 },
        { feature: 'Account in good standing', contribution: -0.10 },
        { feature: 'Standard value range', contribution: -0.05 },
        { feature: 'OCR confidence 97%', contribution: -0.08 },
      ],
    },
  },
  {
    instrument_id: 'INS-20260812-00144', queue_tier: 'very_high', status: 'PENDING',
    claimed_by: null, claimed_by_me: false,
    iet_deadline: _T(22),
    account_display: '0533030112233445',
    amount_display: '₹1,25,00,000', amount_words: 'One Crore Twenty Five Lakh Only',
    payee_display: 'Apex Infrastructure Ltd.', payee_name: 'Apex Infrastructure Ltd.',
    drawer_name: 'Apex Infrastructure Ltd.',
    cheque_number: '000144', micr_code: '110026001',
    cheque_date: '08-Aug-2026', branch_ifsc: 'UBIN0530002',
    branch_name: 'Connaught Place Branch, New Delhi',
    drawee_bank: 'Union Bank of India', drawee_branch: 'Connaught Place Branch, Delhi',
    date: '08-Aug-2026', payee: 'Apex Infrastructure Ltd.',
    amount_figures: '1,25,00,000', micr: '110026001',
    risk_flags: ['VERY_HIGH_VALUE', 'STOP_PAYMENT'],
    ai_summary: 'Stop payment instruction registered on this account. Amount exceeds ₹1 Cr threshold. Immediate ops_manager escalation required.',
    ai: {
      ocr_confidence: 0.96, ocr_model: 'GOT-OCR2.0',
      signature_score: 0.79, signature_model: 'Siamese-SigNet',
      fraud_score: 0.88, fraud_model: 'XGBoost + LLM',
      alteration_risk: 0.12,
      shap: [
        { feature: 'Stop payment instruction active', contribution: +0.35 },
        { feature: 'Very high value (>₹1 Cr)', contribution: +0.22 },
        { feature: 'Signature below 80% threshold', contribution: +0.10 },
        { feature: 'Self-drawn cheque (drawer = payee)', contribution: +0.08 },
        { feature: 'Account active', contribution: -0.05 },
      ],
    },
  },
  {
    instrument_id: 'INS-20260812-00145', queue_tier: 'standard', status: 'PENDING',
    claimed_by: null, claimed_by_me: false,
    iet_deadline: _T(145),
    account_display: '0534040556677889',
    amount_display: '₹12,500', amount_words: 'Twelve Thousand Five Hundred Only',
    payee_display: 'Kavitha Reddy', payee_name: 'Kavitha Reddy',
    drawer_name: 'Srinivas Reddy',
    cheque_number: '000145', micr_code: '500026001',
    cheque_date: '12-Aug-2026', branch_ifsc: 'UBIN0530006',
    branch_name: 'Abids Branch, Hyderabad',
    drawee_bank: 'Union Bank of India', drawee_branch: 'Abids Branch, Hyderabad',
    date: '12-Aug-2026', payee: 'Kavitha Reddy',
    amount_figures: '12,500', micr: '500026001',
    risk_flags: [],
    ai_summary: null,
    ai: {
      ocr_confidence: 0.98, ocr_model: 'GOT-OCR2.0',
      signature_score: 0.96, signature_model: 'Siamese-SigNet',
      fraud_score: 0.05, fraud_model: 'XGBoost + LLM',
      alteration_risk: 0.02,
      shap: [
        { feature: 'Signature match 96%', contribution: -0.18 },
        { feature: 'Low value, low risk', contribution: -0.12 },
        { feature: 'No adverse account history', contribution: -0.09 },
      ],
    },
  },
  {
    instrument_id: 'INS-20260812-00146', queue_tier: 'high_value', status: 'PENDING',
    claimed_by: null, claimed_by_me: false,
    iet_deadline: _T(55),
    account_display: '0535050998877661',
    amount_display: '₹8,75,000', amount_words: 'Eight Lakh Seventy Five Thousand Only',
    payee_display: 'Anand Exports Pvt. Ltd.', payee_name: 'Anand Exports Pvt. Ltd.',
    drawer_name: 'Global Trade Finance Co.',
    cheque_number: '000146', micr_code: '560026001',
    cheque_date: '09-Aug-2026', branch_ifsc: 'UBIN0530005',
    branch_name: 'MG Road Branch, Bengaluru',
    drawee_bank: 'Union Bank of India', drawee_branch: 'MG Road Branch, Bengaluru',
    date: '09-Aug-2026', payee: 'Anand Exports Pvt. Ltd.',
    amount_figures: '8,75,000', micr: '560026001',
    risk_flags: ['DORMANT_ACCOUNT'],
    ai_summary: 'Drawee account dormant for 14 months. Last activity Feb 2025. High-value instrument on dormant account requires manual clearance.',
    ai: {
      ocr_confidence: 0.94, ocr_model: 'GOT-OCR2.0',
      signature_score: 0.88, signature_model: 'Siamese-SigNet',
      fraud_score: 0.44, fraud_model: 'XGBoost + LLM',
      alteration_risk: 0.09,
      shap: [
        { feature: 'Account dormant 14 months', contribution: +0.28 },
        { feature: 'High value (₹8.75L)', contribution: +0.14 },
        { feature: 'Signature match 88%', contribution: -0.04 },
        { feature: 'No stop payment', contribution: -0.07 },
        { feature: 'Payee is a registered company', contribution: -0.05 },
      ],
    },
  },
]

const RETURN_REASONS = [
  { code: 'FUNDS_INSUFFICIENT', label: 'Insufficient Funds' },
  { code: 'ACCOUNT_CLOSED',    label: 'Account Closed' },
  { code: 'STOP_PAYMENT',      label: 'Stop Payment Issued' },
  { code: 'SIGNATURE_DIFFER',  label: 'Signature Mismatch' },
  { code: 'ALTERATION',        label: 'Alteration Detected' },
  { code: 'ACCOUNT_FROZEN',    label: 'Account Frozen' },
  { code: 'STALE_CHEQUE',      label: 'Stale Cheque (> 3 months)' },
  { code: 'AMOUNT_MISMATCH',   label: 'Amount in Words / Figures Mismatch' },
  { code: 'DORMANT_ACCOUNT',   label: 'Dormant Account' },
]

// ─── IET countdown ────────────────────────────────────────────────────────────

const _now = () => Date.now() / 1000

function useTickingCountdowns(items) {
  const [remaining, setRemaining] = useState({})
  const ref = useRef(items)
  ref.current = items
  useEffect(() => {
    function recompute() {
      const map = {}
      for (const it of ref.current) map[it.instrument_id] = Math.max(0, it.iet_deadline - _now())
      setRemaining(map)
    }
    recompute()
    const t = setInterval(recompute, 1000)
    return () => clearInterval(t)
  }, [])
  return remaining
}

function fmtCountdown(secs) {
  if (secs <= 0) return 'EXPIRED'
  const h = Math.floor(secs / 3600), m = Math.floor((secs % 3600) / 60), s = Math.floor(secs % 60)
  if (h > 0) return `${h}h ${m}m`
  return `${m}m ${String(s).padStart(2, '0')}s`
}

function ietColor(secs, isDark) {
  if (secs <= 0)        return 'text-red-500 font-bold animate-pulse'
  if (secs <= 30 * 60) return 'text-red-400 font-semibold'
  if (secs <= 60 * 60) return 'text-amber-400'
  return isDark ? 'text-emerald-400' : 'text-emerald-600'
}

// ─── Tier / status badges ─────────────────────────────────────────────────────

const TIER_D = {
  standard:   'bg-slate-700/60 text-slate-300 border-slate-600/40',
  high_value: 'bg-amber-900/50 text-amber-300 border-amber-700/40',
  very_high:  'bg-red-900/50   text-red-300   border-red-700/40',
}
const TIER_L = {
  standard:   'bg-slate-100 text-slate-600 border-slate-300',
  high_value: 'bg-amber-50  text-amber-700 border-amber-200',
  very_high:  'bg-red-50    text-red-700   border-red-200',
}

function TierBadge({ tier, isDark }) {
  return (
    <span className={`text-xs px-2 py-0.5 rounded border font-medium ${isDark ? TIER_D[tier] : TIER_L[tier]}`}>
      {TIER_LABEL[tier] ?? tier}
    </span>
  )
}

function StatusBadge({ status, claimedBy, isDark }) {
  if (status === 'CLAIMED') return (
    <span className={`text-xs px-2 py-0.5 rounded border font-medium ${isDark ? 'bg-violet-900/40 text-violet-300 border-violet-700/40' : 'bg-violet-50 text-violet-700 border-violet-200'}`}>
      Claimed · {(claimedBy ?? '').split('@')[0]}
    </span>
  )
  if (status === 'CONFIRMED') return (
    <span className={`text-xs px-2 py-0.5 rounded border font-medium ${isDark ? 'bg-emerald-900/40 text-emerald-300 border-emerald-700/40' : 'bg-emerald-50 text-emerald-700 border-emerald-200'}`}>
      Confirmed (PAY)
    </span>
  )
  if (status === 'RETURNED') return (
    <span className={`text-xs px-2 py-0.5 rounded border font-medium ${isDark ? 'bg-red-900/40 text-red-300 border-red-700/40' : 'bg-red-50 text-red-700 border-red-200'}`}>
      Returned
    </span>
  )
  if (status === 'ON_HOLD') return (
    <span className={`text-xs px-2 py-0.5 rounded border font-medium ${isDark ? 'bg-amber-900/40 text-amber-300 border-amber-700/40' : 'bg-amber-50 text-amber-700 border-amber-200'}`}>
      On Hold
    </span>
  )
  return (
    <span className={`text-xs px-2 py-0.5 rounded border font-medium ${isDark ? 'bg-blue-900/40 text-blue-300 border-blue-700/40' : 'bg-blue-50 text-blue-700 border-blue-200'}`}>
      Pending
    </span>
  )
}

// ─── AI score bar ─────────────────────────────────────────────────────────────

function ScoreBar({ label, value, good = 'high', isDark }) {
  const pct = Math.round(value * 100)
  const isGood = good === 'high' ? pct >= 90 : pct <= 20
  const isMid  = good === 'high' ? pct >= 70 && pct < 90 : pct > 20 && pct <= 50
  const color  = isGood ? 'bg-emerald-500' : isMid ? 'bg-amber-500' : 'bg-red-500'
  return (
    <div>
      <div className="flex justify-between text-[10px] mb-1">
        <span className={isDark ? 'text-slate-400' : 'text-slate-500'}>{label}</span>
        <span className={`font-mono font-semibold ${isGood ? (isDark?'text-emerald-400':'text-emerald-600') : isMid ? 'text-amber-500' : 'text-red-500'}`}>{pct}%</span>
      </div>
      <div className={`h-1.5 rounded-full overflow-hidden ${isDark ? 'bg-white/8' : 'bg-slate-200'}`}>
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

// ─── SHAP row ─────────────────────────────────────────────────────────────────

function ShapRow({ feature, contribution, isDark }) {
  const pct = Math.abs(contribution) * 100 / 0.40  // scale: max ±0.40 = full bar
  const pos = contribution > 0
  return (
    <div className="flex items-center gap-2 text-[11px]">
      <div className="flex-1 text-right">
        {pos ? '' : <span className={isDark ? 'text-slate-300' : 'text-slate-700'}>{feature}</span>}
        {!pos ? '' : null}
      </div>
      <div className="relative flex items-center" style={{ width: 120 }}>
        {pos ? (
          <div className="absolute left-1/2 h-3 rounded-r bg-red-400/70 transition-all" style={{ width: `${(pct/2).toFixed(1)}%`, maxWidth: 58 }} />
        ) : (
          <div className="absolute right-1/2 h-3 rounded-l bg-emerald-400/70 transition-all" style={{ width: `${(pct/2).toFixed(1)}%`, maxWidth: 58 }} />
        )}
        <div className={`absolute inset-x-0 top-1/2 h-px ${isDark ? 'bg-white/15' : 'bg-slate-300'}`} />
      </div>
      <div className="flex-1">
        {pos ? <span className={isDark ? 'text-slate-300' : 'text-slate-700'}>{feature}</span> : ''}
      </div>
    </div>
  )
}

// ─── Expanded AI + Cheque panel ───────────────────────────────────────────────

function ExpandedPanel({ item, isDark }) {
  const ai = item.ai ?? {}
  const th = {
    card:   isDark ? 'bg-navy-950/80 border-white/6' : 'bg-slate-50 border-slate-200',
    label:  isDark ? 'text-slate-500 text-[9px] uppercase tracking-widest' : 'text-slate-400 text-[9px] uppercase tracking-widest',
    val:    isDark ? 'text-slate-200 text-xs' : 'text-slate-800 text-xs',
    sec:    isDark ? 'text-slate-400 text-[10px] font-semibold uppercase tracking-wide mb-2' : 'text-slate-500 text-[10px] font-semibold uppercase tracking-wide mb-2',
  }

  return (
    <div className={`border rounded-xl mt-2 p-4 ${th.card}`}>
      <div className="flex flex-col lg:flex-row gap-5">

        {/* Left: cheque image */}
        <div className="flex-shrink-0">
          <div className={`${th.sec}`}>Cheque Image (Front)</div>
          <div className="overflow-x-auto">
            <div style={{ minWidth: 420, maxWidth: 560 }}>
              <MockChequeFront item={item} />
            </div>
          </div>
        </div>

        {/* Right: AI analysis */}
        <div className="flex-1 space-y-4 min-w-0">

          {/* AI scores */}
          <div>
            <div className={th.sec}>AI Analysis</div>
            <div className="space-y-2">
              <ScoreBar label={`OCR Confidence (${ai.ocr_model ?? 'OCR'})`} value={ai.ocr_confidence ?? 0} good="high" isDark={isDark} />
              <ScoreBar label={`Signature Match (${ai.signature_model ?? 'SigNet'})`} value={ai.signature_score ?? 0} good="high" isDark={isDark} />
              <ScoreBar label={`Fraud Score (${ai.fraud_model ?? 'XGBoost'})`} value={ai.fraud_score ?? 0} good="low" isDark={isDark} />
              <ScoreBar label="Alteration Risk" value={ai.alteration_risk ?? 0} good="low" isDark={isDark} />
            </div>
          </div>

          {/* SHAP */}
          {(ai.shap ?? []).length > 0 && (
            <div>
              <div className={th.sec}>SHAP — Key Factors</div>
              <div className={`text-[9px] mb-2 flex justify-center gap-4 ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>
                <span className="text-emerald-500">◀ lowers risk</span>
                <span className="text-red-400">raises risk ▶</span>
              </div>
              <div className="space-y-1.5">
                {ai.shap.map((s, i) => <ShapRow key={i} {...s} isDark={isDark} />)}
              </div>
            </div>
          )}

          {/* AI narrative */}
          {item.ai_summary && (
            <div className={`text-xs rounded-lg px-3 py-2 border-l-2 border-violet-500 ${isDark ? 'bg-violet-900/20 text-slate-300' : 'bg-violet-50 text-slate-700'}`}>
              <span className={`font-semibold ${isDark ? 'text-violet-300' : 'text-violet-700'}`}>AI Observation: </span>
              {item.ai_summary}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Hold / Return modals ─────────────────────────────────────────────────────

function HoldModal({ instrument, onConfirm, onCancel, isDark }) {
  const [reason, setReason] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const th = {
    overlay: 'fixed inset-0 z-50 flex items-center justify-center bg-black/60',
    modal:   isDark ? 'bg-navy-900 border border-white/10 rounded-2xl p-6 w-full max-w-md shadow-2xl' : 'bg-white border border-slate-200 rounded-2xl p-6 w-full max-w-md shadow-2xl',
    label:   isDark ? 'text-xs font-medium text-slate-400 mb-1 block' : 'text-xs font-medium text-slate-500 mb-1 block',
    input:   isDark ? 'w-full rounded-lg bg-white/5 border border-white/10 text-slate-200 text-sm px-3 py-2 focus:outline-none focus:border-violet-500' : 'w-full rounded-lg bg-white border border-slate-200 text-slate-800 text-sm px-3 py-2 focus:outline-none focus:border-violet-400',
    heading: isDark ? 'text-base font-semibold text-white' : 'text-base font-semibold text-slate-900',
  }
  return (
    <div className={th.overlay}>
      <div className={th.modal}>
        <h2 className={th.heading}>Place Hold</h2>
        <p className={`text-xs mt-1 mb-4 ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>
          {instrument.instrument_id} — <span className="text-amber-400">IET clock continues running.</span>
        </p>
        <div className="space-y-3">
          <div>
            <label className={th.label}>Hold Reason *</label>
            <textarea rows={3} value={reason} onChange={e => setReason(e.target.value)}
              placeholder="Describe why branch consultation is needed…" className={th.input} />
          </div>
          <div>
            <label className={th.label}>Branch Email *</label>
            <input type="email" value={email} onChange={e => setEmail(e.target.value)}
              placeholder="mgr@branch.unionbank.in" className={th.input} />
          </div>
          <div>
            <label className={th.label}>Branch WhatsApp (optional)</label>
            <input type="tel" value={phone} onChange={e => setPhone(e.target.value)}
              placeholder="+919876543210" className={th.input} />
          </div>
        </div>
        <div className="flex gap-2 mt-5 justify-end">
          <button onClick={onCancel} className={`text-sm px-4 py-1.5 rounded-lg border font-medium ${isDark ? 'border-white/10 text-slate-400 hover:bg-white/5' : 'border-slate-200 text-slate-600 hover:bg-slate-50'}`}>Cancel</button>
          <button disabled={!reason.trim() || !email.trim()} onClick={() => onConfirm({ reason, email, phone })}
            className="text-sm px-4 py-1.5 rounded-lg font-medium bg-amber-500 hover:bg-amber-400 text-white disabled:opacity-40">
            Place Hold
          </button>
        </div>
      </div>
    </div>
  )
}

function ReturnModal({ instrument, onConfirm, onCancel, isDark }) {
  const [reason, setReason] = useState('')
  const th = {
    overlay: 'fixed inset-0 z-50 flex items-center justify-center bg-black/60',
    modal:   isDark ? 'bg-navy-900 border border-white/10 rounded-2xl p-6 w-full max-w-md shadow-2xl' : 'bg-white border border-slate-200 rounded-2xl p-6 w-full max-w-md shadow-2xl',
    label:   isDark ? 'text-xs font-medium text-slate-400 mb-1 block' : 'text-xs font-medium text-slate-500 mb-1 block',
    select:  isDark ? 'w-full rounded-lg bg-white/5 border border-white/10 text-slate-200 text-sm px-3 py-2 focus:outline-none focus:border-red-500' : 'w-full rounded-lg bg-white border border-slate-200 text-slate-800 text-sm px-3 py-2 focus:outline-none focus:border-red-400',
    heading: isDark ? 'text-base font-semibold text-white' : 'text-base font-semibold text-slate-900',
  }
  return (
    <div className={th.overlay}>
      <div className={th.modal}>
        <h2 className={th.heading}>Return Instrument</h2>
        <p className={`text-xs mt-1 mb-4 ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>
          {instrument.instrument_id} will be returned to drawer.
        </p>
        <div>
          <label className={th.label}>Return Reason *</label>
          <select value={reason} onChange={e => setReason(e.target.value)} className={th.select}>
            <option value="">— Select reason —</option>
            {RETURN_REASONS.map(r => <option key={r.code} value={r.code}>{r.label}</option>)}
          </select>
        </div>
        <div className="flex gap-2 mt-5 justify-end">
          <button onClick={onCancel} className={`text-sm px-4 py-1.5 rounded-lg border font-medium ${isDark ? 'border-white/10 text-slate-400 hover:bg-white/5' : 'border-slate-200 text-slate-600 hover:bg-slate-50'}`}>Cancel</button>
          <button disabled={!reason} onClick={() => onConfirm(reason)}
            className="text-sm px-4 py-1.5 rounded-lg font-medium bg-red-600 hover:bg-red-500 text-white disabled:opacity-40">
            Confirm Return
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function CTSInwardReviewQueue() {
  const { isDark } = useTheme()
  const { bankId, isDemo } = useBankContext()
  const { setHeader } = usePageHeader?.() ?? {}
  const queryClient = useQueryClient()

  const [tierFilter, setTierFilter]   = useState('all')
  const [expandedId, setExpandedId]   = useState(null)
  const [holdTarget, setHoldTarget]   = useState(null)
  const [returnTarget, setReturnTarget] = useState(null)
  const [toast, setToast]             = useState(null)

  // Demo-mode local state: starts as MOCK_REVIEW_ITEMS, mutations update in-place
  const [demoItems, setDemoItems]     = useState(() => MOCK_REVIEW_ITEMS)

  useEffect(() => {
    setHeader?.({
      title: 'Inward Human Review Queue',
      subtitle: 'Claim an instrument to review, then Confirm (PAY) or Return — IET countdown active',
    })
  }, [])

  const th = {
    page:    isDark ? 'bg-navy-950'        : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'         : 'text-slate-900',
    body:    isDark ? 'text-slate-300'     : 'text-slate-700',
    muted:   isDark ? 'text-slate-400'     : 'text-slate-500',
    faint:   isDark ? 'text-slate-600'     : 'text-slate-400',
    divider: isDark ? 'border-white/8'     : 'border-slate-200',
    tab:     (active) => active
      ? (isDark ? 'bg-white/8 text-white border-white/15' : 'bg-slate-100 text-slate-900 border-slate-300')
      : (isDark ? 'text-slate-400 border-transparent hover:border-white/10 hover:text-slate-300' : 'text-slate-500 border-transparent hover:text-slate-700'),
  }

  const showToast = useCallback((msg, type = 'success') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3500)
  }, [])

  // ── Remote data (non-demo) ──────────────────────────────────────────────────
  const { data, isLoading, isError } = useQuery({
    queryKey: ['cts-review-queue', bankId, tierFilter],
    queryFn: async () => {
      const url = tierFilter === 'all'
        ? `/v1/cts/review/queue?bank_id=${bankId}`
        : `/v1/cts/review/queue?bank_id=${bankId}&tier=${tierFilter}`
      const res = await fetch(url, { credentials: 'include' })
      if (!res.ok) throw new Error('Failed to load review queue')
      return res.json()
    },
    refetchInterval: 15_000,
    enabled: !isDemo,
    retry: false,
  })

  const rawItems = isDemo ? demoItems : (data?.items ?? [])
  const items = useMemo(
    () => tierFilter === 'all' ? rawItems : rawItems.filter(it => it.queue_tier === tierFilter),
    [rawItems, tierFilter]
  )
  const remaining = useTickingCountdowns(rawItems)
  const sorted = [...items].sort((a, b) => (remaining[a.instrument_id] ?? 0) - (remaining[b.instrument_id] ?? 0))

  // ── Mutations ───────────────────────────────────────────────────────────────

  function updateDemoItem(instrument_id, patch) {
    setDemoItems(prev => prev.map(it => it.instrument_id === instrument_id ? { ...it, ...patch } : it))
  }

  async function apiPost(url, body) {
    const res = await fetch(url, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      credentials: 'include', body: JSON.stringify(body ?? {}),
    })
    if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.message ?? `HTTP ${res.status}`) }
    return res.json()
  }

  async function handleClaim(item) {
    if (isDemo) {
      updateDemoItem(item.instrument_id, { status: 'CLAIMED', claimed_by: 'preethi.menon@unionbank.in', claimed_by_me: true })
      setExpandedId(item.instrument_id)
      showToast(`Claimed ${item.instrument_id} — cheque image and AI analysis loaded`)
      return
    }
    try {
      await apiPost(`/v1/cts/review/${item.instrument_id}/claim`)
      queryClient.invalidateQueries({ queryKey: ['cts-review-queue', bankId] })
      showToast(`Claimed ${item.instrument_id}`)
    } catch (e) { showToast(e.message, 'error') }
  }

  async function handleHoldConfirm({ reason, email, phone }) {
    const item = holdTarget; setHoldTarget(null)
    if (isDemo) {
      updateDemoItem(item.instrument_id, { status: 'ON_HOLD' })
      showToast(`Hold placed — branch notified at ${email}`)
      return
    }
    try {
      await apiPost(`/v1/cts/holds/${item.instrument_id}`, { hold_reason: reason, iet_deadline: item.iet_deadline, branch_email: email, branch_phone: phone || undefined })
      queryClient.invalidateQueries({ queryKey: ['cts-review-queue', bankId] })
      showToast(`Hold placed on ${item.instrument_id}`)
    } catch (e) { showToast(e.message, 'error') }
  }

  async function handleConfirm(item) {
    if (isDemo) {
      updateDemoItem(item.instrument_id, { status: 'CONFIRMED' })
      setExpandedId(null)
      showToast(`Confirmed (PAY) — ${item.instrument_id} filed to NGCH`)
      return
    }
    try {
      await apiPost(`/v1/cts/review/${item.instrument_id}/confirm`)
      queryClient.invalidateQueries({ queryKey: ['cts-review-queue', bankId] })
      showToast(`Confirmed (PAY) ${item.instrument_id}`)
    } catch (e) { showToast(e.message, 'error') }
  }

  async function handleReturnConfirm(returnReason) {
    const item = returnTarget; setReturnTarget(null)
    if (isDemo) {
      updateDemoItem(item.instrument_id, { status: 'RETURNED' })
      setExpandedId(null)
      showToast(`Returned ${item.instrument_id} — ${returnReason}`)
      return
    }
    try {
      await apiPost(`/v1/cts/review/${item.instrument_id}/return`, { return_reason: returnReason })
      queryClient.invalidateQueries({ queryKey: ['cts-review-queue', bankId] })
      showToast(`Returned ${item.instrument_id} — ${returnReason}`)
    } catch (e) { showToast(e.message, 'error') }
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5 relative`}>

        {toast && (
          <div className={`fixed top-4 right-4 z-50 text-sm px-4 py-2 rounded-xl shadow-lg font-medium
            ${toast.type === 'error' ? 'bg-red-600 text-white' : (isDark ? 'bg-emerald-700 text-white' : 'bg-emerald-500 text-white')}`}>
            {toast.msg}
          </div>
        )}

        {holdTarget && <HoldModal instrument={holdTarget} onConfirm={handleHoldConfirm} onCancel={() => setHoldTarget(null)} isDark={isDark} />}
        {returnTarget && <ReturnModal instrument={returnTarget} onConfirm={handleReturnConfirm} onCancel={() => setReturnTarget(null)} isDark={isDark} />}

        {/* Header */}
        <div className="flex items-center justify-between flex-wrap gap-3 mb-5">
          <div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>Inward Human Review Queue</h1>
            <p className={`text-xs mt-0.5 ${th.muted}`}>
              {isLoading ? 'Loading…' : `${items.length} instrument${items.length !== 1 ? 's' : ''} · click any row to view cheque image and AI analysis`}
            </p>
          </div>
          <div className={`text-xs px-3 py-1 rounded-full border ${isDark ? 'border-amber-700/40 bg-amber-900/30 text-amber-300' : 'border-amber-200 bg-amber-50 text-amber-700'}`}>
            IET countdown active — breach rate must be 0.000%
          </div>
        </div>

        {/* Tier filter tabs */}
        <div className={`flex gap-1 mb-5 border-b ${th.divider}`}>
          {TIERS.map(t => (
            <button key={t} onClick={() => setTierFilter(t)}
              className={`text-xs px-3 py-2 border-b-2 -mb-px font-medium transition-colors ${th.tab(tierFilter === t)}`}>
              {TIER_LABEL[t]}
            </button>
          ))}
        </div>

        {isLoading && <div className={`text-center py-16 ${th.muted}`}>Loading queue…</div>}
        {isError && <div className="text-center py-16 text-amber-400/70">Backend not reachable — retrying every 15s.</div>}
        {!isLoading && !isError && items.length === 0 && (
          <div className={`text-center py-16 ${th.muted}`}>No instruments in this tier.</div>
        )}

        {/* Instrument rows */}
        {!isLoading && !isError && sorted.length > 0 && (
          <div className="space-y-3">
            {sorted.map(item => {
              const secs = remaining[item.instrument_id] ?? 0
              const isExpanded = expandedId === item.instrument_id
              const isClaimed  = item.status === 'CLAIMED'
              const isDone     = item.status === 'CONFIRMED' || item.status === 'RETURNED'

              return (
                <div key={item.instrument_id}>
                  {/* Card header — always visible */}
                  <div
                    onClick={() => setExpandedId(isExpanded ? null : item.instrument_id)}
                    className={`rounded-xl border p-4 cursor-pointer transition-colors ${th.card}
                      ${secs <= 30 * 60 && secs > 0 && !isDone ? (isDark ? 'border-red-800/50' : 'border-red-200') : ''}
                      ${isExpanded ? (isDark ? 'rounded-b-none border-b-0' : 'rounded-b-none border-b-0') : ''}
                      ${isDark ? 'hover:bg-white/2' : 'hover:bg-slate-50'}`}
                  >
                    {/* Top row */}
                    <div className="flex items-start justify-between gap-4 flex-wrap">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className={`font-mono text-sm font-semibold ${th.heading}`}>{item.instrument_id}</span>
                        <TierBadge tier={item.queue_tier} isDark={isDark} />
                        <StatusBadge status={item.status} claimedBy={item.claimed_by} isDark={isDark} />
                      </div>
                      <div className="flex items-center gap-3">
                        <div className="flex items-center gap-1.5">
                          <span className={`text-xs ${th.muted}`}>IET</span>
                          <span className={`font-mono text-sm tabular-nums ${isDone ? th.muted : ietColor(secs, isDark)}`}>
                            {isDone ? '—' : fmtCountdown(secs)}
                          </span>
                        </div>
                        <span className={`text-xs ${isDark ? 'text-slate-600' : 'text-slate-400'}`}>{isExpanded ? '▲' : '▼'}</span>
                      </div>
                    </div>

                    {/* Summary details */}
                    <div className={`mt-3 grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-2 text-xs ${th.muted}`}>
                      <div>
                        <div className={`uppercase tracking-wide text-[10px] mb-0.5 ${th.faint}`}>Account No.</div>
                        <div className={`font-mono ${th.body}`}>{item.account_display}</div>
                      </div>
                      <div>
                        <div className={`uppercase tracking-wide text-[10px] mb-0.5 ${th.faint}`}>Payee</div>
                        <div className={th.body}>{item.payee_display}</div>
                      </div>
                      <div>
                        <div className={`uppercase tracking-wide text-[10px] mb-0.5 ${th.faint}`}>Amount</div>
                        <div className={`font-semibold ${isDark ? 'text-emerald-400' : 'text-emerald-700'}`}>{item.amount_display}</div>
                      </div>
                      <div>
                        <div className={`uppercase tracking-wide text-[10px] mb-0.5 ${th.faint}`}>Branch · Cheque No.</div>
                        <div className={th.body}>{item.branch_name} · #{item.cheque_number}</div>
                      </div>
                    </div>

                    {/* Risk flags */}
                    {(item.risk_flags ?? []).length > 0 && (
                      <div className="mt-2.5 flex gap-1.5 flex-wrap">
                        {item.risk_flags.map(f => (
                          <span key={f} className={`text-[10px] px-2 py-0.5 rounded font-medium border ${isDark ? 'bg-red-900/40 text-red-300 border-red-700/40' : 'bg-red-50 text-red-700 border-red-200'}`}>{f}</span>
                        ))}
                      </div>
                    )}

                    {/* Action buttons — only when not done */}
                    {!isDone && (
                      <div className="mt-3 flex gap-2 flex-wrap" onClick={e => e.stopPropagation()}>
                        {!isClaimed && (
                          <button onClick={() => handleClaim(item)}
                            className={`text-xs px-3 py-1.5 rounded-lg font-medium transition-colors ${isDark ? 'bg-violet-600 hover:bg-violet-500 text-white' : 'bg-violet-600 hover:bg-violet-700 text-white'}`}>
                            Claim &amp; Review
                          </button>
                        )}
                        {isClaimed && item.claimed_by_me && (
                          <>
                            <button onClick={() => setHoldTarget(item)}
                              className="text-xs px-3 py-1.5 rounded-lg font-medium bg-amber-600 hover:bg-amber-500 text-white">
                              Hold
                            </button>
                            <button onClick={() => handleConfirm(item)}
                              className="text-xs px-3 py-1.5 rounded-lg font-medium bg-emerald-600 hover:bg-emerald-500 text-white">
                              Confirm (PAY)
                            </button>
                            <button onClick={() => setReturnTarget(item)}
                              className="text-xs px-3 py-1.5 rounded-lg font-medium bg-red-700 hover:bg-red-600 text-white">
                              Return
                            </button>
                          </>
                        )}
                        {isClaimed && !item.claimed_by_me && (
                          <span className={`text-xs ${th.muted}`}>Locked by another reviewer</span>
                        )}
                        {item.status === 'ON_HOLD' && (
                          <span className={`text-xs ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>On hold — release from Hold Queue to resume</span>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Expanded panel: cheque image + AI */}
                  {isExpanded && <ExpandedPanel item={item} isDark={isDark} />}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </AppShell>
  )
}

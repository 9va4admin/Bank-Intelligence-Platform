/**
 * CTSSubmissionQueue — Submission stage (Stage 3).
 * Cheque image visible in the detail panel via tabs: Front | Back | Pay-in Slip | Fields.
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { useMutation } from '@tanstack/react-query'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'
import useDemoData from '../../../shared/hooks/useDemoData'
import { getReasonByLabel, getReturnReasons } from '../data/returnReasons'
import ChequeImageViewer from '../components/ChequeImageViewer'
import { demoChequeUrl } from '../demoImages'

const _API_BASE = import.meta.env.VITE_API_BASE ?? ''

function useOutwardQueue({ pollEnabled }) {
  const [items, setItems] = useState([])
  const timerRef = useRef(null)
  const fetch_ = useCallback(async () => {
    if (!pollEnabled) return
    try {
      const res = await fetch(`${_API_BASE}/v1/cts/outward/human-review-queue?limit=100`, { credentials: 'include' })
      if (!res.ok) return
      const json = await res.json()
      setItems(json.items ?? [])
    } catch { /* keep last */ }
  }, [pollEnabled])
  useEffect(() => {
    if (!pollEnabled) return
    fetch_()
    timerRef.current = setInterval(fetch_, 30_000)
    return () => clearInterval(timerRef.current)
  }, [fetch_, pollEnabled])
  return items
}

function adaptQueueItem(d) {
  const src = d.status === 'STP_RETURN' ? 'STP' : 'HUMAN_REVIEW'
  return {
    instrument_id: d.instrument_id,
    drawee_bank: '—', drawee_branch: '—',
    source_stage: src,
    date: '—',
    payee: d.payee_display ?? '—',
    drawer_name: '—',
    account_display: d.account_display ?? '—',
    amount_figures: d.amount_range ?? '—',
    amount_words: '—',
    micr: '—',
    alterations: false,
    manual_fields: [],
    iet_deadline: null,
    lot_id: d.lot_id ?? '—',
    status: d.status ?? 'HUMAN_REVIEW',
    fraud_score: d.fraud_score ?? 0,
    micr_confidence: d.ocr_confidence ?? 0.95,
    checks: { cts_valid: true, date_valid: true, signature_present: true, amount_words_match: true },
  }
}

// ── Mock data ─────────────────────────────────────────────────────────────────

// deposit_channel: how the customer submitted this cheque at the presenting branch
//   PAY_IN_SLIP     — customer filled a physical pay-in / deposit slip
//   BACK_ANNOTATION — customer wrote A/c number + mobile on the back of the cheque
//   KIOSK           — customer deposited via CDM / kiosk (details captured digitally)
// Outward instruments: presenting bank's scores only — OCR, vision/CTS-2010, MICR, IQA.
// Presenter does NOT compute fraud score or signature match (drawee bank's responsibility).
const MOCK_OUTWARD = [
  {
    instrument_id: 'CHQ-OUT-S001', drawee_bank: 'State Bank of India', drawee_branch: 'Andheri East', source_stage: 'STP',
    date: '15/07/2026', payee: 'Rajesh Kumar Verma', drawer_name: 'Vikram P. Joshi', account_display: '32119478125',
    amount_figures: '₹12,50,000', amount_words: 'Twelve Lakh Fifty Thousand Only', micr: '400002123',
    alterations: false, manual_fields: [],
    ocr_score: 0.98, vision_compliance: 0.97, micr_confidence: 0.99, iqa_score: 0.99,
    checks: { amount_words_match: true, date_valid: true, cts_valid: true, signature_present: true },
    front_bw_url: null, front_gray_url: null,
    deposit_channel: 'PAY_IN_SLIP',
    deposit_data: { depositor_name: 'Rajesh Kumar Verma', depositor_account: '4000401231', deposit_amount: '₹12,50,000', counter_token: 'T-0001', date: '15/07/2026', branch: 'Andheri East' },
  },
  {
    instrument_id: 'CHQ-OUT-S002', drawee_bank: 'HDFC Bank', drawee_branch: 'Bandra West', source_stage: 'VERIFIED',
    date: '14/07/2026', payee: 'Sunita P. Joshi', drawer_name: 'Anand R. Mehta', account_display: '50100238012901',
    amount_figures: '₹2,40,000', amount_words: 'Two Lakh Forty Thousand Only', micr: '400001234',
    alterations: false, manual_fields: ['payee', 'amount_words'],
    ocr_score: 0.88, vision_compliance: 0.91, micr_confidence: 0.98, iqa_score: 0.97,
    checks: { amount_words_match: false, date_valid: true, cts_valid: true, signature_present: true },
    front_bw_url: null, front_gray_url: null,
    deposit_channel: 'BACK_ANNOTATION',
    deposit_data: { extracted_account: '4000512347', extracted_mobile: '9876501234', ocr_confidence: 0.88 },
  },
  {
    instrument_id: 'CHQ-OUT-S003', drawee_bank: 'Bank of Baroda', drawee_branch: 'Fort', source_stage: 'VERIFIED',
    date: '15/07/2026', payee: 'Kavita R. Desai', drawer_name: 'Ramesh D. Shah', account_display: '05520023456789',
    amount_figures: '₹3,80,500', amount_words: 'Three Lakh Eighty Thousand Five Hundred Only', micr: '400008901',
    alterations: false, manual_fields: ['payee', 'amount_figures', 'amount_words'],
    ocr_score: 0.85, vision_compliance: 0.88, micr_confidence: 0.97, iqa_score: 0.96,
    checks: { amount_words_match: true, date_valid: true, cts_valid: false, signature_present: true },
    front_bw_url: null, front_gray_url: null,
    deposit_channel: 'KIOSK',
    deposit_data: { name: 'Kavita R. Desai', account: '4000623458', txn_id: 'CDM-003-20260715', timestamp: '11:25 AM  15/07/2026' },
  },
]

const MOCK_INWARD = [
  {
    // Payer (drawer): Girish V. Naik — Saraswat customer; Payee: Ramesh N. Rao — received at other bank
    instrument_id: 'CHQ-IN-S001', account_display: '00000000004521', drawee_bank: 'Saraswat Co-op Bank', drawee_branch: 'Dadar', source_stage: 'STP',
    iet_deadline: new Date(Date.now() + 68 * 60000).toISOString(),
    date: '15/07/2026', payee: 'Ramesh N. Rao', drawer_name: 'Girish V. Naik',
    amount_figures: '₹45,000', amount_words: 'Forty Five Thousand Only', micr: '400005678',
    alterations: false, manual_fields: [], ocr_score: 0.99, fraud_score: 0.02, sig_score: 0.98, iqa_score: 0.99,
    front_bw_url: null, front_gray_url: null,
  },
  {
    // Payer (drawer): Kavita P. Shah — Saraswat customer; Payee: Meena S. Sharma — received at other bank
    instrument_id: 'CHQ-IN-S002', account_display: '00000000008912', drawee_bank: 'Saraswat Co-op Bank', drawee_branch: 'Vile Parle', source_stage: 'VERIFIED',
    iet_deadline: new Date(Date.now() + 22 * 60000).toISOString(),
    date: '14/07/2026', payee: 'Meena S. Sharma', drawer_name: 'Kavita P. Shah',
    amount_figures: '₹3,20,000', amount_words: 'Three Lakh Twenty Thousand Only', micr: '400009012',
    alterations: false, manual_fields: ['payee', 'amount_words'], ocr_score: 0.88, fraud_score: 0.09, sig_score: 0.92, iqa_score: 0.97,
    front_bw_url: null, front_gray_url: null,
  },
  {
    // Payer (drawer): Rohit D. Kulkarni — Saraswat customer; Payee: Suresh B. Agarwal — received at other bank
    instrument_id: 'CHQ-IN-S003', account_display: '00000000006677', drawee_bank: 'Saraswat Co-op Bank', drawee_branch: 'Borivali', source_stage: 'VERIFIED',
    iet_deadline: new Date(Date.now() + 51 * 60000).toISOString(),
    date: '15/07/2026', payee: 'Suresh B. Agarwal', drawer_name: 'Rohit D. Kulkarni',
    amount_figures: '₹1,10,000', amount_words: 'One Lakh Ten Thousand Only', micr: '400007890',
    alterations: false, manual_fields: ['payee'], ocr_score: 0.89, fraud_score: 0.07, sig_score: 0.93, iqa_score: 0.97,
    front_bw_url: null, front_gray_url: null,
  },
]

// ── Helpers ───────────────────────────────────────────────────────────────────

function ScorePill({ label, value, isDark }) {
  const pct = Math.round(value * 100)
  const color = value >= 0.95 ? 'emerald' : value >= 0.85 ? 'amber' : 'red'
  const colors = {
    emerald: isDark ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30' : 'text-emerald-700 bg-emerald-50 border-emerald-300',
    amber:   isDark ? 'text-amber-400 bg-amber-500/10 border-amber-500/30'       : 'text-amber-700 bg-amber-50 border-amber-300',
    red:     isDark ? 'text-red-400 bg-red-500/10 border-red-500/30'             : 'text-red-700 bg-red-50 border-red-300',
  }
  return (
    <div className={`flex flex-col items-center px-3 py-2 rounded-lg border text-center ${colors[color]}`}>
      <span className="text-xs font-bold">{pct}%</span>
      <span className="text-[9px] font-medium">{label}</span>
    </div>
  )
}

function FieldRow({ label, value, isDark, isManual }) {
  return (
    <div className={`flex items-start gap-2 py-1.5 border-b text-xs ${isDark ? 'border-white/5' : 'border-slate-100'}`}>
      <span className={`w-32 shrink-0 ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>{label}</span>
      <span className={`flex-1 font-mono ${isManual ? (isDark ? 'text-amber-300' : 'text-amber-700') : (isDark ? 'text-slate-200' : 'text-slate-800')}`}>{value}</span>
      {isManual && <span className={`text-[9px] font-bold ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>MANUAL</span>}
    </div>
  )
}

function IETMini({ deadline, isDark }) {
  const [mins, setMins] = useState(0)
  useEffect(() => {
    function tick() { setMins(Math.max(0, Math.round((new Date(deadline) - Date.now()) / 60000))) }
    tick()
    const t = setInterval(tick, 10000)
    return () => clearInterval(t)
  }, [deadline])
  const urgent = mins < 30
  return (
    <span className={`font-mono text-[11px] font-semibold ${urgent ? 'text-red-400 animate-pulse' : isDark ? 'text-sky-400' : 'text-sky-600'}`}>
      IET {mins}m {urgent ? '⚠' : ''}
    </span>
  )
}

function ReturnPicker({ isDark, onReturn, onClose }) {
  const [search, setSearch] = useState('')
  const grouped = getReturnReasons()
  return (
    <div className={`absolute bottom-14 left-0 z-50 w-72 rounded-xl border shadow-2xl overflow-hidden ${isDark ? 'bg-navy-900 border-white/10' : 'bg-white border-slate-200'}`}>
      <div className={`px-3 py-2 border-b ${isDark ? 'border-white/10' : 'border-slate-200'}`}>
        <input autoFocus type="text" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search return reasons…"
          className={`w-full text-xs bg-transparent outline-none ${isDark ? 'text-slate-300' : 'text-slate-700'}`}
          onKeyDown={e => e.key === 'Escape' && onClose()}
        />
      </div>
      <div className="max-h-56 overflow-y-auto">
        {Object.entries(grouped).map(([group, reasons]) => {
          const filtered = search ? reasons.filter(r => r.toLowerCase().includes(search.toLowerCase())) : reasons
          if (!filtered.length) return null
          return (
            <div key={group}>
              <div className={`px-3 pt-2 pb-1 text-[9px] uppercase font-semibold tracking-widest ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>{group}</div>
              {filtered.map(r => {
                const entry = getReasonByLabel(r)
                return (
                  <button key={r} type="button" onMouseDown={() => { onReturn(r, entry); onClose() }}
                    className={`w-full text-left px-3 py-2 text-xs flex items-center justify-between gap-2 transition-colors ${isDark ? 'hover:bg-white/5 text-slate-300' : 'hover:bg-slate-50 text-slate-700'}`}
                  >
                    <span className="truncate">{r}</span>
                    {entry && <span className={`shrink-0 text-[9px] font-mono font-bold ${entry.customerFault ? (isDark ? 'text-red-400' : 'text-red-600') : (isDark ? 'text-sky-400' : 'text-sky-600')}`}>{entry.code}</span>}
                  </button>
                )
              })}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function ConfirmCountdown({ onConfirm, onCancel, isDark }) {
  const [count, setCount] = useState(2)
  const timerRef = useRef(null)
  useEffect(() => {
    timerRef.current = setInterval(() => {
      setCount(c => {
        if (c <= 1) { clearInterval(timerRef.current); onConfirm(); return 0 }
        return c - 1
      })
    }, 1000)
    return () => clearInterval(timerRef.current)
  }, [onConfirm])

  return (
    <div className={`flex items-center gap-3 px-4 py-2.5 rounded-xl border ${isDark ? 'bg-emerald-500/10 border-emerald-500/30' : 'bg-emerald-50 border-emerald-400'}`}>
      <div className={`text-sm font-bold ${isDark ? 'text-emerald-400' : 'text-emerald-700'}`}>Confirming in {count}s…</div>
      <div className={`flex-1 h-1 rounded-full overflow-hidden ${isDark ? 'bg-white/10' : 'bg-emerald-200'}`}>
        <div className={`h-full rounded-full ${isDark ? 'bg-emerald-400' : 'bg-emerald-500'} transition-all`} style={{ width: `${(count / 2) * 100}%` }} />
      </div>
      <button type="button" onClick={() => { clearInterval(timerRef.current); onCancel() }}
        className={`text-xs font-semibold ${isDark ? 'text-slate-400 hover:text-white' : 'text-slate-500 hover:text-slate-800'}`}
      >Cancel</button>
    </div>
  )
}

// ── Deposit channel config (outward only) ────────────────────────────────────

const DEPOSIT_CHANNEL_CFG = {
  PAY_IN_SLIP:     { label: 'Pay-in Slip', icon: '🧾', color: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30', colorL: 'text-emerald-700 bg-emerald-50 border-emerald-400' },
  BACK_ANNOTATION: { label: 'Back Note',   icon: '✍️',  color: 'text-sky-400 bg-sky-500/10 border-sky-500/30',             colorL: 'text-sky-700 bg-sky-50 border-sky-400'             },
  KIOSK:           { label: 'Kiosk/CDM',   icon: '🏧',  color: 'text-violet-400 bg-violet-500/10 border-violet-500/30',    colorL: 'text-violet-700 bg-violet-50 border-violet-400'    },
}

// ── Viewer props helper ───────────────────────────────────────────────────────

function _viewerProps(item, isInward) {
  const views = [
    { key: 'BFB', label: 'Front (B&W)',  url: item.front_bw_url   ?? null, iqaScore: item.iqa_score ?? 0.94 },
    { key: 'BBB', label: 'Back (B&W)',   url: item.front_gray_url ?? null, iqaScore: item.iqa_score ? item.iqa_score - 0.02 : 0.91 },
    { key: 'BFG', label: 'Front (Gray)', url: null,                         iqaScore: item.iqa_score ? item.iqa_score - 0.03 : 0.89 },
  ]
  const fields = {
    payee:          item.payee,
    date:           item.date,
    amount_figures: item.amount_figures,
    amount_words:   item.amount_words,
    micr:           item.micr,
    alterations:    item.alterations,
    drawer_name:    item.drawer_name,
    bank_name:      item.drawee_bank,
    bank_branch:    item.drawee_branch,
    account_display: item.account_display,
  }
  const depositInfo = !isInward && item.deposit_data ? {
    channel: item.deposit_channel,
    data:    item.deposit_data,
  } : undefined
  return { views, fields, depositInfo }
}

// ── Detail panel ──────────────────────────────────────────────────────────────

function DetailPanel({ item, isInward, isDark, onConfirm, onReturn }) {
  const [imgTab, setImgTab] = useState('image')
  const [showReturnPicker, setShowReturnPicker] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [submitted, setSubmitted] = useState(false)

  const th = {
    heading: isDark ? 'text-white' : 'text-slate-900',
    lbl:     isDark ? 'text-slate-500' : 'text-slate-400',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
  }

  const imgTabs = [
    { id: 'image',       label: '▣ Image'        },
    { id: 'fields',      label: '📋 Fields'      },
    { id: 'ai_analysis', label: '🤖 AI Analysis' },
    { id: 'passport',    label: '🪪 Passport'    },
  ]

  function handleConfirm() { setSubmitted(true); onConfirm(item.instrument_id) }

  if (submitted) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-3">
        <div className="text-4xl">✓</div>
        <div className={`text-lg font-semibold ${th.heading}`}>{isInward ? 'Confirmed' : 'Filed to NGCH'}</div>
        <div className={`text-sm ${th.muted}`}>{item.instrument_id}</div>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Panel header */}
      <div className={`px-5 py-3 border-b ${th.divider} shrink-0`}>
        <div className="flex items-center gap-3">
          <div>
            <div className={`font-mono text-sm font-bold ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>{item.instrument_id}</div>
            {isInward
              ? <div className={`text-xs mt-0.5 ${th.muted}`}>Account {item.account_display} · {item.drawee_bank}</div>
              : <div className={`text-xs mt-0.5 ${th.muted}`}>{item.drawee_bank} · {item.drawee_branch}</div>
            }
          </div>
          <div className="ml-auto flex flex-col items-end gap-1">
            <span className={`text-[9px] font-bold px-2 py-0.5 rounded-full border ${
              item.source_stage === 'STP'
                ? (isDark ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400' : 'bg-emerald-50 border-emerald-400 text-emerald-700')
                : (isDark ? 'bg-sky-500/10 border-sky-500/30 text-sky-400' : 'bg-sky-50 border-sky-400 text-sky-700')
            }`}>{item.source_stage}</span>
            {isInward && item.iet_deadline && <IETMini deadline={item.iet_deadline} isDark={isDark} />}
          </div>
        </div>
      </div>

      {/* Image / fields / AI / Passport tabs */}
      <div className={`flex border-b ${th.divider} shrink-0 overflow-x-auto`}>
        {imgTabs.map(t => (
          <button key={t.id} type="button" onClick={() => setImgTab(t.id)}
            className={`px-3 py-2 text-[11px] font-medium transition-colors border-b-2 -mb-px whitespace-nowrap ${imgTab === t.id
              ? (isDark ? 'border-amber-400 text-amber-300' : 'border-amber-500 text-amber-700')
              : (isDark ? 'border-transparent text-slate-500 hover:text-slate-300' : 'border-transparent text-slate-400 hover:text-slate-600')
            }`}
          >{t.label}</button>
        ))}
      </div>

      {/* Content area */}
      <div className="flex-1 overflow-y-auto">
        {imgTab === 'image' && (
          <ChequeImageViewer
            {..._viewerProps(item, isInward)}
            isDark={isDark}
            title={item.instrument_id}
            compact
          />
        )}
        {imgTab === 'fields' && (
          <div className="px-5 py-3">
            <div className={`text-[10px] font-semibold uppercase tracking-wider mb-2 ${th.lbl}`}>
              Validated Fields
              {item.manual_fields?.length > 0 && (
                <span className={`ml-2 font-normal lowercase ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>
                  ({item.manual_fields.length} manually corrected)
                </span>
              )}
            </div>
            <FieldRow label="Date"           value={item.date}            isDark={isDark} />
            <FieldRow label="Payee"          value={item.payee}           isDark={isDark} isManual={item.manual_fields?.includes('payee')} />
            <FieldRow label="Amount"         value={item.amount_figures}  isDark={isDark} isManual={item.manual_fields?.includes('amount_figures')} />
            <FieldRow label="Amount (words)" value={item.amount_words}    isDark={isDark} isManual={item.manual_fields?.includes('amount_words')} />
            <FieldRow label="MICR"           value={item.micr}            isDark={isDark} />
            <FieldRow label="Alterations"    value={item.alterations ? '⚠ Detected' : '✓ None'} isDark={isDark} />
          </div>
        )}

        {imgTab === 'ai_analysis' && (
          <div className="px-5 py-4 space-y-5">
            {/* Score pills — inward: OCR/Sig/Fraud/IQA; outward: OCR/Vision/MICR/IQA */}
            <div>
              <div className={`text-[10px] font-semibold uppercase tracking-wider mb-2.5 ${th.lbl}`}>AI Confidence</div>
              <div className="grid grid-cols-2 gap-2">
                <ScorePill label="OCR Accuracy" value={item.ocr_score} isDark={isDark} />
                {isInward ? (
                  <>
                    <ScorePill label="Signature Match" value={item.sig_score}             isDark={isDark} />
                    <ScorePill label="Fraud Clean"      value={1 - item.fraud_score}       isDark={isDark} />
                  </>
                ) : (
                  <>
                    <ScorePill label="Vision / CTS-10"  value={item.vision_compliance}    isDark={isDark} />
                    <ScorePill label="MICR Confidence"  value={item.micr_confidence}       isDark={isDark} />
                  </>
                )}
                <ScorePill label="Image IQA" value={item.iqa_score} isDark={isDark} />
              </div>
            </div>

            {/* Risk signals — different for inward vs outward */}
            <div>
              <div className={`text-[10px] font-semibold uppercase tracking-wider mb-2 ${th.lbl}`}>Risk Signals</div>
              {isInward ? (
                <div className={`rounded-lg border p-3 space-y-2 text-[11px] ${
                  item.fraud_score > 0.12
                    ? (isDark ? 'bg-red-500/8 border-red-500/25' : 'bg-red-50 border-red-300')
                    : (isDark ? 'bg-emerald-500/5 border-emerald-500/15' : 'bg-emerald-50 border-emerald-200')
                }`}>
                  {[
                    { label: 'Fraud score',         val: `${(item.fraud_score * 100).toFixed(1)}%`,    warn: item.fraud_score > 0.12 },
                    { label: 'Alteration detected', val: item.alterations ? '⚠ Yes' : '✓ None',        warn: item.alterations        },
                    { label: 'Signature match',     val: `${(item.sig_score * 100).toFixed(0)}%`,       warn: item.sig_score < 0.88   },
                    { label: 'Image quality',       val: `${(item.iqa_score * 100).toFixed(0)}%`,       warn: item.iqa_score < 0.90   },
                    { label: 'Manually corrected',  val: `${item.manual_fields?.length ?? 0} field(s)`, warn: (item.manual_fields?.length ?? 0) > 0 },
                  ].map(({ label, val, warn }) => (
                    <div key={label} className="flex items-center justify-between">
                      <span className={isDark ? 'text-slate-400' : 'text-slate-500'}>{label}</span>
                      <span className={`font-mono font-semibold ${warn ? (isDark ? 'text-red-400' : 'text-red-700') : (isDark ? 'text-emerald-400' : 'text-emerald-700')}`}>{val}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className={`rounded-lg border p-3 space-y-2 text-[11px] ${
                  (!item.checks?.cts_valid || !item.checks?.date_valid || !item.checks?.signature_present)
                    ? (isDark ? 'bg-red-500/8 border-red-500/25' : 'bg-red-50 border-red-300')
                    : (isDark ? 'bg-emerald-500/5 border-emerald-500/15' : 'bg-emerald-50 border-emerald-200')
                }`}>
                  {[
                    { label: 'Signature present',   val: item.checks?.signature_present   ? '✓ Detected' : '⚠ Missing', warn: !item.checks?.signature_present   },
                    { label: 'Amount words match',   val: item.checks?.amount_words_match  ? '✓ Match'    : '⚠ Mismatch', warn: !item.checks?.amount_words_match  },
                    { label: 'Date valid',            val: item.checks?.date_valid          ? '✓ Valid'    : '⚠ Invalid',  warn: !item.checks?.date_valid           },
                    { label: 'CTS-2010 compliant',    val: item.checks?.cts_valid           ? '✓ Pass'     : '⚠ Fail',     warn: !item.checks?.cts_valid            },
                    { label: 'Alteration detected',   val: item.alterations ? '⚠ Yes' : '✓ None',                         warn: !!item.alterations                 },
                    { label: 'Manually corrected',    val: `${item.manual_fields?.length ?? 0} field(s)`,                  warn: (item.manual_fields?.length ?? 0) > 0 },
                  ].map(({ label, val, warn }) => (
                    <div key={label} className="flex items-center justify-between">
                      <span className={isDark ? 'text-slate-400' : 'text-slate-500'}>{label}</span>
                      <span className={`font-mono font-semibold ${warn ? (isDark ? 'text-red-400' : 'text-red-700') : (isDark ? 'text-emerald-400' : 'text-emerald-700')}`}>{val}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Model attribution — different for inward vs outward */}
            <div>
              <div className={`text-[10px] font-semibold uppercase tracking-wider mb-2 ${th.lbl}`}>Model Attribution</div>
              <div className="space-y-1.5 text-[11px]">
                {(isInward ? [
                  { task: 'OCR / MICR',     model: 'GOT-OCR2.0'     },
                  { task: 'Signature',       model: 'Siamese Net v2'  },
                  { task: 'Fraud scoring',   model: 'XGBoost + SHAP'  },
                  { task: 'Risk narrative',  model: 'Llama 3.3 70B'   },
                  { task: 'Vision / layout', model: 'Qwen2-VL 72B'   },
                ] : [
                  { task: 'OCR / MICR',       model: 'GOT-OCR2.0'            },
                  { task: 'Vision / CTS-2010', model: 'Qwen2-VL 72B'          },
                  { task: 'Compliance check',  model: 'CTS-2010 Validator v3' },
                ]).map(({ task, model }) => (
                  <div key={task} className="flex items-center justify-between">
                    <span className={th.lbl}>{task}</span>
                    <span className={`font-mono ${isDark ? 'text-slate-300' : 'text-slate-700'}`}>{model}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {imgTab === 'passport' && (
          <div className="px-5 py-4">
            <div className={`text-[10px] font-semibold uppercase tracking-wider mb-3 ${th.lbl}`}>Cheque Passport</div>
            <div className={`rounded-xl border divide-y text-xs ${isDark ? 'border-white/10 divide-white/5' : 'border-slate-200 divide-slate-100'}`}>
              {/* Header row */}
              <div className={`flex items-center justify-between px-4 py-2.5 ${isDark ? 'bg-white/3' : 'bg-slate-50'}`}>
                <span className={`font-mono text-sm font-bold ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>{item.instrument_id}</span>
                <span className={`text-[9px] font-bold px-2 py-0.5 rounded border ${
                  item.source_stage === 'STP'
                    ? (isDark ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400' : 'border-emerald-400 bg-emerald-50 text-emerald-700')
                    : (isDark ? 'border-sky-500/40 bg-sky-500/10 text-sky-400' : 'border-sky-400 bg-sky-50 text-sky-700')
                }`}>{item.source_stage}</span>
              </div>
              {/* Field rows */}
              {[
                { label: 'Payee',          value: item.payee          },
                { label: 'Drawer',         value: item.drawer_name    },
                { label: 'Amount',         value: item.amount_figures },
                { label: 'Amount (words)', value: item.amount_words   },
                { label: 'Date',           value: item.date           },
                { label: 'MICR',           value: item.micr           },
                { label: 'Account',        value: item.account_display },
                { label: 'Drawee Bank',    value: item.drawee_bank    },
                { label: 'Branch',         value: item.drawee_branch  },
              ].filter(r => r.value).map(({ label, value }) => (
                <div key={label} className="flex items-start gap-3 px-4 py-2">
                  <span className={`w-28 shrink-0 ${th.lbl}`}>{label}</span>
                  <span className={`font-mono ${isDark ? 'text-slate-200' : 'text-slate-800'}`}>{value}</span>
                </div>
              ))}
              {/* Deposit channel section (outward only) */}
              {!isInward && item.deposit_channel && (() => {
                const DCFG = {
                  PAY_IN_SLIP:     { label: 'Pay-in Slip', icon: '🧾' },
                  BACK_ANNOTATION: { label: 'Back Note',   icon: '✍️' },
                  KIOSK:           { label: 'Kiosk / CDM', icon: '🏧' },
                }
                const dd = item.deposit_data ?? {}
                const depositRows =
                  item.deposit_channel === 'PAY_IN_SLIP' ? [
                    { label: 'Depositor',    value: dd.depositor_name    },
                    { label: 'Dep. Account', value: dd.depositor_account },
                    { label: 'Deposit Amt',  value: dd.deposit_amount    },
                    { label: 'Token',        value: dd.counter_token     },
                    { label: 'Dep. Branch',  value: dd.branch            },
                  ] : item.deposit_channel === 'BACK_ANNOTATION' ? [
                    { label: 'Ext. Account', value: dd.extracted_account },
                    { label: 'Ext. Mobile',  value: dd.extracted_mobile  },
                  ] : item.deposit_channel === 'KIOSK' ? [
                    { label: 'Depositor',    value: dd.name      },
                    { label: 'CDM Account',  value: dd.account   },
                    { label: 'Txn ID',       value: dd.txn_id    },
                    { label: 'Timestamp',    value: dd.timestamp },
                  ] : []
                return (
                  <>
                    <div className={`px-4 py-1.5 text-[9px] font-semibold uppercase tracking-wider ${isDark ? 'bg-white/2 text-slate-500' : 'bg-slate-50 text-slate-400'}`}>
                      {DCFG[item.deposit_channel]?.icon} {DCFG[item.deposit_channel]?.label ?? item.deposit_channel}
                    </div>
                    {depositRows.filter(r => r.value).map(({ label, value }) => (
                      <div key={label} className="flex items-start gap-3 px-4 py-2">
                        <span className={`w-28 shrink-0 ${th.lbl}`}>{label}</span>
                        <span className={`font-mono ${isDark ? 'text-slate-200' : 'text-slate-800'}`}>{value}</span>
                      </div>
                    ))}
                  </>
                )
              })()}
              {/* IET footer (inward only) */}
              {isInward && item.iet_deadline && (
                <div className={`flex items-center justify-between px-4 py-2.5 ${isDark ? 'bg-white/2' : 'bg-slate-50'}`}>
                  <span className={th.lbl}>IET Deadline</span>
                  <IETMini deadline={item.iet_deadline} isDark={isDark} />
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Footer actions */}
      <div className={`px-5 py-3 border-t ${th.divider} shrink-0 flex flex-col gap-2 relative`}>
        {showReturnPicker && (
          <ReturnPicker isDark={isDark}
            onReturn={(reason, entry) => { setShowReturnPicker(false); onReturn(item.instrument_id, reason, entry) }}
            onClose={() => setShowReturnPicker(false)}
          />
        )}
        {confirming && isInward
          ? <ConfirmCountdown isDark={isDark} onConfirm={handleConfirm} onCancel={() => setConfirming(false)} />
          : (
            <button type="button" onClick={() => isInward ? setConfirming(true) : handleConfirm()}
              className={`w-full py-2.5 rounded-xl text-sm font-semibold transition-all ${isDark ? 'bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 hover:bg-emerald-500/30' : 'bg-emerald-500 text-white hover:bg-emerald-600'}`}
            >{isInward ? '✓ Confirm — File to NGCH' : '↑ Submit to NGCH'}</button>
          )
        }
        <button type="button" onClick={() => setShowReturnPicker(v => !v)}
          className={`w-full py-2 rounded-xl text-sm font-semibold transition-all border ${isDark ? 'border-red-500/30 bg-red-500/10 text-red-400 hover:bg-red-500/20' : 'border-red-300 bg-red-50 text-red-700 hover:bg-red-100'}`}
        >✕ Return to Verification</button>
      </div>
    </div>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────────

// Threshold comes from bank config (GET /v1/config/cts → high_value_amount_threshold).
// ₹5,00,000 is the default shipped in Helm values; each bank overrides via Admin UI.
const MOCK_HV_THRESHOLD_SQ = 500000

function parseAmt(amtStr) {
  return parseInt((amtStr || '').replace(/[₹,\s]/g, ''), 10) || 0
}
function isHV(inst, threshold = MOCK_HV_THRESHOLD_SQ) {
  return parseAmt(inst.amount_figures) >= threshold
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function CTSSubmissionQueue({ mode = 'outward' }) {
  const { isDark } = useTheme()
  const { isDemo } = useBankContext()
  const isInward = mode === 'inward'
  const BASE = useDemoData(isInward ? MOCK_INWARD : MOCK_OUTWARD)

  const liveOutward = useOutwardQueue({ pollEnabled: !isInward && !isDemo })
  const prevLiveRef = useRef([])

  const [instruments, setInstruments] = useState(BASE)
  const [selected, setSelected]       = useState(BASE[0]?.instrument_id ?? null)
  const [filter, setFilter]           = useState('ALL')

  useEffect(() => {
    if (!isInward && liveOutward.length > 0 && liveOutward !== prevLiveRef.current) {
      prevLiveRef.current = liveOutward
      const adapted = liveOutward.map(adaptQueueItem)
      setInstruments(adapted)
      setSelected(prev => adapted.find(i => i.instrument_id === prev) ? prev : adapted[0]?.instrument_id ?? null)
    }
  }, [liveOutward, isInward])

  const th = {
    page:    isDark ? 'bg-navy-950'       : 'bg-slate-50',
    heading: isDark ? 'text-white'        : 'text-slate-900',
    lbl:     isDark ? 'text-slate-500'    : 'text-slate-400',
    muted:   isDark ? 'text-slate-400'    : 'text-slate-500',
    divider: isDark ? 'border-white/8'    : 'border-slate-200',
    row:     isDark ? 'border-white/5'    : 'border-slate-100',
    rowHov:  isDark ? 'hover:bg-white/3'  : 'hover:bg-slate-50',
    selRow:  isDark ? 'bg-white/6 border-l-2 border-amber-400' : 'bg-amber-50 border-l-2 border-amber-500',
  }

  const filtered = instruments.filter(i => {
    if (filter === 'STP')        return i.source_stage === 'STP'
    if (filter === 'VERIFIED')   return i.source_stage === 'VERIFIED'
    if (filter === 'HIGH_VALUE') return isHV(i)
    return true
  })
  const hvCount      = instruments.filter(i => isHV(i)).length
  const selectedItem = instruments.find(i => i.instrument_id === selected)

  const confirmMutation = useMutation({
    mutationFn: async (instrumentId) => {
      const res = await fetch(`/v1/cts/review/${encodeURIComponent(instrumentId)}/decide`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ action: 'CONFIRM', reason: 'Ops reviewer confirmed — all checks passed' }),
      })
      if (!res.ok) throw new Error('Confirm failed')
      return res.json()
    },
    onSuccess: (_, instrumentId) => {
      setInstruments(prev => {
        const next = prev.filter(i => i.instrument_id !== instrumentId)
        setSelected(next[0]?.instrument_id ?? null)
        return next
      })
    },
  })

  const returnMutation = useMutation({
    mutationFn: async ({ instrumentId, reason }) => {
      const res = await fetch(`/v1/cts/review/${encodeURIComponent(instrumentId)}/decide`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ action: 'RETURN', reason: reason || 'Return requested by ops reviewer' }),
      })
      if (!res.ok) throw new Error('Return failed')
      return res.json()
    },
    onSuccess: (_, { instrumentId }) => {
      setInstruments(prev => {
        const next = prev.filter(i => i.instrument_id !== instrumentId)
        setSelected(next[0]?.instrument_id ?? null)
        return next
      })
    },
  })

  function handleConfirm(instrumentId) {
    confirmMutation.mutate(instrumentId)
  }

  function handleReturn(instrumentId, reason) {
    returnMutation.mutate({ instrumentId, reason })
  }

  return (
    <AppShell>
      <div className={`flex-1 flex flex-col min-h-0 ${th.page}`}>
        {/* Page header */}
        <div className={`px-6 py-3 border-b ${th.divider} shrink-0 flex items-center gap-4`}>
          <div>
            <h1 className={`text-base font-semibold ${th.heading}`}>{isInward ? 'Submission IQ' : 'Submission OQ'}</h1>
            <p className={`text-[11px] ${th.muted}`}>
              {isInward ? 'Cheque image · 2s cancellable confirm before NGCH filing' : 'Cheque image · Submit to NGCH · Confirmed → Outward File'}
            </p>
          </div>
          <div className={`ml-auto text-[10px] px-3 py-1 rounded-lg border font-medium ${isDark ? 'bg-violet-400/5 border-violet-400/20 text-violet-400' : 'bg-violet-50 border-violet-300 text-violet-700'}`}>
            Stage 3 of 3 — Submission
          </div>
          {/* Filter buttons */}
          <div className="flex items-center gap-1">
            {[
              ['ALL',        'All'],
              ['STP',        'STP'],
              ['VERIFIED',   'Verified'],
              ['HIGH_VALUE', `HV ≥₹${(MOCK_HV_THRESHOLD_SQ / 100000).toFixed(0)}L`],
            ].map(([val, lbl]) => (
              <button key={val} onClick={() => setFilter(val)}
                className={`px-2.5 py-1 rounded-lg text-[10px] font-medium transition-all ${filter === val
                  ? val === 'HIGH_VALUE'
                    ? (isDark ? 'bg-red-500/20 text-red-300' : 'bg-red-600 text-white')
                    : (isDark ? 'bg-white/15 text-white' : 'bg-slate-800 text-white')
                  : val === 'HIGH_VALUE'
                    ? (isDark ? 'text-red-400/70 hover:bg-red-500/10' : 'text-red-600 hover:bg-red-50')
                    : (isDark ? 'text-slate-400 hover:bg-white/5' : 'text-slate-500 hover:bg-slate-100')
                }`}
              >{lbl}{val === 'HIGH_VALUE' && hvCount > 0 ? ` (${hvCount})` : ''}</button>
            ))}
          </div>
          <div className={`text-[11px] font-semibold ${th.heading}`}>{filtered.length} pending</div>
        </div>

        {/* Split layout */}
        <div className="flex-1 flex min-h-0 overflow-hidden">
          {/* Left: instrument list */}
          <div className={`w-64 shrink-0 flex flex-col border-r ${th.divider} overflow-hidden`}>
            <div className="flex-1 overflow-y-auto">
              {instruments.length === 0 ? (
                <div className={`flex flex-col items-center justify-center h-full gap-2 ${th.lbl}`}>
                  <div className="text-3xl">✓</div>
                  <div className="text-sm">Queue empty</div>
                  <div className="text-[11px]">All instruments filed</div>
                </div>
              ) : filtered.map(inst => {
                const isSel = inst.instrument_id === selected
                const minsLeft = inst.iet_deadline ? Math.max(0, Math.round((new Date(inst.iet_deadline) - Date.now()) / 60000)) : null
                const urgent = minsLeft != null && minsLeft < 30
                return (
                  <button key={inst.instrument_id} type="button" onClick={() => setSelected(inst.instrument_id)}
                    className={`w-full text-left px-4 py-3 border-b transition-all ${th.row} ${isSel ? th.selRow : th.rowHov}`}
                  >
                    <div className="flex items-center gap-2">
                      <span className={`font-mono text-[11px] font-bold truncate ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>{inst.instrument_id}</span>
                      <span className={`ml-auto text-[9px] font-bold px-1.5 py-0.5 rounded-full border shrink-0 ${
                        inst.source_stage === 'STP'
                          ? (isDark ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400' : 'bg-emerald-50 border-emerald-400 text-emerald-700')
                          : (isDark ? 'bg-sky-500/10 border-sky-500/30 text-sky-400' : 'bg-sky-50 border-sky-400 text-sky-700')
                      }`}>{inst.source_stage}</span>
                    </div>
                    {!isInward && inst.deposit_channel && (() => {
                      const ch = DEPOSIT_CHANNEL_CFG[inst.deposit_channel]
                      return ch ? (
                        <div className={`inline-flex items-center gap-1 text-[9px] font-semibold px-1.5 py-0.5 rounded border mt-0.5 ${isDark ? ch.color : ch.colorL}`}>
                          <span>{ch.icon}</span><span>{ch.label}</span>
                        </div>
                      ) : null
                    })()}
                    <div className={`text-[11px] ${th.muted} mt-0.5 truncate`}>
                      {isInward ? `Acct ${inst.account_display}` : inst.drawee_bank}
                    </div>
                    {isInward && minsLeft != null && (
                      <div className={`text-[10px] font-mono font-semibold mt-0.5 ${urgent ? 'text-red-400' : isDark ? 'text-sky-400' : 'text-sky-600'}`}>
                        IET {minsLeft}m {urgent ? '⚠' : ''}
                      </div>
                    )}
                    <div className={`text-[11px] mt-0.5 flex items-center gap-1.5`}>
                      <span className={th.muted}>{inst.amount_figures}</span>
                      {isHV(inst) && (
                        <span className={`text-[8px] font-bold px-1 py-0.5 rounded border ${isDark ? 'bg-red-500/10 border-red-500/30 text-red-400' : 'bg-red-50 border-red-300 text-red-600'}`}>HV</span>
                      )}
                    </div>
                    {inst.manual_fields?.length > 0 && (
                      <div className={`text-[9px] mt-0.5 ${isDark ? 'text-amber-400/60' : 'text-amber-600/60'}`}>
                        {inst.manual_fields.length} MANUAL field{inst.manual_fields.length > 1 ? 's' : ''}
                      </div>
                    )}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Right: detail panel with cheque image tabs */}
          <div className="flex-1 min-w-0 overflow-hidden">
            {selectedItem
              ? <DetailPanel key={selectedItem.instrument_id} item={selectedItem} isInward={isInward} isDark={isDark} onConfirm={handleConfirm} onReturn={handleReturn} />
              : (
                <div className={`h-full flex flex-col items-center justify-center gap-2 ${th.lbl}`}>
                  <div className="text-4xl">✓</div>
                  <div className="text-sm font-medium">Submission queue empty</div>
                  <div className="text-[11px]">All instruments processed</div>
                </div>
              )
            }
          </div>
        </div>
      </div>
    </AppShell>
  )
}

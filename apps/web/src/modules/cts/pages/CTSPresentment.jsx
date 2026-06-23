import { useState, useEffect, useRef } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'

// ─── Mock Data ────────────────────────────────────────────────────────────────

const SESSIONS = [
  { id: 'SES-0619-001', window: '10:00–12:00', status: 'ACTIVE',  submitted: 1247, accepted: 1231, rejected: 16,  returned: 4  },
  { id: 'SES-0619-002', window: '12:00–14:00', status: 'PENDING', submitted: 0,    accepted: 0,    rejected: 0,   returned: 0  },
  { id: 'SES-0619-003', window: '14:00–16:00', status: 'PENDING', submitted: 0,    accepted: 0,    rejected: 0,   returned: 0  },
]

const IQA_FAIL_REASONS = [
  'Image too dark — rescan required',
  'MICR band not readable',
  'Image skew > 2°',
  'Torn corner — rescan',
  'Duplicate instrument detected',
]

function makeBatch(n, startIdx = 0) {
  const zones = ['MUMBAI', 'PUNE', 'DELHI', 'CHENNAI']
  const statuses = ['CAPTURED', 'IQA_PASS', 'IQA_FAIL', 'AI_EXTRACTED', 'PKI_SIGNED', 'SUBMITTED', 'NGCH_ACK', 'NGCH_REJECT']
  const weights  = [0.05, 0.08, 0.04, 0.15, 0.12, 0.20, 0.28, 0.08]
  function pick() {
    const r = Math.random()
    let cum = 0
    for (let i = 0; i < weights.length; i++) { cum += weights[i]; if (r < cum) return statuses[i] }
    return 'NGCH_ACK'
  }
  // Lot assignment: every 15 instruments → new lot (NGCH convention)
  const LOT_SIZE = 15
  return Array.from({ length: n }, (_, i) => {
    const idx = startIdx + i
    const status = pick()
    const amts   = ['₹12,500', '₹45,000', '₹2,00,000', '₹8,75,000', '₹15,000', '₹3,50,000']
    const payees = ['Reliance Ind.', 'HDFC Securities', 'Tata Cons.', 'Infosys Ltd.', 'SBI MF']
    const iqaFail = status === 'IQA_FAIL'
    const lotSeq  = Math.floor(idx / LOT_SIZE) + 1
    return {
      instrument_id: `CHQ-OUT-${String(idx + 1).padStart(5, '0')}`,
      account_display: `****${1000 + ((idx * 37) % 9000)}`,
      payee: payees[idx % payees.length],
      amount: amts[idx % amts.length],
      zone: zones[idx % zones.length],
      micr: `0${idx % 9}2000${String(idx).padStart(6, '0')}`,
      date_on_cheque: '19-Jun-2026',
      lot_number: `LOT_SVCB0000001_20260619_SES-0619-001_${String(lotSeq).padStart(2, '0')}`,
      lot_seq: lotSeq,
      status,
      iqa_fail_reason: iqaFail ? IQA_FAIL_REASONS[idx % IQA_FAIL_REASONS.length] : null,
      ocr_confidence: iqaFail ? null : (0.72 + Math.random() * 0.27).toFixed(2),
      sig_score: iqaFail ? null : (0.74 + Math.random() * 0.25).toFixed(2),
      amount_words_match: iqaFail ? null : Math.random() > 0.04,
      date_valid: iqaFail ? null : Math.random() > 0.02,
      cts_valid: iqaFail ? null : Math.random() > 0.01,
      scanner_id: `SCN-${String((idx % 4) + 1).padStart(2, '0')}`,
      captured_at: new Date(Date.now() - (n - idx) * 4200).toISOString(),
      ngch_ack_id: ['NGCH_ACK', 'NGCH_REJECT'].includes(status)
        ? `NGCH-${Date.now()}-${idx}` : null,
    }
  })
}

const INITIAL_BATCH = makeBatch(42)

// STATUS_META_D / STATUS_META_L are selected per-render based on isDark
const STATUS_META_D = {
  CAPTURED:     { label: 'Captured',     color: 'text-slate-400',    bg: 'bg-slate-400/10 border-slate-400/20'   },
  IQA_PASS:     { label: 'IQA Pass',     color: 'text-sky-400',      bg: 'bg-sky-400/10 border-sky-400/20'       },
  IQA_FAIL:     { label: 'IQA Fail',     color: 'text-red-400',      bg: 'bg-red-400/10 border-red-400/25'       },
  AI_EXTRACTED: { label: 'AI Extracted', color: 'text-violet-400',   bg: 'bg-violet-400/10 border-violet-400/20' },
  PKI_SIGNED:   { label: 'PKI Signed',   color: 'text-amber-400',    bg: 'bg-amber-400/10 border-amber-400/20'   },
  SUBMITTED:    { label: 'Submitted',    color: 'text-blue-400',     bg: 'bg-blue-400/10 border-blue-400/20'     },
  NGCH_ACK:     { label: 'NGCH ACK ✓',  color: 'text-emerald-400',  bg: 'bg-emerald-400/10 border-emerald-400/20'},
  NGCH_REJECT:  { label: 'NGCH Reject',  color: 'text-red-500',      bg: 'bg-red-500/10 border-red-500/25'       },
}
const STATUS_META_L = {
  CAPTURED:     { label: 'Captured',     color: 'text-slate-500',    bg: 'bg-slate-50 border-slate-300'          },
  IQA_PASS:     { label: 'IQA Pass',     color: 'text-sky-600',      bg: 'bg-sky-50 border-sky-300'              },
  IQA_FAIL:     { label: 'IQA Fail',     color: 'text-red-600',      bg: 'bg-red-50 border-red-300'              },
  AI_EXTRACTED: { label: 'AI Extracted', color: 'text-violet-600',   bg: 'bg-violet-50 border-violet-300'        },
  PKI_SIGNED:   { label: 'PKI Signed',   color: 'text-amber-600',    bg: 'bg-amber-50 border-amber-300'          },
  SUBMITTED:    { label: 'Submitted',    color: 'text-blue-600',     bg: 'bg-blue-50 border-blue-300'            },
  NGCH_ACK:     { label: 'NGCH ACK ✓',  color: 'text-emerald-700',  bg: 'bg-emerald-50 border-emerald-300'      },
  NGCH_REJECT:  { label: 'NGCH Reject',  color: 'text-red-700',      bg: 'bg-red-50 border-red-300'              },
}
// STATUS_META is aliased per-component using isDark (see below)

const PIPELINE_STEPS = [
  { id: 'CAPTURE',   label: 'Scan & Capture',   icon: '📷', desc: 'Scanner feed → TIFF+JPEG'    },
  { id: 'IQA',       label: 'IQA',              icon: '🔍', desc: 'Image quality check'          },
  { id: 'AI',        label: 'AI Extraction',    icon: '🤖', desc: 'OCR · MICR · fields'          },
  { id: 'VALIDATE',  label: 'Cross-Validate',   icon: '⚖',  desc: 'Amount words · date · CTS'    },
  { id: 'PKI',       label: 'PKI Sign (HSM)',    icon: '🔐', desc: 'HSM digital signature'        },
  { id: 'SUBMIT',    label: 'Submit to NGCH',   icon: '📤', desc: 'SFTP · API · MCP'             },
  { id: 'ACK',       label: 'NGCH ACK',         icon: '✅', desc: 'Accept / reject from NGCH'    },
]

function pipelinePos(status) {
  const map = { CAPTURED: 0, IQA_PASS: 1, IQA_FAIL: 1, AI_EXTRACTED: 2, PKI_SIGNED: 3, SUBMITTED: 4, NGCH_ACK: 5, NGCH_REJECT: 5 }
  return map[status] ?? 0
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function SessionBar({ sessions, activeIdx, onSelect, isDark }) {
  const th = {
    bar:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    label:  isDark ? 'text-slate-400' : 'text-slate-500',
    sessionActive: isDark ? 'border-gold-400/50 bg-gold-400/10 text-gold-400 font-semibold' : 'border-amber-400/60 bg-amber-50 text-amber-700 font-semibold',
    sessionIdle:   isDark ? 'border-white/10 text-slate-400 hover:text-slate-200 hover:border-white/20' : 'border-slate-200 text-slate-500 hover:text-slate-700 hover:border-slate-300',
    live:   isDark ? 'text-emerald-400' : 'text-emerald-600',
    scnFeed: isDark ? 'text-emerald-400' : 'text-emerald-600',
  }
  return (
    <div className={`shrink-0 border-b ${th.bar} px-5 py-2 flex items-center gap-3`}>
      <span className={`text-[10px] uppercase tracking-widest ${th.label} mr-1`}>NGCH Sessions</span>
      {sessions.map((s, i) => {
        const active = i === activeIdx
        const isLive = s.status === 'ACTIVE'
        return (
          <button key={s.id} onClick={() => onSelect(i)}
            className={`flex items-center gap-1.5 px-3 py-1 rounded-lg border text-[11px] transition-all ${
              active ? th.sessionActive : th.sessionIdle
            }`}>
            {isLive && <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />}
            <span className="font-mono">{s.window}</span>
            {s.status === 'ACTIVE' && <span className={`text-[9px] font-medium ${th.live}`}>LIVE</span>}
            {s.status === 'PENDING' && <span className={`text-[9px] ${th.label}`}>Pending</span>}
          </button>
        )
      })}
      <div className={`ml-auto flex items-center gap-4 text-[11px] ${th.label}`}>
        <span>📷 <span className="font-mono font-semibold">4</span> scanners</span>
        <span>📁 <span className="font-mono font-semibold">2</span> folders</span>
        <span className={`font-mono font-semibold ${th.scnFeed}`}>SCN feed active</span>
      </div>
    </div>
  )
}

function KpiStrip({ batch, filterStatus, onFilter, isDark }) {
  const total     = batch.length
  const iqaFail   = batch.filter(b => b.status === 'IQA_FAIL').length
  const extracted = batch.filter(b => ['AI_EXTRACTED','PKI_SIGNED','SUBMITTED','NGCH_ACK','NGCH_REJECT'].includes(b.status)).length
  const submitted = batch.filter(b => ['SUBMITTED','NGCH_ACK','NGCH_REJECT'].includes(b.status)).length
  const acked     = batch.filter(b => b.status === 'NGCH_ACK').length
  const rejected  = batch.filter(b => b.status === 'NGCH_REJECT').length
  const amtMismatch = batch.filter(b => b.amount_words_match === false).length
  const dateInvalid = batch.filter(b => b.date_valid === false).length

  const th = {
    card:    isDark ? 'bg-navy-900/50 border-white/8' : 'bg-white border-slate-200',
    cardAct: isDark ? 'bg-gold-400/10 border-gold-400/40' : 'bg-amber-50 border-amber-300',
    lbl:     isDark ? 'text-slate-500' : 'text-slate-400',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
  }

  const tiles = [
    { key: 'ALL',          label: 'Total Batch',    val: total,       color: isDark ? 'text-white' : 'text-slate-900' },
    { key: 'IQA_FAIL',     label: 'IQA Fail',       val: iqaFail,     color: iqaFail > 0 ? 'text-red-400' : (isDark ? 'text-emerald-400' : 'text-emerald-600') },
    { key: 'AI_EXTRACTED', label: 'AI Extracted',   val: extracted,   color: isDark ? 'text-violet-400' : 'text-violet-600' },
    { key: 'SUBMITTED',    label: 'Submitted NGCH', val: submitted,   color: isDark ? 'text-blue-400' : 'text-blue-600' },
    { key: 'NGCH_ACK',     label: 'NGCH ACK',       val: acked,       color: isDark ? 'text-emerald-400' : 'text-emerald-600' },
    { key: 'NGCH_REJECT',  label: 'NGCH Reject',    val: rejected,    color: rejected > 0 ? 'text-red-400' : (isDark ? 'text-slate-500' : 'text-slate-400') },
    { key: 'AMT_MISMATCH', label: 'Amt Mismatch',   val: amtMismatch, color: amtMismatch > 0 ? 'text-amber-400' : (isDark ? 'text-slate-500' : 'text-slate-400') },
    { key: 'DATE_INVALID', label: 'Date Invalid',   val: dateInvalid, color: dateInvalid > 0 ? 'text-amber-400' : (isDark ? 'text-slate-500' : 'text-slate-400') },
  ]

  return (
    <div className={`shrink-0 border-b ${th.divider} px-5 py-3`}>
      <div className="flex gap-4 overflow-x-auto">
        {tiles.map(t => {
          const active = filterStatus === t.key
          return (
            <button key={t.key}
              onClick={() => onFilter(active ? 'ALL' : t.key)}
              className={`shrink-0 rounded-xl border px-4 py-2 min-w-[100px] text-left transition-all ${
                active ? th.cardAct : `${th.card} ${isDark ? 'hover:border-gold-400/20' : 'hover:border-amber-300/50'}`
              }`}>
              <div className={`text-[10px] uppercase tracking-widest ${th.lbl} mb-0.5`}>{t.label}</div>
              <div className={`text-2xl font-bold font-mono ${t.color}`}>{t.val}</div>
            </button>
          )
        })}
      </div>
    </div>
  )
}

function PipelineLane({ batch, isDark }) {
  const counts = {}
  PIPELINE_STEPS.forEach((_, i) => { counts[i] = 0 })
  batch.forEach(b => { const p = pipelinePos(b.status); counts[p] = (counts[p] || 0) + 1 })
  const total = batch.length || 1

  const th = {
    lbl:     isDark ? 'text-slate-500' : 'text-slate-400',
    bar:     isDark ? 'bg-white/5' : 'bg-slate-100',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    cnt:     isDark ? 'text-slate-300' : 'text-slate-700',
  }

  return (
    <div className={`shrink-0 border-b ${th.divider} px-5 py-3`}>
      <div className={`text-[10px] uppercase tracking-widest ${th.lbl} mb-2`}>Outward Pipeline — Current Session</div>
      <div className="flex gap-2 items-end">
        {PIPELINE_STEPS.map((step, i) => {
          const cnt = counts[i] || 0
          const pct = Math.round((cnt / total) * 100)
          return (
            <div key={step.id} className="flex-1 min-w-0">
              <div className="flex items-baseline justify-between mb-1">
                <span className={`text-[10px] ${th.lbl} truncate`}>{step.icon} {step.label}</span>
                <span className={`text-[10px] font-mono font-bold shrink-0 ml-1 ${th.cnt}`}>{cnt}</span>
              </div>
              <div className={`h-1.5 ${th.bar} rounded-full overflow-hidden`}>
                <div className="h-full bg-gold-400 rounded-full transition-all" style={{ width: `${pct}%` }} />
              </div>
              <div className={`text-[9px] ${th.lbl} mt-0.5`}>{step.desc}</div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function BatchRow({ item, selected, onClick, isDark }) {
  const STATUS_META = isDark ? STATUS_META_D : STATUS_META_L
  const s = STATUS_META[item.status] || STATUS_META['CAPTURED']
  const th = {
    row:  selected
      ? (isDark ? 'bg-gold-400/8 border-gold-400/30' : 'bg-amber-50 border-amber-300')
      : (isDark ? 'border-white/4 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50'),
    id:   isDark ? 'text-gold-400' : 'text-amber-600',
    meta: isDark ? 'text-slate-400' : 'text-slate-500',
    muted: isDark ? 'text-slate-500' : 'text-slate-400',
  }

  return (
    <div onClick={onClick}
      className={`flex items-center gap-3 px-4 py-2.5 border-b ${th.row} cursor-pointer transition-colors`}>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className={`text-[11px] font-mono ${th.id}`}>{item.instrument_id}</span>
          <span className={`text-[10px] px-1.5 py-0.5 rounded border ${s.bg} ${s.color} font-medium shrink-0`}>{s.label}</span>
          {item.iqa_fail_reason && (
            <span className={`text-[9px] truncate max-w-[120px] text-red-400`} title={item.iqa_fail_reason}>⚠ {item.iqa_fail_reason}</span>
          )}
        </div>
        <div className={`flex gap-2 text-[10px] ${th.meta} mt-0.5 flex-wrap`}>
          <span>{item.account_display}</span>
          <span>·</span>
          <span className="truncate max-w-[120px]">{item.payee}</span>
          <span>·</span>
          <span>{item.amount}</span>
          <span>·</span>
          <span>{item.zone}</span>
          {item.lot_seq && (
            <>
              <span>·</span>
              <span className={isDark ? 'text-violet-400 font-medium' : 'text-violet-600 font-medium'}>
                Lot {item.lot_seq}
              </span>
            </>
          )}
        </div>
      </div>
      <div className={`shrink-0 text-[9px] font-mono ${th.muted}`}>
        {new Date(item.captured_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
      </div>
    </div>
  )
}

// ─── Outward Pipeline Visualizer ─────────────────────────────────────────────

const STAGE_MS = [850, 320, 1240, 680, 210, 1800, 420]

function OutwardPipelineViz({ item }) {
  const pos = pipelinePos(item.status)
  const isFail = ['IQA_FAIL', 'NGCH_REJECT'].includes(item.status)

  const getState = (i) => {
    if (i < pos) return 'done'
    if (i === pos) return isFail ? 'fail' : 'current'
    return 'pending'
  }

  const bankOf = (i) => i < 6 ? 'pres' : 'ngch'

  const NODE_STYLE = {
    done:    { bg: 'rgba(5,46,22,0.8)',  border: '#10b981', glow: 'rgba(16,185,129,0.5)',   icon: '✓', tc: '#34d399' },
    current: { bg: 'rgba(28,10,0,0.9)', border: '#f59e0b', glow: 'rgba(245,158,11,0.6)',   icon: null, tc: '#fbbf24' },
    fail:    { bg: 'rgba(28,5,5,0.9)',  border: '#ef4444', glow: 'rgba(239,68,68,0.5)',    icon: '✕', tc: '#f87171' },
    pending: { bg: 'rgba(15,23,42,0.5)', border: '#1e293b', glow: 'none',                  icon: null, tc: '#475569' },
  }
  const NGCH_CURRENT = { bg: 'rgba(0,26,36,0.9)', border: '#06b6d4', glow: 'rgba(6,182,212,0.6)', icon: null, tc: '#22d3ee' }

  // Track fill pct: how far along the 7-stage track
  const trackPct = Math.min(100, (pos / (PIPELINE_STEPS.length - 1)) * 100)

  return (
    <div className="relative rounded-xl border border-amber-500/20 overflow-hidden"
      style={{ background: 'linear-gradient(135deg, #05080f 0%, #0a0f1e 60%, #050d14 100%)' }}>

      {/* Subtle radial glow at current stage area */}
      <div className="absolute inset-0 pointer-events-none"
        style={{ background: `radial-gradient(ellipse 60% 80% at ${10 + trackPct * 0.8}% 50%, rgba(245,158,11,0.07) 0%, transparent 70%)` }} />

      {/* Phase labels row */}
      <div className="flex items-center px-4 pt-3 pb-1 gap-2">
        <div className="flex-1 flex items-center gap-1.5">
          <div className="w-1.5 h-1.5 rounded-full" style={{ background: '#f59e0b', boxShadow: '0 0 6px rgba(245,158,11,0.8)' }} />
          <span className="text-[9px] uppercase tracking-widest" style={{ color: 'rgba(245,158,11,0.6)' }}>Presenting Bank</span>
        </div>
        <div className="w-px h-3" style={{ background: 'rgba(255,255,255,0.1)' }} />
        <div className="flex items-center gap-1.5 shrink-0">
          <div className="w-1.5 h-1.5 rounded-full" style={{ background: '#06b6d4', boxShadow: '0 0 6px rgba(6,182,212,0.8)' }} />
          <span className="text-[9px] uppercase tracking-widest" style={{ color: 'rgba(6,182,212,0.6)' }}>NGCH</span>
        </div>
      </div>

      {/* Track + nodes */}
      <div className="relative px-4 pb-4 pt-1">
        {/* Track base */}
        <div className="absolute left-8 right-8 h-px" style={{ top: '28px', background: 'rgba(255,255,255,0.06)' }} />
        {/* Track fill */}
        <div className="absolute left-8 h-px transition-all duration-700"
          style={{
            top: '28px',
            width: `calc(${trackPct}% * (100% - 64px) / 100 + ${trackPct > 0 ? 0 : 0}px)`,
            width: `calc((100% - 64px) * ${trackPct / 100})`,
            background: isFail
              ? 'linear-gradient(90deg, #10b981 0%, #ef4444 100%)'
              : `linear-gradient(90deg, #10b981 0%, #f59e0b ${Math.min(100, trackPct + 5)}%)`,
            boxShadow: isFail ? '0 0 8px rgba(239,68,68,0.4)' : '0 0 8px rgba(245,158,11,0.4)',
            opacity: 0.7,
          }} />

        {/* Stage divider line before NGCH */}
        <div className="absolute w-px"
          style={{ left: `calc(64px + (100% - 64px) * ${5 / 6} - 8px)`, top: '8px', height: '44px', background: 'rgba(255,255,255,0.12)' }} />

        {/* Nodes */}
        <div className="flex items-start">
          {PIPELINE_STEPS.map((step, i) => {
            const state = getState(i)
            const bank = bankOf(i)
            let ns = NODE_STYLE[state]
            if (state === 'current' && bank === 'ngch') ns = NGCH_CURRENT
            if (state === 'fail' && bank === 'ngch') ns = { ...NODE_STYLE.fail }

            return (
              <div key={step.id} className="flex-1 min-w-0 flex flex-col items-center relative">
                {/* Node circle */}
                <div className="w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold border-2 transition-all duration-500 relative z-10"
                  style={{
                    background: ns.bg,
                    borderColor: ns.border,
                    boxShadow: ns.glow !== 'none' ? `0 0 14px ${ns.glow}, inset 0 0 8px ${ns.glow.replace('0.', '0.15')}` : 'none',
                  }}>
                  <span style={{ color: ns.tc, fontSize: state === 'pending' ? '14px' : '13px' }}>
                    {ns.icon ?? step.icon}
                  </span>
                  {/* Pulse ring on current */}
                  {state === 'current' && (
                    <div className="absolute inset-0 rounded-full border-2 animate-ping"
                      style={{ borderColor: ns.border, opacity: 0.35 }} />
                  )}
                </div>

                {/* Label */}
                <div className="text-[8px] mt-1.5 text-center leading-tight font-medium px-0.5"
                  style={{ color: ns.tc, opacity: state === 'pending' ? 0.5 : 1 }}>
                  {step.label}
                </div>

                {/* Timing / status sub-label */}
                <div className="text-[7px] mt-0.5 text-center" style={{ color: ns.tc, opacity: 0.55 }}>
                  {state === 'done'    && `${STAGE_MS[i]}ms`}
                  {state === 'current' && (isFail ? 'FAILED' : '● live')}
                  {state === 'pending' && '—'}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function DetailPanel({ item, isDark }) {
  if (!item) return (
    <div className={`flex-1 flex items-center justify-center ${isDark ? 'text-slate-500' : 'text-slate-300'} text-sm`}>
      Select a cheque to inspect
    </div>
  )
  const STATUS_META = isDark ? STATUS_META_D : STATUS_META_L
  const s  = STATUS_META[item.status] || STATUS_META['CAPTURED']
  const pos = pipelinePos(item.status)

  const th = {
    page:    isDark ? 'bg-transparent' : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900/50 border-white/10' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    lbl:     isDark ? 'text-slate-500' : 'text-slate-400',
    divider: isDark ? 'border-white/10' : 'border-slate-200',
    id:      isDark ? 'text-gold-400' : 'text-amber-600',
    bar:     isDark ? 'bg-white/5' : 'bg-slate-100',
  }

  const fields = [
    { label: 'Instrument ID',   val: item.instrument_id,  mono: true },
    { label: 'Account (masked)',val: item.account_display, mono: true },
    { label: 'Payee Name',      val: item.payee,           mono: false },
    { label: 'Amount',          val: item.amount,          mono: true },
    { label: 'Zone',            val: item.zone,            mono: false },
    { label: 'MICR Code',       val: item.micr,            mono: true },
    { label: 'Date on Cheque',  val: item.date_on_cheque,  mono: false },
    { label: 'Scanner ID',      val: item.scanner_id,      mono: true },
    { label: 'Lot Number',      val: item.lot_number,      mono: true },
  ]

  const checks = item.status !== 'IQA_FAIL' ? [
    { label: 'Amount words match', ok: item.amount_words_match, note: item.amount_words_match === false ? 'Words amount governs per NI Act' : null },
    { label: 'Date validity',      ok: item.date_valid },
    { label: 'CTS cheque valid',   ok: item.cts_valid },
    { label: 'OCR confidence',     ok: parseFloat(item.ocr_confidence) >= 0.85, val: `${(parseFloat(item.ocr_confidence) * 100).toFixed(0)}%` },
    { label: 'Signature score',    ok: parseFloat(item.sig_score) >= 0.78, val: `${(parseFloat(item.sig_score) * 100).toFixed(0)}%` },
  ] : []

  return (
    <div className={`flex flex-col h-full overflow-y-auto ${th.page}`}>
      {/* Header */}
      <div className={`shrink-0 px-5 py-3 border-b ${th.divider} flex items-center gap-3 flex-wrap`}>
        <span className={`text-[13px] font-mono font-semibold ${th.id}`}>{item.instrument_id}</span>
        <span className={`text-[10px] font-mono`}>·</span>
        <span className={`text-[11px] ${th.muted}`}>{item.zone}</span>
        <span className={`text-[10px] px-2 py-0.5 rounded border ${s.bg} ${s.color} font-medium`}>{s.label}</span>
        {item.ngch_ack_id && (
          <span className={`text-[9px] font-mono ${th.lbl}`}>ACK: {item.ngch_ack_id.slice(-12)}</span>
        )}
      </div>

      {/* Pipeline progress */}
      <div className={`shrink-0 px-5 py-3 border-b ${th.divider}`}>
        <div className={`text-[10px] uppercase tracking-widest ${th.lbl} mb-2`}>Outward Clearing Pipeline</div>
        <OutwardPipelineViz item={item} />
      </div>

      <div className="flex-1 px-5 py-4 space-y-4">
        {/* IQA fail alert */}
        {item.iqa_fail_reason && (
          <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3">
            <div className="text-[10px] text-red-400 uppercase tracking-widest mb-1">IQA Failure — Rescan Required</div>
            <div className="text-sm text-red-300 font-medium">{item.iqa_fail_reason}</div>
            <div className="text-[11px] text-red-400/70 mt-1">Instrument excluded from NGCH submission. Operator must rescan and re-submit.</div>
          </div>
        )}

        {/* Amount words mismatch alert */}
        {item.amount_words_match === false && (
          <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3">
            <div className="text-[10px] text-amber-400 uppercase tracking-widest mb-1">Amount Mismatch — NI Act §18</div>
            <div className="text-sm text-amber-300 font-medium">Amount in words governs over amount in figures</div>
            <div className="text-[11px] text-amber-400/70 mt-1">System uses words amount for NGCH submission. Verify with customer before proceed.</div>
          </div>
        )}

        {/* Extracted fields */}
        <div>
          <div className={`text-[10px] uppercase tracking-widest ${th.lbl} mb-2`}>Extracted Fields</div>
          <div className={`rounded-xl border ${th.card} divide-y ${th.divider}`}>
            {fields.map(f => (
              <div key={f.label} className="flex items-center justify-between px-4 py-2">
                <span className={`text-[11px] ${th.muted}`}>{f.label}</span>
                <span className={`text-[11px] ${f.mono ? 'font-mono' : ''} ${th.body}`}>{f.val ?? '—'}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Cross-validation */}
        {checks.length > 0 && (
          <div>
            <div className={`text-[10px] uppercase tracking-widest ${th.lbl} mb-2`}>Cross-Validation</div>
            <div className={`rounded-xl border ${th.card} divide-y ${th.divider}`}>
              {checks.map(c => (
                <div key={c.label} className="flex items-center justify-between px-4 py-2">
                  <div>
                    <span className={`text-[11px] ${th.muted}`}>{c.label}</span>
                    {c.note && <div className={`text-[9px] text-amber-400/80 mt-0.5`}>{c.note}</div>}
                  </div>
                  <div className="flex items-center gap-2">
                    {c.val && <span className={`text-[11px] font-mono ${th.body}`}>{c.val}</span>}
                    <span className={`text-[11px] font-semibold ${c.ok ? (isDark ? 'text-emerald-400' : 'text-emerald-600') : 'text-red-400'}`}>
                      {c.ok ? '✓' : '✕'}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* NGCH submission details */}
        {['SUBMITTED', 'NGCH_ACK', 'NGCH_REJECT'].includes(item.status) && (
          <div>
            <div className={`text-[10px] uppercase tracking-widest ${th.lbl} mb-2`}>NGCH Submission</div>
            <div className={`rounded-xl border ${th.card} divide-y ${th.divider}`}>
              <div className="flex items-center justify-between px-4 py-2">
                <span className={`text-[11px] ${th.muted}`}>Transport</span>
                <span className={`text-[11px] ${th.body}`}>SFTP → NGCH DEM</span>
              </div>
              <div className="flex items-center justify-between px-4 py-2">
                <span className={`text-[11px] ${th.muted}`}>File format</span>
                <span className={`text-[11px] font-mono ${th.body}`}>CXF (XML) + CIBF</span>
              </div>
              <div className="flex items-center justify-between px-4 py-2">
                <span className={`text-[11px] ${th.muted}`}>HSM signed</span>
                <span className={`text-[11px] ${isDark ? 'text-emerald-400' : 'text-emerald-600'}`}>✓ FIPS 140-2 L3</span>
              </div>
              {item.ngch_ack_id && (
                <div className="flex items-center justify-between px-4 py-2">
                  <span className={`text-[11px] ${th.muted}`}>NGCH ACK ID</span>
                  <span className={`text-[10px] font-mono ${th.body}`}>{item.ngch_ack_id.slice(-16)}</span>
                </div>
              )}
              {item.status === 'NGCH_REJECT' && (
                <div className="flex items-center justify-between px-4 py-2">
                  <span className={`text-[11px] text-red-400`}>Reject reason</span>
                  <span className={`text-[11px] text-red-400`}>Invalid MICR / Duplicate</span>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function CTSPresentment() {
  const { isDark } = useTheme()
  const [batch, setBatch] = useState(INITIAL_BATCH)
  const [selected, setSelected] = useState(INITIAL_BATCH[0])
  const [activeSession, setActiveSession] = useState(0)
  const [filterStatus, setFilterStatus] = useState('ALL')
  const [filterLot, setFilterLot]       = useState('ALL')
  const [search, setSearch] = useState('')

  const addedRef = useRef(42)

  // Simulate incoming captures from scanner feed
  useEffect(() => {
    const timer = setInterval(() => {
      if (Math.random() > 0.35) return
      const newItem = makeBatch(1, addedRef.current)[0]
      addedRef.current += 1
      setBatch(prev => [newItem, ...prev].slice(0, 200))
    }, 2800)
    return () => clearInterval(timer)
  }, [])

  // Simulate status progression
  useEffect(() => {
    const timer = setInterval(() => {
      setBatch(prev => prev.map(item => {
        if (Math.random() > 0.12) return item
        const progress = {
          CAPTURED: 'IQA_PASS',
          IQA_PASS: 'AI_EXTRACTED',
          AI_EXTRACTED: 'PKI_SIGNED',
          PKI_SIGNED: 'SUBMITTED',
          SUBMITTED: Math.random() > 0.06 ? 'NGCH_ACK' : 'NGCH_REJECT',
        }
        const next = progress[item.status]
        if (!next) return item
        return { ...item, status: next }
      }))
    }, 1800)
    return () => clearInterval(timer)
  }, [])

  const STATUS_META = isDark ? STATUS_META_D : STATUS_META_L

  const th = {
    page:    isDark ? 'bg-transparent' : 'bg-slate-50',
    divider: isDark ? 'border-white/10' : 'border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    lbl:     isDark ? 'text-slate-500' : 'text-slate-400',
    search:  isDark
      ? 'bg-white/5 border-white/10 text-slate-300 placeholder:text-slate-600 focus:border-gold-400/40'
      : 'bg-white border-slate-300 text-slate-700 placeholder:text-slate-400 focus:border-amber-400',
    sel:     isDark
      ? 'bg-white/5 border-white/10 text-slate-300 focus:border-gold-400/40'
      : 'bg-white border-slate-300 text-slate-700 focus:border-amber-400',
  }

  const allStatuses = ['ALL', ...Object.keys(STATUS_META)]

  // Derive unique lot numbers from batch for the lot filter dropdown
  const lotNumbers = ['ALL', ...Array.from(new Set(batch.map(b => b.lot_number).filter(Boolean)))
    .sort()]

  const visible = batch.filter(item => {
    if (filterStatus === 'AMT_MISMATCH') {
      if (item.amount_words_match !== false) return false
    } else if (filterStatus === 'DATE_INVALID') {
      if (item.date_valid !== false) return false
    } else if (filterStatus === 'AI_EXTRACTED') {
      if (!['AI_EXTRACTED','PKI_SIGNED','SUBMITTED','NGCH_ACK','NGCH_REJECT'].includes(item.status)) return false
    } else if (filterStatus === 'SUBMITTED') {
      if (!['SUBMITTED','NGCH_ACK','NGCH_REJECT'].includes(item.status)) return false
    } else if (filterStatus !== 'ALL') {
      if (item.status !== filterStatus) return false
    }
    if (filterLot !== 'ALL' && item.lot_number !== filterLot) return false
    if (search && !item.instrument_id.toLowerCase().includes(search.toLowerCase())
        && !item.payee.toLowerCase().includes(search.toLowerCase())
        && !item.account_display.includes(search)) return false
    return true
  })

  return (
    <AppShell>
      <div className={`flex flex-col h-full ${th.page}`}>
        {/* Session selector */}
        <SessionBar sessions={SESSIONS} activeIdx={activeSession} onSelect={setActiveSession} />

        {/* KPI strip */}
        <KpiStrip batch={batch} filterStatus={filterStatus} onFilter={setFilterStatus} isDark={isDark} />

        {/* Pipeline progress */}
        <PipelineLane batch={batch} isDark={isDark} />

        {/* Main body: list + detail */}
        <div className="flex flex-1 min-h-0">
          {/* Batch list */}
          <div className={`w-[480px] shrink-0 border-r ${th.divider} flex flex-col`}>
            {/* Toolbar */}
            <div className={`shrink-0 px-3 py-2 border-b ${th.divider} flex items-center gap-2`}>
              <input
                value={search} onChange={e => setSearch(e.target.value)}
                placeholder="Search ID / payee / account…"
                className={`flex-1 text-[11px] rounded-lg border px-3 py-1.5 focus:outline-none ${th.search}`}
              />
              <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)}
                className={`text-[11px] rounded-lg border px-2 py-1.5 focus:outline-none ${th.sel}`}>
                {allStatuses.map(s => (
                  <option key={s} value={s}>{s === 'ALL' ? 'All Statuses' : (STATUS_META[s]?.label ?? s)}</option>
                ))}
              </select>
              <select value={filterLot} onChange={e => setFilterLot(e.target.value)}
                className={`text-[11px] rounded-lg border px-2 py-1.5 focus:outline-none ${th.sel}`}>
                {lotNumbers.map(l => (
                  <option key={l} value={l}>
                    {l === 'ALL' ? 'All Lots' : `Lot ${batch.find(b => b.lot_number === l)?.lot_seq ?? l}`}
                  </option>
                ))}
              </select>
              <span className={`text-[10px] font-mono shrink-0 ${th.lbl}`}>{visible.length}/{batch.length}</span>
            </div>

            {/* Column headers */}
            <div className={`shrink-0 px-4 py-1.5 border-b ${th.divider} flex items-center gap-2`}>
              <span className={`text-[9px] uppercase tracking-widest ${th.lbl} flex-1`}>Instrument · Payee · Amount</span>
              <span className={`text-[9px] uppercase tracking-widest ${th.lbl}`}>Time</span>
            </div>

            <div className="flex-1 overflow-y-auto">
              {visible.length === 0 && (
                <div className={`text-center ${th.lbl} text-sm py-16`}>No cheques match filter</div>
              )}
              {visible.map(item => (
                <BatchRow
                  key={item.instrument_id}
                  item={item}
                  selected={selected?.instrument_id === item.instrument_id}
                  onClick={() => setSelected(item)}
                />
              ))}
            </div>
          </div>

          {/* Detail panel */}
          <div className="flex-1 min-w-0">
            <DetailPanel item={selected} isDark={isDark} />
          </div>
        </div>
      </div>
    </AppShell>
  )
}

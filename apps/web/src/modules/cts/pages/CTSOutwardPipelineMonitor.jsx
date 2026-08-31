/**
 * CTSOutwardPipelineMonitor — React Flow swimlane for outward clearing.
 * Stages: SCANNED → IQA → AI_EXTRACTED → PKI_SIGNED → LOT → ENDORSED → NGCH
 *
 * Unlike inward, there is no per-cheque IET watchdog. The risk here is the
 * session submission window: NGCH closes at 12:00 and 16:00. Instruments not
 * submitted in time are deferred to the next session.
 */
import { useState, useCallback, useMemo } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  Panel,
  BackgroundVariant,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'

// ── Layout constants ──────────────────────────────────────────────────────────

const LANE_W   = 172
const HDR_H    = 56
const CHQ_W    = 150
const CHQ_H    = 108
const CHQ_PAD  = 11
const CHQ_VPAD = 12
const CHQ_GAP  = 10

// ── Stage config ─────────────────────────────────────────────────────────────

export const STAGES = [
  { id: 'SCANNED',      label: 'Scanned',       icon: '📄', x: 0            },
  { id: 'IQA',          label: 'IQA',           icon: '🔬', x: LANE_W       },
  { id: 'AI_EXTRACTED', label: 'AI Extracted',  icon: '🤖', x: LANE_W * 2   },
  { id: 'PKI_SIGNED',   label: 'PKI Signed',    icon: '🔐', x: LANE_W * 3   },
  { id: 'LOT',          label: 'Lot Assembled', icon: '📦', x: LANE_W * 4   },
  { id: 'ENDORSED',     label: 'Endorsed',      icon: '✅', x: LANE_W * 5   },
  { id: 'NGCH',         label: 'NGCH Filed',    icon: '📤', x: LANE_W * 6   },
]

// ── Session deadline urgency (outward equivalent of IET urgency) ──────────────

export function sessionUrgency(sessionDeadlineMs) {
  const mins = Math.max(0, (sessionDeadlineMs - Date.now()) / 60000)
  if (mins < 5)  return 'urgent'
  if (mins < 20) return 'critical'
  if (mins < 45) return 'warning'
  if (mins < 90) return 'caution'
  return 'safe'
}

// ── Stage urgency (IQA fail, AI low-conf) ────────────────────────────────────

export function stageUrgency(instr) {
  if (instr.iqa_fail)          return 'critical'
  if (instr.cts_violation)     return 'critical'
  if (instr.amount_mismatch)   return 'warning'
  if (instr.ocr_conf < 0.85)   return 'warning'
  return sessionUrgency(instr.sessionDeadline)
}

// ── Mock instruments ──────────────────────────────────────────────────────────

export function makeMockInstruments() {
  const now = Date.now()
  const SESSION_CLOSE = now + 94 * 60000  // next NGCH window closes in 94 minutes

  const DRAWEES = ['SBI Andheri', 'HDFC Bandra', 'Axis Colaba', 'BOB Dadar', 'ICICI Nariman', 'PNB Fort', 'Canara Fort', 'UBI Mumbai']
  const AMOUNTS = ['₹[<1L]', '₹[1L-5L]', '₹[5L-10L]', '₹[10L-1Cr]', '₹[1L-5L]', '₹[<1L]', '₹[1L-5L]']
  const LOTS    = ['LOT-01', 'LOT-01', 'LOT-02', 'LOT-02', 'LOT-03']

  return [
    // SCANNED — just captured, awaiting IQA
    { id: 'OUT-8841', stage: 'SCANNED',      drawee: DRAWEES[0], amount: AMOUNTS[0], lot: null,      sessionDeadline: SESSION_CLOSE, ocr_conf: null,  iqa_fail: false, cts_violation: false, amount_mismatch: false, scanner: 'SCN-01' },
    { id: 'OUT-8842', stage: 'SCANNED',      drawee: DRAWEES[1], amount: AMOUNTS[1], lot: null,      sessionDeadline: SESSION_CLOSE, ocr_conf: null,  iqa_fail: false, cts_violation: false, amount_mismatch: false, scanner: 'SCN-02' },
    { id: 'OUT-8843', stage: 'SCANNED',      drawee: DRAWEES[2], amount: AMOUNTS[2], lot: null,      sessionDeadline: SESSION_CLOSE, ocr_conf: null,  iqa_fail: false, cts_violation: false, amount_mismatch: false, scanner: 'SCN-01' },
    // IQA — image quality being assessed
    { id: 'OUT-8835', stage: 'IQA',          drawee: DRAWEES[3], amount: AMOUNTS[3], lot: null,      sessionDeadline: SESSION_CLOSE, ocr_conf: null,  iqa_fail: false, cts_violation: false, amount_mismatch: false, iqa_score: 0.96 },
    { id: 'OUT-8836', stage: 'IQA',          drawee: DRAWEES[4], amount: AMOUNTS[4], lot: null,      sessionDeadline: SESSION_CLOSE, ocr_conf: null,  iqa_fail: true,  cts_violation: false, amount_mismatch: false, iqa_score: 0.38, iqa_reason: 'Image skew > 2°' },
    // AI_EXTRACTED — OCR + Qwen2-VL complete
    { id: 'OUT-8829', stage: 'AI_EXTRACTED', drawee: DRAWEES[5], amount: AMOUNTS[5], lot: null,      sessionDeadline: SESSION_CLOSE, ocr_conf: 0.98,  iqa_fail: false, cts_violation: false, amount_mismatch: false },
    { id: 'OUT-8830', stage: 'AI_EXTRACTED', drawee: DRAWEES[6], amount: AMOUNTS[6], lot: null,      sessionDeadline: SESSION_CLOSE, ocr_conf: 0.81,  iqa_fail: false, cts_violation: false, amount_mismatch: true  },
    { id: 'OUT-8831', stage: 'AI_EXTRACTED', drawee: DRAWEES[0], amount: AMOUNTS[0], lot: null,      sessionDeadline: SESSION_CLOSE, ocr_conf: 0.97,  iqa_fail: false, cts_violation: true,  amount_mismatch: false },
    // PKI_SIGNED — HSM FIPS 140-2 signed
    { id: 'OUT-8820', stage: 'PKI_SIGNED',   drawee: DRAWEES[1], amount: AMOUNTS[1], lot: null,      sessionDeadline: SESSION_CLOSE, ocr_conf: 0.99,  iqa_fail: false, cts_violation: false, amount_mismatch: false },
    { id: 'OUT-8821', stage: 'PKI_SIGNED',   drawee: DRAWEES[2], amount: AMOUNTS[2], lot: null,      sessionDeadline: SESSION_CLOSE, ocr_conf: 0.97,  iqa_fail: false, cts_violation: false, amount_mismatch: false },
    // LOT — assembled into lot, awaiting endorsement
    { id: 'OUT-8812', stage: 'LOT',          drawee: DRAWEES[3], amount: AMOUNTS[3], lot: LOTS[0],   sessionDeadline: SESSION_CLOSE, ocr_conf: 0.98,  iqa_fail: false, cts_violation: false, amount_mismatch: false },
    { id: 'OUT-8813', stage: 'LOT',          drawee: DRAWEES[4], amount: AMOUNTS[4], lot: LOTS[1],   sessionDeadline: SESSION_CLOSE, ocr_conf: 0.96,  iqa_fail: false, cts_violation: false, amount_mismatch: false },
    { id: 'OUT-8814', stage: 'LOT',          drawee: DRAWEES[5], amount: AMOUNTS[0], lot: LOTS[2],   sessionDeadline: SESSION_CLOSE, ocr_conf: 0.99,  iqa_fail: false, cts_violation: false, amount_mismatch: false },
    // ENDORSED — batch stamped, ready for NGCH submission
    { id: 'OUT-8804', stage: 'ENDORSED',     drawee: DRAWEES[6], amount: AMOUNTS[1], lot: LOTS[0],   sessionDeadline: SESSION_CLOSE, ocr_conf: 0.98,  iqa_fail: false, cts_violation: false, amount_mismatch: false },
    { id: 'OUT-8805', stage: 'ENDORSED',     drawee: DRAWEES[0], amount: AMOUNTS[2], lot: LOTS[3],   sessionDeadline: SESSION_CLOSE, ocr_conf: 0.97,  iqa_fail: false, cts_violation: false, amount_mismatch: false },
    // NGCH — submitted, awaiting acknowledgement
    { id: 'OUT-8795', stage: 'NGCH',         drawee: DRAWEES[1], amount: AMOUNTS[3], lot: LOTS[4],   sessionDeadline: SESSION_CLOSE, ocr_conf: 0.99,  iqa_fail: false, cts_violation: false, amount_mismatch: false, ngch_status: 'ACK_PENDING' },
    { id: 'OUT-8796', stage: 'NGCH',         drawee: DRAWEES[2], amount: AMOUNTS[5], lot: LOTS[0],   sessionDeadline: SESSION_CLOSE, ocr_conf: 0.98,  iqa_fail: false, cts_violation: false, amount_mismatch: false, ngch_status: 'ACCEPTED'    },
  ]
}

// ── Node builder ──────────────────────────────────────────────────────────────

export function buildInitialNodes(instruments) {
  const nodes = []
  STAGES.forEach(stage => {
    const inStage = instruments.filter(i => i.stage === stage.id)
    const hasCrit = inStage.some(i => ['critical', 'urgent'].includes(stageUrgency(i)))
    nodes.push({
      id:          `hdr-${stage.id}`,
      type:        'stageHeader',
      position:    { x: stage.x, y: 0 },
      data:        { label: stage.label, icon: stage.icon, count: inStage.length, hasCrit },
      draggable:   false,
      selectable:  false,
      connectable: false,
    })
  })
  const counters = {}
  instruments.forEach(instr => {
    const stage = STAGES.find(s => s.id === instr.stage)
    if (!stage) return
    const idx = counters[instr.stage] ?? 0
    counters[instr.stage] = idx + 1
    nodes.push({
      id:          instr.id,
      type:        'chequeNode',
      position:    { x: stage.x + CHQ_PAD, y: HDR_H + CHQ_VPAD + idx * (CHQ_H + CHQ_GAP) },
      data:        { ...instr },
      draggable:   false,
      connectable: false,
    })
  })
  return nodes
}

// ── Custom node: StageHeaderNode ──────────────────────────────────────────────

function StageHeaderNode({ data }) {
  const { isDark } = useTheme()
  return (
    <div
      style={{ width: LANE_W, height: HDR_H }}
      className={`flex flex-col items-center justify-center select-none border-b
        ${isDark ? 'bg-navy-900/70 border-white/10 text-slate-300' : 'bg-slate-100 border-slate-200 text-slate-600'}`}
    >
      <span className="text-base leading-none">{data.icon}</span>
      <span className={`text-[10px] font-mono uppercase tracking-widest mt-0.5
        ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>
        {data.label}
      </span>
      {data.count > 0 && (
        <span className={`text-[9px] font-mono mt-0.5
          ${data.hasCrit ? 'text-red-400' : isDark ? 'text-slate-600' : 'text-slate-400'}`}>
          {data.count} instrument{data.count > 1 ? 's' : ''}
        </span>
      )}
    </div>
  )
}

// ── Custom node: OutwardChequeNode ────────────────────────────────────────────

const URGENCY_BORDER = {
  urgent:   'border-red-500',
  critical: 'border-red-400',
  warning:  'border-amber-400',
  caution:  'border-yellow-300',
  safe:     'border-emerald-500/50',
}
const URGENCY_BG_D = {
  urgent:   'bg-red-950/70',
  critical: 'bg-red-900/30',
  warning:  'bg-amber-900/20',
  caution:  'bg-yellow-900/10',
  safe:     'bg-navy-900',
}
const URGENCY_BG_L = {
  urgent:   'bg-red-50',
  critical: 'bg-orange-50',
  warning:  'bg-amber-50',
  caution:  'bg-yellow-50',
  safe:     'bg-white',
}

function OutwardChequeNode({ data, selected }) {
  const { isDark } = useTheme()
  const u = stageUrgency(data)
  const minsLeft = Math.max(0, Math.round((data.sessionDeadline - Date.now()) / 60000))
  const urgent = minsLeft < 20

  return (
    <div
      style={{ width: CHQ_W, height: CHQ_H }}
      className={`rounded-lg border-2 px-3 py-2 cursor-pointer transition-shadow
        ${URGENCY_BORDER[u]}
        ${isDark ? URGENCY_BG_D[u] : URGENCY_BG_L[u]}
        ${selected ? (isDark ? 'ring-2 ring-amber-400 ring-offset-1 ring-offset-navy-900' : 'ring-2 ring-amber-500 ring-offset-1') : ''}
        ${u === 'urgent' ? 'animate-pulse' : ''}`}
    >
      {/* ID + lot badge */}
      <div className="flex items-center justify-between mb-1">
        <span className={`font-mono text-[10px] font-semibold
          ${isDark ? 'text-slate-300' : 'text-slate-700'}`}>
          ****{data.id.slice(-4)}
        </span>
        {data.lot && (
          <span className={`text-[9px] font-mono px-1 py-0.5 rounded
            ${isDark ? 'bg-sky-900/60 text-sky-300' : 'bg-sky-100 text-sky-700'}`}>
            {data.lot}
          </span>
        )}
      </div>

      {/* Drawee bank */}
      <div className={`text-[10px] truncate mb-0.5 ${isDark ? 'text-slate-300' : 'text-slate-700'}`}>
        {data.drawee}
      </div>

      {/* Amount */}
      <div className={`text-[11px] font-mono mb-1.5 ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>
        {data.amount}
      </div>

      {/* Stage-specific indicator */}
      {data.iqa_fail && (
        <div className="text-[9px] font-bold text-red-400 truncate">⚠ IQA FAIL — Rescan</div>
      )}
      {data.cts_violation && !data.iqa_fail && (
        <div className="text-[9px] font-bold text-red-400 truncate">⚠ CTS-2010 Fail</div>
      )}
      {data.amount_mismatch && !data.iqa_fail && !data.cts_violation && (
        <div className="text-[9px] font-bold text-amber-400 truncate">⚠ Amount Mismatch</div>
      )}
      {data.ocr_conf != null && !data.iqa_fail && !data.cts_violation && !data.amount_mismatch && (
        <div className={`text-[9px] font-mono ${data.ocr_conf >= 0.95 ? (isDark ? 'text-emerald-400' : 'text-emerald-600') : 'text-amber-400'}`}>
          OCR {Math.round(data.ocr_conf * 100)}%
        </div>
      )}
      {data.ngch_status && (
        <div className={`text-[9px] font-bold ${data.ngch_status === 'ACCEPTED' ? 'text-emerald-400' : (isDark ? 'text-sky-400' : 'text-sky-600')}`}>
          {data.ngch_status === 'ACCEPTED' ? '✓ Accepted' : '⟳ Ack Pending'}
        </div>
      )}

      {/* Session countdown */}
      <div className={`text-[9px] font-mono mt-1 ${urgent ? 'text-red-400 font-bold' : (isDark ? 'text-slate-500' : 'text-slate-400')}`}>
        Window: {minsLeft}m {urgent ? '⚠' : ''}
      </div>
    </div>
  )
}

// ── Node types ────────────────────────────────────────────────────────────────

const nodeTypes = {
  stageHeader: StageHeaderNode,
  chequeNode:  OutwardChequeNode,
}

// ── Detail panel ──────────────────────────────────────────────────────────────

function DetailPanel({ instr, onClose, isDark }) {
  const th = {
    surface: isDark ? 'bg-navy-900 border-white/8'    : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'                    : 'text-slate-900',
    body:    isDark ? 'text-slate-300'                : 'text-slate-700',
    muted:   isDark ? 'text-slate-400'                : 'text-slate-500',
    lbl:     isDark ? 'text-slate-500'                : 'text-slate-400',
    stat:    isDark ? 'bg-navy-800/60 border-white/6' : 'bg-slate-100 border-slate-200',
    divider: isDark ? 'border-white/8'                : 'border-slate-200',
  }

  const minsLeft = Math.max(0, Math.round((instr.sessionDeadline - Date.now()) / 60000))
  const u = stageUrgency(instr)
  const urgentColor = { urgent: 'text-red-400', critical: 'text-red-400', warning: 'text-amber-400', caution: 'text-yellow-400', safe: 'text-emerald-400' }[u]

  const rows = [
    { label: 'Instrument',   value: `****${instr.id.slice(-4)}` },
    { label: 'Stage',        value: instr.stage },
    { label: 'Drawee Bank',  value: instr.drawee },
    { label: 'Amount',       value: instr.amount },
    { label: 'Lot',          value: instr.lot ?? '—' },
    { label: 'Scanner',      value: instr.scanner ?? '—' },
    { label: 'OCR Confidence', value: instr.ocr_conf != null ? `${Math.round(instr.ocr_conf * 100)}%` : '—' },
    { label: 'NGCH Status',  value: instr.ngch_status ?? '—' },
  ].filter(r => r.value !== '—')

  const alerts = [
    instr.iqa_fail        && { sev: 'critical', msg: `IQA fail — ${instr.iqa_reason ?? 'Rescan required'}` },
    instr.cts_violation   && { sev: 'critical', msg: 'CTS-2010 compliance violation' },
    instr.amount_mismatch && { sev: 'warning',  msg: 'Amount in figures ≠ words — routed to Verification OQ' },
    instr.ocr_conf != null && instr.ocr_conf < 0.85 && { sev: 'warning', msg: `Low OCR confidence (${Math.round(instr.ocr_conf * 100)}%) — manual verification needed` },
  ].filter(Boolean)

  return (
    <div className={`w-72 border-l flex flex-col gap-4 p-5 overflow-y-auto ${th.surface}`}>
      <div className="flex items-center justify-between">
        <span className={`text-sm font-semibold ${th.heading}`}>Outward Detail</span>
        <button onClick={onClose} className={`text-lg leading-none ${th.muted} hover:opacity-70`}>×</button>
      </div>

      {/* Session window countdown */}
      <div className={`rounded-xl border px-4 py-3 ${th.stat}`}>
        <div className={`text-[10px] uppercase tracking-wide font-semibold ${th.lbl}`}>Session Window</div>
        <div className={`text-2xl font-mono font-bold mt-1 ${urgentColor}`}>{minsLeft}m</div>
        <div className={`text-[11px] mt-0.5 ${th.muted}`}>
          {minsLeft < 20 ? 'URGENT — submit before NGCH closes' : 'Until next NGCH submission close'}
        </div>
      </div>

      {/* Alert pills */}
      {alerts.length > 0 && (
        <div className="space-y-2">
          {alerts.map((a, i) => (
            <div key={i} className={`text-[11px] px-3 py-2 rounded-lg border ${
              a.sev === 'critical'
                ? (isDark ? 'bg-red-900/30 border-red-700/40 text-red-300' : 'bg-red-50 border-red-300 text-red-700')
                : (isDark ? 'bg-amber-900/20 border-amber-700/30 text-amber-300' : 'bg-amber-50 border-amber-300 text-amber-700')
            }`}>⚠ {a.msg}</div>
          ))}
        </div>
      )}

      {/* Field rows */}
      <div className={`rounded-xl border divide-y ${isDark ? 'border-white/8 divide-white/5' : 'border-slate-200 divide-slate-100'}`}>
        {rows.map(r => (
          <div key={r.label} className="flex items-center justify-between px-4 py-2.5">
            <span className={`text-[11px] ${th.lbl}`}>{r.label}</span>
            <span className={`text-[11px] font-medium ${th.body}`}>{r.value}</span>
          </div>
        ))}
      </div>

      {/* Stage note */}
      <div className={`text-[11px] px-3 py-2.5 rounded-lg border leading-relaxed ${th.stat} ${th.muted}`}>
        {{
          SCANNED:      'Scanner captured — awaiting IQA pass before AI extraction.',
          IQA:          'Image quality assessment in progress. IQA fail → operator rescan.',
          AI_EXTRACTED: 'GOT-OCR2.0 + Qwen2-VL 72B running. Amount mismatch → Verification OQ.',
          PKI_SIGNED:   'FIPS 140-2 Level 3 HSM signing complete — CTS-2010 PKI requirement.',
          LOT:          `Lot assembled. NGCH allows max 25 instruments per lot per filing.`,
          ENDORSED:     'Batch endorsement stamp applied — bank IFSC + date + authorisation.',
          NGCH:         'Filed to NGCH clearing house. Awaiting settlement acknowledgement.',
        }[instr.stage] ?? ''}
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

const INSTRUMENTS = makeMockInstruments()

export default function CTSOutwardPipelineMonitor() {
  const { isDark } = useTheme()
  const { bankName } = useBankContext()
  const [selectedId, setSelectedId] = useState(null)

  const th = {
    page:    isDark ? 'bg-navy-950'                    : 'bg-slate-50',
    surface: isDark ? 'bg-navy-900 border-white/8'     : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'                     : 'text-slate-900',
    muted:   isDark ? 'text-slate-400'                 : 'text-slate-500',
    divider: isDark ? 'border-white/8'                 : 'border-slate-200',
    stat:    isDark ? 'bg-navy-800/50 border-white/6'  : 'bg-slate-100 border-slate-200',
    flow:    isDark ? '#03061a'                         : '#f8fafc',
  }

  const initialNodes = useMemo(() => buildInitialNodes(INSTRUMENTS), [])
  const [nodes, , onNodesChange] = useNodesState(initialNodes)

  const onNodeClick = useCallback((_, node) => {
    if (node.type !== 'chequeNode') return
    setSelectedId(prev => prev === node.id ? null : node.id)
  }, [])
  const onPaneClick = useCallback(() => setSelectedId(null), [])

  const total       = INSTRUMENTS.length
  const iqaFails    = INSTRUMENTS.filter(i => i.iqa_fail).length
  const ctsViolations = INSTRUMENTS.filter(i => i.cts_violation).length
  const amtMismatch = INSTRUMENTS.filter(i => i.amount_mismatch).length
  const ngchFiled   = INSTRUMENTS.filter(i => i.stage === 'NGCH').length
  const selected    = selectedId ? INSTRUMENTS.find(i => i.id === selectedId) : null

  const maxPerStage = STAGES.reduce((m, s) => Math.max(m, INSTRUMENTS.filter(i => i.stage === s.id).length), 0)
  const canvasHeight = HDR_H + CHQ_VPAD + maxPerStage * (CHQ_H + CHQ_GAP) + 40

  return (
    <AppShell>
      <div className={`flex-1 flex flex-col overflow-hidden ${th.page}`}>

        {/* Page header */}
        <div className={`flex items-center justify-between px-6 py-4 border-b ${th.divider} ${th.surface}`}>
          <div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>Outward Pipeline Monitor</h1>
            <p className={`text-xs mt-0.5 ${th.muted}`}>
              {bankName} · {total} instruments in outward clearing pipeline — current session
            </p>
          </div>
          <div className={`flex items-center gap-2`}>
            {(iqaFails + ctsViolations + amtMismatch) > 0 && (
              <div className={`text-[10px] font-mono px-3 py-1.5 rounded-full border ${isDark ? 'bg-red-900/30 border-red-700/40 text-red-300' : 'bg-red-50 border-red-300 text-red-700'}`}>
                {iqaFails + ctsViolations + amtMismatch} flagged
              </div>
            )}
            <div className={`text-[10px] font-mono px-3 py-1.5 rounded-full border ${th.stat} ${th.muted}`}>
              LIVE · outward session
            </div>
          </div>
        </div>

        {/* Stats bar */}
        <div className={`flex items-center gap-3 px-6 py-3 border-b ${th.divider}`}>
          {[
            { label: 'In Pipeline',    value: total,         color: th.heading },
            { label: 'IQA Fails',      value: iqaFails,      color: iqaFails      > 0 ? 'text-red-400'     : th.muted },
            { label: 'CTS Violations', value: ctsViolations, color: ctsViolations > 0 ? 'text-red-400'     : th.muted },
            { label: 'Amt Mismatch',   value: amtMismatch,   color: amtMismatch   > 0 ? 'text-amber-400'   : th.muted },
            { label: 'NGCH Filed',     value: ngchFiled,     color: 'text-emerald-400' },
          ].map(s => (
            <div key={s.label} className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border ${th.stat}`}>
              <span className={`text-xl font-mono font-bold tabular-nums leading-none ${s.color}`}>{s.value}</span>
              <span className={`text-xs ${th.muted}`}>{s.label}</span>
            </div>
          ))}
        </div>

        {/* Canvas + detail panel */}
        <div className="flex flex-1 min-h-0 overflow-hidden">
          <div className="flex-1 relative h-full">
            <ReactFlow
              nodes={nodes}
              edges={[]}
              nodeTypes={nodeTypes}
              onNodesChange={onNodesChange}
              onNodeClick={onNodeClick}
              onPaneClick={onPaneClick}
              fitView
              fitViewOptions={{ padding: 0.12, maxZoom: 1 }}
              panOnDrag
              zoomOnScroll
              minZoom={0.35}
              maxZoom={1.5}
              proOptions={{ hideAttribution: true }}
              style={{ background: th.flow }}
            >
              <Background
                variant={BackgroundVariant.Dots}
                color={isDark ? '#0b1554' : '#e2e8f0'}
                gap={22}
                size={1.5}
              />
              <Controls
                showInteractive={false}
                style={{
                  background: isDark ? '#060d2e' : '#ffffff',
                  border: isDark ? '1px solid rgba(255,255,255,0.08)' : '1px solid #e2e8f0',
                  borderRadius: 8,
                }}
              />
              <MiniMap
                nodeColor={n => {
                  if (n.type !== 'chequeNode') return isDark ? '#0b1554' : '#e2e8f0'
                  const u = stageUrgency(n.data)
                  return { urgent: '#ef4444', critical: '#f87171', warning: '#fbbf24', caution: '#fde68a', safe: '#34d399' }[u]
                }}
                maskColor={isDark ? 'rgba(3,6,26,0.75)' : 'rgba(248,250,252,0.75)'}
                style={{
                  background: isDark ? '#060d2e' : '#f1f5f9',
                  border: isDark ? '1px solid rgba(255,255,255,0.08)' : '1px solid #e2e8f0',
                  borderRadius: 8,
                }}
              />
              <Panel position="bottom-left">
                <div className={`flex items-center gap-3 text-[10px] font-mono px-3 py-2 rounded-lg border ${th.stat} ${th.muted}`}>
                  <span>Status:</span>
                  {[
                    { label: 'OK',      color: 'bg-emerald-500' },
                    { label: 'Watch',   color: 'bg-yellow-400'  },
                    { label: 'Warning', color: 'bg-amber-400'   },
                    { label: 'Action',  color: 'bg-red-400'     },
                    { label: 'URGENT',  color: 'bg-red-500 animate-pulse' },
                  ].map(l => (
                    <span key={l.label} className="flex items-center gap-1">
                      <span className={`inline-block w-2 h-2 rounded-full ${l.color}`} />
                      {l.label}
                    </span>
                  ))}
                </div>
              </Panel>
            </ReactFlow>
          </div>

          {selected && (
            <DetailPanel instr={selected} onClose={() => setSelectedId(null)} isDark={isDark} />
          )}
        </div>
      </div>
    </AppShell>
  )
}

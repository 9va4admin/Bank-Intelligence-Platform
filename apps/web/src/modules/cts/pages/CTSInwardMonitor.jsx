import { useState, useCallback, useMemo, useEffect, useRef } from 'react'
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
import IETTimer from '../components/IETTimer'

const _API_BASE = import.meta.env.VITE_API_BASE ?? ''

function useLiveFlow({ pollEnabled }) {
  const [items, setItems] = useState(null)
  const timerRef = useRef(null)
  const fetch_ = useCallback(async () => {
    try {
      const res = await fetch(`${_API_BASE}/v1/cts/inward/live-flow?limit=50`, { credentials: 'include' })
      if (!res.ok) return
      const json = await res.json()
      // Map API shape → instrument shape that buildInitialNodes expects
      setItems((json.items ?? []).map(i => ({
        id: i.instrument_id,
        stage: i.stage || 'RECEIVED',
        amount: i.amount_range || '₹[<1L]',
        micr: i.micr_suffix || '000000000000',
        fraud: i.fraud_score ?? 0,
        latency: i.elapsed_ms ?? 0,
        outcome: i.decision || 'PENDING',
      })))
    } catch { /* keep last */ }
  }, [])
  useEffect(() => {
    if (!pollEnabled) return
    fetch_()
    timerRef.current = setInterval(fetch_, 10_000)
    return () => clearInterval(timerRef.current)
  }, [fetch_, pollEnabled])
  return items
}

// ── Layout constants ──────────────────────────────────────────────────────────

const LANE_W   = 180
const HDR_H    = 52
const CHQ_W    = 158
const CHQ_H    = 118
const CHQ_PAD  = 11
const CHQ_VPAD = 14
const CHQ_GAP  = 10

// ── Stage config (exported for tests) ────────────────────────────────────────

export const STAGES = [
  { id: 'RECEIVED',  label: 'Received',     icon: '📥', x: 0            },
  { id: 'OCR',       label: 'OCR',          icon: '🔢', x: LANE_W       },
  { id: 'SIGNATURE', label: 'Signature',    icon: '✍',  x: LANE_W * 2   },
  { id: 'FRAUD',     label: 'Fraud Score',  icon: '🛡',  x: LANE_W * 3   },
  { id: 'REVIEW',    label: 'Decision',     icon: '⚖',  x: LANE_W * 4   },
  { id: 'NGCH',      label: 'NGCH Filing',  icon: '📤', x: LANE_W * 5   },
]

// ── Urgency classifier (exported for tests) ───────────────────────────────────

export function urgency(ietDeadline) {
  const mins = Math.max(0, (ietDeadline - Date.now()) / 60000)
  if (mins < 5)  return 'urgent'
  if (mins < 15) return 'critical'
  if (mins < 30) return 'warning'
  if (mins < 60) return 'caution'
  return 'safe'
}

// ── Mock instruments (exported for tests) ─────────────────────────────────────

export function makeMockInstruments() {
  const now = Date.now()
  return [
    { id: 'CHQ-7821', stage: 'RECEIVED',  ietDeadline: now + 172 * 60000, bank: 'Saraswat CB',  amount: '₹[1L-5L]',   script: null, status: 'PROCESSING'   },
    { id: 'CHQ-7822', stage: 'RECEIVED',  ietDeadline: now + 168 * 60000, bank: 'SBI Andheri',  amount: '₹[<1L]',     script: null, status: 'PROCESSING'   },
    { id: 'CHQ-7815', stage: 'OCR',       ietDeadline: now + 147 * 60000, bank: 'Cosmos Bank',  amount: '₹[5L-10L]',  script: 'ml', status: 'PROCESSING'   },
    { id: 'CHQ-7816', stage: 'OCR',       ietDeadline: now + 82  * 60000, bank: 'HDFC Bandra',  amount: '₹[1L-5L]',   script: null, status: 'PROCESSING'   },
    { id: 'CHQ-7809', stage: 'SIGNATURE', ietDeadline: now + 55  * 60000, bank: 'Axis Colaba',  amount: '₹[>1Cr]',    script: null, status: 'PROCESSING'   },
    { id: 'CHQ-7810', stage: 'SIGNATURE', ietDeadline: now + 29  * 60000, bank: 'BOB Dadar',    amount: '₹[10L-1Cr]', script: 'hi', status: 'PROCESSING'   },
    { id: 'CHQ-7802', stage: 'FRAUD',     ietDeadline: now + 18  * 60000, bank: 'UCO Parel',    amount: '₹[5L-10L]',  script: null, status: 'PROCESSING'   },
    { id: 'CHQ-7795', stage: 'REVIEW',    ietDeadline: now + 11  * 60000, bank: 'Federal Bank', amount: '₹[1L-5L]',   script: 'ml', status: 'HUMAN_REVIEW' },
    { id: 'CHQ-7796', stage: 'REVIEW',    ietDeadline: now + 4   * 60000, bank: 'Saraswat CB',  amount: '₹[<1L]',     script: null, status: 'HUMAN_REVIEW' },
    { id: 'CHQ-7788', stage: 'NGCH',      ietDeadline: now + 61  * 60000, bank: 'SBI Kurla',    amount: '₹[1L-5L]',   script: null, status: 'NGCH_FILING'  },
  ]
}

// ── Node builder (exported for tests) ────────────────────────────────────────

export function buildInitialNodes(instruments) {
  const nodes = []

  // Stage header nodes
  STAGES.forEach(stage => {
    const inStage   = instruments.filter(i => i.stage === stage.id)
    const hasCrit   = inStage.some(i => ['critical', 'urgent'].includes(urgency(i.ietDeadline)))
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

  // Cheque nodes — stacked within each stage column
  const counters = {}
  instruments.forEach(instr => {
    const stage = STAGES.find(s => s.id === instr.stage)
    if (!stage) return
    const idx = counters[instr.stage] ?? 0
    counters[instr.stage] = idx + 1
    nodes.push({
      id:          instr.id,
      type:        'chequeNode',
      position:    {
        x: stage.x + CHQ_PAD,
        y: HDR_H + CHQ_VPAD + idx * (CHQ_H + CHQ_GAP),
      },
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
          {data.count} in-flight
        </span>
      )}
    </div>
  )
}

// ── Custom node: ChequeNode ───────────────────────────────────────────────────

const URGENCY_BORDER = {
  urgent:   'border-red-500',
  critical: 'border-red-400',
  warning:  'border-amber-400',
  caution:  'border-yellow-300',
  safe:     'border-emerald-500/50',
}

const URGENCY_BG_DARK = {
  urgent:   'bg-red-950/70',
  critical: 'bg-red-900/30',
  warning:  'bg-amber-900/20',
  caution:  'bg-yellow-900/10',
  safe:     'bg-navy-900',
}

const URGENCY_BG_LIGHT = {
  urgent:   'bg-red-50',
  critical: 'bg-red-50/80',
  warning:  'bg-amber-50',
  caution:  'bg-yellow-50',
  safe:     'bg-white',
}

function ChequeNode({ data, selected }) {
  const { isDark } = useTheme()
  const u = urgency(data.ietDeadline)

  return (
    <div
      style={{ width: CHQ_W, height: CHQ_H }}
      className={`rounded-lg border-2 px-3 py-2.5 cursor-pointer transition-shadow
        ${URGENCY_BORDER[u]}
        ${isDark ? URGENCY_BG_DARK[u] : URGENCY_BG_LIGHT[u]}
        ${selected ? (isDark ? 'ring-2 ring-sky-400 ring-offset-1 ring-offset-navy-900' : 'ring-2 ring-sky-500 ring-offset-1') : ''}
        ${u === 'urgent' ? 'animate-pulse' : ''}`}
    >
      {/* ID row + script badge */}
      <div className="flex items-center justify-between mb-1">
        <span className={`font-mono text-[10px] font-semibold
          ${isDark ? 'text-slate-300' : 'text-slate-700'}`}>
          ****{data.id.slice(-4)}
        </span>
        {data.script && (
          <span className={`text-[9px] font-mono px-1 py-0.5 rounded
            ${isDark ? 'bg-violet-900/60 text-violet-300' : 'bg-violet-100 text-violet-700'}`}>
            {data.script.toUpperCase()}
          </span>
        )}
      </div>

      {/* Bank */}
      <div className={`text-[11px] truncate mb-0.5 ${isDark ? 'text-slate-300' : 'text-slate-700'}`}>
        {data.bank}
      </div>

      {/* Amount */}
      <div className={`text-[11px] font-mono mb-2 ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>
        {data.amount}
      </div>

      {/* IET countdown */}
      <IETTimer deadline={data.ietDeadline} compact />
    </div>
  )
}

// ── Node types registry ───────────────────────────────────────────────────────

const nodeTypes = {
  stageHeader: StageHeaderNode,
  chequeNode:  ChequeNode,
}

// ── Lane divider lines ────────────────────────────────────────────────────────
// Renders vertical separator lines between stage columns as an SVG overlay.

function LaneDividers({ isDark, stageCount, laneHeight }) {
  const color = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.07)'
  const totalWidth = stageCount * LANE_W
  return (
    <svg
      style={{ position: 'absolute', top: 0, left: 0, width: totalWidth, height: laneHeight, pointerEvents: 'none', zIndex: 0 }}
    >
      {Array.from({ length: stageCount - 1 }).map((_, i) => (
        <line
          key={i}
          x1={(i + 1) * LANE_W}
          y1={0}
          x2={(i + 1) * LANE_W}
          y2={laneHeight}
          stroke={color}
          strokeWidth={1}
        />
      ))}
    </svg>
  )
}

// ── Detail panel ──────────────────────────────────────────────────────────────

function DetailPanel({ instr, onClose, isDark }) {
  const th = {
    surface: isDark ? 'bg-navy-900 border-white/8'    : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'                    : 'text-slate-900',
    body:    isDark ? 'text-slate-300'                : 'text-slate-700',
    muted:   isDark ? 'text-slate-400'                : 'text-slate-500',
    mono:    isDark ? 'text-slate-400'                : 'text-slate-500',
    stat:    isDark ? 'bg-navy-800/60 border-white/6' : 'bg-slate-100 border-slate-200',
  }

  const rows = [
    { label: 'Instrument',  value: `****${instr.id.slice(-4)}` },
    { label: 'Stage',       value: instr.stage },
    { label: 'Status',      value: instr.status },
    { label: 'Bank',        value: instr.bank },
    { label: 'Amount',      value: instr.amount },
    { label: 'Script',      value: instr.script?.toUpperCase() ?? '—' },
  ]

  return (
    <div className={`w-72 border-l flex flex-col gap-4 p-5 overflow-y-auto ${th.surface}`}>
      <div className="flex items-center justify-between">
        <span className={`text-sm font-semibold ${th.heading}`}>Cheque Detail</span>
        <button
          onClick={onClose}
          className={`text-lg leading-none ${th.muted} hover:opacity-70`}
          aria-label="Close detail panel"
        >
          ×
        </button>
      </div>

      <IETTimer deadline={instr.ietDeadline} bright />

      <div className="flex flex-col gap-3">
        {rows.map(row => (
          <div key={row.label}>
            <div className={`text-[10px] font-mono uppercase tracking-wider ${th.muted}`}>
              {row.label}
            </div>
            <div className={`text-sm font-medium mt-0.5 ${th.body}`}>{row.value}</div>
          </div>
        ))}
      </div>

      <div className={`text-xs px-3 py-2.5 rounded-lg border leading-relaxed ${th.stat} ${th.muted}`}>
        IET Watchdog armed — fires emergency NGCH filing at T−30s regardless of processing state.
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

const _STATIC_INSTRUMENTS = makeMockInstruments()

export default function CTSInwardMonitor() {
  const { isDark } = useTheme()
  const { isDemo } = useBankContext()
  const [selectedId, setSelectedId] = useState(null)

  const liveFlow = useLiveFlow({ pollEnabled: !isDemo })

  // Demo invariant
  const INSTRUMENTS = useMemo(() => {
    if (isDemo || !liveFlow || liveFlow.length === 0) return _STATIC_INSTRUMENTS
    return liveFlow
  }, [isDemo, liveFlow])

  const th = {
    page:    isDark ? 'bg-navy-950'                    : 'bg-slate-50',
    surface: isDark ? 'bg-navy-900 border-white/8'     : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'                     : 'text-slate-900',
    muted:   isDark ? 'text-slate-400'                 : 'text-slate-500',
    divider: isDark ? 'border-white/8'                 : 'border-slate-200',
    stat:    isDark ? 'bg-navy-800/50 border-white/6'  : 'bg-slate-100 border-slate-200',
    flow:    isDark ? '#03061a'                        : '#f8fafc',
  }

  const initialNodes = useMemo(() => buildInitialNodes(INSTRUMENTS), [INSTRUMENTS])
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes)

  // Keep ReactFlow nodes in sync when live data updates
  useEffect(() => { setNodes(buildInitialNodes(INSTRUMENTS)) }, [INSTRUMENTS, setNodes])

  const onNodeClick = useCallback((_, node) => {
    if (node.type !== 'chequeNode') return
    setSelectedId(prev => prev === node.id ? null : node.id)
  }, [])

  const onPaneClick = useCallback(() => setSelectedId(null), [])

  // Stats
  const total    = INSTRUMENTS.length
  const critical = INSTRUMENTS.filter(i => ['critical', 'urgent'].includes(urgency(i.ietDeadline))).length
  const inReview = INSTRUMENTS.filter(i => i.stage === 'REVIEW').length
  const inNgch   = INSTRUMENTS.filter(i => i.stage === 'NGCH').length
  const selected = selectedId ? INSTRUMENTS.find(i => i.id === selectedId) : null

  // Canvas height covers all nodes (deepest column)
  const maxPerStage = STAGES.reduce((m, s) => {
    const n = INSTRUMENTS.filter(i => i.stage === s.id).length
    return Math.max(m, n)
  }, 0)
  const canvasHeight = HDR_H + CHQ_VPAD + maxPerStage * (CHQ_H + CHQ_GAP) + 40

  return (
    <AppShell>
      <div className={`flex-1 flex flex-col overflow-hidden ${th.page}`}>

        {/* ── Page header ── */}
        <div className={`flex items-center justify-between px-6 py-4 border-b ${th.divider} ${th.surface}`}>
          <div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>Inward IET Monitor</h1>
            <p className={`text-xs mt-0.5 ${th.muted}`}>
              Live pipeline — {total} cheques in-flight this clearing session
            </p>
          </div>
          <div className={`text-[10px] font-mono px-3 py-1.5 rounded-full border ${th.stat} ${th.muted}`}>
            LIVE · updates every 1s
          </div>
        </div>

        {/* ── Stats bar ── */}
        <div className={`flex items-center gap-3 px-6 py-3 border-b ${th.divider}`}>
          {[
            { label: 'In-Flight',    value: total,    color: th.heading },
            { label: 'IET Critical', value: critical, color: critical > 0 ? 'text-red-400'     : th.muted },
            { label: 'Human Review', value: inReview, color: inReview  > 0 ? 'text-amber-400'  : th.muted },
            { label: 'NGCH Filing',  value: inNgch,   color: 'text-emerald-400' },
          ].map(s => (
            <div key={s.label}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border ${th.stat}`}>
              <span className={`text-xl font-mono font-bold tabular-nums leading-none ${s.color}`}>
                {s.value}
              </span>
              <span className={`text-xs ${th.muted}`}>{s.label}</span>
            </div>
          ))}
        </div>

        {/* ── Canvas + detail panel ── */}
        <div className="flex overflow-hidden" style={{ height: 'calc(100vh - 160px)' }}>

          {/* React Flow canvas */}
          <div className="flex-1 relative">
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
              style={{ width: '100%', height: '100%', background: th.flow }}
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
                  const u = urgency(n.data.ietDeadline)
                  return { urgent: '#ef4444', critical: '#f87171', warning: '#fbbf24', caution: '#fde68a', safe: '#34d399' }[u]
                }}
                maskColor={isDark ? 'rgba(3,6,26,0.75)' : 'rgba(248,250,252,0.75)'}
                style={{
                  background: isDark ? '#060d2e' : '#f1f5f9',
                  border: isDark ? '1px solid rgba(255,255,255,0.08)' : '1px solid #e2e8f0',
                  borderRadius: 8,
                }}
              />

              {/* Stage dividers + urgency legend */}
              <Panel position="bottom-left">
                <div className={`flex items-center gap-3 text-[10px] font-mono px-3 py-2 rounded-lg border ${th.stat} ${th.muted}`}>
                  <span>IET:</span>
                  {[
                    { label: '>60m', color: 'bg-emerald-500' },
                    { label: '30–60m', color: 'bg-yellow-400' },
                    { label: '15–30m', color: 'bg-amber-400' },
                    { label: '<15m', color: 'bg-red-400' },
                    { label: '<5m', color: 'bg-red-500 animate-pulse' },
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

          {/* Detail panel */}
          {selected && (
            <DetailPanel
              instr={selected}
              onClose={() => setSelectedId(null)}
              isDark={isDark}
            />
          )}
        </div>
      </div>
    </AppShell>
  )
}

/**
 * CTSDemoPipeline — End-to-end cheque processing demo.
 *
 * Flow:
 *   1. Upload cheque images (drag-and-drop or "Load Sample Cheques")
 *   2. Presentment pipeline: OCR → CTS-2010 → Vision LLM → Decision
 *   3. NPCI simulation: route accepted cheques to drawee banks
 *   4. Drawee pipeline: Sig Vault → CBS → Fraud → Decision
 *   5. Download CSVs for both phases
 *
 * All processing events arrive via SSE (/v1/demo/sessions/{id}/stream).
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'
import { useBankContext } from '../../../shared/context/BankContext'

// ── Step definitions (matching backend pipeline.py) ───────────────────────────

const PRESENTMENT_STAGES = [
  { id: 'file_detected',   label: 'File Detected',     icon: '📁', color: 'sky'     },
  { id: 'image_load',      label: 'Image Load',        icon: '🖼',  color: 'violet'  },
  { id: 'ocr_micr',        label: 'OCR · MICR',        icon: '🔤', color: 'blue'    },
  { id: 'cts_compliance',  label: 'CTS-2010',          icon: '✅', color: 'indigo'  },
  { id: 'vision_llm',      label: 'Vision LLM',        icon: '🧠', color: 'purple'  },
  { id: 'data_extraction', label: 'Data Check',        icon: '📊', color: 'cyan'    },
  { id: 'lot_assignment',  label: 'Lot Assign',        icon: '📦', color: 'teal'    },
  { id: 'decision',        label: 'Decision',          icon: '⚡', color: 'emerald' },
]

const DRAWEE_STAGES = [
  { id: 'file_receipt',    label: 'File Receipt',      icon: '📥', color: 'sky'     },
  { id: 'ocr_reextract',   label: 'OCR Re-extract',   icon: '🔤', color: 'violet'  },
  { id: 'rbi_checklist',   label: 'RBI Checklist',    icon: '📋', color: 'blue'    },
  { id: 'signature_vault', label: 'Sig Vault',         icon: '✍',  color: 'indigo'  },
  { id: 'account_status',  label: 'Account CBS',       icon: '🏦', color: 'cyan'    },
  { id: 'stop_payment',    label: 'Stop Payment',      icon: '🚫', color: 'orange'  },
  { id: 'pps_check',       label: 'PPS Check',         icon: '📋', color: 'teal'    },
  { id: 'fraud_score',     label: 'Fraud Score',       icon: '🛡',  color: 'amber'   },
  { id: 'vision_llm',      label: 'Vision LLM',        icon: '🧠', color: 'purple'  },
  { id: 'decision',        label: 'NGCH Filed',        icon: '📤', color: 'emerald' },
]

const SAMPLE_FILES = Array.from({ length: 12 }, (_, i) =>
  `CHQ_2026070${String(i + 1).padStart(2, '0')}_${['SBIN','HDFC','ICIC','UTIB'][i % 4]}${String(100001 + i * 7).padStart(6,'0')}.jpg`
)

const COLOR_MAP = {
  sky:     { text: 'text-sky-400',     bg: 'bg-sky-500/15',     border: 'border-sky-500/30',     dot: 'bg-sky-400'     },
  violet:  { text: 'text-violet-400',  bg: 'bg-violet-500/15',  border: 'border-violet-500/30',  dot: 'bg-violet-400'  },
  blue:    { text: 'text-blue-400',    bg: 'bg-blue-500/15',    border: 'border-blue-500/30',    dot: 'bg-blue-400'    },
  indigo:  { text: 'text-indigo-400',  bg: 'bg-indigo-500/15',  border: 'border-indigo-500/30',  dot: 'bg-indigo-400'  },
  purple:  { text: 'text-purple-400',  bg: 'bg-purple-500/15',  border: 'border-purple-500/30',  dot: 'bg-purple-400'  },
  cyan:    { text: 'text-cyan-400',    bg: 'bg-cyan-500/15',    border: 'border-cyan-500/30',    dot: 'bg-cyan-400'    },
  teal:    { text: 'text-teal-400',    bg: 'bg-teal-500/15',    border: 'border-teal-500/30',    dot: 'bg-teal-400'    },
  emerald: { text: 'text-emerald-400', bg: 'bg-emerald-500/15', border: 'border-emerald-500/30', dot: 'bg-emerald-400' },
  orange:  { text: 'text-orange-400',  bg: 'bg-orange-500/15',  border: 'border-orange-500/30',  dot: 'bg-orange-400'  },
  amber:   { text: 'text-amber-400',   bg: 'bg-amber-500/15',   border: 'border-amber-500/30',   dot: 'bg-amber-400'   },
}

// ── Utility ───────────────────────────────────────────────────────────────────

const API = '/v1/demo'
const statusColor = (status) => ({
  queued:     'text-slate-400',
  processing: 'text-amber-400',
  success:    'text-emerald-400',
  failed:     'text-red-400',
}[status] || 'text-slate-400')

const statusBadge = (status, isDark) => {
  const bases = {
    queued:     isDark ? 'bg-slate-800 text-slate-400 border-slate-700' : 'bg-slate-100 text-slate-500 border-slate-200',
    processing: 'bg-amber-900/30 text-amber-300 border-amber-700/40 animate-pulse',
    success:    isDark ? 'bg-emerald-900/30 text-emerald-300 border-emerald-700/40' : 'bg-emerald-50 text-emerald-700 border-emerald-200',
    failed:     isDark ? 'bg-red-900/30 text-red-300 border-red-700/40' : 'bg-red-50 text-red-700 border-red-200',
  }
  return `px-2 py-0.5 rounded-full border text-[9px] font-semibold uppercase ${bases[status] || bases.queued}`
}

// ── Stage chip ────────────────────────────────────────────────────────────────

function StageChip({ stage, activeSteps, completedSteps, failedSteps, isDark }) {
  const c    = COLOR_MAP[stage.color] || COLOR_MAP.sky
  const active  = activeSteps.has(stage.id)
  const done    = completedSteps.has(stage.id)
  const failed  = failedSteps.has(stage.id)

  let cls = isDark
    ? `bg-white/4 border-white/10 ${isDark ? 'text-slate-500' : 'text-slate-400'}`
    : `bg-white border-slate-200 text-slate-400`

  if (failed) cls = `bg-red-900/20 border-red-700/40 text-red-300`
  else if (done)   cls = `${c.bg} ${c.border} ${c.text}`
  else if (active) cls = `${c.bg} ${c.border} ${c.text} ring-2 ring-offset-0 ${c.border}`

  return (
    <div className={`flex flex-col items-center gap-1 px-2.5 py-2 rounded-xl border text-center w-[78px] shrink-0 transition-all duration-300 ${cls}`}>
      <span className="text-base leading-none">{stage.icon}</span>
      <span className="text-[9px] font-semibold leading-tight">{stage.label}</span>
      {active && <span className={`w-1.5 h-1.5 rounded-full ${c.dot} animate-ping`} />}
    </div>
  )
}

// ── Phase progress bar ─────────────────────────────────────────────────────────

const PHASES = ['setup', 'presentment', 'npci', 'drawee', 'complete']
const PHASE_LABELS = { setup: '1. Upload', presentment: '2. Presentment', npci: '3. NPCI Routing', drawee: '4. Drawee Processing', complete: '5. Complete' }

function PhaseBar({ phase, isDark }) {
  const idx = PHASES.indexOf(phase)
  return (
    <div className={`shrink-0 px-6 py-2 border-b flex items-center gap-0 overflow-x-auto ${isDark ? 'border-white/8 bg-white/2' : 'border-slate-200 bg-white'}`}>
      {PHASES.map((p, i) => {
        const done    = i < idx
        const current = i === idx
        return (
          <div key={p} className="flex items-center">
            <div className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-[10px] font-semibold transition-all duration-300 ${
              current ? 'bg-violet-600 text-white' :
              done    ? (isDark ? 'text-emerald-400' : 'text-emerald-600') :
                        (isDark ? 'text-slate-600' : 'text-slate-400')
            }`}>
              {done && <span>✓</span>}
              {PHASE_LABELS[p]}
            </div>
            {i < PHASES.length - 1 && (
              <span className={`mx-1 text-[10px] ${isDark ? 'text-slate-700' : 'text-slate-300'}`}>›</span>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ── Upload / Setup zone ────────────────────────────────────────────────────────

function UploadZone({ files, onFiles, onLoadSamples, onStart, isDark }) {
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef(null)

  const handleDrop = useCallback((e) => {
    e.preventDefault()
    setDragging(false)
    const dropped = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('image/') || f.name.endsWith('.jpg') || f.name.endsWith('.png') || f.name.endsWith('.tif'))
    if (dropped.length) onFiles(dropped)
  }, [onFiles])

  const th = {
    zone:  isDark ? 'border-white/15 bg-white/3 hover:bg-white/5' : 'border-slate-300 bg-slate-50 hover:bg-slate-100',
    drag:  isDark ? 'border-violet-500/60 bg-violet-900/20' : 'border-violet-400 bg-violet-50',
    card:  isDark ? 'bg-white/4 border-white/8' : 'bg-white border-slate-200',
    muted: isDark ? 'text-slate-400' : 'text-slate-500',
    body:  isDark ? 'text-slate-300' : 'text-slate-700',
  }

  return (
    <div className="flex flex-col gap-4 max-w-3xl mx-auto w-full mt-6">
      {/* Drop zone */}
      <div
        className={`border-2 border-dashed rounded-2xl p-10 text-center cursor-pointer transition-all duration-200 ${dragging ? th.drag : th.zone}`}
        onDragOver={e => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
      >
        <div className="text-4xl mb-3">🗂</div>
        <div className={`text-sm font-semibold mb-1 ${isDark ? 'text-white' : 'text-slate-800'}`}>
          Drop cheque images here
        </div>
        <div className={`text-xs ${th.muted}`}>JPG · PNG · TIF · TIFF accepted</div>
        <input ref={inputRef} type="file" multiple accept="image/*,.tif,.tiff" className="hidden"
          onChange={e => onFiles(Array.from(e.target.files))} />
      </div>

      {/* OR divider */}
      <div className={`flex items-center gap-3 ${th.muted} text-xs`}>
        <div className={`flex-1 h-px ${isDark ? 'bg-white/8' : 'bg-slate-200'}`} />
        <span>or</span>
        <div className={`flex-1 h-px ${isDark ? 'bg-white/8' : 'bg-slate-200'}`} />
      </div>

      {/* Load sample button */}
      <button
        onClick={onLoadSamples}
        className={`w-full py-3 rounded-xl border text-sm font-semibold transition-colors ${
          isDark ? 'border-violet-700/50 bg-violet-900/20 text-violet-300 hover:bg-violet-900/40' : 'border-violet-300 bg-violet-50 text-violet-700 hover:bg-violet-100'
        }`}
      >
        📋 Load 12 Sample Cheques (demo)
      </button>

      {/* File list */}
      {files.length > 0 && (
        <div className={`rounded-xl border overflow-hidden ${th.card}`}>
          <div className={`px-4 py-2 border-b flex items-center justify-between ${isDark ? 'border-white/8' : 'border-slate-100'}`}>
            <span className={`text-[10px] font-semibold uppercase tracking-widest ${th.muted}`}>{files.length} file{files.length > 1 ? 's' : ''} ready</span>
            <span className={`text-[10px] ${th.muted}`}>Drag more to add</span>
          </div>
          <div className="max-h-48 overflow-y-auto divide-y" style={{ borderColor: isDark ? 'rgba(255,255,255,0.05)' : '#f1f5f9' }}>
            {files.map((f, i) => (
              <div key={i} className={`flex items-center gap-3 px-4 py-2 text-[11px] ${isDark ? 'hover:bg-white/3' : 'hover:bg-slate-50'}`}>
                <span className="text-sm">🖼</span>
                <span className={`font-mono truncate flex-1 ${th.body}`}>{typeof f === 'string' ? f : f.name}</span>
                <span className={`shrink-0 ${th.muted}`}>{typeof f === 'object' ? `${(f.size / 1024).toFixed(0)} KB` : ''}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Start button */}
      {files.length > 0 && (
        <button
          onClick={onStart}
          className="w-full py-3.5 rounded-xl bg-violet-600 hover:bg-violet-700 text-white font-semibold text-sm transition-colors"
        >
          ▶ Start Presentment Processing ({files.length} cheque{files.length > 1 ? 's' : ''})
        </button>
      )}
    </div>
  )
}

// ── NPCI routing view ──────────────────────────────────────────────────────────

function NPCIView({ npciGroups, stats, onRunDrawee, sessionId, isDark }) {
  const th = {
    card:  isDark ? 'bg-white/4 border-white/8' : 'bg-white border-slate-200',
    muted: isDark ? 'text-slate-400' : 'text-slate-500',
    head:  isDark ? 'text-white' : 'text-slate-900',
  }

  return (
    <div className="flex flex-col gap-5 max-w-3xl mx-auto w-full mt-6">
      {/* Summary */}
      <div className={`rounded-xl border px-5 py-4 flex items-center gap-6 ${isDark ? 'bg-emerald-900/10 border-emerald-700/30' : 'bg-emerald-50 border-emerald-200'}`}>
        <span className="text-2xl">✅</span>
        <div>
          <div className={`text-sm font-semibold ${isDark ? 'text-emerald-300' : 'text-emerald-800'}`}>Presentment Complete</div>
          <div className={`text-xs mt-0.5 ${isDark ? 'text-emerald-400/70' : 'text-emerald-600'}`}>
            {stats.success} accepted · {stats.failed} rejected · routed to {Object.keys(npciGroups).length} clearing banks
          </div>
        </div>
        <div className="ml-auto flex gap-3">
          <a href={`${API}/sessions/${sessionId}/csv/presentment-success`}
            className={`px-3 py-1.5 rounded-lg border text-[11px] font-semibold transition-colors ${isDark ? 'border-emerald-700/40 text-emerald-300 hover:bg-emerald-900/30' : 'border-emerald-300 text-emerald-700 hover:bg-emerald-100'}`}
            download>
            ⬇ Success CSV
          </a>
          <a href={`${API}/sessions/${sessionId}/csv/presentment-failure`}
            className={`px-3 py-1.5 rounded-lg border text-[11px] font-semibold transition-colors ${isDark ? 'border-red-700/40 text-red-300 hover:bg-red-900/30' : 'border-red-300 text-red-700 hover:bg-red-100'}`}
            download>
            ⬇ Failure CSV
          </a>
        </div>
      </div>

      {/* NPCI routing header */}
      <div className={`text-xs font-semibold uppercase tracking-widest ${th.muted}`}>
        NPCI Clearing House — Routing accepted cheques by drawee bank
      </div>

      {/* Bank routing cards */}
      <div className="grid grid-cols-2 gap-3">
        {Object.entries(npciGroups).map(([bank, count]) => (
          <div key={bank} className={`rounded-xl border p-4 ${th.card}`}>
            <div className="flex items-start justify-between mb-3">
              <div>
                <div className={`text-xs font-semibold ${th.head}`}>{bank}</div>
                <div className={`text-[10px] mt-0.5 ${th.muted}`}>{count} cheque{count > 1 ? 's' : ''} routed</div>
              </div>
              <span className="text-xl">🏦</span>
            </div>
            <button
              onClick={() => onRunDrawee(bank)}
              className={`w-full py-2 rounded-lg text-[11px] font-semibold transition-colors ${
                isDark ? 'bg-violet-900/40 text-violet-300 hover:bg-violet-900/60 border border-violet-700/40' : 'bg-violet-50 text-violet-700 hover:bg-violet-100 border border-violet-200'
              }`}
            >
              ▶ Process as {bank.split(' ')[0]}
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Complete view ─────────────────────────────────────────────────────────────

function CompleteView({ draweeStats, sessionId, isDark }) {
  const th = {
    card:  isDark ? 'bg-white/4 border-white/8' : 'bg-white border-slate-200',
    muted: isDark ? 'text-slate-400' : 'text-slate-500',
  }
  return (
    <div className="flex flex-col gap-5 max-w-2xl mx-auto w-full mt-8">
      <div className={`rounded-xl border px-6 py-5 text-center ${isDark ? 'bg-indigo-900/10 border-indigo-700/30' : 'bg-indigo-50 border-indigo-200'}`}>
        <div className="text-3xl mb-2">🎉</div>
        <div className={`text-base font-semibold ${isDark ? 'text-indigo-200' : 'text-indigo-900'}`}>End-to-End Demo Complete</div>
        <div className={`text-xs mt-1 ${isDark ? 'text-indigo-400' : 'text-indigo-600'}`}>
          {draweeStats.success} confirmed · {draweeStats.failed} returned
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        {[
          { label: 'Drawee Success CSV', ep: 'drawee-success', color: 'emerald' },
          { label: 'Drawee Failure CSV', ep: 'drawee-failure', color: 'red' },
          { label: 'Presentment Success', ep: 'presentment-success', color: 'violet' },
          { label: 'Presentment Failure', ep: 'presentment-failure', color: 'orange' },
        ].map(({ label, ep, color }) => (
          <a key={ep} href={`${API}/sessions/${sessionId}/csv/${ep}`} download
            className={`rounded-xl border px-4 py-3 text-[11px] font-semibold flex items-center gap-2 transition-colors ${
              isDark ? `bg-${color}-900/20 border-${color}-700/40 text-${color}-300 hover:bg-${color}-900/40`
                     : `bg-${color}-50 border-${color}-200 text-${color}-700 hover:bg-${color}-100`
            }`}>
            <span>⬇</span> {label}
          </a>
        ))}
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function CTSDemoPipeline() {
  const { isDark }    = useTheme()
  const { bankType }  = useBankContext()
  usePageHeader({ subtitle: 'End-to-end live demo — Presentment · NPCI routing · Drawee processing' })

  const [phase,      setPhase]      = useState('setup')
  const [sessionId,  setSessionId]  = useState(null)
  const [files,      setFiles]      = useState([])
  const [items,      setItems]      = useState({})        // itemId → item state
  const [eventLog,   setEventLog]   = useState([])
  const [npciGroups, setNpciGroups] = useState({})
  const [stats,      setStats]      = useState({ success: 0, failed: 0 })
  const [draweeStats, setDraweeStats] = useState({ success: 0, failed: 0 })
  const [activeSteps, setActiveSteps]   = useState(new Set())
  const [doneSteps,   setDoneSteps]     = useState(new Set())
  const [failedSteps, setFailedSteps]   = useState(new Set())
  const esRef = useRef(null)
  const logRef = useRef(null)

  const currentStages = phase === 'drawee' ? DRAWEE_STAGES : PRESENTMENT_STAGES

  const th = {
    page:   isDark ? 'bg-[#020817]'          : 'bg-slate-50',
    card:   isDark ? 'bg-white/4 border-white/8' : 'bg-white border-slate-200',
    muted:  isDark ? 'text-slate-400'        : 'text-slate-500',
    faint:  isDark ? 'text-slate-600'        : 'text-slate-400',
    body:   isDark ? 'text-slate-300'        : 'text-slate-700',
    head:   isDark ? 'text-white'            : 'text-slate-900',
    divider: isDark ? 'border-white/8'       : 'border-slate-200',
    row:    isDark ? 'border-white/4 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
  }

  // Scroll event log to top on new entry
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = 0
  }, [eventLog.length])

  const connectSSE = useCallback((sid) => {
    if (esRef.current) esRef.current.close()
    const es = new EventSource(`${API}/sessions/${sid}/stream`)

    const on = (type, handler) => es.addEventListener(type, e => {
      try { handler(JSON.parse(e.data)) } catch {}
    })

    on('session_started', (d) => {
      addLog('info', `Session started — ${d.total_items} cheques`)
    })

    on('item_started', (d) => {
      setItems(prev => ({ ...prev, [d.item_id]: { ...prev[d.item_id], item_id: d.item_id, filename: d.filename, status: 'processing', currentStep: null } }))
    })

    on('step_started', (d) => {
      setItems(prev => {
        const it = prev[d.item_id] || {}
        return { ...prev, [d.item_id]: { ...it, currentStep: d.step } }
      })
      setActiveSteps(prev => new Set([...prev, d.step]))
    })

    on('step_complete', (d) => {
      setItems(prev => {
        const it = prev[d.item_id] || {}
        return { ...prev, [d.item_id]: { ...it, currentStep: d.step, steps: [...(it.steps || []), { step: d.step, status: 'passed', ms: d.duration_ms, data: d.data }] } }
      })
      setActiveSteps(prev => { const s = new Set(prev); s.delete(d.step); return s })
      setDoneSteps(prev => new Set([...prev, d.step]))
    })

    on('step_failed', (d) => {
      setActiveSteps(prev => { const s = new Set(prev); s.delete(d.step); return s })
      setFailedSteps(prev => new Set([...prev, d.step]))
      addLog('error', `${d.reason}: ${d.detail}`)
    })

    on('item_complete', (d) => {
      setItems(prev => {
        const it = prev[d.item_id] || {}
        return { ...prev, [d.item_id]: { ...it, status: d.decision === 'ACCEPTED' || d.decision === 'CONFIRMED' ? 'success' : 'failed', decision: d.decision, reason: d.reason, ms: d.total_ms } }
      })
      if (d.decision === 'ACCEPTED' || d.decision === 'CONFIRMED') {
        setStats(p => ({ ...p, success: p.success + 1 }))
        addLog('success', `${d.item_id} → ${d.decision} (${d.total_ms}ms)`)
      } else {
        setStats(p => ({ ...p, failed: p.failed + 1 }))
        addLog('error', `${d.item_id} → ${d.decision}: ${d.reason}`)
      }
    })

    on('presentment_complete', (d) => {
      setNpciGroups(d.npci_groups || {})
      setStats({ success: d.success, failed: d.failed })
      setPhase('npci')
      setActiveSteps(new Set())
      addLog('info', `Presentment done — ${d.success} accepted, ${d.failed} rejected`)
    })

    on('drawee_started', (d) => {
      setActiveSteps(new Set())
      setDoneSteps(new Set())
      setFailedSteps(new Set())
      addLog('info', `Drawee processing started for ${d.bank} — ${d.total_items} cheques`)
    })

    on('drawee_complete', (d) => {
      setDraweeStats({ success: d.success, failed: d.failed })
      setPhase('complete')
      setActiveSteps(new Set())
      addLog('info', `Drawee done — ${d.success} confirmed, ${d.failed} returned`)
    })

    es.onerror = () => addLog('error', 'SSE connection lost')
    esRef.current = es
  }, [])

  useEffect(() => () => esRef.current?.close(), [])

  function addLog(type, msg) {
    const ts = new Date().toLocaleTimeString('en-IN', { hour12: false })
    setEventLog(prev => [{ type, msg, ts }, ...prev].slice(0, 60))
  }

  async function handleStart() {
    const filenames = files.map(f => typeof f === 'string' ? f : f.name)

    // Create session
    const sessResp = await fetch(`${API}/sessions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ bank_id: 'saraswat-coop', filenames }),
    })
    if (!sessResp.ok) return addLog('error', 'Failed to create session')
    const { session_id } = await sessResp.json()
    setSessionId(session_id)

    // Connect SSE first, then trigger pipeline
    connectSSE(session_id)
    setPhase('presentment')
    setItems({})
    setStats({ success: 0, failed: 0 })
    setActiveSteps(new Set())
    setDoneSteps(new Set())
    setFailedSteps(new Set())

    await fetch(`${API}/sessions/${session_id}/run-presentment`, { method: 'POST' })
  }

  async function handleRunDrawee(bankName) {
    if (!sessionId) return
    setPhase('drawee')
    setItems({})
    setDraweeStats({ success: 0, failed: 0 })
    addLog('info', `Starting drawee processing for ${bankName}…`)
    await fetch(`${API}/sessions/${sessionId}/run-drawee`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ bank_name: bankName }),
    })
  }

  function handleFiles(newFiles) {
    setFiles(prev => {
      const names = new Set(prev.map(f => typeof f === 'string' ? f : f.name))
      const fresh = newFiles.filter(f => !names.has(typeof f === 'string' ? f : f.name))
      return [...prev, ...fresh]
    })
  }

  const itemList = Object.values(items)
  const processing = itemList.filter(it => it.status === 'processing').length
  const success = itemList.filter(it => it.status === 'success').length
  const failed  = itemList.filter(it => it.status === 'failed').length

  return (
    <AppShell>
      <div className={`flex flex-col h-full overflow-hidden ${th.page}`}>

        {/* Phase progress bar */}
        <PhaseBar phase={phase} isDark={isDark} />

        {/* KPI strip — visible during processing */}
        {(phase === 'presentment' || phase === 'drawee') && (
          <div className={`shrink-0 px-6 py-2.5 border-b ${th.divider} flex items-center gap-8`}>
            {[
              { label: 'Processing', val: processing, color: 'text-amber-400' },
              { label: phase === 'drawee' ? 'Confirmed' : 'Accepted',   val: success, color: 'text-emerald-400' },
              { label: phase === 'drawee' ? 'Returned' : 'Rejected',    val: failed,  color: 'text-red-400'     },
              { label: 'Total', val: itemList.length, color: isDark ? 'text-slate-300' : 'text-slate-700' },
            ].map(k => (
              <div key={k.label} className="flex items-baseline gap-2">
                <span className={`text-2xl font-black font-mono tabular-nums ${k.color}`}>{k.val}</span>
                <span className={`text-[10px] ${th.faint}`}>{k.label}</span>
              </div>
            ))}
          </div>
        )}

        <div className="flex flex-1 min-h-0 overflow-hidden">

          {/* Left: item queue */}
          <div className={`w-80 shrink-0 border-r ${th.divider} flex flex-col`}>
            <div className={`px-3 py-2 border-b ${th.divider} flex items-center justify-between`}>
              <span className={`text-[10px] font-semibold uppercase tracking-widest ${th.muted}`}>
                Cheque Queue
              </span>
              <span className={`text-[10px] font-mono ${th.faint}`}>{itemList.length || files.length}</span>
            </div>
            <div className="flex-1 overflow-y-auto">
              {phase === 'setup' && files.map((f, i) => (
                <div key={i} className={`flex items-center gap-2.5 px-3 py-2 border-b text-[10px] ${th.row}`}>
                  <span>🖼</span>
                  <span className={`font-mono truncate flex-1 ${th.body}`}>{typeof f === 'string' ? f : f.name}</span>
                  <span className={`${th.faint}`}>Queued</span>
                </div>
              ))}
              {phase !== 'setup' && itemList.map(it => (
                <div key={it.item_id} className={`border-b px-3 py-2 text-[10px] ${th.row}`}>
                  <div className="flex items-center gap-2 mb-1">
                    <span className={statusColor(it.status)}>
                      {it.status === 'success' ? '✓' : it.status === 'failed' ? '✕' : it.status === 'processing' ? '⟳' : '○'}
                    </span>
                    <span className={`font-mono truncate flex-1 ${th.body}`}>{it.filename}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={statusBadge(it.status, isDark)}>
                      {it.decision || it.status}
                    </span>
                    {it.status === 'processing' && it.currentStep && (
                      <span className={`text-[9px] font-mono ${th.faint} truncate`}>{it.currentStep}</span>
                    )}
                    {it.ms > 0 && (
                      <span className={`ml-auto text-[9px] font-mono ${th.faint}`}>{it.ms}ms</span>
                    )}
                  </div>
                  {it.reason && (
                    <div className={`text-[9px] mt-1 text-red-400 truncate`}>{it.reason}</div>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Center: main content */}
          <div className="flex-1 flex flex-col overflow-hidden">

            {/* Pipeline stage chips — visible during processing */}
            {(phase === 'presentment' || phase === 'drawee') && (
              <div className={`shrink-0 px-4 pt-4 pb-3 border-b ${th.divider}`}>
                <div className={`text-[9px] font-semibold uppercase tracking-widest mb-3 ${th.faint}`}>
                  {phase === 'presentment' ? 'Presentment Pipeline (8 stages)' : 'Drawee Pipeline (10 stages)'}
                </div>
                <div className="flex items-center gap-1.5 flex-wrap">
                  {currentStages.map(stage => (
                    <StageChip
                      key={stage.id}
                      stage={stage}
                      activeSteps={activeSteps}
                      completedSteps={doneSteps}
                      failedSteps={failedSteps}
                      isDark={isDark}
                    />
                  ))}
                </div>
              </div>
            )}

            {/* Phase-specific content */}
            <div className="flex-1 overflow-y-auto px-4 py-2">
              {phase === 'setup' && (
                <UploadZone
                  files={files}
                  onFiles={handleFiles}
                  onLoadSamples={() => setFiles(SAMPLE_FILES)}
                  onStart={handleStart}
                  isDark={isDark}
                />
              )}
              {phase === 'npci' && (
                <NPCIView
                  npciGroups={npciGroups}
                  stats={stats}
                  sessionId={sessionId}
                  onRunDrawee={handleRunDrawee}
                  isDark={isDark}
                />
              )}
              {phase === 'complete' && (
                <CompleteView
                  draweeStats={draweeStats}
                  sessionId={sessionId}
                  isDark={isDark}
                />
              )}

              {/* Step detail table — visible during active processing */}
              {(phase === 'presentment' || phase === 'drawee') && itemList.length > 0 && (
                <div className={`mt-3 rounded-xl border overflow-hidden ${th.card}`}>
                  <div className={`px-4 py-2 border-b ${th.divider}`}>
                    <span className={`text-[10px] font-semibold uppercase tracking-widest ${th.muted}`}>
                      Live Processing Detail
                    </span>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-[10px]">
                      <thead>
                        <tr className={`border-b ${th.divider}`}>
                          {['File', 'Status', 'Current Step', 'Decision', 'Time'].map(h => (
                            <th key={h} className={`px-3 py-2 text-left font-semibold ${th.muted}`}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {itemList.slice(0, 30).map(it => (
                          <tr key={it.item_id} className={`border-b ${th.row}`}>
                            <td className={`px-3 py-2 font-mono truncate max-w-[140px] ${th.body}`}>{it.filename}</td>
                            <td className="px-3 py-2">
                              <span className={statusBadge(it.status, isDark)}>{it.status}</span>
                            </td>
                            <td className={`px-3 py-2 font-mono ${th.faint}`}>{it.currentStep || '—'}</td>
                            <td className={`px-3 py-2 font-semibold ${
                              it.decision === 'ACCEPTED' || it.decision === 'CONFIRMED' ? 'text-emerald-400' :
                              it.decision === 'REJECTED' || it.decision === 'RETURNED' ? 'text-red-400' : th.faint
                            }`}>{it.decision || '—'}</td>
                            <td className={`px-3 py-2 font-mono ${th.faint}`}>{it.ms ? `${it.ms}ms` : '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Right: live event feed */}
          <div className={`w-64 shrink-0 border-l ${th.divider} flex flex-col`}>
            <div className={`px-3 py-2 border-b ${th.divider} flex items-center justify-between`}>
              <span className={`text-[10px] font-semibold uppercase tracking-widest ${th.muted}`}>Live Feed</span>
              {phase !== 'setup' && (
                <span className="flex items-center gap-1 text-[9px] text-emerald-400">
                  <span className="w-1 h-1 rounded-full bg-emerald-400 animate-pulse" />Live
                </span>
              )}
            </div>
            <div ref={logRef} className="flex-1 overflow-y-auto p-2 space-y-1">
              {eventLog.length === 0 && (
                <div className={`text-[10px] text-center mt-8 ${th.faint}`}>Events will appear here</div>
              )}
              {eventLog.map((ev, i) => (
                <div key={i} className={`text-[9px] rounded px-2 py-1 flex items-start gap-1.5 ${
                  ev.type === 'error'   ? (isDark ? 'bg-red-900/20 text-red-300'     : 'bg-red-50 text-red-700') :
                  ev.type === 'success' ? (isDark ? 'bg-emerald-900/20 text-emerald-300' : 'bg-emerald-50 text-emerald-700') :
                                         (isDark ? 'bg-white/3 text-slate-400'      : 'bg-slate-50 text-slate-600')
                }`}>
                  <span className="font-mono shrink-0 opacity-60">{ev.ts}</span>
                  <span className="leading-relaxed">{ev.msg}</span>
                </div>
              ))}
            </div>

            {/* Download shortcuts */}
            {(phase === 'npci' || phase === 'complete') && sessionId && (
              <div className={`shrink-0 p-3 border-t ${th.divider} space-y-2`}>
                <div className={`text-[9px] font-semibold uppercase tracking-widest mb-2 ${th.muted}`}>Downloads</div>
                <a href={`${API}/sessions/${sessionId}/csv/presentment-success`} download
                  className={`block text-center py-1.5 rounded-lg text-[10px] font-semibold border transition-colors ${isDark ? 'border-emerald-700/40 text-emerald-300 hover:bg-emerald-900/20' : 'border-emerald-200 text-emerald-700 hover:bg-emerald-50'}`}>
                  ⬇ Presentment Success
                </a>
                <a href={`${API}/sessions/${sessionId}/csv/presentment-failure`} download
                  className={`block text-center py-1.5 rounded-lg text-[10px] font-semibold border transition-colors ${isDark ? 'border-red-700/40 text-red-300 hover:bg-red-900/20' : 'border-red-200 text-red-700 hover:bg-red-50'}`}>
                  ⬇ Presentment Failure
                </a>
                {phase === 'complete' && <>
                  <a href={`${API}/sessions/${sessionId}/csv/drawee-success`} download
                    className={`block text-center py-1.5 rounded-lg text-[10px] font-semibold border transition-colors ${isDark ? 'border-violet-700/40 text-violet-300 hover:bg-violet-900/20' : 'border-violet-200 text-violet-700 hover:bg-violet-50'}`}>
                    ⬇ Drawee Confirmed
                  </a>
                  <a href={`${API}/sessions/${sessionId}/csv/drawee-failure`} download
                    className={`block text-center py-1.5 rounded-lg text-[10px] font-semibold border transition-colors ${isDark ? 'border-orange-700/40 text-orange-300 hover:bg-orange-900/20' : 'border-orange-200 text-orange-700 hover:bg-orange-50'}`}>
                    ⬇ Drawee Returned
                  </a>
                </>}
              </div>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  )
}

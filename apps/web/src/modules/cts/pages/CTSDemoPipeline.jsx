/**
 * CTSDemoPipeline — End-to-end cheque processing demo.
 *
 * Fully self-contained — no backend, no API calls.
 * All pipeline steps run as simulated async tasks in the browser.
 *
 * Flow:
 *   1. Upload cheque images (drag-and-drop or "Load Sample Cheques")
 *   2. Presentment pipeline: OCR → CTS-2010 → Vision LLM → Decision
 *   3. NPCI simulation: route accepted cheques to drawee banks
 *   4. Drawee pipeline: Sig Vault → CBS → Fraud → Decision
 *   5. Download CSVs for both phases
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'
import { useBankContext } from '../../../shared/context/BankContext'

// ── Pipeline configuration ────────────────────────────────────────────────────

const MAX_CONCURRENT = 5

const PRESENTMENT_STAGES = [
  { id: 'file_detected',   label: 'File Detected',     icon: '📁', color: 'sky',     minMs:  40, maxMs:  150 },
  { id: 'image_load',      label: 'Image Load',        icon: '🖼',  color: 'violet',  minMs:  80, maxMs:  250 },
  { id: 'ocr_micr',        label: 'OCR · MICR',        icon: '🔤', color: 'blue',    minMs: 350, maxMs:  750 },
  { id: 'cts_compliance',  label: 'CTS-2010',          icon: '✅', color: 'indigo',  minMs: 120, maxMs:  350 },
  { id: 'vision_llm',      label: 'Vision LLM',        icon: '🧠', color: 'purple',  minMs: 500, maxMs: 1100 },
  { id: 'data_extraction', label: 'Data Check',        icon: '📊', color: 'cyan',    minMs: 150, maxMs:  400 },
  { id: 'lot_assignment',  label: 'Lot Assign',        icon: '📦', color: 'teal',    minMs:  60, maxMs:  160 },
  { id: 'decision',        label: 'Decision',          icon: '⚡', color: 'emerald', minMs:  40, maxMs:  120 },
]

const DRAWEE_STAGES = [
  { id: 'file_receipt',    label: 'File Receipt',      icon: '📥', color: 'sky',     minMs:  60, maxMs:  180 },
  { id: 'ocr_reextract',   label: 'OCR Re-extract',   icon: '🔤', color: 'violet',  minMs: 300, maxMs:  650 },
  { id: 'rbi_checklist',   label: 'RBI Checklist',    icon: '📋', color: 'blue',    minMs: 180, maxMs:  420 },
  { id: 'signature_vault', label: 'Sig Vault',         icon: '✍',  color: 'indigo',  minMs: 280, maxMs:  600 },
  { id: 'account_status',  label: 'Account CBS',       icon: '🏦', color: 'cyan',    minMs: 180, maxMs:  380 },
  { id: 'stop_payment',    label: 'Stop Payment',      icon: '🚫', color: 'orange',  minMs: 220, maxMs:  450 },
  { id: 'pps_check',       label: 'PPS Check',         icon: '📋', color: 'teal',    minMs: 130, maxMs:  300 },
  { id: 'fraud_score',     label: 'Fraud Score',       icon: '🛡',  color: 'amber',   minMs: 280, maxMs:  580 },
  { id: 'vision_llm',      label: 'Vision LLM',        icon: '🧠', color: 'purple',  minMs: 480, maxMs: 1000 },
  { id: 'decision',        label: 'NGCH Filed',        icon: '📤', color: 'emerald', minMs:  50, maxMs:  140 },
]

const DRAWEE_BANKS = [
  'State Bank of India',
  'HDFC Bank Ltd',
  'ICICI Bank Ltd',
  'Axis Bank Ltd',
]

const SAMPLE_FILES = Array.from({ length: 12 }, (_, i) =>
  `CHQ_2026070${String(i + 1).padStart(2, '0')}_${['SBIN','HDFC','ICIC','UTIB'][i % 4]}${String(100001 + i * 7).padStart(6,'0')}.jpg`
)

const AMOUNTS  = [10000, 25000, 45000, 72500, 100000, 200000, 350000, 500000]
const WORDS    = ['Ten Thousand Only','Twenty Five Thousand Only','Forty Five Thousand Only','Seventy Two Thousand Five Hundred Only','One Lakh Only','Two Lakhs Only','Three Lakhs Fifty Thousand Only','Five Lakhs Only']
const PAYEES   = ['M/s Sunshine Traders','ABC Enterprises Pvt Ltd','R.K. Construction Co.','Priya Hospital Trust','National Exports Ltd','Kotak Mahindra Bank Ltd','Future Tech Solutions','Rajesh Kumar']

// ── Deterministic failure injection ──────────────────────────────────────────

function presentmentFailure(idx) {
  if (idx % 7 === 6)  return { step: 'data_extraction', reason: 'AMOUNT_MISMATCH',    detail: `Amount figures ₹${((idx % 5 + 1) * 10000).toLocaleString('en-IN')} do not match words — discrepancy detected.` }
  if (idx % 13 === 12) return { step: 'vision_llm',      reason: 'ALTERATION_DETECTED', detail: 'Qwen2-VL reports overwriting in amount field (tamper confidence 0.91). Rejected per CTS-2010 §5.2.' }
  if (idx % 19 === 18) return { step: 'cts_compliance',  reason: 'CTS_IMAGE_QUALITY',   detail: 'Image DPI below CTS-2010 minimum (96 DPI required, detected 68 DPI). Re-scan required.' }
  return null
}

function draweeFailure(idx) {
  if (idx % 11 === 10) return { step: 'stop_payment',    reason: 'STOP_PAYMENT_ACTIVE', detail: 'CBS confirms stop-payment instruction active (filed 2026-06-29 14:32). Instrument returned.' }
  if (idx % 17 === 16) return { step: 'signature_vault', reason: 'SIGNATURE_MISMATCH',  detail: 'Siamese SNN match score 0.42 (threshold 0.85). 2 registered specimens. Human review required.' }
  if (idx % 23 === 22) return { step: 'account_status',  reason: 'ACCOUNT_FROZEN',      detail: 'CBS: account FROZEN (court order CO-2026-MUM-4421). Instrument returned immediately.' }
  return null
}

function micrData(idx) {
  const cheque = String(800001 + idx).padStart(6, '0')
  const acct   = Array.from({ length: 11 }, (_, i) => (idx * 31 + i * 7) % 10).join('')
  return { micr_line: `⑈${cheque}⑆SBIN${String(idx * 13 % 10000000).padStart(7,'0')}⑉${acct.slice(0,9)}`, cheque_number: cheque, account_number: `****${acct.slice(-4)}`, confidence: (0.97 + (idx % 3) * 0.01).toFixed(2) }
}

function extractionData(idx) {
  const ai = idx % AMOUNTS.length
  const words = idx % 7 === 6 ? WORDS[ai].replace('Five','Six').replace('Ten','Eleven') : WORDS[ai]
  const day   = String((idx % 28) + 1).padStart(2,'0')
  const month = String((idx % 12) + 1).padStart(2,'0')
  return { amount_figures: `₹${AMOUNTS[ai].toLocaleString('en-IN')}`, amount_words: words, payee: PAYEES[idx % PAYEES.length], date: `${day}-${month}-2026`, match_ok: idx % 7 !== 6 }
}

// ── Concurrency limiter (browser Semaphore) ───────────────────────────────────

function createSemaphore(n) {
  let count = 0
  const queue = []
  return {
    async acquire() {
      if (count < n) { count++; return }
      await new Promise(resolve => queue.push(resolve))
    },
    release() {
      const next = queue.shift()
      if (next) { next() } else { count-- }
    },
  }
}

// ── CSV generation ────────────────────────────────────────────────────────────

function toCSV(rows, headers) {
  const escape = v => `"${String(v ?? '').replace(/"/g, '""')}"`
  const lines  = [headers.map(escape).join(',')]
  rows.forEach(r => lines.push(headers.map(h => escape(r[h])).join(',')))
  return lines.join('\r\n')
}

function downloadCSV(content, filename) {
  const blob = new Blob([content], { type: 'text/csv' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  URL.revokeObjectURL(url)
}

function buildSuccessCSV(items, phase) {
  const success = items.filter(it => it.status === 'success')
  if (phase === 'presentment') {
    const rows = success.map((it, i) => ({
      '#': i + 1, Filename: it.filename,
      MICR_Line:  it.steps.find(s => s.step === 'ocr_micr')?.data?.micr_line ?? '-',
      Payee:      it.extracted?.payee ?? '-',
      Amount:     it.extracted?.amount_figures ?? '-',
      Date:       it.extracted?.date ?? '-',
      Lot:        it.steps.find(s => s.step === 'lot_assignment')?.data?.lot_id ?? '-',
      Status:     'ACCEPTED',
      Total_ms:   it.totalMs,
    }))
    return toCSV(rows, ['#','Filename','MICR_Line','Payee','Amount','Date','Lot','Status','Total_ms'])
  }
  const rows = success.map((it, i) => ({
    '#': i + 1, Filename: it.filename,
    Payee:       it.extracted?.payee ?? '-',
    Amount:      it.extracted?.amount_figures ?? '-',
    Date:        it.extracted?.date ?? '-',
    Sig_Score:   it.steps.find(s => s.step === 'signature_vault')?.data?.match_score ?? '-',
    Fraud_Score: it.steps.find(s => s.step === 'fraud_score')?.data?.fraud_score ?? '-',
    Decision:    it.decision ?? 'CONFIRMED',
    Total_ms:    it.totalMs,
  }))
  return toCSV(rows, ['#','Filename','Payee','Amount','Date','Sig_Score','Fraud_Score','Decision','Total_ms'])
}

function buildFailureCSV(items) {
  const failed = items.filter(it => it.status === 'failed')
  const rows   = failed.map((it, i) => {
    const fs = it.steps.find(s => s.status === 'failed')
    return { '#': i + 1, Filename: it.filename, Reject_Reason: it.rejectReason ?? '-', Detail: fs?.detail ?? '-', Failed_At_Step: fs?.step ?? '-', Total_ms: it.totalMs }
  })
  return toCSV(rows, ['#','Filename','Reject_Reason','Detail','Failed_At_Step','Total_ms'])
}

// ── Color map ─────────────────────────────────────────────────────────────────

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

const statusColor = s => ({ queued: 'text-slate-400', processing: 'text-amber-400', success: 'text-emerald-400', failed: 'text-red-400' }[s] || 'text-slate-400')

function statusBadge(s, isDark) {
  const m = {
    queued:     isDark ? 'bg-slate-800 text-slate-400 border-slate-700' : 'bg-slate-100 text-slate-500 border-slate-200',
    processing: 'bg-amber-900/30 text-amber-300 border-amber-700/40 animate-pulse',
    success:    isDark ? 'bg-emerald-900/30 text-emerald-300 border-emerald-700/40' : 'bg-emerald-50 text-emerald-700 border-emerald-200',
    failed:     isDark ? 'bg-red-900/30 text-red-300 border-red-700/40' : 'bg-red-50 text-red-700 border-red-200',
  }
  return `px-2 py-0.5 rounded-full border text-[9px] font-semibold uppercase ${m[s] || m.queued}`
}

// ── Sub-components ────────────────────────────────────────────────────────────

const PHASES = ['setup','presentment','npci','drawee','complete']
const PHASE_LABELS = { setup:'1. Upload', presentment:'2. Presentment', npci:'3. NPCI Routing', drawee:'4. Drawee Processing', complete:'5. Complete' }

function PhaseBar({ phase, isDark }) {
  const idx = PHASES.indexOf(phase)
  return (
    <div className={`shrink-0 px-6 py-2 border-b flex items-center overflow-x-auto ${isDark ? 'border-white/8 bg-white/2' : 'border-slate-200 bg-white'}`}>
      {PHASES.map((p, i) => (
        <div key={p} className="flex items-center">
          <div className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-[10px] font-semibold transition-all duration-300 whitespace-nowrap ${
            i === idx ? 'bg-violet-600 text-white' :
            i < idx   ? (isDark ? 'text-emerald-400' : 'text-emerald-600') :
                        (isDark ? 'text-slate-600' : 'text-slate-400')
          }`}>
            {i < idx && <span>✓</span>}
            {PHASE_LABELS[p]}
          </div>
          {i < PHASES.length - 1 && <span className={`mx-1 text-[10px] ${isDark ? 'text-slate-700' : 'text-slate-300'}`}>›</span>}
        </div>
      ))}
    </div>
  )
}

function StageChip({ stage, activeSteps, doneSteps, failedSteps, isDark }) {
  const c = COLOR_MAP[stage.color] || COLOR_MAP.sky
  const active = activeSteps.has(stage.id)
  const done   = doneSteps.has(stage.id)
  const failed = failedSteps.has(stage.id)
  let cls = isDark ? 'bg-white/4 border-white/10 text-slate-500' : 'bg-white border-slate-200 text-slate-400'
  if (failed) cls = 'bg-red-900/20 border-red-700/40 text-red-300'
  else if (done)   cls = `${c.bg} ${c.border} ${c.text}`
  else if (active) cls = `${c.bg} ${c.border} ${c.text} ring-2 ring-offset-0 ring-current`
  return (
    <div className={`flex flex-col items-center gap-1 px-2.5 py-2 rounded-xl border text-center w-[78px] shrink-0 transition-all duration-300 ${cls}`}>
      <span className="text-base leading-none">{stage.icon}</span>
      <span className="text-[9px] font-semibold leading-tight">{stage.label}</span>
      {active && <span className={`w-1.5 h-1.5 rounded-full ${c.dot} animate-ping`} />}
    </div>
  )
}

function UploadZone({ files, onFiles, onLoadSamples, onStart, isDark }) {
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef(null)
  const th = {
    zone:  isDark ? 'border-white/15 bg-white/3 hover:bg-white/5' : 'border-slate-300 bg-slate-50 hover:bg-slate-100',
    drag:  isDark ? 'border-violet-500/60 bg-violet-900/20' : 'border-violet-400 bg-violet-50',
    card:  isDark ? 'bg-white/4 border-white/8' : 'bg-white border-slate-200',
    muted: isDark ? 'text-slate-400' : 'text-slate-500',
    body:  isDark ? 'text-slate-300' : 'text-slate-700',
  }
  const handleDrop = useCallback((e) => {
    e.preventDefault(); setDragging(false)
    const dropped = Array.from(e.dataTransfer.files).filter(f => /\.(jpg|jpeg|png|tif|tiff)$/i.test(f.name))
    if (dropped.length) onFiles(dropped)
  }, [onFiles])
  return (
    <div className="flex flex-col gap-4 max-w-3xl mx-auto w-full mt-6">
      <div className={`border-2 border-dashed rounded-2xl p-10 text-center cursor-pointer transition-all duration-200 ${dragging ? th.drag : th.zone}`}
        onDragOver={e => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}>
        <div className="text-4xl mb-3">🗂</div>
        <div className={`text-sm font-semibold mb-1 ${isDark ? 'text-white' : 'text-slate-800'}`}>Drop cheque images here</div>
        <div className={`text-xs ${th.muted}`}>JPG · PNG · TIF · TIFF accepted</div>
        <input ref={inputRef} type="file" multiple accept="image/*,.tif,.tiff" className="hidden"
          onChange={e => onFiles(Array.from(e.target.files))} />
      </div>
      <div className={`flex items-center gap-3 ${th.muted} text-xs`}>
        <div className={`flex-1 h-px ${isDark ? 'bg-white/8' : 'bg-slate-200'}`} />
        <span>or</span>
        <div className={`flex-1 h-px ${isDark ? 'bg-white/8' : 'bg-slate-200'}`} />
      </div>
      <button onClick={onLoadSamples}
        className={`w-full py-3 rounded-xl border text-sm font-semibold transition-colors ${isDark ? 'border-violet-700/50 bg-violet-900/20 text-violet-300 hover:bg-violet-900/40' : 'border-violet-300 bg-violet-50 text-violet-700 hover:bg-violet-100'}`}>
        📋 Load 12 Sample Cheques (demo)
      </button>
      {files.length > 0 && (
        <div className={`rounded-xl border overflow-hidden ${th.card}`}>
          <div className={`px-4 py-2 border-b flex items-center justify-between ${isDark ? 'border-white/8' : 'border-slate-100'}`}>
            <span className={`text-[10px] font-semibold uppercase tracking-widest ${th.muted}`}>{files.length} file{files.length > 1 ? 's' : ''} ready</span>
          </div>
          <div className="max-h-48 overflow-y-auto">
            {files.map((f, i) => (
              <div key={i} className={`flex items-center gap-3 px-4 py-2 text-[11px] border-b ${isDark ? 'border-white/4 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50'}`}>
                <span className="text-sm">🖼</span>
                <span className={`font-mono truncate flex-1 ${th.body}`}>{typeof f === 'string' ? f : f.name}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {files.length > 0 && (
        <button onClick={onStart}
          className="w-full py-3.5 rounded-xl bg-violet-600 hover:bg-violet-700 text-white font-semibold text-sm transition-colors">
          ▶ Start Presentment Processing ({files.length} cheque{files.length > 1 ? 's' : ''})
        </button>
      )}
    </div>
  )
}

function NPCIView({ npciGroups, items, onRunDrawee, isDark }) {
  const success = items.filter(it => it.status === 'success').length
  const failed  = items.filter(it => it.status === 'failed').length
  const th = {
    card:  isDark ? 'bg-white/4 border-white/8' : 'bg-white border-slate-200',
    muted: isDark ? 'text-slate-400' : 'text-slate-500',
    head:  isDark ? 'text-white' : 'text-slate-900',
  }
  return (
    <div className="flex flex-col gap-5 max-w-3xl mx-auto w-full mt-6">
      <div className={`rounded-xl border px-5 py-4 flex items-center gap-6 ${isDark ? 'bg-emerald-900/10 border-emerald-700/30' : 'bg-emerald-50 border-emerald-200'}`}>
        <span className="text-2xl">✅</span>
        <div>
          <div className={`text-sm font-semibold ${isDark ? 'text-emerald-300' : 'text-emerald-800'}`}>Presentment Complete</div>
          <div className={`text-xs mt-0.5 ${isDark ? 'text-emerald-400/70' : 'text-emerald-600'}`}>
            {success} accepted · {failed} rejected · routed to {Object.keys(npciGroups).length} clearing banks
          </div>
        </div>
        <div className="ml-auto flex gap-3">
          <button onClick={() => downloadCSV(buildSuccessCSV(items, 'presentment'), 'presentment_success.csv')}
            className={`px-3 py-1.5 rounded-lg border text-[11px] font-semibold transition-colors ${isDark ? 'border-emerald-700/40 text-emerald-300 hover:bg-emerald-900/30' : 'border-emerald-300 text-emerald-700 hover:bg-emerald-100'}`}>
            ⬇ Success CSV
          </button>
          <button onClick={() => downloadCSV(buildFailureCSV(items), 'presentment_failure.csv')}
            className={`px-3 py-1.5 rounded-lg border text-[11px] font-semibold transition-colors ${isDark ? 'border-red-700/40 text-red-300 hover:bg-red-900/30' : 'border-red-300 text-red-700 hover:bg-red-100'}`}>
            ⬇ Failure CSV
          </button>
        </div>
      </div>
      <div className={`text-xs font-semibold uppercase tracking-widest ${th.muted}`}>NPCI Clearing House — Routing accepted cheques by drawee bank</div>
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
            <button onClick={() => onRunDrawee(bank)}
              className={`w-full py-2 rounded-lg text-[11px] font-semibold transition-colors ${isDark ? 'bg-violet-900/40 text-violet-300 hover:bg-violet-900/60 border border-violet-700/40' : 'bg-violet-50 text-violet-700 hover:bg-violet-100 border border-violet-200'}`}>
              ▶ Process as {bank.split(' ')[0]}
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

function CompleteView({ presentItems, draweeItems, isDark }) {
  const ds = { success: draweeItems.filter(it => it.status === 'success').length, failed: draweeItems.filter(it => it.status === 'failed').length }
  return (
    <div className="flex flex-col gap-5 max-w-2xl mx-auto w-full mt-8">
      <div className={`rounded-xl border px-6 py-5 text-center ${isDark ? 'bg-indigo-900/10 border-indigo-700/30' : 'bg-indigo-50 border-indigo-200'}`}>
        <div className="text-3xl mb-2">🎉</div>
        <div className={`text-base font-semibold ${isDark ? 'text-indigo-200' : 'text-indigo-900'}`}>End-to-End Demo Complete</div>
        <div className={`text-xs mt-1 ${isDark ? 'text-indigo-400' : 'text-indigo-600'}`}>{ds.success} confirmed · {ds.failed} returned</div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        {[
          { label: 'Drawee Confirmed CSV',   fn: () => downloadCSV(buildSuccessCSV(draweeItems,  'drawee'),       'drawee_confirmed.csv'),   color: 'emerald' },
          { label: 'Drawee Returned CSV',    fn: () => downloadCSV(buildFailureCSV(draweeItems),                  'drawee_returned.csv'),    color: 'red'     },
          { label: 'Presentment Success',    fn: () => downloadCSV(buildSuccessCSV(presentItems, 'presentment'), 'presentment_success.csv'), color: 'violet'  },
          { label: 'Presentment Failure',    fn: () => downloadCSV(buildFailureCSV(presentItems),                'presentment_failure.csv'), color: 'orange'  },
        ].map(({ label, fn, color }) => (
          <button key={label} onClick={fn}
            className={`rounded-xl border px-4 py-3 text-[11px] font-semibold flex items-center gap-2 transition-colors text-left ${
              color === 'emerald' ? (isDark ? 'bg-emerald-900/20 border-emerald-700/40 text-emerald-300 hover:bg-emerald-900/40' : 'bg-emerald-50 border-emerald-200 text-emerald-700 hover:bg-emerald-100') :
              color === 'red'     ? (isDark ? 'bg-red-900/20 border-red-700/40 text-red-300 hover:bg-red-900/40' : 'bg-red-50 border-red-200 text-red-700 hover:bg-red-100') :
              color === 'violet'  ? (isDark ? 'bg-violet-900/20 border-violet-700/40 text-violet-300 hover:bg-violet-900/40' : 'bg-violet-50 border-violet-200 text-violet-700 hover:bg-violet-100') :
                                    (isDark ? 'bg-orange-900/20 border-orange-700/40 text-orange-300 hover:bg-orange-900/40' : 'bg-orange-50 border-orange-200 text-orange-700 hover:bg-orange-100')
            }`}>
            <span>⬇</span> {label}
          </button>
        ))}
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

const fresh = (filename) => ({ filename, status: 'queued', steps: [], decision: null, rejectReason: null, extracted: null, draweeBank: null, totalMs: 0, currentStep: null })

export default function CTSDemoPipeline() {
  const { isDark }   = useTheme()
  const { bankType } = useBankContext()
  usePageHeader({ subtitle: 'End-to-end live demo — Presentment · NPCI routing · Drawee processing' })

  const [phase,       setPhase]       = useState('setup')
  const [files,       setFiles]       = useState([])
  const [items,       setItems]       = useState([])       // presentment items
  const [draweeItems, setDraweeItems] = useState([])       // drawee items
  const [npciGroups,  setNpciGroups]  = useState({})       // bank → count
  const [eventLog,    setEventLog]    = useState([])
  const [activeSteps, setActiveSteps] = useState(new Set())
  const [doneSteps,   setDoneSteps]   = useState(new Set())
  const [failedSteps, setFailedSteps] = useState(new Set())
  const logRef    = useRef(null)
  const runningRef = useRef(false)

  useEffect(() => { if (logRef.current) logRef.current.scrollTop = 0 }, [eventLog.length])

  const th = {
    page:    isDark ? 'bg-[#020817]'          : 'bg-slate-50',
    card:    isDark ? 'bg-white/4 border-white/8' : 'bg-white border-slate-200',
    muted:   isDark ? 'text-slate-400'        : 'text-slate-500',
    faint:   isDark ? 'text-slate-600'        : 'text-slate-400',
    body:    isDark ? 'text-slate-300'        : 'text-slate-700',
    head:    isDark ? 'text-white'            : 'text-slate-900',
    divider: isDark ? 'border-white/8'        : 'border-slate-200',
    row:     isDark ? 'border-white/4 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
  }

  const addLog = useCallback((type, msg) => {
    const ts = new Date().toLocaleTimeString('en-IN', { hour12: false })
    setEventLog(prev => [{ type, msg, ts }, ...prev].slice(0, 60))
  }, [])

  // Mutate a single item in the items array immutably by filename reference
  const updateItem = useCallback((setter, filename, patch) => {
    setter(prev => prev.map(it => it.filename === filename ? { ...it, ...patch } : it))
  }, [])

  // ── Presentment pipeline ──────────────────────────────────────────────────

  async function processPresent(item, idx, sem) {
    await sem.acquire()
    try {
      const fail = presentmentFailure(idx)
      const t0   = Date.now()
      updateItem(setItems, item.filename, { status: 'processing', currentStep: null })
      addLog('info', `Started: ${item.filename}`)

      for (const stage of PRESENTMENT_STAGES) {
        updateItem(setItems, item.filename, { currentStep: stage.id })
        setActiveSteps(prev => new Set([...prev, stage.id]))

        const ms = stage.minMs + Math.floor(Math.random() * (stage.maxMs - stage.minMs))
        await new Promise(r => setTimeout(r, ms))

        if (fail && fail.step === stage.id) {
          // step failed
          setActiveSteps(prev => { const s = new Set(prev); s.delete(stage.id); return s })
          setFailedSteps(prev => new Set([...prev, stage.id]))
          const totalMs = Date.now() - t0
          updateItem(setItems, item.filename, {
            status: 'failed', decision: 'REJECTED', rejectReason: fail.reason,
            totalMs, currentStep: stage.id,
            steps: [...item.steps, { step: stage.id, status: 'failed', detail: fail.detail, ms }],
          })
          // also update on setItems fresh ref
          setItems(prev => prev.map(it => {
            if (it.filename !== item.filename) return it
            return { ...it, status: 'failed', decision: 'REJECTED', rejectReason: fail.reason, totalMs, currentStep: stage.id, steps: [...it.steps, { step: stage.id, status: 'failed', detail: fail.detail, ms }] }
          }))
          addLog('error', `${item.filename} → REJECTED (${fail.reason})`)
          return
        }

        // step passed
        let data = null
        if (stage.id === 'ocr_micr')        data = micrData(idx)
        else if (stage.id === 'data_extraction') { data = extractionData(idx); setItems(prev => prev.map(it => it.filename !== item.filename ? it : { ...it, extracted: data })) }
        else if (stage.id === 'vision_llm')  data = { tamper_risk: (0.01 + Math.random() * 0.03).toFixed(3), confidence: (0.95 + Math.random() * 0.04).toFixed(3), model: 'Qwen2-VL-7B' }
        else if (stage.id === 'cts_compliance') data = { checks_passed: 8, checks_total: 8 }
        else if (stage.id === 'lot_assignment') data = { lot_id: `LOT-${String(Math.floor(idx / 25) + 1).padStart(3,'0')}`, lot_position: (idx % 25) + 1 }

        setActiveSteps(prev => { const s = new Set(prev); s.delete(stage.id); return s })
        setDoneSteps(prev => new Set([...prev, stage.id]))
        setItems(prev => prev.map(it => it.filename !== item.filename ? it : { ...it, steps: [...it.steps, { step: stage.id, status: 'passed', ms, data }] }))
      }

      const totalMs = Date.now() - t0
      const draweeBank = DRAWEE_BANKS[idx % DRAWEE_BANKS.length]
      setItems(prev => prev.map(it => it.filename !== item.filename ? it : { ...it, status: 'success', decision: 'ACCEPTED', draweeBank, totalMs, currentStep: null }))
      addLog('success', `${item.filename} → ACCEPTED → ${draweeBank} (${totalMs}ms)`)
    } finally {
      sem.release()
    }
  }

  async function runPresentment(fileList) {
    if (runningRef.current) return
    runningRef.current = true
    const initialItems = fileList.map(f => fresh(typeof f === 'string' ? f : f.name))
    setItems(initialItems)
    setPhase('presentment')
    setActiveSteps(new Set())
    setDoneSteps(new Set())
    setFailedSteps(new Set())
    addLog('info', `Presentment started — ${initialItems.length} cheques`)

    const sem = createSemaphore(MAX_CONCURRENT)
    await Promise.all(initialItems.map((item, idx) => processPresent(item, idx, sem)))

    // Build NPCI groups from final state
    setItems(prev => {
      const groups = {}
      prev.forEach(it => {
        if (it.status === 'success' && it.draweeBank) {
          groups[it.draweeBank] = (groups[it.draweeBank] || 0) + 1
        }
      })
      setNpciGroups(groups)
      const s = prev.filter(it => it.status === 'success').length
      const f = prev.filter(it => it.status === 'failed').length
      addLog('info', `Presentment done — ${s} accepted, ${f} rejected`)
      return prev
    })
    setPhase('npci')
    runningRef.current = false
  }

  // ── Drawee pipeline ───────────────────────────────────────────────────────

  async function processDrawee(item, idx, sem, setter) {
    await sem.acquire()
    try {
      const fail = draweeFailure(idx)
      const t0   = Date.now()
      setter(prev => prev.map(it => it.filename !== item.filename ? it : { ...it, status: 'processing', currentStep: null }))

      for (const stage of DRAWEE_STAGES) {
        setter(prev => prev.map(it => it.filename !== item.filename ? it : { ...it, currentStep: stage.id }))
        setActiveSteps(prev => new Set([...prev, stage.id]))

        const ms = stage.minMs + Math.floor(Math.random() * (stage.maxMs - stage.minMs))
        await new Promise(r => setTimeout(r, ms))

        if (fail && fail.step === stage.id) {
          setActiveSteps(prev => { const s = new Set(prev); s.delete(stage.id); return s })
          setFailedSteps(prev => new Set([...prev, stage.id]))
          const totalMs = Date.now() - t0
          setter(prev => prev.map(it => it.filename !== item.filename ? it : { ...it, status: 'failed', decision: 'RETURNED', rejectReason: fail.reason, totalMs, steps: [...it.steps, { step: stage.id, status: 'failed', detail: fail.detail, ms }] }))
          addLog('error', `${item.filename} → RETURNED (${fail.reason})`)
          return
        }

        let data = null
        if (stage.id === 'signature_vault') data = { match_score: (0.88 + Math.random() * 0.10).toFixed(3), specimens: 2, model: 'Siamese-SNN' }
        else if (stage.id === 'fraud_score') data = { fraud_score: (Math.random() * 0.15).toFixed(3), threshold: 0.72, shap_top: 'account_age' }
        else if (stage.id === 'rbi_checklist') data = { checks: 11, passed: 11, failed: 0 }
        else if (stage.id === 'account_status') data = { status: 'ACTIVE', balance_sufficient: true }
        else if (stage.id === 'pps_check') data = { registered: true, amount_match: true }

        setActiveSteps(prev => { const s = new Set(prev); s.delete(stage.id); return s })
        setDoneSteps(prev => new Set([...prev, stage.id]))
        setter(prev => prev.map(it => it.filename !== item.filename ? it : { ...it, steps: [...it.steps, { step: stage.id, status: 'passed', ms, data }] }))
      }

      const totalMs = Date.now() - t0
      setter(prev => prev.map(it => it.filename !== item.filename ? it : { ...it, status: 'success', decision: 'CONFIRMED', totalMs, currentStep: null }))
      addLog('success', `${item.filename} → CONFIRMED (${totalMs}ms)`)
    } finally {
      sem.release()
    }
  }

  async function runDrawee(bankName) {
    if (runningRef.current) return
    runningRef.current = true

    // Get accepted items for this bank from current items state
    setItems(prev => {
      const bankItems = prev.filter(it => it.status === 'success' && it.draweeBank === bankName)
      const di = bankItems.map(it => ({ ...fresh(it.filename), extracted: it.extracted }))
      setDraweeItems(di)

      // kick off async after state update
      setTimeout(async () => {
        setPhase('drawee')
        setActiveSteps(new Set())
        setDoneSteps(new Set())
        setFailedSteps(new Set())
        addLog('info', `Drawee processing started for ${bankName} — ${di.length} cheques`)

        const sem = createSemaphore(MAX_CONCURRENT)
        await Promise.all(di.map((item, idx) => processDrawee(item, idx, sem, setDraweeItems)))

        setDraweeItems(prev2 => {
          const s = prev2.filter(it => it.status === 'success').length
          const f = prev2.filter(it => it.status === 'failed').length
          addLog('info', `Drawee done — ${s} confirmed, ${f} returned`)
          return prev2
        })
        setPhase('complete')
        runningRef.current = false
      }, 0)

      return prev
    })
  }

  function handleFiles(newFiles) {
    setFiles(prev => {
      const names = new Set(prev.map(f => typeof f === 'string' ? f : f.name))
      return [...prev, ...newFiles.filter(f => !names.has(typeof f === 'string' ? f : f.name))]
    })
  }

  const displayItems = phase === 'drawee' || phase === 'complete' ? draweeItems : items
  const currentStages = phase === 'drawee' ? DRAWEE_STAGES : PRESENTMENT_STAGES

  const processing = displayItems.filter(it => it.status === 'processing').length
  const success    = displayItems.filter(it => it.status === 'success').length
  const failed     = displayItems.filter(it => it.status === 'failed').length

  return (
    <AppShell>
      <div className={`flex flex-col h-full overflow-hidden ${th.page}`}>
        <PhaseBar phase={phase} isDark={isDark} />

        {/* KPI strip */}
        {(phase === 'presentment' || phase === 'drawee') && (
          <div className={`shrink-0 px-6 py-2.5 border-b ${th.divider} flex items-center gap-8`}>
            {[
              { label: 'Processing', val: processing, color: 'text-amber-400' },
              { label: phase === 'drawee' ? 'Confirmed' : 'Accepted', val: success, color: 'text-emerald-400' },
              { label: phase === 'drawee' ? 'Returned'  : 'Rejected',  val: failed,  color: 'text-red-400'     },
              { label: 'Total', val: displayItems.length, color: isDark ? 'text-slate-300' : 'text-slate-700' },
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
          <div className={`w-72 shrink-0 border-r ${th.divider} flex flex-col`}>
            <div className={`px-3 py-2 border-b ${th.divider} flex items-center justify-between`}>
              <span className={`text-[10px] font-semibold uppercase tracking-widest ${th.muted}`}>Cheque Queue</span>
              <span className={`text-[10px] font-mono ${th.faint}`}>{displayItems.length || files.length}</span>
            </div>
            <div className="flex-1 overflow-y-auto">
              {phase === 'setup' && files.map((f, i) => (
                <div key={i} className={`flex items-center gap-2.5 px-3 py-2 border-b text-[10px] ${th.row}`}>
                  <span>🖼</span>
                  <span className={`font-mono truncate flex-1 ${th.body}`}>{typeof f === 'string' ? f : f.name}</span>
                </div>
              ))}
              {phase !== 'setup' && displayItems.map((it, i) => (
                <div key={i} className={`border-b px-3 py-2 text-[10px] ${th.row}`}>
                  <div className="flex items-center gap-2 mb-1">
                    <span className={statusColor(it.status)}>{it.status === 'success' ? '✓' : it.status === 'failed' ? '✕' : it.status === 'processing' ? '⟳' : '○'}</span>
                    <span className={`font-mono truncate flex-1 ${th.body}`}>{it.filename}</span>
                  </div>
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className={statusBadge(it.status, isDark)}>{it.decision || it.status}</span>
                    {it.status === 'processing' && it.currentStep && (
                      <span className={`text-[9px] font-mono ${th.faint} truncate`}>{it.currentStep}</span>
                    )}
                    {it.totalMs > 0 && <span className={`ml-auto text-[9px] font-mono ${th.faint}`}>{it.totalMs}ms</span>}
                  </div>
                  {it.rejectReason && <div className="text-[9px] mt-1 text-red-400 truncate">{it.rejectReason}</div>}
                </div>
              ))}
            </div>
          </div>

          {/* Center */}
          <div className="flex-1 flex flex-col overflow-hidden">
            {/* Stage chips */}
            {(phase === 'presentment' || phase === 'drawee') && (
              <div className={`shrink-0 px-4 pt-4 pb-3 border-b ${th.divider}`}>
                <div className={`text-[9px] font-semibold uppercase tracking-widest mb-3 ${th.faint}`}>
                  {phase === 'presentment' ? 'Presentment Pipeline (8 stages)' : 'Drawee Pipeline (10 stages) — RBI CTS checklist · Sig Vault · CBS · Fraud · NGCH'}
                </div>
                <div className="flex items-center gap-1.5 flex-wrap">
                  {currentStages.map(stage => (
                    <StageChip key={stage.id} stage={stage} activeSteps={activeSteps} doneSteps={doneSteps} failedSteps={failedSteps} isDark={isDark} />
                  ))}
                </div>
              </div>
            )}

            <div className="flex-1 overflow-y-auto px-4 py-2">
              {phase === 'setup' && (
                <UploadZone files={files} onFiles={handleFiles} onLoadSamples={() => setFiles(SAMPLE_FILES)} onStart={() => runPresentment(files)} isDark={isDark} />
              )}
              {phase === 'npci' && (
                <NPCIView npciGroups={npciGroups} items={items} onRunDrawee={runDrawee} isDark={isDark} />
              )}
              {phase === 'complete' && (
                <CompleteView presentItems={items} draweeItems={draweeItems} isDark={isDark} />
              )}

              {/* Live processing table */}
              {(phase === 'presentment' || phase === 'drawee') && displayItems.length > 0 && (
                <div className={`mt-3 rounded-xl border overflow-hidden ${th.card}`}>
                  <div className={`px-4 py-2 border-b ${th.divider}`}>
                    <span className={`text-[10px] font-semibold uppercase tracking-widest ${th.muted}`}>Live Processing Detail</span>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-[10px]">
                      <thead>
                        <tr className={`border-b ${th.divider}`}>
                          {['File','Status','Current Step','Decision','Time'].map(h => (
                            <th key={h} className={`px-3 py-2 text-left font-semibold ${th.muted}`}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {displayItems.slice(0, 30).map((it, i) => (
                          <tr key={i} className={`border-b ${th.row}`}>
                            <td className={`px-3 py-2 font-mono truncate max-w-[140px] ${th.body}`}>{it.filename}</td>
                            <td className="px-3 py-2"><span className={statusBadge(it.status, isDark)}>{it.status}</span></td>
                            <td className={`px-3 py-2 font-mono ${th.faint}`}>{it.currentStep || '—'}</td>
                            <td className={`px-3 py-2 font-semibold ${it.decision === 'ACCEPTED' || it.decision === 'CONFIRMED' ? 'text-emerald-400' : it.decision === 'REJECTED' || it.decision === 'RETURNED' ? 'text-red-400' : th.faint}`}>{it.decision || '—'}</td>
                            <td className={`px-3 py-2 font-mono ${th.faint}`}>{it.totalMs ? `${it.totalMs}ms` : '—'}</td>
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
          <div className={`w-60 shrink-0 border-l ${th.divider} flex flex-col`}>
            <div className={`px-3 py-2 border-b ${th.divider} flex items-center justify-between`}>
              <span className={`text-[10px] font-semibold uppercase tracking-widest ${th.muted}`}>Live Feed</span>
              {phase !== 'setup' && phase !== 'npci' && phase !== 'complete' && (
                <span className="flex items-center gap-1 text-[9px] text-emerald-400">
                  <span className="w-1 h-1 rounded-full bg-emerald-400 animate-pulse" />Live
                </span>
              )}
            </div>
            <div ref={logRef} className="flex-1 overflow-y-auto p-2 space-y-1">
              {eventLog.length === 0 && <div className={`text-[10px] text-center mt-8 ${th.faint}`}>Events will appear here</div>}
              {eventLog.map((ev, i) => (
                <div key={i} className={`text-[9px] rounded px-2 py-1 flex items-start gap-1.5 ${
                  ev.type === 'error'   ? (isDark ? 'bg-red-900/20 text-red-300'         : 'bg-red-50 text-red-700') :
                  ev.type === 'success' ? (isDark ? 'bg-emerald-900/20 text-emerald-300' : 'bg-emerald-50 text-emerald-700') :
                                         (isDark ? 'bg-white/3 text-slate-400'          : 'bg-slate-50 text-slate-600')
                }`}>
                  <span className="font-mono shrink-0 opacity-60">{ev.ts}</span>
                  <span className="leading-relaxed break-all">{ev.msg}</span>
                </div>
              ))}
            </div>

            {/* Download shortcuts during NPCI/Complete phases */}
            {(phase === 'npci' || phase === 'complete') && (
              <div className={`shrink-0 p-3 border-t ${th.divider} space-y-2`}>
                <div className={`text-[9px] font-semibold uppercase tracking-widest mb-2 ${th.muted}`}>Downloads</div>
                <button onClick={() => downloadCSV(buildSuccessCSV(items, 'presentment'), 'presentment_success.csv')}
                  className={`block w-full text-center py-1.5 rounded-lg text-[10px] font-semibold border transition-colors ${isDark ? 'border-emerald-700/40 text-emerald-300 hover:bg-emerald-900/20' : 'border-emerald-200 text-emerald-700 hover:bg-emerald-50'}`}>
                  ⬇ Presentment Success
                </button>
                <button onClick={() => downloadCSV(buildFailureCSV(items), 'presentment_failure.csv')}
                  className={`block w-full text-center py-1.5 rounded-lg text-[10px] font-semibold border transition-colors ${isDark ? 'border-red-700/40 text-red-300 hover:bg-red-900/20' : 'border-red-200 text-red-700 hover:bg-red-50'}`}>
                  ⬇ Presentment Failure
                </button>
                {phase === 'complete' && <>
                  <button onClick={() => downloadCSV(buildSuccessCSV(draweeItems, 'drawee'), 'drawee_confirmed.csv')}
                    className={`block w-full text-center py-1.5 rounded-lg text-[10px] font-semibold border transition-colors ${isDark ? 'border-violet-700/40 text-violet-300 hover:bg-violet-900/20' : 'border-violet-200 text-violet-700 hover:bg-violet-50'}`}>
                    ⬇ Drawee Confirmed
                  </button>
                  <button onClick={() => downloadCSV(buildFailureCSV(draweeItems), 'drawee_returned.csv')}
                    className={`block w-full text-center py-1.5 rounded-lg text-[10px] font-semibold border transition-colors ${isDark ? 'border-orange-700/40 text-orange-300 hover:bg-orange-900/20' : 'border-orange-200 text-orange-700 hover:bg-orange-50'}`}>
                    ⬇ Drawee Returned
                  </button>
                </>}
              </div>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  )
}

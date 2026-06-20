import { useState, useEffect, useRef } from 'react'
import { useTheme } from '../../../shared/theme/ThemeContext'
import AppShell from '../../../shared/layout/AppShell'

// ── Mock scanner registry ─────────────────────────────────────────────────
const SCANNERS = [
  { id: 'SCN-001', oem: 'PANINI',  model: 'Panini I:Deal',    status: 'READY',       counter: 1287, operator: 'Ramesh K.' },
  { id: 'SCN-002', oem: 'CANON',   model: 'Canon CR-190i',    status: 'SCANNING',    counter: 943,  operator: 'Priya M.' },
  { id: 'SCN-003', oem: 'PANINI',  model: 'Panini MyMicr',    status: 'READY',       counter: 2104, operator: 'Anil S.' },
  { id: 'SCN-004', oem: 'CANON',   model: 'Canon CR-120',     status: 'OFFLINE',     counter: 621,  operator: '—' },
  { id: 'SCN-005', oem: 'GENERIC', model: 'TWAIN Compatible', status: 'ERROR',       counter: 88,   operator: 'Suresh P.' },
]

// Simulate incoming scans from active scanners
function generateScan(idx, scanner) {
  const chequeNos = ['100001','100002','100003','100004','100005','100006','100007','100008','100009','100010']
  const accounts  = ['4521','7832','2291','6610','3347','9901','1123','5580','7744','2256']
  const i = idx % 10
  return {
    scan_id:    `SCAN-20260619-${String(idx + 1).padStart(6, '0')}`,
    scanner_id: scanner.id,
    oem:        scanner.oem,
    model:      scanner.model,
    cheque_no:  chequeNos[i],
    acct_suffix: accounts[i],
    front_dpi:  300,
    front_kb:   +(35 + Math.random() * 15).toFixed(1),
    micr_ok:    Math.random() > 0.05,
    iqa_score:  +(0.82 + Math.random() * 0.17).toFixed(3),
    ts:         new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
    status:     'QUEUED',
  }
}

const OEM_COLOR = {
  PANINI:  { badge: 'bg-blue-500/20 text-blue-300 border-blue-700/40', dot: 'bg-blue-400' },
  CANON:   { badge: 'bg-purple-500/20 text-purple-300 border-purple-700/40', dot: 'bg-purple-400' },
  GENERIC: { badge: 'bg-slate-500/20 text-slate-400 border-slate-600/40', dot: 'bg-slate-400' },
}
const OEM_COLOR_L = {
  PANINI:  { badge: 'bg-blue-50 text-blue-700 border-blue-200', dot: 'bg-blue-500' },
  CANON:   { badge: 'bg-purple-50 text-purple-700 border-purple-200', dot: 'bg-purple-500' },
  GENERIC: { badge: 'bg-slate-100 text-slate-600 border-slate-300', dot: 'bg-slate-400' },
}

const STATUS_COLOR = {
  READY:    { d: 'text-emerald-400', l: 'text-emerald-600', dot: 'bg-emerald-500' },
  SCANNING: { d: 'text-amber-400',   l: 'text-amber-600',   dot: 'bg-amber-400 animate-pulse' },
  OFFLINE:  { d: 'text-slate-500',   l: 'text-slate-400',   dot: 'bg-slate-500' },
  ERROR:    { d: 'text-red-400',     l: 'text-red-600',     dot: 'bg-red-500' },
}

export default function CTSScanner() {
  const { isDark } = useTheme()
  const [scans, setScans]         = useState([])
  const [scanCount, setScanCount] = useState(0)
  const [running, setRunning]     = useState(false)
  const intervalRef               = useRef(null)

  function startScan() {
    setRunning(true)
    let idx = scanCount
    intervalRef.current = setInterval(() => {
      const activeScanners = SCANNERS.filter(s => s.status === 'READY' || s.status === 'SCANNING')
      const scanner = activeScanners[idx % activeScanners.length]
      const scan = generateScan(idx, scanner)
      setScans(prev => [scan, ...prev].slice(0, 50))
      setScanCount(c => c + 1)
      idx++
    }, 1400)
  }

  function stopScan() {
    setRunning(false)
    clearInterval(intervalRef.current)
  }

  useEffect(() => () => clearInterval(intervalRef.current), [])

  const oemC = isDark ? OEM_COLOR : OEM_COLOR_L

  const th = {
    page:    isDark ? 'bg-transparent'                      : 'bg-slate-50',
    card:    isDark ? 'bg-white/4 border-white/8'       : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'                       : 'text-slate-900',
    body:    isDark ? 'text-slate-300'                   : 'text-slate-700',
    muted:   isDark ? 'text-slate-400'                   : 'text-slate-500',
    faint:   isDark ? 'text-slate-600'                   : 'text-slate-400',
    divider: isDark ? 'border-white/8'                   : 'border-slate-200',
    row:     isDark ? 'border-white/4 hover:bg-white/2'  : 'border-slate-100 hover:bg-slate-50',
    mono:    isDark ? 'text-slate-300 font-mono text-xs' : 'text-slate-600 font-mono text-xs',
  }

  const micrOk   = scans.filter(s => s.micr_ok).length
  const micrFail = scans.filter(s => !s.micr_ok).length
  const avgIqa   = scans.length ? (scans.reduce((a, s) => a + s.iqa_score, 0) / scans.length).toFixed(3) : '—'

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>

        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>Scanner SDK</h1>
            <p className={`text-xs ${th.muted} mt-0.5`}>Panini · Canon · TWAIN/ISIS — OEM-agnostic ingestion</p>
          </div>
          <button
            onClick={running ? stopScan : startScan}
            className={`flex items-center gap-2 text-xs rounded-lg px-4 py-2 font-medium transition-colors ${
              running
                ? 'bg-red-600 hover:bg-red-500 text-white'
                : 'bg-emerald-600 hover:bg-emerald-500 text-white'
            }`}
          >
            <span className={`w-2 h-2 rounded-full ${running ? 'bg-white animate-pulse' : 'bg-white'}`} />
            {running ? 'Stop Scanning' : 'Start Scanning'}
          </button>
        </div>

        {/* Connected scanners grid */}
        <div className="grid grid-cols-5 gap-3 mb-6">
          {SCANNERS.map(s => {
            const sc = STATUS_COLOR[s.status] || STATUS_COLOR.OFFLINE
            const oc = oemC[s.oem] || oemC.GENERIC
            return (
              <div key={s.id} className={`border rounded-xl p-3 ${th.card}`}>
                <div className="flex items-start justify-between mb-2">
                  <span className={`text-[10px] px-1.5 py-0.5 rounded border font-medium ${oc.badge}`}>{s.oem}</span>
                  <div className={`w-2 h-2 rounded-full mt-0.5 ${sc.dot}`} />
                </div>
                <div className={`text-xs font-medium ${th.heading} mb-0.5`}>{s.model}</div>
                <div className={`text-[10px] ${th.muted}`}>{s.id}</div>
                <div className={`text-[10px] mt-1 font-medium ${isDark ? sc.d : sc.l}`}>{s.status}</div>
                <div className={`text-[10px] ${th.faint} mt-1`}>{s.counter.toLocaleString()} scans</div>
                <div className={`text-[10px] ${th.faint}`}>{s.operator}</div>
              </div>
            )
          })}
        </div>

        {/* Session KPI strip */}
        <div className="grid grid-cols-4 gap-3 mb-4">
          {[
            { label: 'Scanned This Session', value: scanCount,      color: th.heading },
            { label: 'MICR OK',              value: micrOk,         color: isDark ? 'text-emerald-400' : 'text-emerald-600' },
            { label: 'MICR Failures',        value: micrFail,       color: micrFail > 0 ? (isDark ? 'text-red-400' : 'text-red-600') : (isDark ? 'text-emerald-400' : 'text-emerald-600') },
            { label: 'Avg IQA Score',        value: avgIqa,         color: isDark ? 'text-amber-400' : 'text-amber-600' },
          ].map(k => (
            <div key={k.label} className={`border rounded-xl px-4 py-3 ${th.card}`}>
              <div className={`text-[10px] ${th.faint} mb-1`}>{k.label}</div>
              <div className={`text-2xl font-bold ${k.color}`}>{k.value}</div>
            </div>
          ))}
        </div>

        {/* Scan feed */}
        <div className={`border rounded-xl overflow-hidden ${th.card}`}>
          <div className={`px-4 py-2.5 border-b ${th.divider} flex items-center justify-between`}>
            <span className={`text-sm font-medium ${th.heading}`}>Live Scan Feed</span>
            {running && (
              <span className="flex items-center gap-1.5 text-[10px] text-emerald-400">
                <span className="w-1.5 h-1.5 bg-emerald-400 rounded-full animate-pulse" />
                LIVE
              </span>
            )}
          </div>

          {/* Table header */}
          <div className={`grid grid-cols-12 gap-2 px-4 py-2 border-b ${th.divider} text-[10px] ${th.faint} font-medium uppercase tracking-wider`}>
            <div className="col-span-3">Scan ID</div>
            <div className="col-span-1">OEM</div>
            <div className="col-span-2">Cheque / Acct</div>
            <div className="col-span-1 text-center">DPI</div>
            <div className="col-span-1 text-center">KB</div>
            <div className="col-span-1 text-center">MICR</div>
            <div className="col-span-1 text-center">IQA</div>
            <div className="col-span-2 text-right">Time</div>
          </div>

          {scans.length === 0 && (
            <div className={`px-4 py-8 text-center text-sm ${th.muted}`}>
              Press <strong>Start Scanning</strong> to simulate live scanner ingestion.
            </div>
          )}

          {scans.map(scan => {
            const oc = oemC[scan.oem] || oemC.GENERIC
            return (
              <div key={scan.scan_id} className={`grid grid-cols-12 gap-2 px-4 py-2.5 border-b ${th.row} transition-colors text-xs`}>
                <div className={`col-span-3 ${th.mono}`}>{scan.scan_id}</div>
                <div className="col-span-1">
                  <span className={`text-[10px] px-1.5 py-0.5 rounded border font-medium ${oc.badge}`}>{scan.oem}</span>
                </div>
                <div className={`col-span-2 ${th.muted}`}>
                  <div>{scan.cheque_no}</div>
                  <div className={`text-[10px] ${th.faint}`}>****{scan.acct_suffix}</div>
                </div>
                <div className={`col-span-1 text-center ${th.body}`}>{scan.front_dpi}</div>
                <div className={`col-span-1 text-center ${th.body}`}>{scan.front_kb}</div>
                <div className={`col-span-1 text-center font-medium ${scan.micr_ok ? (isDark ? 'text-emerald-400' : 'text-emerald-600') : (isDark ? 'text-red-400' : 'text-red-600')}`}>
                  {scan.micr_ok ? '✓' : '✗'}
                </div>
                <div className={`col-span-1 text-center ${scan.iqa_score >= 0.90 ? (isDark ? 'text-emerald-400' : 'text-emerald-600') : scan.iqa_score >= 0.70 ? (isDark ? 'text-amber-400' : 'text-amber-600') : (isDark ? 'text-red-400' : 'text-red-600')}`}>
                  {scan.iqa_score}
                </div>
                <div className={`col-span-2 text-right ${th.faint}`}>{scan.ts}</div>
              </div>
            )
          })}
        </div>

        {/* SDK reference */}
        <div className={`mt-4 border rounded-xl p-4 ${th.card}`}>
          <div className={`text-xs font-medium ${th.heading} mb-3`}>SDK Integration Reference</div>
          <div className="grid grid-cols-3 gap-4">
            {[
              { oem: 'Panini', models: 'I:Deal · MyMicr · Vision X', interface: 'Panini SDK (COM/.NET)', note: 'Supports MICR E-13B + CMC-7' },
              { oem: 'Canon',  models: 'CR-190i · CR-120 · CR-80',   interface: 'Canon SDK / ISIS driver', note: 'Duplex scan, auto-feed, IQA built-in' },
              { oem: 'Generic', models: 'Any TWAIN/ISIS device',      interface: 'TWAIN 2.x / ISIS 3.x',  note: 'Fallback — no MICR guarantee' },
            ].map(s => (
              <div key={s.oem}>
                <div className={`text-xs font-semibold ${th.heading}`}>{s.oem}</div>
                <div className={`text-[10px] ${th.muted} mt-0.5`}>{s.models}</div>
                <div className={`text-[10px] ${th.faint} mt-1`}>{s.interface}</div>
                <div className={`text-[10px] ${th.faint}`}>{s.note}</div>
              </div>
            ))}
          </div>
        </div>

      </div>
    </AppShell>
  )
}

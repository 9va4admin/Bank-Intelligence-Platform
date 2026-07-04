/**
 * Branch Portal — Scanner Monitor (/branch/scan)
 *
 * Live view of the EEH upload stream. Each row is a cheque the scanner has
 * sent to the EEH service. Status updates arrive via SSE (real-time).
 *
 * Drop-folder model: the scanner-bridge agent watches the OEM drop folder,
 * calls EEH UploadCheque gRPC, and the EEH pushes back ChequeAck events.
 * This UI subscribes to the SSE stream and shows per-item results.
 */
import { useState, useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { useTheme } from '../../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../../shared/context/BankContext'
import AppShell from '../../../../shared/layout/AppShell'

// ─── Mock SSE feed (simulates ChequeAck events arriving over time) ───────────

const MOCK_INSTRUMENTS = [
  { scan_id: 'SC-001247', idempotency_key: 'br01:sess01:247', micr_suffix: '4521', payee: 'N***', amount_range: '₹[1L-5L]', status: 'ACCEPTED', lot_id: 'LOT-0007', ts: '10:43:51' },
  { scan_id: 'SC-001246', idempotency_key: 'br01:sess01:246', micr_suffix: '8873', payee: 'M***', amount_range: '₹[<1L]',    status: 'ACCEPTED', lot_id: 'LOT-0007', ts: '10:43:49' },
  { scan_id: 'SC-001245', idempotency_key: 'br01:sess01:245', micr_suffix: '2211', payee: 'R***', amount_range: '₹[1L-5L]', status: 'HELD',     lot_id: '',         ts: '10:43:47', mismatch_id: 'MM-001', mismatch_fields: ['amount_figures'] },
  { scan_id: 'SC-001244', idempotency_key: 'br01:sess01:244', micr_suffix: '6699', payee: 'A***', amount_range: '₹[<1L]',    status: 'REJECTED', lot_id: '',         ts: '10:43:44', reason: 'CTS_IMAGE_QUALITY' },
  { scan_id: 'SC-001243', idempotency_key: 'br01:sess01:243', micr_suffix: '3312', payee: 'S***', amount_range: '₹[5L-10L]', status: 'ACCEPTED', lot_id: 'LOT-0007', ts: '10:43:42' },
  { scan_id: 'SC-001242', idempotency_key: 'br01:sess01:242', micr_suffix: '7741', payee: 'K***', amount_range: '₹[1L-5L]', status: 'ACCEPTED', lot_id: 'LOT-0007', ts: '10:43:40' },
  { scan_id: 'SC-001241', idempotency_key: 'br01:sess01:241', micr_suffix: '0023', payee: 'P***', amount_range: '₹[<1L]',    status: 'ACCEPTED', lot_id: 'LOT-0007', ts: '10:43:38' },
  { scan_id: 'SC-001240', idempotency_key: 'br01:sess01:240', micr_suffix: '9988', payee: 'V***', amount_range: '₹[1L-5L]', status: 'ACCEPTED', lot_id: 'LOT-0006', ts: '10:43:35' },
]

const STATUS_CFG = {
  ACCEPTED: { label: 'Accepted', bg: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30' },
  REJECTED: { label: 'Rejected', bg: 'bg-red-500/15 text-red-400 border-red-500/30' },
  HELD:     { label: 'On Hold',  bg: 'bg-amber-500/15 text-amber-400 border-amber-500/30' },
  DUPLICATE:{ label: 'Duplicate',bg: 'bg-slate-500/15 text-slate-400 border-slate-500/30' },
  PENDING:  { label: 'Sending…', bg: 'bg-blue-500/15 text-blue-400 border-blue-500/30' },
}

function StatusPill({ status }) {
  const cfg = STATUS_CFG[status] || STATUS_CFG.PENDING
  return (
    <span className={`inline-flex items-center text-xs px-2 py-0.5 rounded border font-medium ${cfg.bg}`}>
      {cfg.label}
    </span>
  )
}

function EventRow({ item, isDark }) {
  const th = {
    row:    isDark ? 'border-white/4 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
    mono:   isDark ? 'text-slate-300 font-mono text-xs' : 'text-slate-600 font-mono text-xs',
    muted:  isDark ? 'text-slate-400 text-xs' : 'text-slate-500 text-xs',
  }
  return (
    <tr className={`border-b transition-colors ${th.row}`}>
      <td className={`py-2 px-3 ${th.muted}`}>{item.ts}</td>
      <td className={`py-2 px-3 ${th.mono}`}>{item.scan_id}</td>
      <td className={`py-2 px-3 ${th.mono}`}>****{item.micr_suffix}</td>
      <td className={`py-2 px-3 ${th.muted}`}>{item.payee}</td>
      <td className={`py-2 px-3 ${th.muted} tabular-nums`}>{item.amount_range}</td>
      <td className="py-2 px-3"><StatusPill status={item.status} /></td>
      <td className={`py-2 px-3 ${th.mono}`}>{item.lot_id || '—'}</td>
      <td className={`py-2 px-3 ${th.muted}`}>
        {item.mismatch_id && (
          <Link to="/branch/mismatch" className="text-amber-400 hover:underline text-xs">
            {item.mismatch_id}
          </Link>
        )}
        {item.reason && <span className="text-red-400 text-xs">{item.reason}</span>}
      </td>
    </tr>
  )
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function BranchScanMonitor() {
  const { isDark } = useTheme()
  const { bankId } = useBankContext()

  // SSE connection state
  const [sseStatus, setSseStatus] = useState('CONNECTING')
  const [instruments, setInstruments] = useState(MOCK_INSTRUMENTS)
  const [autoScroll, setAutoScroll] = useState(true)
  const [rateCps, setRateCps] = useState(0.8)   // cheques per second (mock)
  const tableRef = useRef(null)

  // Simulate SSE connection on mount
  useEffect(() => {
    const t = setTimeout(() => setSseStatus('CONNECTED'), 600)
    return () => clearTimeout(t)
  }, [])

  // Auto-scroll to top (newest item) when new instruments arrive
  useEffect(() => {
    if (autoScroll && tableRef.current) {
      tableRef.current.scrollTop = 0
    }
  }, [instruments, autoScroll])

  const th = {
    page:    isDark ? 'bg-navy-950'  : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'   : 'text-slate-900',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    th:      isDark ? 'text-slate-500 bg-navy-900/80 text-xs font-medium uppercase tracking-wider'
                    : 'text-slate-400 bg-slate-50 text-xs font-medium uppercase tracking-wider',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
  }

  const accepted = instruments.filter(i => i.status === 'ACCEPTED').length
  const rejected = instruments.filter(i => i.status === 'REJECTED').length
  const held = instruments.filter(i => i.status === 'HELD').length

  return (
    <AppShell>
      <div className={`flex-1 flex flex-col ${th.page}`}>
        {/* Header bar */}
        <div className={`flex items-center justify-between px-6 py-3 border-b ${th.divider}`}>
          <div className="flex items-center gap-4">
            <Link to="/branch" className={`text-sm ${th.muted} hover:text-blue-400 transition-colors`}>
              ← Dashboard
            </Link>
            <h1 className={`text-base font-semibold ${th.heading}`}>Scanner Monitor</h1>
          </div>
          <div className="flex items-center gap-4 text-xs">
            <span className={`flex items-center gap-1.5 ${th.muted}`}>
              <span className={`w-1.5 h-1.5 rounded-full ${sseStatus === 'CONNECTED' ? 'bg-emerald-400 animate-pulse' : 'bg-slate-500'}`} />
              SSE {sseStatus}
            </span>
            <span className={th.muted}>{rateCps.toFixed(1)} c/s</span>
            <label className={`flex items-center gap-1.5 ${th.muted} cursor-pointer`}>
              <input
                type="checkbox"
                checked={autoScroll}
                onChange={e => setAutoScroll(e.target.checked)}
                className="accent-blue-500"
              />
              Auto-scroll
            </label>
          </div>
        </div>

        {/* Summary strip */}
        <div className={`flex items-center gap-6 px-6 py-2 border-b ${th.divider} text-xs`}>
          <span className={th.muted}>
            <span className="text-white font-medium">{instruments.length}</span> total
          </span>
          <span className="text-emerald-400 font-medium">{accepted} accepted</span>
          <span className={rejected > 0 ? 'text-red-400 font-medium' : th.muted}>
            {rejected} rejected
          </span>
          <span className={held > 0 ? 'text-amber-400 font-medium' : th.muted}>
            {held} held
          </span>
          {held > 0 && (
            <Link to="/branch/mismatch" className="text-amber-400 hover:underline">
              Review held items →
            </Link>
          )}
        </div>

        {/* Event table */}
        <div className="flex-1 overflow-y-auto" ref={tableRef}>
          <table className="w-full border-collapse">
            <thead className="sticky top-0 z-10">
              <tr>
                {['Time', 'Scan ID', 'MICR (last 4)', 'Payee', 'Amount', 'Status', 'Lot', 'Notes'].map(h => (
                  <th key={h} className={`px-3 py-2 text-left border-b ${th.divider} ${th.th}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {instruments.map(item => (
                <EventRow key={item.scan_id} item={item} isDark={isDark} />
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </AppShell>
  )
}

/**
 * Branch Portal — Scanner Monitor (/branch/scan)
 *
 * Live view of the scan stream per session. Merges two data sources:
 *  1. /v1/cts/scan-monitor/recent  — submitted instruments (EEH / drop-folder path)
 *  2. /v1/cts/outward/session/{id}/scan-log — Canon CSD edge agent events
 *     including DOUBLE_FEED_DETECTED (held at branch, never sent to central)
 *     and IMPRINTER_FAULT (submitted but needs manual re-stamp).
 *
 * Double-feed rows are visually prominent — red left stripe + tinted background
 * — so the teller can see immediately which cheques need to be re-fed.
 */
import { useState, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useTheme } from '../../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../../shared/context/BankContext'
import AppShell from '../../../../shared/layout/AppShell'

// ─── Mock SSE feed (simulates ChequeAck events arriving over time) ───────────

const MOCK_INSTRUMENTS = [
  { scan_id: 'SC-001247', micr_suffix: '4521', payee: 'Nandini Joshi',     amount_range: '₹[1L-5L]',  status: 'ACCEPTED',             lot_id: 'LOT-0007', ts: '10:43:51', micr_source: 'HARDWARE' },
  { scan_id: 'SC-001246', micr_suffix: '8873', payee: 'Mahesh Kumar',      amount_range: '₹[<1L]',    status: 'ACCEPTED',             lot_id: 'LOT-0007', ts: '10:43:49', micr_source: 'HARDWARE' },
  // Double-feed — NOT sent to central; teller must separate and re-feed
  { scan_id: 'SC-001246B',micr_suffix: '????', payee: '—',                 amount_range: '—',          status: 'DOUBLE_FEED_DETECTED', lot_id: '',         ts: '10:43:48', micr_source: 'UNKNOWN' },
  { scan_id: 'SC-001245', micr_suffix: '2211', payee: 'Rajesh Kulkarni',   amount_range: '₹[1L-5L]',  status: 'HELD',                 lot_id: '',         ts: '10:43:47', mismatch_id: 'MM-001', mismatch_fields: ['amount_figures'], micr_source: 'HARDWARE' },
  { scan_id: 'SC-001244', micr_suffix: '6699', payee: 'Anita Sharma',      amount_range: '₹[<1L]',    status: 'REJECTED',             lot_id: '',         ts: '10:43:44', reason: 'CTS_IMAGE_QUALITY', micr_source: 'OCR' },
  { scan_id: 'SC-001243', micr_suffix: '3312', payee: 'Sunil Enterprises', amount_range: '₹[5L-10L]', status: 'ACCEPTED',             lot_id: 'LOT-0007', ts: '10:43:42', micr_source: 'HARDWARE' },
  // Imprinter fault — cheque submitted but physical stamp failed; needs manual re-stamp at branch
  { scan_id: 'SC-001242', micr_suffix: '7741', payee: 'Kishore Mehta',     amount_range: '₹[1L-5L]',  status: 'IMPRINTER_FAULT',      lot_id: 'LOT-0007', ts: '10:43:40', micr_source: 'HARDWARE' },
  { scan_id: 'SC-001241', micr_suffix: '0023', payee: 'Priya Deshmukh',    amount_range: '₹[<1L]',    status: 'ACCEPTED',             lot_id: 'LOT-0007', ts: '10:43:38', micr_source: 'HARDWARE' },
  { scan_id: 'SC-001240', micr_suffix: '9988', payee: 'Vinod Apte',        amount_range: '₹[1L-5L]',  status: 'ACCEPTED',             lot_id: 'LOT-0006', ts: '10:43:35', micr_source: 'HARDWARE' },
]

// stripe: left-border class applied to <tr> for actionable statuses (double-feed, fault)
const STATUS_CFG = {
  ACCEPTED:             { label: 'Accepted',     bg: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30', stripe: null },
  REJECTED:             { label: 'Rejected',     bg: 'bg-red-500/15 text-red-400 border-red-500/30',            stripe: null },
  HELD:                 { label: 'On Hold',      bg: 'bg-amber-500/15 text-amber-400 border-amber-500/30',      stripe: null },
  DUPLICATE:            { label: 'Duplicate',    bg: 'bg-slate-500/15 text-slate-400 border-slate-500/30',      stripe: null },
  PENDING:              { label: 'Sending…',     bg: 'bg-blue-500/15 text-blue-400 border-blue-500/30',         stripe: null },
  // Double-feed: two cheques passed together; images unusable; NOT sent to central.
  // Teller must physically separate and re-feed each individually.
  DOUBLE_FEED_DETECTED: { label: 'Double Feed',  bg: 'bg-red-600/20 text-red-300 border-red-500/40',            stripe: 'border-l-4 border-l-red-500' },
  // Imprinter fault: cheque WAS submitted to central but physical stamp failed.
  // Teller must re-stamp manually before returning the cheque to the customer.
  IMPRINTER_FAULT:      { label: 'Stamp Fault',  bg: 'bg-amber-500/15 text-amber-400 border-amber-500/30',      stripe: 'border-l-4 border-l-amber-500' },
  UPLOAD_FAILED:        { label: 'Upload Failed', bg: 'bg-red-500/15 text-red-400 border-red-500/30',            stripe: 'border-l-4 border-l-red-400' },
}

function StatusPill({ status }) {
  const cfg = STATUS_CFG[status] || STATUS_CFG.PENDING
  return (
    <span className={`inline-flex items-center text-xs px-2 py-0.5 rounded border font-medium ${cfg.bg}`}>
      {cfg.label}
    </span>
  )
}

function MicrSourceBadge({ source }) {
  if (!source || source === 'UNKNOWN') return null
  return (
    <span className={`ml-1.5 inline-flex items-center text-[10px] px-1.5 py-0 rounded border font-medium ${
      source === 'HARDWARE'
        ? 'bg-sky-500/10 text-sky-400 border-sky-500/30'
        : 'bg-slate-500/10 text-slate-400 border-slate-500/30'
    }`}>
      {source === 'HARDWARE' ? 'HW' : 'OCR'}
    </span>
  )
}

function EventRow({ item, isDark }) {
  const isDoubleFeed    = item.status === 'DOUBLE_FEED_DETECTED'
  const isImprinterFault = item.status === 'IMPRINTER_FAULT'
  const cfg = STATUS_CFG[item.status] || STATUS_CFG.PENDING

  const th = {
    row:   isDark
      ? `border-white/4 hover:bg-white/2 ${isDoubleFeed ? 'bg-red-950/40' : ''} ${isImprinterFault ? 'bg-amber-950/20' : ''}`
      : `border-slate-100 hover:bg-slate-50 ${isDoubleFeed ? 'bg-red-50' : ''} ${isImprinterFault ? 'bg-amber-50' : ''}`,
    mono:  isDark ? 'text-slate-300 font-mono text-xs' : 'text-slate-600 font-mono text-xs',
    muted: isDark ? 'text-slate-400 text-xs' : 'text-slate-500 text-xs',
    faint: isDark ? 'text-slate-600 text-xs' : 'text-slate-400 text-xs',
  }

  return (
    <tr className={`border-b transition-colors ${th.row} ${cfg.stripe ?? ''}`}>
      <td className={`py-2 px-3 ${th.muted}`}>{item.ts}</td>
      <td className={`py-2 px-3 ${th.mono}`}>{item.scan_id}</td>
      <td className={`py-2 px-3 ${th.mono}`}>
        {isDoubleFeed ? <span className={th.faint}>—</span> : `****${item.micr_suffix}`}
        <MicrSourceBadge source={item.micr_source} />
      </td>
      <td className={`py-2 px-3 ${isDoubleFeed ? th.faint : th.muted}`}>
        {isDoubleFeed ? 'Not readable' : item.payee}
      </td>
      <td className={`py-2 px-3 ${isDoubleFeed ? th.faint : th.muted} tabular-nums`}>
        {isDoubleFeed ? '—' : item.amount_range}
      </td>
      <td className="py-2 px-3"><StatusPill status={item.status} /></td>
      <td className={`py-2 px-3 ${th.mono}`}>
        {isDoubleFeed ? <span className={th.faint}>—</span> : (item.lot_id || '—')}
      </td>
      <td className={`py-2 px-3 ${th.muted}`}>
        {isDoubleFeed && (
          <span className="text-red-400 text-xs font-medium">Separate &amp; re-feed individually</span>
        )}
        {isImprinterFault && (
          <span className="text-amber-400 text-xs font-medium">Manual re-stamp required</span>
        )}
        {item.mismatch_id && (
          <Link to="/branch/mismatch" className="text-amber-400 hover:underline text-xs">
            {item.mismatch_id}
          </Link>
        )}
        {item.reason && !isDoubleFeed && (
          <span className="text-red-400 text-xs">{item.reason}</span>
        )}
      </td>
    </tr>
  )
}

// ─── Component ────────────────────────────────────────────────────────────────

// Normalise an instrument event (scan-monitor path) to a display row.
function normalizeInstrument(e) {
  return {
    scan_id:         e.scan_id,
    micr_suffix:     e.micr_suffix ?? '????',
    micr_source:     e.micr_source ?? 'UNKNOWN',
    payee:           e.payee_display ?? '—',
    amount_range:    e.amount_range ?? '—',
    status:          e.outcome === 'ACCEPTED'      ? 'ACCEPTED'
                   : e.outcome === 'CTS_REJECTED'  ? 'REJECTED'
                   : e.outcome === 'MISMATCH_HELD' ? 'HELD'
                   : (e.outcome ?? 'PENDING'),
    lot_id:          e.lot_id ?? '',
    mismatch_id:     e.mismatch_id ?? null,
    mismatch_fields: e.mismatch_fields ?? null,
    reason:          e.reject_reason ?? null,
    ts:              e.scanned_at ? new Date(e.scanned_at).toLocaleTimeString('en-IN', { hour12: false }) : '',
    _sort_ts:        e.scanned_at ?? '',
  }
}

// Normalise a scan-event record (outward_scan_events path — double-feed, imprinter fault).
function normalizeScanEvent(e) {
  return {
    scan_id:      e.scan_id,
    micr_suffix:  e.micr_suffix ?? '????',
    micr_source:  e.micr_source ?? 'UNKNOWN',
    payee:        '—',
    amount_range: '—',
    status:       e.event_type === 'DOUBLE_FEED_DETECTED' ? 'DOUBLE_FEED_DETECTED'
                : e.event_type === 'IMPRINTER_FAULT'      ? 'IMPRINTER_FAULT'
                : 'UPLOAD_FAILED',
    lot_id:       '',
    mismatch_id:  null,
    reason:       null,
    ts:           e.created_at ? new Date(e.created_at).toLocaleTimeString('en-IN', { hour12: false }) : '',
    _sort_ts:     e.created_at ?? '',
  }
}

export default function BranchScanMonitor() {
  const { isDark } = useTheme()
  const { bankId, branchId, isDemo } = useBankContext()

  const [autoScroll, setAutoScroll] = useState(true)
  const tableRef = useRef(null)
  const prevCountRef = useRef(0)

  // Query 1 — submitted instruments (EEH / drop-folder path)
  const { data, isLoading, isError } = useQuery({
    queryKey: ['scan-monitor', bankId],
    queryFn: async () => {
      const res = await fetch(`/v1/cts/scan-monitor/recent?limit=50&bank_id=${bankId}`, { credentials: 'include' })
      if (!res.ok) throw new Error('Failed to load scan events')
      return res.json()
    },
    enabled: !isDemo,
    refetchInterval: isDemo ? false : 3_000,
    staleTime: 0,
    retry: false,
  })

  // Query 2 — double-feed and imprinter fault events from the Canon CSD edge agent path.
  // These are NOT in the scan-monitor (they were never submitted to central).
  const { data: scanEventsData } = useQuery({
    queryKey: ['scan-events', bankId, branchId],
    queryFn: async () => {
      const params = new URLSearchParams({ bank_id: bankId, limit: '50' })
      if (branchId) params.set('branch_id', branchId)
      const res = await fetch(`/v1/cts/outward/scan-events?${params}`, { credentials: 'include' })
      if (!res.ok) return { events: [] }
      return res.json()
    },
    enabled: !isDemo && !!branchId,
    refetchInterval: isDemo ? false : 3_000,
    staleTime: 0,
    retry: false,
  })

  const submittedRows   = (data?.events ?? []).map(normalizeInstrument)
  const scanEventRows   = (scanEventsData?.events ?? []).map(normalizeScanEvent)

  // Merge and sort newest-first. In demo mode show the static mock list.
  const instruments = isDemo
    ? MOCK_INSTRUMENTS
    : [...submittedRows, ...scanEventRows].sort((a, b) => b._sort_ts.localeCompare(a._sort_ts)).slice(0, 100)

  const sseStatus = isError ? 'ERROR' : isLoading ? 'CONNECTING' : 'LIVE'

  const rateCps = (() => {
    if (instruments.length < 2) return 0
    const first = new Date(rawEvents[rawEvents.length - 1]?.scanned_at)
    const last  = new Date(rawEvents[0]?.scanned_at)
    const secs  = (last - first) / 1000
    return secs > 0 ? (instruments.length / secs).toFixed(1) : 0
  })()

  // Auto-scroll to top (newest item) when new instruments arrive
  useEffect(() => {
    const count = instruments.length
    if (autoScroll && tableRef.current && count > prevCountRef.current) {
      tableRef.current.scrollTop = 0
    }
    prevCountRef.current = count
  }, [instruments.length, autoScroll])

  const th = {
    page:    isDark ? 'bg-navy-950'  : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'   : 'text-slate-900',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    th:      isDark ? 'text-slate-500 bg-navy-900/80 text-xs font-medium uppercase tracking-wider'
                    : 'text-slate-400 bg-slate-50 text-xs font-medium uppercase tracking-wider',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
  }

  const accepted     = instruments.filter(i => i.status === 'ACCEPTED').length
  const rejected     = instruments.filter(i => i.status === 'REJECTED').length
  const held         = instruments.filter(i => i.status === 'HELD').length
  const doubleFeed   = instruments.filter(i => i.status === 'DOUBLE_FEED_DETECTED').length
  const impFault     = instruments.filter(i => i.status === 'IMPRINTER_FAULT').length

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
              <span className={`w-1.5 h-1.5 rounded-full ${
                sseStatus === 'LIVE' ? 'bg-emerald-400 animate-pulse'
                : sseStatus === 'ERROR' ? 'bg-red-400'
                : 'bg-slate-500'
              }`} />
              {sseStatus}
            </span>
            <span className={th.muted}>{rateCps} c/s</span>
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

        {/* Double-feed alert — shown when the scanner has detected overlapping cheques.
            These were physically ejected by the scanner and NOT sent to central.
            Teller must separate them and feed each individually. */}
        {doubleFeed > 0 && (
          <div className={`flex items-start gap-3 px-6 py-3 border-b ${
            isDark ? 'bg-red-950/50 border-red-700/40 text-red-300' : 'bg-red-50 border-red-200 text-red-700'
          }`}>
            <svg className="w-4 h-4 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
            </svg>
            <div className="text-sm">
              <span className="font-semibold">
                {doubleFeed} cheque{doubleFeed > 1 ? 's' : ''} double-fed
              </span>
              {' '}— scanner ejected the overlapping documents. These have{' '}
              <span className="font-semibold">not</span> been sent to central processing.
              Separate and re-feed each cheque individually.
            </div>
          </div>
        )}

        {/* Imprinter fault notice — cheque WAS submitted but physical stamp failed */}
        {impFault > 0 && (
          <div className={`flex items-start gap-3 px-6 py-2 border-b ${
            isDark ? 'bg-amber-950/30 border-amber-700/30 text-amber-300' : 'bg-amber-50 border-amber-200 text-amber-700'
          }`}>
            <svg className="w-4 h-4 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 9v7.5" />
            </svg>
            <div className="text-sm">
              <span className="font-semibold">
                {impFault} cheque{impFault > 1 ? 's' : ''} not physically stamped
              </span>
              {' '}— submitted to central processing but endorsement print failed.
              Apply manual branch stamp before returning to customer.
            </div>
          </div>
        )}

        {/* Summary strip */}
        <div className={`flex items-center gap-6 px-6 py-2 border-b ${th.divider} text-xs`}>
          <span className={th.muted}>
            <span className={`font-medium ${isDark ? 'text-white' : 'text-slate-900'}`}>{instruments.length}</span> total
          </span>
          <span className="text-emerald-400 font-medium">{accepted} accepted</span>
          <span className={rejected > 0 ? 'text-red-400 font-medium' : th.muted}>
            {rejected} rejected
          </span>
          <span className={held > 0 ? 'text-amber-400 font-medium' : th.muted}>
            {held} held
          </span>
          {doubleFeed > 0 && (
            <span className="text-red-400 font-semibold flex items-center gap-1">
              <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
              </svg>
              {doubleFeed} double-feed — re-scan needed
            </span>
          )}
          {impFault > 0 && (
            <span className="text-amber-400 font-medium">{impFault} stamp fault</span>
          )}
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

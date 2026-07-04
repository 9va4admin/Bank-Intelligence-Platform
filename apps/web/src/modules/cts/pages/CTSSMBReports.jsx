/**
 * CTSSMBReports — reports for Sub-Member Bank users.
 *
 * Shows only the SMB's own clearing data:
 *   - Daily summary (vol/val, STP rate, return rate) — downloadable CSV
 *   - Return Reason File (RRF) — returned instruments with return reasons
 *   - Settlement statement — net position with sponsor bank
 *
 * smbOnly: SB users see their own aggregated reports elsewhere.
 */
import { useState, useMemo } from 'react'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'
import AppShell from '../../../shared/layout/AppShell'
import { useEffect } from 'react'

// ─── Mock data ────────────────────────────────────────────────────────────────

const MOCK_SESSIONS = [
  { session_id: 'SES-COSB-001', date: '2026-07-05', slot: '10:00–12:00', status: 'SETTLED',
    total: 143, stp_confirmed: 124, stp_returned: 11, manual_confirmed: 6, manual_returned: 2,
    value_L: 38.0, returned_value_L: 3.2, stp_rate: 86.7, return_rate: 9.1 },
  { session_id: 'SES-COSB-002', date: '2026-07-05', slot: '12:00–14:00', status: 'OPEN',
    total: 175, stp_confirmed: 149, stp_returned: 12, manual_confirmed: 8, manual_returned: 3,
    value_L: 46.5, returned_value_L: 4.1, stp_rate: 85.1, return_rate: 8.6 },
]

const MOCK_RRF = [
  { instrument_id: 'CHQ-SMB-001503', account_display: '****4412', amount_range: '₹[1L-5L]', return_reason: 'SIGNATURE_MISMATCH',      return_code: '20', filed_at: '13:10' },
  { instrument_id: 'CHQ-SMB-001641', account_display: '****7823', amount_range: '₹[1L-5L]', return_reason: 'STOP_PAYMENT_ACTIVE',       return_code: '02', filed_at: '13:35' },
  { instrument_id: 'CHQ-SMB-001720', account_display: '****3301', amount_range: '₹[<1L]',   return_reason: 'ACCOUNT_FROZEN',            return_code: '07', filed_at: '14:02' },
  { instrument_id: 'CHQ-SMB-001390', account_display: '****9988', amount_range: '₹[5L-10L]', return_reason: 'INSUFFICIENT_FUNDS',       return_code: '01', filed_at: '12:48' },
  { instrument_id: 'CHQ-SMB-001244', account_display: '****5567', amount_range: '₹[1L-5L]', return_reason: 'ALTERATION_DETECTED',       return_code: '30', filed_at: '11:55' },
  { instrument_id: 'CHQ-SMB-001180', account_display: '****1102', amount_range: '₹[<1L]',   return_reason: 'CTS_IMAGE_QUALITY_FAIL',    return_code: '34', filed_at: '11:22' },
  { instrument_id: 'CHQ-SMB-001030', account_display: '****7490', amount_range: '₹[1L-5L]', return_reason: 'PPS_AMOUNT_MISMATCH',       return_code: '22', filed_at: '10:58' },
]

const MOCK_SETTLEMENT = {
  date: '2026-07-05',
  sponsor_bank: 'Saraswat Co-operative Bank',
  sponsor_ifsc: 'SRCB0000001',
  inward_count: 318,
  inward_value_L: 84.5,
  return_count: 23,
  return_value_L: 7.3,
  net_receivable_L: 77.2,
  net_direction: 'RECEIVE',
  status: 'PENDING',    // PENDING | SETTLED
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function toCSV(rows, headers) {
  const escape = v => `"${String(v).replace(/"/g, '""')}"`
  const lines = [headers.join(','), ...rows.map(r => headers.map(h => escape(r[h] ?? '')).join(','))]
  return lines.join('\n')
}

function downloadCSV(csv, filename) {
  const blob = new Blob([csv], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  URL.revokeObjectURL(url)
}

// ─── Sub-components ───────────────────────────────────────────────────────────

const TABS = ['Daily Summary', 'Return Reason File', 'Settlement']

function SummaryTab({ sessions, bankId, isDark }) {
  const th = {
    header:  isDark ? 'text-slate-500 border-white/8'      : 'text-slate-400 border-slate-200',
    row:     isDark ? 'border-white/5 hover:bg-white/2'    : 'border-slate-100 hover:bg-slate-50',
    cell:    isDark ? 'text-slate-300'                      : 'text-slate-700',
    good:    isDark ? 'text-emerald-400'                    : 'text-emerald-600',
    warn:    isDark ? 'text-amber-400'                      : 'text-amber-600',
    pill: (s) => s === 'SETTLED'
      ? (isDark ? 'bg-emerald-900/40 text-emerald-300 border-emerald-700/40' : 'bg-emerald-50 text-emerald-700 border-emerald-200')
      : (isDark ? 'bg-sky-900/40 text-sky-300 border-sky-700/40' : 'bg-sky-50 text-sky-700 border-sky-200'),
  }

  const totals = useMemo(() => sessions.reduce((acc, s) => ({
    total:          acc.total + s.total,
    stp_confirmed:  acc.stp_confirmed + s.stp_confirmed,
    stp_returned:   acc.stp_returned + s.stp_returned,
    manual_confirmed: acc.manual_confirmed + s.manual_confirmed,
    manual_returned: acc.manual_returned + s.manual_returned,
    value_L:        acc.value_L + s.value_L,
    returned_value_L: acc.returned_value_L + s.returned_value_L,
  }), { total: 0, stp_confirmed: 0, stp_returned: 0, manual_confirmed: 0, manual_returned: 0, value_L: 0, returned_value_L: 0 }), [sessions])

  const handleDownload = () => {
    const rows = sessions.map(s => ({
      session_id: s.session_id,
      date: s.date,
      slot: s.slot,
      status: s.status,
      total: s.total,
      stp_confirmed: s.stp_confirmed,
      stp_returned: s.stp_returned,
      manual_confirmed: s.manual_confirmed,
      manual_returned: s.manual_returned,
      value_L: s.value_L,
      return_rate: s.return_rate,
    }))
    const csv = toCSV(rows, ['session_id', 'date', 'slot', 'status', 'total', 'stp_confirmed', 'stp_returned', 'manual_confirmed', 'manual_returned', 'value_L', 'return_rate'])
    downloadCSV(csv, `SMB-Daily-Summary-${bankId}-${new Date().toISOString().slice(0, 10)}.csv`)
  }

  return (
    <div>
      <div className="flex justify-end mb-3">
        <button
          onClick={handleDownload}
          className={`text-xs px-3 py-1.5 rounded-lg border font-medium transition-colors ${
            isDark ? 'border-white/15 text-slate-300 hover:bg-white/5' : 'border-slate-200 text-slate-600 hover:bg-slate-50'
          }`}
        >
          Download CSV
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className={`text-xs uppercase tracking-wide border-b ${th.header}`}>
              <th className="text-left py-2 pr-3 font-medium">Session</th>
              <th className="text-left py-2 pr-3 font-medium">Slot</th>
              <th className="text-left py-2 pr-3 font-medium">Status</th>
              <th className="text-right py-2 pr-3 font-medium">Total</th>
              <th className="text-right py-2 pr-3 font-medium">STP ✓</th>
              <th className="text-right py-2 pr-3 font-medium">Returns</th>
              <th className="text-right py-2 pr-3 font-medium">Value (₹L)</th>
              <th className="text-right py-2 font-medium">Return %</th>
            </tr>
          </thead>
          <tbody>
            {sessions.map(s => (
              <tr key={s.session_id} className={`border-b ${th.row}`}>
                <td className={`py-2.5 pr-3 font-mono text-xs ${th.cell}`}>{s.session_id}</td>
                <td className={`py-2.5 pr-3 ${th.cell}`}>{s.slot}</td>
                <td className="py-2.5 pr-3">
                  <span className={`text-xs px-2 py-0.5 rounded border font-medium ${th.pill(s.status)}`}>{s.status}</span>
                </td>
                <td className={`py-2.5 pr-3 text-right tabular-nums ${th.cell}`}>{s.total}</td>
                <td className={`py-2.5 pr-3 text-right tabular-nums ${th.good}`}>{s.stp_confirmed}</td>
                <td className={`py-2.5 pr-3 text-right tabular-nums ${isDark ? 'text-red-400' : 'text-red-600'}`}>
                  {s.stp_returned + s.manual_returned}
                </td>
                <td className={`py-2.5 pr-3 text-right tabular-nums ${th.cell}`}>{s.value_L.toFixed(2)}</td>
                <td className={`py-2.5 text-right tabular-nums ${s.return_rate > 10 ? th.warn : th.good}`}>
                  {s.return_rate.toFixed(1)}%
                </td>
              </tr>
            ))}
            {/* Totals row */}
            <tr className={`border-t-2 ${isDark ? 'border-white/20' : 'border-slate-300'}`}>
              <td colSpan={3} className={`py-2.5 pr-3 text-xs font-semibold uppercase ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>Day Total</td>
              <td className={`py-2.5 pr-3 text-right tabular-nums font-semibold ${th.cell}`}>{totals.total}</td>
              <td className={`py-2.5 pr-3 text-right tabular-nums font-semibold ${th.good}`}>{totals.stp_confirmed}</td>
              <td className={`py-2.5 pr-3 text-right tabular-nums font-semibold ${isDark ? 'text-red-400' : 'text-red-600'}`}>
                {totals.stp_returned + totals.manual_returned}
              </td>
              <td className={`py-2.5 pr-3 text-right tabular-nums font-semibold ${th.cell}`}>{totals.value_L.toFixed(2)}</td>
              <td className="py-2.5" />
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  )
}

const REASON_LABEL = {
  SIGNATURE_MISMATCH:    'Signature mismatch',
  STOP_PAYMENT_ACTIVE:   'Stop payment active',
  ACCOUNT_FROZEN:        'Account frozen',
  INSUFFICIENT_FUNDS:    'Insufficient funds',
  ALTERATION_DETECTED:   'Alteration detected',
  CTS_IMAGE_QUALITY_FAIL:'CTS image quality fail',
  PPS_AMOUNT_MISMATCH:   'PPS amount mismatch',
}

function RRFTab({ items, bankId, isDark }) {
  const th = {
    header:  isDark ? 'text-slate-500 border-white/8'      : 'text-slate-400 border-slate-200',
    row:     isDark ? 'border-white/5 hover:bg-white/2'    : 'border-slate-100 hover:bg-slate-50',
    cell:    isDark ? 'text-slate-300'                      : 'text-slate-700',
    code:    isDark ? 'text-slate-400'                      : 'text-slate-500',
  }

  const handleDownload = () => {
    const rows = items.map(i => ({
      instrument_id: i.instrument_id,
      account_display: i.account_display,
      amount_range: i.amount_range,
      return_code: i.return_code,
      return_reason: i.return_reason,
      filed_at: i.filed_at,
    }))
    const csv = toCSV(rows, ['instrument_id', 'account_display', 'amount_range', 'return_code', 'return_reason', 'filed_at'])
    downloadCSV(csv, `SMB-RRF-${bankId}-${new Date().toISOString().slice(0, 10)}.csv`)
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <p className={`text-xs ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>
          {items.length} returned instruments · today
        </p>
        <button
          onClick={handleDownload}
          className={`text-xs px-3 py-1.5 rounded-lg border font-medium transition-colors ${
            isDark ? 'border-white/15 text-slate-300 hover:bg-white/5' : 'border-slate-200 text-slate-600 hover:bg-slate-50'
          }`}
        >
          Download RRF CSV
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className={`text-xs uppercase tracking-wide border-b ${th.header}`}>
              <th className="text-left py-2 pr-3 font-medium">Instrument</th>
              <th className="text-left py-2 pr-3 font-medium">Account</th>
              <th className="text-left py-2 pr-3 font-medium">Amount</th>
              <th className="text-left py-2 pr-3 font-medium">Code</th>
              <th className="text-left py-2 pr-3 font-medium">Reason</th>
              <th className="text-left py-2 font-medium">Filed</th>
            </tr>
          </thead>
          <tbody>
            {items.map(r => (
              <tr key={r.instrument_id} className={`border-b ${th.row}`}>
                <td className={`py-2.5 pr-3 font-mono text-xs ${th.cell}`}>{r.instrument_id}</td>
                <td className={`py-2.5 pr-3 font-mono ${th.code}`}>{r.account_display}</td>
                <td className={`py-2.5 pr-3 tabular-nums ${th.cell}`}>{r.amount_range}</td>
                <td className={`py-2.5 pr-3 tabular-nums font-semibold ${th.code}`}>{r.return_code}</td>
                <td className={`py-2.5 pr-3 ${th.cell}`}>{REASON_LABEL[r.return_reason] || r.return_reason.replace(/_/g, ' ')}</td>
                <td className={`py-2.5 tabular-nums ${th.code}`}>{r.filed_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function SettlementTab({ data, bankName, bankId, isDark }) {
  const th = {
    card:    isDark ? 'bg-white/4 border-white/10'   : 'bg-slate-50 border-slate-200',
    label:   isDark ? 'text-slate-400'               : 'text-slate-500',
    value:   isDark ? 'text-white'                   : 'text-slate-900',
    muted:   isDark ? 'text-slate-500'               : 'text-slate-400',
    divider: isDark ? 'border-white/8'               : 'border-slate-200',
  }

  const handleDownload = () => {
    const lines = [
      `ASTRA Settlement Statement`,
      `Bank: ${bankName} (${bankId})`,
      `Date: ${data.date}`,
      `Sponsor Bank: ${data.sponsor_bank} (${data.sponsor_ifsc})`,
      ``,
      `Inward instruments: ${data.inward_count}`,
      `Inward value: ₹${data.inward_value_L}L`,
      `Returns: ${data.return_count}`,
      `Return value: ₹${data.return_value_L}L`,
      `Net position: ₹${data.net_receivable_L}L ${data.net_direction}`,
      `Status: ${data.status}`,
    ]
    downloadCSV(lines.join('\n'), `SMB-Settlement-${bankId}-${data.date}.txt`)
  }

  return (
    <div className="max-w-lg mx-auto space-y-4">
      <div className={`rounded-xl border p-5 ${th.card}`}>
        <div className="flex items-start justify-between mb-4">
          <div>
            <div className={`text-xs uppercase tracking-wide font-semibold ${th.label}`}>Settlement Statement</div>
            <div className={`text-sm font-semibold mt-0.5 ${th.value}`}>{data.date}</div>
          </div>
          <span className={`text-xs px-2.5 py-1 rounded-full border font-medium ${
            data.status === 'SETTLED'
              ? (isDark ? 'bg-emerald-900/40 text-emerald-300 border-emerald-700/40' : 'bg-emerald-50 text-emerald-700 border-emerald-200')
              : (isDark ? 'bg-amber-900/40 text-amber-300 border-amber-700/40' : 'bg-amber-50 text-amber-700 border-amber-200')
          }`}>{data.status}</span>
        </div>

        <div className={`text-xs ${th.label} mb-1`}>Sponsor Bank</div>
        <div className={`text-sm font-medium mb-4 ${th.value}`}>{data.sponsor_bank}</div>

        <div className={`border-t ${th.divider} pt-4 grid grid-cols-2 gap-4`}>
          <div>
            <div className={`text-xs ${th.label}`}>Inward instruments</div>
            <div className={`text-2xl font-bold tabular-nums ${th.value}`}>{data.inward_count}</div>
            <div className={`text-xs ${th.muted}`}>₹{data.inward_value_L}L total value</div>
          </div>
          <div>
            <div className={`text-xs ${th.label}`}>Returns</div>
            <div className={`text-2xl font-bold tabular-nums ${isDark ? 'text-red-400' : 'text-red-600'}`}>{data.return_count}</div>
            <div className={`text-xs ${th.muted}`}>₹{data.return_value_L}L returned value</div>
          </div>
        </div>

        <div className={`border-t ${th.divider} mt-4 pt-4 flex items-center justify-between`}>
          <div>
            <div className={`text-xs ${th.label}`}>Net position</div>
            <div className={`text-3xl font-bold tabular-nums ${isDark ? 'text-emerald-400' : 'text-emerald-600'}`}>
              ₹{data.net_receivable_L}L
            </div>
            <div className={`text-xs ${isDark ? 'text-emerald-500' : 'text-emerald-600'}`}>{data.net_direction} from sponsor</div>
          </div>
        </div>
      </div>

      <button
        onClick={handleDownload}
        className={`w-full text-sm px-4 py-2.5 rounded-lg border font-medium transition-colors ${
          isDark ? 'border-white/15 text-slate-300 hover:bg-white/5' : 'border-slate-200 text-slate-600 hover:bg-slate-50'
        }`}
      >
        Download Settlement Statement
      </button>
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function CTSSMBReports() {
  const { bankName, bankId } = useBankContext()
  const { isDark } = useTheme()
  const { setHeader } = usePageHeader()
  const [activeTab, setActiveTab] = useState(0)

  useEffect(() => {
    setHeader({ title: 'SMB Reports', subtitle: bankName })
  }, [setHeader, bankName])

  const th = {
    page:    isDark ? 'bg-navy-950'             : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'              : 'text-slate-900',
    muted:   isDark ? 'text-slate-400'          : 'text-slate-500',
    divider: isDark ? 'border-white/8'          : 'border-slate-200',
    tab: (a) => a
      ? (isDark ? 'bg-white/10 text-white border-white/20' : 'bg-slate-900 text-white border-slate-800')
      : (isDark ? 'text-slate-400 border-white/8 hover:text-slate-200' : 'text-slate-500 border-slate-200 hover:text-slate-700'),
  }

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        <div className={`rounded-xl border ${th.card} overflow-hidden`}>
          {/* Tab bar */}
          <div className={`flex border-b ${th.divider}`}>
            {TABS.map((tab, i) => (
              <button
                key={tab}
                onClick={() => setActiveTab(i)}
                className={`px-5 py-3 text-sm font-medium border-b-2 -mb-px transition-colors ${th.tab(i === activeTab)}`}
              >
                {tab}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div className="p-5">
            {activeTab === 0 && <SummaryTab sessions={MOCK_SESSIONS} bankId={bankId} isDark={isDark} />}
            {activeTab === 1 && <RRFTab items={MOCK_RRF} bankId={bankId} isDark={isDark} />}
            {activeTab === 2 && <SettlementTab data={MOCK_SETTLEMENT} bankName={bankName} bankId={bankId} isDark={isDark} />}
          </div>
        </div>
      </div>
    </AppShell>
  )
}

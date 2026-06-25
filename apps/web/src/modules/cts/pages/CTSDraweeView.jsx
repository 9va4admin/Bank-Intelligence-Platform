/**
 * CTS Drawee Bank View — outward cheques we presented to other banks.
 *
 * "Drawee bank" perspective: cheques drawn on our customers by other banks.
 * - How many cheques came in (for us to pay)  ← presenting bank view (already in CTSOpsDashboard)
 * "Presenting bank" perspective: cheques we collected from our customers and sent to NGCH.
 * - How many of our customers' cheques did we present, how many got returned?  ← THIS PAGE
 *
 * This page shows the OUTWARD side:
 *   - Branch-wise outward cheque submission counts
 *   - Returns received from NGCH per return reason
 *   - Which branches have high return rates (branch health)
 *   - Combined net position with inward for the day
 */
import { useState } from 'react'
import { useTheme } from '../../../shared/theme/ThemeContext'
import AppShell from '../../../shared/layout/AppShell'

// ─── Mock data ────────────────────────────────────────────────────────────────

const SESSIONS = ['SES-20260625-001', 'SES-20260625-002', 'SES-20260625-003']

const BRANCHES = [
  { code: 'BOM001', name: 'Andheri (W)',  outward: 312, value_cr: 8.4,  returned: 28, reasons: { FUNDS_INSUFFICIENT: 13, SIGNATURE_MISMATCH: 8, ACCOUNT_CLOSED: 4, OTHER: 3 } },
  { code: 'BOM002', name: 'Bandra (E)',   outward: 289, value_cr: 7.1,  returned: 24, reasons: { FUNDS_INSUFFICIENT: 10, SIGNATURE_MISMATCH: 7, ALTERATION: 4, OTHER: 3 } },
  { code: 'BOM003', name: 'Churchgate',   outward: 445, value_cr: 18.3, returned: 31, reasons: { FUNDS_INSUFFICIENT: 18, SIGNATURE_MISMATCH: 6, ACCOUNT_CLOSED: 5, OTHER: 2 } },
  { code: 'BOM004', name: 'Dadar',        outward: 198, value_cr: 5.2,  returned: 22, reasons: { FUNDS_INSUFFICIENT: 9,  SIGNATURE_MISMATCH: 7, ALTERATION: 3, OTHER: 3 } },
  { code: 'BOM005', name: 'Goregaon',     outward: 167, value_cr: 4.3,  returned: 12, reasons: { FUNDS_INSUFFICIENT: 7,  SIGNATURE_MISMATCH: 3, OTHER: 2 } },
  { code: 'BOM006', name: 'Kurla',        outward: 234, value_cr: 6.1,  returned: 29, reasons: { FUNDS_INSUFFICIENT: 14, SIGNATURE_MISMATCH: 9, ACCOUNT_CLOSED: 4, OTHER: 2 } },
  { code: 'BOM007', name: 'Malad',        outward: 143, value_cr: 3.8,  returned: 10, reasons: { FUNDS_INSUFFICIENT: 5,  SIGNATURE_MISMATCH: 3, OTHER: 2 } },
  { code: 'BOM008', name: 'Vashi',        outward: 267, value_cr: 9.2,  returned: 33, reasons: { FUNDS_INSUFFICIENT: 15, SIGNATURE_MISMATCH: 10, ALTERATION: 5, OTHER: 3 } },
  { code: 'BOM009', name: 'Borivali',     outward: 189, value_cr: 5.6,  returned: 16, reasons: { FUNDS_INSUFFICIENT: 8,  SIGNATURE_MISMATCH: 5, OTHER: 3 } },
  { code: 'BOM010', name: 'Thane',        outward: 236, value_cr: 7.3,  returned: 20, reasons: { FUNDS_INSUFFICIENT: 9,  SIGNATURE_MISMATCH: 6, ACCOUNT_CLOSED: 3, OTHER: 2 } },
]

const RETURN_REASONS_TOTAL = {
  FUNDS_INSUFFICIENT: 108,
  SIGNATURE_MISMATCH:  64,
  ACCOUNT_CLOSED:      22,
  ALTERATION:          15,
  OTHER:               16,
}

const PRESENTING_BANKS = [
  { ifsc: 'HDFC0000001', name: 'HDFC Bank (us)',  outward: 2480, value_cr: 66.3, returned: 199, accepted: 2281 },
  { ifsc: 'ICIC0000001', name: 'ICICI (drawee)',  outward: 312,  value_cr: 8.4,  returned: 24,  accepted: 288 },
  { ifsc: 'SBIN0000001', name: 'SBI (drawee)',    outward: 445,  value_cr: 14.2, returned: 38,  accepted: 407 },
  { ifsc: 'UTIB0000001', name: 'Axis (drawee)',   outward: 198,  value_cr: 5.2,  returned: 17,  accepted: 181 },
  { ifsc: 'KKBK0000001', name: 'Kotak (drawee)',  outward: 267,  value_cr: 9.8,  returned: 21,  accepted: 246 },
]

// ─── Sub-components ───────────────────────────────────────────────────────────

function ReturnReasonBar({ reasons, total, isDark }) {
  const COLORS = {
    FUNDS_INSUFFICIENT: 'bg-red-500',
    SIGNATURE_MISMATCH: 'bg-orange-400',
    ACCOUNT_CLOSED:     'bg-amber-400',
    ALTERATION:         'bg-purple-400',
    OTHER:              'bg-slate-400',
  }
  const LABELS = {
    FUNDS_INSUFFICIENT: 'Funds Insufficient',
    SIGNATURE_MISMATCH: 'Signature Mismatch',
    ACCOUNT_CLOSED:     'Account Closed',
    ALTERATION:         'Alteration',
    OTHER:              'Other',
  }
  const muted = isDark ? 'text-slate-400' : 'text-slate-500'
  const body  = isDark ? 'text-slate-300' : 'text-slate-700'
  return (
    <div className="space-y-2">
      {Object.entries(reasons).map(([k, v]) => (
        <div key={k}>
          <div className="flex justify-between mb-0.5">
            <span className={`text-[11px] ${muted}`}>{LABELS[k] || k}</span>
            <span className={`text-[11px] font-mono ${body}`}>{v} ({((v / total) * 100).toFixed(1)}%)</span>
          </div>
          <div className={`h-1.5 rounded-full ${isDark ? 'bg-white/5' : 'bg-slate-100'}`}>
            <div className={`h-full rounded-full ${COLORS[k] || 'bg-slate-400'}`} style={{ width: `${(v / total) * 100}%` }} />
          </div>
        </div>
      ))}
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function CTSDraweeView() {
  const { isDark } = useTheme()
  const [selectedSession, setSelectedSession] = useState(SESSIONS[1])
  const [sortBy, setSortBy] = useState('returned_desc')

  const th = {
    page:    isDark ? 'bg-navy-950' : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    row:     isDark ? 'border-white/4 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
    tab:     (active) => active
      ? (isDark ? 'bg-white/10 text-white border-white/20' : 'bg-slate-900 text-white border-slate-900')
      : (isDark ? 'text-slate-400 border-white/8 hover:text-white' : 'text-slate-500 border-slate-200 hover:text-slate-800'),
  }

  const totalOutward = BRANCHES.reduce((s, b) => s + b.outward, 0)
  const totalReturned = BRANCHES.reduce((s, b) => s + b.returned, 0)
  const totalValueCr  = BRANCHES.reduce((s, b) => s + b.value_cr, 0)

  const sorted = [...BRANCHES].sort((a, b) => {
    if (sortBy === 'returned_desc') return b.returned - a.returned
    if (sortBy === 'rate_desc')     return (b.returned / b.outward) - (a.returned / a.outward)
    if (sortBy === 'volume_desc')   return b.outward - a.outward
    return 0
  })

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page}`}>
        {/* Header */}
        <div className={`sticky top-0 z-10 ${isDark ? 'bg-navy-950/95' : 'bg-slate-50/95'} backdrop-blur border-b ${th.divider} px-6 py-3`}>
          <div className="flex items-center justify-between">
            <div>
              <h1 className={`text-base font-semibold ${th.heading}`}>Outward & Combined Position</h1>
              <p className={`text-[11px] ${th.muted}`}>Presenting + Drawee · {selectedSession}</p>
            </div>
            <div className="flex gap-2">
              {SESSIONS.map(s => (
                <button key={s} onClick={() => setSelectedSession(s)}
                  className={`text-[10px] px-2.5 py-1 rounded-lg border transition-colors ${th.tab(selectedSession === s)}`}>
                  {s.split('-')[3] + ':00'}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="px-6 py-5 max-w-7xl space-y-5">

          {/* Summary row */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { label: 'Total Outward',   value: totalOutward.toLocaleString(),           color: th.heading, sub: `₹${totalValueCr.toFixed(1)}Cr` },
              { label: 'NGCH Returned',   value: totalReturned.toLocaleString(),           color: 'text-red-400',     sub: `${((totalReturned / totalOutward) * 100).toFixed(1)}% rate` },
              { label: 'NGCH Accepted',   value: (totalOutward - totalReturned).toLocaleString(), color: 'text-emerald-400', sub: 'cleared' },
              { label: 'Net Position',    value: '₹43.2Cr',                               color: 'text-emerald-400', sub: 'RECEIVE today' },
            ].map(k => (
              <div key={k.label} className={`border rounded-xl p-4 ${th.card}`}>
                <div className={`text-[10px] uppercase tracking-wide ${th.muted} mb-1`}>{k.label}</div>
                <div className={`text-xl font-bold font-mono ${k.color}`}>{k.value}</div>
                <div className={`text-[10px] mt-0.5 ${th.muted}`}>{k.sub}</div>
              </div>
            ))}
          </div>

          {/* Two column: branch table + return reasons */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

            {/* Branch table */}
            <div className={`lg:col-span-2 border rounded-xl ${th.card}`}>
              <div className={`px-4 py-3 border-b ${th.divider} flex items-center justify-between`}>
                <span className={`text-[11px] font-semibold uppercase tracking-wide ${th.muted}`}>Branch-wise Outward</span>
                <select
                  value={sortBy}
                  onChange={e => setSortBy(e.target.value)}
                  className={`text-[10px] border rounded px-2 py-1 ${isDark ? 'bg-navy-900 border-white/10 text-slate-300' : 'bg-white border-slate-200 text-slate-600'}`}
                >
                  <option value="returned_desc">Sort: Most Returns</option>
                  <option value="rate_desc">Sort: Highest Return Rate</option>
                  <option value="volume_desc">Sort: Highest Volume</option>
                </select>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-[12px]">
                  <thead>
                    <tr className={`border-b ${th.divider}`}>
                      {['Branch', 'Outward', 'Value', 'Returned', 'Return Rate'].map(h => (
                        <th key={h} className={`px-4 py-2 text-left text-[10px] uppercase tracking-wide ${th.muted}`}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {sorted.map(b => {
                      const rate = (b.returned / b.outward) * 100
                      return (
                        <tr key={b.code} className={`border-b ${th.row} transition-colors`}>
                          <td className={`px-4 py-2.5 font-medium ${th.body}`}>{b.name}</td>
                          <td className={`px-4 py-2.5 font-mono ${th.body}`}>{b.outward}</td>
                          <td className={`px-4 py-2.5 font-mono text-gold-400`}>₹{b.value_cr}Cr</td>
                          <td className={`px-4 py-2.5 font-mono ${b.returned > 25 ? 'text-red-400' : th.body}`}>{b.returned}</td>
                          <td className="px-4 py-2.5">
                            <span className={`text-[11px] font-mono px-1.5 py-0.5 rounded ${
                              rate > 12 ? 'bg-red-900/40 text-red-300' :
                              rate > 8  ? 'bg-amber-900/40 text-amber-300' :
                              isDark    ? 'bg-emerald-900/40 text-emerald-300' : 'bg-emerald-100 text-emerald-700'
                            }`}>{rate.toFixed(1)}%</span>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                  <tfoot>
                    <tr className={`border-t ${th.divider} font-semibold`}>
                      <td className={`px-4 py-2.5 ${th.heading}`}>Total</td>
                      <td className={`px-4 py-2.5 font-mono ${th.heading}`}>{totalOutward}</td>
                      <td className={`px-4 py-2.5 font-mono text-gold-400`}>₹{totalValueCr.toFixed(1)}Cr</td>
                      <td className={`px-4 py-2.5 font-mono text-red-400`}>{totalReturned}</td>
                      <td className={`px-4 py-2.5 font-mono ${th.heading}`}>{((totalReturned / totalOutward) * 100).toFixed(1)}%</td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            </div>

            {/* Return reasons */}
            <div className={`border rounded-xl p-4 ${th.card}`}>
              <div className={`text-[11px] font-semibold uppercase tracking-wide ${th.muted} mb-4`}>Return Reasons</div>
              <ReturnReasonBar reasons={RETURN_REASONS_TOTAL} total={totalReturned} isDark={isDark} />
              <div className={`mt-4 pt-4 border-t ${th.divider}`}>
                <div className={`text-[11px] font-semibold uppercase tracking-wide ${th.muted} mb-3`}>By Presenting Bank</div>
                {PRESENTING_BANKS.map(b => (
                  <div key={b.ifsc} className={`flex items-center justify-between py-1.5 border-b ${th.divider}`}>
                    <span className={`text-[11px] ${th.body}`}>{b.name}</span>
                    <div className="flex items-center gap-2">
                      <span className={`text-[11px] font-mono ${th.muted}`}>{b.outward}</span>
                      <span className={`text-[11px] font-mono ${b.returned > 30 ? 'text-red-400' : 'text-emerald-400'}`}>
                        {((b.returned / b.outward) * 100).toFixed(1)}%
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

        </div>
      </div>
    </AppShell>
  )
}

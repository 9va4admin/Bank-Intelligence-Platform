/**
 * Branch Portal — Session History (/branch/history)
 *
 * Lists past clearing sessions for this branch. Shows lot count, instrument
 * totals, and provides download links for session CXF and lot summaries.
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useTheme } from '../../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../../shared/context/BankContext'
import AppShell from '../../../../shared/layout/AppShell'

// ─── Mock history ─────────────────────────────────────────────────────────────

const MOCK_SESSIONS = [
  {
    session_id: 'sess-branch-01-2026-07-04',
    clearing_date: '2026-07-04',
    session_type: 'MORNING',
    status: 'OPEN',
    lots: 7,
    total_uploaded: 247,
    total_accepted: 241,
    total_rejected: 4,
    total_held: 2,
    opened_at: '09:30:00',
    closed_at: null,
    operator: 'op-mahesh',
  },
  {
    session_id: 'sess-branch-01-2026-07-03',
    clearing_date: '2026-07-03',
    session_type: 'MORNING',
    status: 'SUBMITTED',
    lots: 12,
    total_uploaded: 412,
    total_accepted: 408,
    total_rejected: 3,
    total_held: 1,
    opened_at: '09:31:12',
    closed_at: '15:44:22',
    operator: 'op-mahesh',
  },
  {
    session_id: 'sess-branch-01-2026-07-02',
    clearing_date: '2026-07-02',
    session_type: 'MORNING',
    status: 'RECONCILED',
    lots: 9,
    total_uploaded: 318,
    total_accepted: 316,
    total_rejected: 2,
    total_held: 0,
    opened_at: '09:29:44',
    closed_at: '15:38:11',
    operator: 'op-priya',
  },
]

const STATUS_COLORS = {
  OPEN:        'bg-blue-500/15 text-blue-400 border-blue-500/30',
  SEALED:      'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
  SUBMITTED:   'bg-purple-500/15 text-purple-400 border-purple-500/30',
  RECONCILED:  'bg-slate-500/15 text-slate-400 border-slate-500/30',
}

function SessionRow({ sess, isDark, onDownload }) {
  const th = {
    row:   isDark ? 'border-white/4 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
    mono:  isDark ? 'text-xs font-mono text-slate-300' : 'text-xs font-mono text-slate-600',
    muted: isDark ? 'text-xs text-slate-400' : 'text-xs text-slate-500',
  }
  const color = STATUS_COLORS[sess.status] || STATUS_COLORS.RECONCILED
  return (
    <tr className={`border-b transition-colors ${th.row}`}>
      <td className={`py-2.5 px-3 ${th.muted}`}>{sess.clearing_date}</td>
      <td className={`py-2.5 px-3 ${th.muted}`}>{sess.session_type}</td>
      <td className="py-2.5 px-3">
        <span className={`inline-flex items-center text-xs px-2 py-0.5 rounded border ${color}`}>
          {sess.status}
        </span>
      </td>
      <td className={`py-2.5 px-3 ${th.muted} tabular-nums`}>{sess.lots}</td>
      <td className={`py-2.5 px-3 ${th.muted} tabular-nums`}>{sess.total_uploaded}</td>
      <td className={`py-2.5 px-3 tabular-nums`}>
        <span className="text-emerald-400 text-xs">{sess.total_accepted}</span>
        {' / '}
        <span className={sess.total_rejected > 0 ? 'text-red-400 text-xs' : `${th.muted}`}>
          {sess.total_rejected}
        </span>
      </td>
      <td className={`py-2.5 px-3 ${th.muted}`}>
        {sess.opened_at}
        {sess.closed_at && <> → {sess.closed_at}</>}
      </td>
      <td className={`py-2.5 px-3 ${th.muted}`}>{sess.operator}</td>
      <td className="py-2.5 px-3">
        <div className="flex gap-1.5">
          {sess.status !== 'OPEN' && (
            <>
              <button
                onClick={() => onDownload(sess.session_id, 'cxf')}
                className="text-xs px-2 py-0.5 border rounded text-blue-400 border-blue-400/30 hover:bg-blue-400/10 transition-colors"
              >
                CXF
              </button>
              <button
                onClick={() => onDownload(sess.session_id, 'summary')}
                className={`text-xs px-2 py-0.5 border rounded transition-colors ${
                  isDark ? 'border-white/10 text-slate-400 hover:text-white' : 'border-slate-200 text-slate-400 hover:text-slate-700'
                }`}
              >
                Summary
              </button>
            </>
          )}
        </div>
      </td>
    </tr>
  )
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function BranchSessionHistory() {
  const { isDark } = useTheme()
  const { bankId } = useBankContext()
  const [sessions] = useState(MOCK_SESSIONS)

  const th = {
    page:    isDark ? 'bg-navy-950' : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'  : 'text-slate-900',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    thCell:  isDark ? 'text-slate-500 bg-navy-900/80 text-xs font-medium uppercase tracking-wider'
                    : 'text-slate-400 bg-slate-50 text-xs font-medium uppercase tracking-wider',
  }

  function handleDownload(session_id, type) {
    // In production: GET /v1/branch/sessions/{session_id}/download?type={cxf|summary}
    alert(`Download ${type.toUpperCase()} for session ${session_id.slice(-8)} (Phase 3)`)
  }

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        <div className="flex items-center gap-4 mb-5">
          <Link to="/branch" className={`text-sm ${th.muted} hover:text-blue-400 transition-colors`}>
            ← Dashboard
          </Link>
          <h1 className={`text-lg font-semibold ${th.heading}`}>Session History</h1>
        </div>

        <div className={`rounded-lg border overflow-hidden ${th.card}`}>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse">
              <thead>
                <tr>
                  {['Date', 'Session', 'Status', 'Lots', 'Uploaded', 'Accepted / Rejected', 'Time', 'Operator', 'Downloads'].map(h => (
                    <th key={h} className={`px-3 py-2 text-left border-b ${th.divider} ${th.thCell}`}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sessions.map(sess => (
                  <SessionRow key={sess.session_id} sess={sess} isDark={isDark} onDownload={handleDownload} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </AppShell>
  )
}

import { useState } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'

// ── Mock data ────────────────────────────────────────────────────────────────

const MOCK_LEDGER = [
  {
    sub_member_id: 'smb-mh-vasavi',
    bank_name: 'Vasavi Co-operative Bank',
    session_date: '2026-06-26',
    clearing_session: 'SESSION_1',
    total: 312,
    stp_confirm: 265,
    stp_return: 34,
    human_review: 11,
    iet_emergency: 0,
    in_flight: 2,
    return_rate: 0.109,
    shield_status: 'CLEAR',
    avg_fraud_score: 0.08,
    ngch_filed: 310,
    audit_written: 312,
    ledger_updated_at: '2026-06-26T09:43:01Z',
  },
  {
    sub_member_id: 'smb-mh-kjsb',
    bank_name: 'Kalyan Janata Sahakari Bank',
    session_date: '2026-06-26',
    clearing_session: 'SESSION_1',
    total: 87,
    stp_confirm: 58,
    stp_return: 18,
    human_review: 10,
    iet_emergency: 0,
    in_flight: 1,
    return_rate: 0.207,
    shield_status: 'SOFT_HOLD',
    avg_fraud_score: 0.19,
    ngch_filed: 86,
    audit_written: 87,
    ledger_updated_at: '2026-06-26T09:43:02Z',
  },
  {
    sub_member_id: 'smb-gj-mucb',
    bank_name: 'Mehsana Urban Co-op Bank',
    session_date: '2026-06-26',
    clearing_session: 'SESSION_1',
    total: 211,
    stp_confirm: 198,
    stp_return: 9,
    human_review: 3,
    iet_emergency: 0,
    in_flight: 1,
    return_rate: 0.043,
    shield_status: 'CLEAR',
    avg_fraud_score: 0.04,
    ngch_filed: 210,
    audit_written: 211,
    ledger_updated_at: '2026-06-26T09:42:58Z',
  },
]

const SHIELD_D = {
  CLEAR:     'bg-emerald-900/40 text-emerald-300 border-emerald-700/50',
  SOFT_HOLD: 'bg-amber-900/40 text-amber-300 border-amber-700/50',
  HARD_STOP: 'bg-red-900/40 text-red-300 border-red-700/50',
}
const SHIELD_L = {
  CLEAR:     'bg-emerald-100 text-emerald-700 border-emerald-300',
  SOFT_HOLD: 'bg-amber-100 text-amber-700 border-amber-300',
  HARD_STOP: 'bg-red-100 text-red-700 border-red-300',
}

// ── Donut-style bar ───────────────────────────────────────────────────────────

function DecisionBar({ row, isDark }) {
  const total = row.total || 1
  const segments = [
    { pct: row.stp_confirm / total, color: isDark ? 'bg-emerald-600' : 'bg-emerald-500', label: 'Confirm' },
    { pct: row.stp_return  / total, color: isDark ? 'bg-red-600' : 'bg-red-500',     label: 'Return'  },
    { pct: row.human_review / total, color: isDark ? 'bg-amber-500' : 'bg-amber-400', label: 'Review'  },
    { pct: row.iet_emergency / total, color: isDark ? 'bg-red-900' : 'bg-red-200',   label: 'IET'     },
    { pct: row.in_flight / total,    color: isDark ? 'bg-slate-600' : 'bg-slate-300', label: 'Flight'  },
  ]
  return (
    <div className="flex h-2 rounded-full overflow-hidden w-32 gap-px">
      {segments.map(({ pct, color }) => (
        <div key={color} className={`${color} transition-all`} style={{ width: `${pct * 100}%` }} />
      ))}
    </div>
  )
}

// ── Detail Panel ─────────────────────────────────────────────────────────────

function LedgerDetailPanel({ row, isDark, onClose }) {
  const th = {
    card:    isDark ? 'bg-white/3 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    kv:      isDark ? 'bg-white/2' : 'bg-slate-50',
  }
  const SHIELD = isDark ? SHIELD_D : SHIELD_L
  const returnPct = (row.return_rate * 100).toFixed(1)

  return (
    <div className={`mt-5 rounded-xl border p-5 ${th.card}`}>
      <div className="flex items-start justify-between mb-4">
        <div>
          <h2 className={`font-semibold ${th.heading}`}>{row.bank_name}</h2>
          <span className={`text-xs ${th.muted}`}>{row.session_date} · {row.clearing_session}</span>
        </div>
        <button onClick={onClose} className={`text-xs ${th.muted}`}>✕</button>
      </div>

      {/* Decision breakdown grid */}
      <div className="grid grid-cols-6 gap-3 mb-4">
        {[
          { label: 'STP Confirm', value: row.stp_confirm, color: isDark ? 'text-emerald-400' : 'text-emerald-600' },
          { label: 'STP Return', value: row.stp_return, color: isDark ? 'text-red-400' : 'text-red-600' },
          { label: 'Human Review', value: row.human_review, color: isDark ? 'text-amber-400' : 'text-amber-600' },
          { label: 'IET Emergency', value: row.iet_emergency, color: isDark ? 'text-red-300' : 'text-red-700' },
          { label: 'In-Flight', value: row.in_flight, color: th.muted },
          { label: 'Total', value: row.total, color: th.heading },
        ].map(({ label, value, color }) => (
          <div key={label} className={`rounded-lg p-3 text-center ${th.kv}`}>
            <div className={`text-[11px] ${th.muted}`}>{label}</div>
            <div className={`text-lg font-bold ${color}`}>{value}</div>
          </div>
        ))}
      </div>

      {/* Shield and audit */}
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div className={`rounded-lg p-4 space-y-3 ${th.kv}`}>
          <div className={`text-[11px] font-medium ${th.muted}`}>Return Rate Shield</div>
          <div className="flex items-center gap-4">
            <div>
              <div className={`text-xl font-bold ${row.return_rate > 0.20 ? (isDark ? 'text-amber-300' : 'text-amber-600') : (isDark ? 'text-emerald-400' : 'text-emerald-600')}`}>
                {returnPct}%
              </div>
              <div className={`text-[11px] ${th.muted}`}>Return Rate</div>
            </div>
            <div>
              <span className={`px-2 py-0.5 rounded-full border text-[10px] font-semibold ${SHIELD[row.shield_status]}`}>
                {row.shield_status.replace('_', ' ')}
              </span>
              <div className={`text-[11px] mt-1 ${th.muted}`}>Shield Status</div>
            </div>
            <div>
              <div className={`text-xl font-bold ${th.heading}`}>{row.avg_fraud_score.toFixed(2)}</div>
              <div className={`text-[11px] ${th.muted}`}>Avg Fraud Score</div>
            </div>
          </div>
        </div>
        <div className={`rounded-lg p-4 space-y-3 ${th.kv}`}>
          <div className={`text-[11px] font-medium ${th.muted}`}>Filing & Audit Integrity</div>
          <div className="space-y-2 text-xs">
            {[
              { label: 'NGCH Filed', value: row.ngch_filed, total: row.total },
              { label: 'Audit Written', value: row.audit_written, total: row.total },
            ].map(({ label, value, total }) => (
              <div key={label} className="flex items-center gap-3">
                <span className={`w-28 ${th.muted}`}>{label}</span>
                <div className={`flex-1 h-1.5 rounded-full ${isDark ? 'bg-white/10' : 'bg-slate-200'} overflow-hidden`}>
                  <div className={`h-full rounded-full ${value === total ? (isDark ? 'bg-emerald-500' : 'bg-emerald-500') : (isDark ? 'bg-amber-500' : 'bg-amber-500')}`} style={{ width: `${value / total * 100}%` }} />
                </div>
                <span className={`w-12 text-right font-semibold ${value === total ? (isDark ? 'text-emerald-400' : 'text-emerald-600') : (isDark ? 'text-amber-400' : 'text-amber-600')}`}>
                  {value}/{total}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className={`text-[11px] ${th.muted}`}>
        Last updated: {row.ledger_updated_at.replace('T', ' ').replace('Z', ' UTC')}
      </div>
    </div>
  )
}

// ── Main Page ────────────────────────────────────────────────────────────────

export default function CTSSMBLedger() {
  const { isDark } = useTheme()
  const [selected, setSelected] = useState(null)
  const [sessionDate, setSessionDate] = useState('2026-06-26')

  const th = {
    page:    isDark ? 'bg-transparent' : 'bg-slate-50',
    card:    isDark ? 'bg-white/3 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    row:     isDark ? 'border-white/5 hover:bg-white/3 cursor-pointer transition-colors' : 'border-slate-100 hover:bg-slate-50 cursor-pointer transition-colors',
    input:   isDark ? 'bg-white/5 border border-white/10 text-slate-300 rounded-lg px-3 py-1.5 text-xs outline-none' : 'bg-white border border-slate-300 text-slate-700 rounded-lg px-3 py-1.5 text-xs outline-none',
  }
  const SHIELD = isDark ? SHIELD_D : SHIELD_L

  const totalCheques = MOCK_LEDGER.reduce((a, r) => a + r.total, 0)
  const totalConfirm = MOCK_LEDGER.reduce((a, r) => a + r.stp_confirm, 0)
  const totalReturn  = MOCK_LEDGER.reduce((a, r) => a + r.stp_return, 0)
  const totalReview  = MOCK_LEDGER.reduce((a, r) => a + r.human_review, 0)
  const shieldAlerts = MOCK_LEDGER.filter(r => r.shield_status !== 'CLEAR').length

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>SMB Batch Ledger</h1>
            <p className={`text-xs mt-0.5 ${th.muted}`}>Session-level clearing summary per Sub-Member Bank — decisions, return rates, NGCH filing integrity</p>
          </div>
          <input
            type="date"
            className={th.input}
            value={sessionDate}
            onChange={e => setSessionDate(e.target.value)}
          />
        </div>

        {/* KPI strip */}
        <div className="grid grid-cols-5 gap-3 mb-5">
          {[
            { label: 'Total Cheques', value: totalCheques.toLocaleString() },
            { label: 'STP Confirm', value: totalConfirm.toLocaleString(), color: isDark ? 'text-emerald-400' : 'text-emerald-600' },
            { label: 'STP Return', value: totalReturn.toLocaleString(), color: isDark ? 'text-red-400' : 'text-red-600' },
            { label: 'Human Review', value: totalReview.toLocaleString(), color: isDark ? 'text-amber-400' : 'text-amber-600' },
            { label: 'Shield Alerts', value: shieldAlerts, color: shieldAlerts > 0 ? (isDark ? 'text-amber-300' : 'text-amber-600') : undefined },
          ].map(({ label, value, color }) => (
            <div key={label} className={`rounded-xl border px-4 py-3 ${th.card}`}>
              <div className={`text-[11px] ${th.muted}`}>{label}</div>
              <div className={`text-xl font-bold mt-0.5 ${color ?? th.heading}`}>{value}</div>
            </div>
          ))}
        </div>

        {/* Table */}
        <div className={`rounded-xl border overflow-hidden ${th.card}`}>
          <table className="w-full text-xs">
            <thead>
              <tr className={`border-b ${th.divider}`}>
                {['Bank', 'Session', 'Confirm', 'Return', 'Review', 'IET', 'Return %', 'Decisions', 'Shield', 'NGCH', ''].map(h => (
                  <th key={h} className={`px-4 py-3 text-left font-medium ${th.muted}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {MOCK_LEDGER.map(row => (
                <tr
                  key={row.sub_member_id}
                  className={`border-b ${th.row}`}
                  onClick={() => setSelected(s => s?.sub_member_id === row.sub_member_id ? null : row)}
                >
                  <td className="px-4 py-3">
                    <div className={`font-medium ${th.heading}`}>{row.bank_name}</div>
                    <div className={`text-[10px] font-mono ${th.muted}`}>{row.sub_member_id}</div>
                  </td>
                  <td className={`px-4 py-3 ${th.muted}`}>{row.clearing_session}</td>
                  <td className={`px-4 py-3 font-semibold ${isDark ? 'text-emerald-400' : 'text-emerald-600'}`}>{row.stp_confirm}</td>
                  <td className={`px-4 py-3 font-semibold ${isDark ? 'text-red-400' : 'text-red-600'}`}>{row.stp_return}</td>
                  <td className={`px-4 py-3 font-semibold ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>{row.human_review}</td>
                  <td className={`px-4 py-3 ${row.iet_emergency > 0 ? (isDark ? 'text-red-300 font-bold' : 'text-red-700 font-bold') : th.muted}`}>{row.iet_emergency}</td>
                  <td className="px-4 py-3">
                    <span className={`font-semibold ${row.return_rate > 0.20 ? (isDark ? 'text-amber-300' : 'text-amber-600') : (isDark ? 'text-emerald-400' : 'text-emerald-600')}`}>
                      {(row.return_rate * 100).toFixed(1)}%
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <DecisionBar row={row} isDark={isDark} />
                  </td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded-full border text-[10px] font-semibold ${SHIELD[row.shield_status]}`}>
                      {row.shield_status.replace('_', ' ')}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`font-medium ${row.ngch_filed < row.total ? (isDark ? 'text-amber-300' : 'text-amber-600') : (isDark ? 'text-emerald-400' : 'text-emerald-600')}`}>
                      {row.ngch_filed}/{row.total}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <button className={`text-[11px] ${isDark ? 'text-cyan-400 hover:text-cyan-300' : 'text-cyan-600 hover:text-cyan-700'}`}>
                      Detail →
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {selected && (
          <LedgerDetailPanel
            row={selected}
            isDark={isDark}
            onClose={() => setSelected(null)}
          />
        )}
      </div>
    </AppShell>
  )
}

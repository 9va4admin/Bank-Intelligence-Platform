import { useState } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'

// ── Mock data ────────────────────────────────────────────────────────────────

const MOCK_LOG = [
  {
    forwarding_id: 'fwd-8a2b3c4d',
    instrument_id: 'CHQ-MH-20260626-00312',
    sub_member_id: 'smb-mh-vasavi',
    bank_name: 'Vasavi Co-operative Bank',
    micr_prefix_matched: '400053',
    forwarding_status: 'COMPLETED',
    terminal_decision: 'STP_CONFIRM',
    iet_deadline_utc: '2026-06-26T12:45:00Z',
    received_at: '2026-06-26T09:41:12Z',
    forwarded_at: '2026-06-26T09:41:13Z',
    completed_at: '2026-06-26T09:41:14Z',
    iet_seconds_remaining: 11027,
    smb_workflow_id: 'smb-cts-smb-mh-vasavi-CHQ-MH-20260626-00312',
    failure_reason: null,
  },
  {
    forwarding_id: 'fwd-9e1f2a3b',
    instrument_id: 'CHQ-MH-20260626-00087',
    sub_member_id: 'smb-mh-kjsb',
    bank_name: 'Kalyan Janata Sahakari Bank',
    micr_prefix_matched: '421301',
    forwarding_status: 'COMPLETED',
    terminal_decision: 'HUMAN_REVIEW',
    iet_deadline_utc: '2026-06-26T12:45:00Z',
    received_at: '2026-06-26T09:39:08Z',
    forwarded_at: '2026-06-26T09:39:09Z',
    completed_at: '2026-06-26T09:39:10Z',
    iet_seconds_remaining: 11150,
    smb_workflow_id: 'smb-cts-smb-mh-kjsb-CHQ-MH-20260626-00087',
    failure_reason: null,
  },
  {
    forwarding_id: 'fwd-1c2d3e4f',
    instrument_id: 'CHQ-MH-20260626-00211',
    sub_member_id: 'smb-gj-mucb',
    bank_name: 'Mehsana Urban Co-op Bank',
    micr_prefix_matched: '384001',
    forwarding_status: 'COMPLETED',
    terminal_decision: 'STP_RETURN',
    iet_deadline_utc: '2026-06-26T12:45:00Z',
    received_at: '2026-06-26T09:38:21Z',
    forwarded_at: '2026-06-26T09:38:22Z',
    completed_at: '2026-06-26T09:38:24Z',
    iet_seconds_remaining: 11197,
    smb_workflow_id: 'smb-cts-smb-gj-mucb-CHQ-MH-20260626-00211',
    failure_reason: null,
  },
  {
    forwarding_id: 'fwd-5a6b7c8d',
    instrument_id: 'CHQ-MH-20260626-00004',
    sub_member_id: 'smb-mh-vasavi',
    bank_name: 'Vasavi Co-operative Bank',
    micr_prefix_matched: '400053',
    forwarding_status: 'FAILED',
    terminal_decision: 'IET_EMERGENCY',
    iet_deadline_utc: '2026-06-26T09:38:00Z',
    received_at: '2026-06-26T09:32:55Z',
    forwarded_at: null,
    completed_at: '2026-06-26T09:33:00Z',
    iet_seconds_remaining: 295,
    smb_workflow_id: null,
    failure_reason: 'INSUFFICIENT_IET_HEADROOM: 295s remaining, need 300s',
  },
  {
    forwarding_id: 'fwd-2e3f4a5b',
    instrument_id: 'CHQ-MH-20260626-00098',
    sub_member_id: 'smb-mh-kjsb',
    bank_name: 'Kalyan Janata Sahakari Bank',
    micr_prefix_matched: '421301',
    forwarding_status: 'FORWARDING',
    terminal_decision: null,
    iet_deadline_utc: '2026-06-26T12:45:00Z',
    received_at: '2026-06-26T09:43:01Z',
    forwarded_at: '2026-06-26T09:43:02Z',
    completed_at: null,
    iet_seconds_remaining: 10918,
    smb_workflow_id: 'smb-cts-smb-mh-kjsb-CHQ-MH-20260626-00098',
    failure_reason: null,
  },
]

const STATUS_D = {
  COMPLETED:  'bg-emerald-900/40 text-emerald-300 border-emerald-700/50',
  FORWARDING: 'bg-cyan-900/40 text-cyan-300 border-cyan-700/50',
  FAILED:     'bg-red-900/40 text-red-300 border-red-700/50',
  RECEIVED:   'bg-slate-800 text-slate-300 border-slate-600',
}
const STATUS_L = {
  COMPLETED:  'bg-emerald-100 text-emerald-700 border-emerald-300',
  FORWARDING: 'bg-cyan-100 text-cyan-700 border-cyan-300',
  FAILED:     'bg-red-100 text-red-700 border-red-300',
  RECEIVED:   'bg-slate-100 text-slate-600 border-slate-300',
}

const DECISION_D = {
  STP_CONFIRM:  'text-emerald-400',
  STP_RETURN:   'text-red-400',
  HUMAN_REVIEW: 'text-amber-400',
  IET_EMERGENCY:'text-red-400',
}
const DECISION_L = {
  STP_CONFIRM:  'text-emerald-600',
  STP_RETURN:   'text-red-600',
  HUMAN_REVIEW: 'text-amber-600',
  IET_EMERGENCY:'text-red-600',
}

function latency(start, end) {
  if (!start || !end) return '—'
  const ms = new Date(end) - new Date(start)
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`
}

// ── Detail Panel ─────────────────────────────────────────────────────────────

function ForwardingDetailPanel({ item, isDark, onClose }) {
  const th = {
    card:    isDark ? 'bg-white/3 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    mono:    isDark ? 'font-mono text-slate-300 text-[11px]' : 'font-mono text-slate-600 text-[11px]',
    kv:      isDark ? 'bg-white/2' : 'bg-slate-50',
  }
  const STATUS   = isDark ? STATUS_D   : STATUS_L
  const DECISION = isDark ? DECISION_D : DECISION_L

  return (
    <div className={`mt-5 rounded-xl border p-5 ${th.card}`}>
      <div className="flex items-start justify-between mb-4">
        <div>
          <h2 className={`font-semibold ${th.heading}`}>Forwarding Hop Detail</h2>
          <span className={`${th.mono}`}>{item.forwarding_id}</span>
        </div>
        <button onClick={onClose} className={`text-xs ${th.muted}`}>✕</button>
      </div>

      <div className="grid grid-cols-2 gap-4 mb-4">
        {/* Left */}
        <div className={`rounded-lg p-4 space-y-3 ${th.kv}`}>
          <div>
            <div className={`text-[11px] ${th.muted}`}>Instrument ID</div>
            <div className={th.mono}>{item.instrument_id}</div>
          </div>
          <div>
            <div className={`text-[11px] ${th.muted}`}>Sub-Member Bank</div>
            <div className={`text-xs font-medium ${th.heading}`}>{item.bank_name}</div>
            <div className={`${th.mono}`}>{item.sub_member_id}</div>
          </div>
          <div>
            <div className={`text-[11px] ${th.muted}`}>MICR Prefix Matched</div>
            <div className={`font-mono font-semibold text-sm ${th.heading}`}>{item.micr_prefix_matched}</div>
          </div>
          <div>
            <div className={`text-[11px] ${th.muted}`}>Terminal Decision</div>
            <div className={`text-sm font-bold ${item.terminal_decision ? DECISION[item.terminal_decision] : th.muted}`}>
              {item.terminal_decision ?? '—'}
            </div>
          </div>
        </div>

        {/* Right */}
        <div className={`rounded-lg p-4 space-y-3 ${th.kv}`}>
          <div>
            <div className={`text-[11px] ${th.muted}`}>Forwarding Status</div>
            <span className={`px-2 py-0.5 rounded-full border text-[10px] font-semibold ${STATUS[item.forwarding_status]}`}>
              {item.forwarding_status}
            </span>
          </div>
          <div>
            <div className={`text-[11px] ${th.muted}`}>IET Headroom at Arrival</div>
            <div className={`text-sm font-bold ${item.iet_seconds_remaining < 300 ? (isDark ? 'text-red-300' : 'text-red-600') : (isDark ? 'text-emerald-400' : 'text-emerald-600')}`}>
              {item.iet_seconds_remaining}s
            </div>
          </div>
          <div>
            <div className={`text-[11px] ${th.muted}`}>IET Deadline</div>
            <div className={`${th.mono}`}>{item.iet_deadline_utc.replace('T', ' ').replace('Z', ' UTC')}</div>
          </div>
          <div>
            <div className={`text-[11px] ${th.muted}`}>Forwarding Latency</div>
            <div className={`text-sm font-bold ${th.heading}`}>{latency(item.received_at, item.completed_at)}</div>
          </div>
        </div>
      </div>

      {/* Timeline */}
      <div className={`rounded-lg p-4 ${th.kv} mb-4`}>
        <div className={`text-[11px] font-medium mb-3 ${th.muted}`}>Forwarding Timeline</div>
        <div className="space-y-2 text-[11px]">
          {[
            { label: 'Received at Sponsor', ts: item.received_at },
            { label: 'Forwarded to SMB Queue', ts: item.forwarded_at },
            { label: 'SMB Processing Complete', ts: item.completed_at },
          ].map(({ label, ts }) => (
            <div key={label} className="flex items-center gap-3">
              <div className={`w-1.5 h-1.5 rounded-full ${ts ? (isDark ? 'bg-cyan-400' : 'bg-cyan-600') : (isDark ? 'bg-white/20' : 'bg-slate-300')}`} />
              <span className={`w-52 ${th.muted}`}>{label}</span>
              <span className={ts ? th.body : th.muted}>{ts ? ts.replace('T', ' ').replace('Z', ' UTC') : '—'}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Failure reason */}
      {item.failure_reason && (
        <div className={`rounded-lg p-3 mb-4 ${isDark ? 'bg-red-900/20 border border-red-700/40' : 'bg-red-50 border border-red-200'}`}>
          <div className={`text-[11px] font-medium mb-1 ${isDark ? 'text-red-300' : 'text-red-700'}`}>Failure Reason</div>
          <div className={`font-mono text-[11px] ${isDark ? 'text-red-200' : 'text-red-800'}`}>{item.failure_reason}</div>
        </div>
      )}

      {/* SMB Workflow ID */}
      {item.smb_workflow_id && (
        <div className={`rounded-lg p-3 ${th.kv}`}>
          <div className={`text-[11px] ${th.muted}`}>SMB Temporal Workflow ID</div>
          <div className={`${th.mono} mt-0.5`}>{item.smb_workflow_id}</div>
        </div>
      )}
    </div>
  )
}

// ── Main Page ────────────────────────────────────────────────────────────────

const ALL_SMBS = ['All SMBs', ...Array.from(new Set(MOCK_LOG.map(l => l.bank_name)))]

export default function CTSSMBForwardingLog() {
  const { isDark } = useTheme()
  const [selected, setSelected] = useState(null)
  const [filterSmb, setFilterSmb] = useState('All SMBs')
  const [filterStatus, setFilterStatus] = useState('All')

  const th = {
    page:    isDark ? 'bg-transparent' : 'bg-slate-50',
    card:    isDark ? 'bg-white/3 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    row:     isDark ? 'border-white/5 hover:bg-white/3 cursor-pointer transition-colors' : 'border-slate-100 hover:bg-slate-50 cursor-pointer transition-colors',
    select:  isDark ? 'bg-white/5 border border-white/10 text-slate-300 rounded-lg px-3 py-1.5 text-xs outline-none' : 'bg-white border border-slate-300 text-slate-700 rounded-lg px-3 py-1.5 text-xs outline-none',
  }
  const STATUS   = isDark ? STATUS_D   : STATUS_L
  const DECISION = isDark ? DECISION_D : DECISION_L

  const filtered = MOCK_LOG.filter(l =>
    (filterSmb === 'All SMBs' || l.bank_name === filterSmb) &&
    (filterStatus === 'All' || l.forwarding_status === filterStatus)
  )

  const completedCount = MOCK_LOG.filter(l => l.forwarding_status === 'COMPLETED').length
  const failedCount    = MOCK_LOG.filter(l => l.forwarding_status === 'FAILED').length
  const inFlightCount  = MOCK_LOG.filter(l => l.forwarding_status === 'FORWARDING').length

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>SMB Forwarding Log</h1>
            <p className={`text-xs mt-0.5 ${th.muted}`}>Per-instrument audit trail for Sponsor Bank → Sub-Member Bank forwarding hops</p>
          </div>
          <div className="flex gap-2">
            <select className={th.select} value={filterSmb} onChange={e => setFilterSmb(e.target.value)}>
              {ALL_SMBS.map(s => <option key={s}>{s}</option>)}
            </select>
            <select className={th.select} value={filterStatus} onChange={e => setFilterStatus(e.target.value)}>
              {['All', 'COMPLETED', 'FORWARDING', 'FAILED', 'RECEIVED'].map(s => <option key={s}>{s}</option>)}
            </select>
          </div>
        </div>

        {/* KPI strip */}
        <div className="grid grid-cols-4 gap-3 mb-5">
          {[
            { label: 'Total Hops Today', value: MOCK_LOG.length },
            { label: 'Completed', value: completedCount },
            { label: 'In-Flight', value: inFlightCount },
            { label: 'IET Failures', value: failedCount, warn: failedCount > 0 },
          ].map(({ label, value, warn }) => (
            <div key={label} className={`rounded-xl border px-4 py-3 ${th.card}`}>
              <div className={`text-[11px] ${th.muted}`}>{label}</div>
              <div className={`text-xl font-bold mt-0.5 ${warn ? (isDark ? 'text-red-300' : 'text-red-600') : th.heading}`}>{value}</div>
            </div>
          ))}
        </div>

        {/* Table */}
        <div className={`rounded-xl border overflow-hidden ${th.card}`}>
          <table className="w-full text-xs">
            <thead>
              <tr className={`border-b ${th.divider}`}>
                {['Instrument', 'Sub-Member', 'MICR', 'Status', 'Decision', 'IET Headroom', 'Latency', 'Forwarded At', ''].map(h => (
                  <th key={h} className={`px-4 py-3 text-left font-medium ${th.muted}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map(item => (
                <tr
                  key={item.forwarding_id}
                  className={`border-b ${th.row}`}
                  onClick={() => setSelected(s => s?.forwarding_id === item.forwarding_id ? null : item)}
                >
                  <td className="px-4 py-3">
                    <div className={`font-mono font-medium ${th.body}`}>{item.instrument_id.slice(-10)}</div>
                    <div className={`text-[10px] font-mono ${th.muted}`}>{item.forwarding_id}</div>
                  </td>
                  <td className="px-4 py-3">
                    <div className={`font-medium ${th.body}`}>{item.bank_name}</div>
                    <div className={`text-[10px] font-mono ${th.muted}`}>{item.micr_prefix_matched}</div>
                  </td>
                  <td className={`px-4 py-3 font-mono font-semibold ${th.heading}`}>{item.micr_prefix_matched}</td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded-full border text-[10px] font-semibold ${STATUS[item.forwarding_status]}`}>
                      {item.forwarding_status}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`font-semibold ${item.terminal_decision ? DECISION[item.terminal_decision] : th.muted}`}>
                      {item.terminal_decision ?? '—'}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`font-semibold ${item.iet_seconds_remaining < 300 ? (isDark ? 'text-red-300' : 'text-red-600') : (isDark ? 'text-emerald-400' : 'text-emerald-600')}`}>
                      {item.iet_seconds_remaining}s
                    </span>
                  </td>
                  <td className={`px-4 py-3 font-medium ${th.heading}`}>{latency(item.received_at, item.completed_at)}</td>
                  <td className={`px-4 py-3 ${th.muted}`}>{item.forwarded_at ? item.forwarded_at.substring(11, 19) + ' UTC' : '—'}</td>
                  <td className="px-4 py-3">
                    <button className={`text-[11px] ${isDark ? 'text-cyan-400 hover:text-cyan-300' : 'text-cyan-600 hover:text-cyan-700'}`}>
                      Detail →
                    </button>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={9} className={`px-4 py-8 text-center text-xs ${th.muted}`}>No forwarding events match the selected filters.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {selected && (
          <ForwardingDetailPanel
            item={selected}
            isDark={isDark}
            onClose={() => setSelected(null)}
          />
        )}
      </div>
    </AppShell>
  )
}

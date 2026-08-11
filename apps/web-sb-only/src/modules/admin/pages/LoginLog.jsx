import { useState } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'

// Mock login events — SB user sees all (SB + SMB tenants), SMB user sees only own
const MOCK_EVENTS = [
  {
    event_id: 'evt-001',
    bank_id: 'hdfc-bank',
    bank_type: 'SB',
    user_id: 'usr-001',
    display_name: 'Rohan Mehta',
    email: 'ops1@bank.com',
    event_type: 'LOGIN_SUCCESS',
    ip_hash: 'a3f9…d12e',
    user_agent: 'Chrome 126 · Windows 11',
    session_id: 'sess-8a7c',
    failure_reason: null,
    occurred_at: '2026-06-29T09:14:22Z',
    immudb_verified: true,
  },
  {
    event_id: 'evt-002',
    bank_id: 'hdfc-bank',
    bank_type: 'SB',
    user_id: 'usr-002',
    display_name: 'Priya Nair',
    email: 'fraud1@bank.com',
    event_type: 'LOGIN_FAILED',
    ip_hash: 'b8e1…f30a',
    user_agent: 'Firefox 127 · macOS',
    session_id: null,
    failure_reason: 'INVALID_PASSWORD',
    occurred_at: '2026-06-29T09:08:55Z',
    immudb_verified: true,
  },
  {
    event_id: 'evt-003',
    bank_id: 'saraswat-coop',
    bank_type: 'SMB',
    user_id: 'smb-usr-001',
    display_name: 'Anil Sawant',
    email: 'smbadmin@saraswat.com',
    event_type: 'LOGIN_SUCCESS',
    ip_hash: 'c5d2…a99b',
    user_agent: 'Edge 125 · Windows 10',
    session_id: 'sess-3b2a',
    failure_reason: null,
    occurred_at: '2026-06-29T08:55:10Z',
    immudb_verified: true,
  },
  {
    event_id: 'evt-004',
    bank_id: 'hdfc-bank',
    bank_type: 'SB',
    user_id: 'usr-001',
    display_name: 'Rohan Mehta',
    email: 'ops1@bank.com',
    event_type: 'SESSION_EXPIRED',
    ip_hash: 'a3f9…d12e',
    user_agent: 'Chrome 126 · Windows 11',
    session_id: 'sess-7c6b',
    failure_reason: null,
    occurred_at: '2026-06-28T18:02:41Z',
    immudb_verified: true,
  },
  {
    event_id: 'evt-005',
    bank_id: 'saraswat-coop',
    bank_type: 'SMB',
    user_id: 'smb-usr-002',
    display_name: 'Meera Kulkarni',
    email: 'smbeditor@saraswat.com',
    event_type: 'TOTP_FAILED',
    ip_hash: 'd9f3…0c1d',
    user_agent: 'Chrome 126 · Android',
    session_id: null,
    failure_reason: 'INVALID_TOTP_CODE',
    occurred_at: '2026-06-28T17:44:19Z',
    immudb_verified: true,
  },
  {
    event_id: 'evt-006',
    bank_id: 'cosmos-bank',
    bank_type: 'SMB',
    user_id: 'smb-usr-003',
    display_name: 'Vivek Joshi',
    email: 'smbadmin@cosmosbank.in',
    event_type: 'LOGIN_SUCCESS',
    ip_hash: 'e2b4…5f8c',
    user_agent: 'Safari 17 · macOS',
    session_id: 'sess-9d4e',
    failure_reason: null,
    occurred_at: '2026-06-28T16:30:07Z',
    immudb_verified: false,
  },
  {
    event_id: 'evt-007',
    bank_id: 'hdfc-bank',
    bank_type: 'SB',
    user_id: 'usr-003',
    display_name: 'Suresh Kumar',
    email: 'mgr1@bank.com',
    event_type: 'LOGOUT',
    ip_hash: 'f7a1…b22c',
    user_agent: 'Chrome 126 · Windows 11',
    session_id: 'sess-1f9a',
    failure_reason: null,
    occurred_at: '2026-06-28T15:00:00Z',
    immudb_verified: true,
  },
  {
    event_id: 'evt-008',
    bank_id: 'saraswat-coop',
    bank_type: 'SMB',
    user_id: 'smb-usr-001',
    display_name: 'Anil Sawant',
    email: 'smbadmin@saraswat.com',
    event_type: 'FORCE_LOGOUT',
    ip_hash: 'c5d2…a99b',
    user_agent: 'Edge 125 · Windows 10',
    session_id: 'sess-3b2a',
    failure_reason: null,
    occurred_at: '2026-06-28T14:20:33Z',
    immudb_verified: true,
  },
]

// Simulate current viewer's role — in production comes from auth context
// 'SB' = sponsor bank user (sees all), 'SMB' = sub-member user (sees own bank_id only)
const VIEWER_BANK_TYPE = 'SB'
const VIEWER_BANK_ID = 'hdfc-bank'

const EVENT_TYPE_META = {
  LOGIN_SUCCESS:  { label: 'Login',          darkCls: 'bg-emerald-900/40 text-emerald-300 border-emerald-700/50', lightCls: 'bg-emerald-100 text-emerald-700 border-emerald-300' },
  LOGIN_FAILED:   { label: 'Login Failed',   darkCls: 'bg-red-900/40 text-red-300 border-red-700/50',           lightCls: 'bg-red-100 text-red-700 border-red-300' },
  LOGOUT:         { label: 'Logout',         darkCls: 'bg-slate-800 text-slate-300 border-slate-700',           lightCls: 'bg-slate-100 text-slate-600 border-slate-300' },
  SESSION_EXPIRED:{ label: 'Session Expired',darkCls: 'bg-amber-900/40 text-amber-300 border-amber-700/50',     lightCls: 'bg-amber-100 text-amber-700 border-amber-300' },
  TOTP_FAILED:    { label: 'TOTP Failed',    darkCls: 'bg-red-900/40 text-red-300 border-red-700/50',           lightCls: 'bg-red-100 text-red-700 border-red-300' },
  FORCE_LOGOUT:   { label: 'Force Logout',   darkCls: 'bg-violet-900/40 text-violet-300 border-violet-700/50', lightCls: 'bg-violet-100 text-violet-700 border-violet-300' },
}

function fmt(iso) {
  const d = new Date(iso)
  return d.toLocaleString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })
}

export default function LoginLog() {
  const { isDark } = useTheme()
  const [eventTypeFilter, setEventTypeFilter] = useState('ALL')
  const [bankTypeFilter, setBankTypeFilter] = useState('ALL')
  const [search, setSearch] = useState('')

  const th = {
    page:    isDark ? 'bg-transparent' : 'bg-slate-50',
    card:    isDark ? 'bg-white/3 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    row:     isDark ? 'border-white/5 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
    input:   isDark ? 'bg-white/5 border-white/10 text-white placeholder-slate-500 focus:border-cyan-500 focus:outline-none' : 'bg-white border-slate-300 text-slate-900 placeholder-slate-400 focus:border-cyan-500 focus:outline-none',
    tab:     (active) => active
      ? (isDark ? 'bg-white/10 text-white' : 'bg-slate-200 text-slate-900')
      : (isDark ? 'text-slate-400 hover:text-slate-200' : 'text-slate-500 hover:text-slate-700'),
    pill:    isDark ? 'bg-white/5 text-slate-300 border-white/8' : 'bg-slate-100 text-slate-600 border-slate-200',
  }

  const isSB = VIEWER_BANK_TYPE === 'SB'

  // Scope events by viewer role
  const scopedEvents = isSB
    ? MOCK_EVENTS
    : MOCK_EVENTS.filter(e => e.bank_id === VIEWER_BANK_ID)

  const filtered = scopedEvents.filter(e => {
    if (eventTypeFilter !== 'ALL' && e.event_type !== eventTypeFilter) return false
    if (bankTypeFilter !== 'ALL' && e.bank_type !== bankTypeFilter) return false
    if (search) {
      const q = search.toLowerCase()
      return (
        e.display_name.toLowerCase().includes(q) ||
        e.email.toLowerCase().includes(q) ||
        e.bank_id.toLowerCase().includes(q)
      )
    }
    return true
  })

  const stats = {
    total: scopedEvents.length,
    success: scopedEvents.filter(e => e.event_type === 'LOGIN_SUCCESS').length,
    failed: scopedEvents.filter(e => ['LOGIN_FAILED', 'TOTP_FAILED'].includes(e.event_type)).length,
    unverified: scopedEvents.filter(e => !e.immudb_verified).length,
  }

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        {/* Header */}
        <div className="mb-5">
          <h1 className={`text-lg font-semibold ${th.heading}`}>Login Log</h1>
          <p className={`text-xs mt-0.5 ${th.muted}`}>
            {isSB
              ? 'Immutable audit trail of all login events across SB and sub-member banks'
              : 'Immutable audit trail of login events for your institution'}
          </p>
        </div>

        {/* Read-only notice */}
        <div className={`flex items-center gap-2 px-3 py-2 rounded-lg border mb-5 text-[11px] ${isDark ? 'bg-amber-900/20 border-amber-700/40 text-amber-300' : 'bg-amber-50 border-amber-200 text-amber-700'}`}>
          <span>🔒</span>
          <span>This log is immutable — stored in Immudb with cryptographic verification. No entries can be edited or deleted.</span>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-4 gap-3 mb-5">
          {[
            { label: 'Total Events', value: stats.total },
            { label: 'Successful Logins', value: stats.success },
            { label: 'Failed Attempts', value: stats.failed },
            { label: 'Pending Immudb Verify', value: stats.unverified },
          ].map(({ label, value }) => (
            <div key={label} className={`rounded-xl border px-4 py-3 ${th.card}`}>
              <div className={`text-[11px] ${th.muted}`}>{label}</div>
              <div className={`text-xl font-bold mt-0.5 ${th.heading}`}>{value}</div>
            </div>
          ))}
        </div>

        {/* Filters */}
        <div className="flex items-center gap-3 mb-4">
          <input
            type="text"
            placeholder="Search user, email, bank…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className={`rounded-lg border px-3 py-2 text-xs w-56 ${th.input}`}
          />

          {/* Event type filter */}
          <div className={`flex items-center gap-1 rounded-lg border p-1 ${isDark ? 'border-white/8 bg-white/3' : 'border-slate-200 bg-slate-100'}`}>
            {['ALL', 'LOGIN_SUCCESS', 'LOGIN_FAILED', 'TOTP_FAILED', 'LOGOUT', 'SESSION_EXPIRED', 'FORCE_LOGOUT'].map(t => (
              <button key={t} onClick={() => setEventTypeFilter(t)}
                className={`px-2.5 py-1 rounded-md text-[10px] font-medium transition-all ${th.tab(eventTypeFilter === t)}`}>
                {t === 'ALL' ? 'All Types' : EVENT_TYPE_META[t]?.label ?? t}
              </button>
            ))}
          </div>

          {/* Bank type filter — only for SB viewers */}
          {isSB && (
            <div className={`flex items-center gap-1 rounded-lg border p-1 ${isDark ? 'border-white/8 bg-white/3' : 'border-slate-200 bg-slate-100'}`}>
              {['ALL', 'SB', 'SMB'].map(t => (
                <button key={t} onClick={() => setBankTypeFilter(t)}
                  className={`px-2.5 py-1 rounded-md text-[10px] font-medium transition-all ${th.tab(bankTypeFilter === t)}`}>
                  {t === 'ALL' ? 'All Banks' : t}
                </button>
              ))}
            </div>
          )}

          <span className={`ml-auto text-[11px] ${th.muted}`}>{filtered.length} event{filtered.length !== 1 ? 's' : ''}</span>
        </div>

        {/* Table */}
        <div className={`rounded-xl border overflow-hidden ${th.card}`}>
          <table className="w-full text-xs">
            <thead>
              <tr className={`border-b ${th.divider}`}>
                {['Time', 'User', isSB && 'Bank', 'Event', 'IP (hash)', 'Device', 'Immudb', ''].filter(Boolean).map(h => (
                  <th key={h} className={`px-4 py-3 text-left font-medium ${th.muted}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={isSB ? 8 : 7} className={`px-4 py-8 text-center ${th.muted}`}>No events match the current filters</td>
                </tr>
              ) : filtered.map(ev => {
                const meta = EVENT_TYPE_META[ev.event_type] ?? { label: ev.event_type, darkCls: th.pill, lightCls: th.pill }
                const cls = isDark ? meta.darkCls : meta.lightCls
                return (
                  <tr key={ev.event_id} className={`border-b transition-colors ${th.row}`}>
                    <td className={`px-4 py-3 whitespace-nowrap ${th.muted}`}>{fmt(ev.occurred_at)}</td>
                    <td className="px-4 py-3">
                      <div className={`font-medium ${th.heading}`}>{ev.display_name}</div>
                      <div className={th.muted}>{ev.email}</div>
                    </td>
                    {isSB && (
                      <td className="px-4 py-3">
                        <div className={th.body}>{ev.bank_id}</div>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${isDark ? 'bg-white/5 text-slate-400 border-white/8' : 'bg-slate-100 text-slate-500 border-slate-200'}`}>{ev.bank_type}</span>
                      </td>
                    )}
                    <td className="px-4 py-3">
                      <span className={`px-2 py-0.5 rounded-full border text-[10px] font-semibold ${cls}`}>
                        {meta.label}
                      </span>
                      {ev.failure_reason && (
                        <div className={`mt-1 text-[10px] ${isDark ? 'text-red-400' : 'text-red-600'}`}>{ev.failure_reason}</div>
                      )}
                    </td>
                    <td className={`px-4 py-3 font-mono ${th.muted}`}>{ev.ip_hash}</td>
                    <td className={`px-4 py-3 max-w-[140px] truncate ${th.muted}`}>{ev.user_agent}</td>
                    <td className="px-4 py-3">
                      {ev.immudb_verified
                        ? <span className={`text-[10px] ${isDark ? 'text-emerald-400' : 'text-emerald-600'}`}>✓ Verified</span>
                        : <span className={`text-[10px] ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>⏳ Pending</span>}
                    </td>
                    <td className="px-4 py-3">
                      {ev.session_id && (
                        <span className={`text-[10px] font-mono ${th.muted}`}>{ev.session_id}</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        <p className={`mt-3 text-[10px] ${th.muted}`}>
          Records are cryptographically sealed in Immudb. Verified entries have been confirmed against the Merkle root.
        </p>
      </div>
    </AppShell>
  )
}

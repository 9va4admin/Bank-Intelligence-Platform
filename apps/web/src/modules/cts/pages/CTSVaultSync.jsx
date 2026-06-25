import { useState } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'

// ── Mock data ──────────────────────────────────────────────────────────────

const MOCK_SYNC_STATUS = {
  last_run_at: '2026-06-25T07:00:14Z',
  triggered_by: 'SCHEDULED',
  duration_seconds: 43,
  pps_records_loaded: 18240,
  stop_cheque_records_loaded: 412,
  status: 'SUCCESS',
  next_scheduled: '2026-06-26T07:00:00Z',
  cbs_connector: 'Finacle REST v2',
  mcp_tool: 'get_pps_data',
}

const MOCK_SYNC_HISTORY = [
  { run_at: '2026-06-25T07:00:14Z', triggered_by: 'SCHEDULED', status: 'SUCCESS', pps: 18240, stop: 412, duration: 43 },
  { run_at: '2026-06-24T07:00:09Z', triggered_by: 'SCHEDULED', status: 'SUCCESS', pps: 18198, stop: 408, duration: 41 },
  { run_at: '2026-06-23T14:22:31Z', triggered_by: 'MANUAL',    status: 'SUCCESS', pps: 18190, stop: 408, duration: 39 },
  { run_at: '2026-06-23T07:00:11Z', triggered_by: 'SCHEDULED', status: 'PARTIAL', pps: 18100, stop: 400, duration: 67 },
  { run_at: '2026-06-22T07:00:08Z', triggered_by: 'SCHEDULED', status: 'SUCCESS', pps: 18050, stop: 396, duration: 40 },
]

const MOCK_PPS = [
  { account_display: '****4521', cheque_series_from: '000001', cheque_series_to: '000050', amount: '₹[1L-5L]', payee_display: 'R***', valid_from: '2026-06-01', valid_to: '2026-12-31', status: 'ACTIVE' },
  { account_display: '****7890', cheque_series_from: '000100', cheque_series_to: '000150', amount: '₹[5L-10L]', payee_display: 'S***', valid_from: '2026-05-15', valid_to: '2026-08-31', status: 'ACTIVE' },
  { account_display: '****1122', cheque_series_from: '000200', cheque_series_to: '000210', amount: '₹[<1L]',    payee_display: 'M***', valid_from: '2026-06-10', valid_to: '2026-07-10', status: 'EXPIRING_SOON' },
  { account_display: '****3344', cheque_series_from: '000300', cheque_series_to: '000399', amount: '₹[>1Cr]',   payee_display: 'P***', valid_from: '2026-04-01', valid_to: '2026-06-30', status: 'EXPIRED' },
  { account_display: '****5566', cheque_series_from: '000050', cheque_series_to: '000099', amount: '₹[10L-1Cr]',payee_display: 'N***', valid_from: '2026-06-20', valid_to: '2026-09-20', status: 'ACTIVE' },
]

const MOCK_STOP = [
  { account_display: '****2233', cheque_number: '000045', reason: 'Lost / Stolen',       requested_at: '2026-06-24T11:30:00Z', status: 'ACTIVE' },
  { account_display: '****8877', cheque_number: '000178', reason: 'Disputed Amount',      requested_at: '2026-06-23T09:15:00Z', status: 'ACTIVE' },
  { account_display: '****4499', cheque_number: '000222', reason: 'Countermand by Drawer',requested_at: '2026-06-20T16:45:00Z', status: 'REVOKED' },
  { account_display: '****6611', cheque_number: '000033', reason: 'Lost / Stolen',        requested_at: '2026-06-18T08:00:00Z', status: 'ACTIVE' },
]

// ── Helpers ────────────────────────────────────────────────────────────────

function fmtDate(iso) {
  return new Date(iso).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })
}

function StatusPill({ status }) {
  const MAP = {
    SUCCESS:        'bg-emerald-900/40 text-emerald-300 border-emerald-700/40',
    PARTIAL:        'bg-amber-900/40   text-amber-300   border-amber-700/40',
    FAILED:         'bg-red-900/40     text-red-300     border-red-700/40',
    ACTIVE:         'bg-emerald-900/40 text-emerald-300 border-emerald-700/40',
    EXPIRING_SOON:  'bg-amber-900/40   text-amber-300   border-amber-700/40',
    EXPIRED:        'bg-slate-800      text-slate-400   border-slate-700',
    REVOKED:        'bg-slate-800      text-slate-400   border-slate-700',
  }
  const LIGHT_MAP = {
    SUCCESS:        'bg-emerald-50 text-emerald-700 border-emerald-200',
    PARTIAL:        'bg-amber-50   text-amber-700   border-amber-200',
    FAILED:         'bg-red-50     text-red-700     border-red-200',
    ACTIVE:         'bg-emerald-50 text-emerald-700 border-emerald-200',
    EXPIRING_SOON:  'bg-amber-50   text-amber-700   border-amber-200',
    EXPIRED:        'bg-slate-100  text-slate-500   border-slate-200',
    REVOKED:        'bg-slate-100  text-slate-500   border-slate-200',
  }
  return (
    <span className={`inline-flex px-2 py-0.5 rounded-full text-[10px] font-semibold border ${MAP[status] ?? MAP.ACTIVE}`}>
      {status.replace('_', ' ')}
    </span>
  )
}

// ── Page ───────────────────────────────────────────────────────────────────

export default function CTSVaultSync() {
  const { isDark } = useTheme()
  const [tab, setTab] = useState('pps')
  const [syncing, setSyncing] = useState(false)
  const [syncMsg, setSyncMsg] = useState(null)
  const [ppsSearch, setPpsSearch] = useState('')
  const [stopSearch, setStopSearch] = useState('')

  const th = {
    page:    isDark ? '' : 'bg-slate-50',
    card:    isDark ? 'bg-white/4 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    row:     isDark ? 'border-white/5 hover:bg-white/3' : 'border-slate-100 hover:bg-slate-50',
    input:   isDark ? 'bg-white/8 border-white/10 text-white placeholder-slate-500' : 'bg-white border-slate-200 text-slate-800 placeholder-slate-400',
  }

  const handleManualSync = async () => {
    setSyncing(true)
    setSyncMsg(null)
    // In production: POST /v1/admin/vault-sync/trigger
    await new Promise((r) => setTimeout(r, 2200))
    setSyncing(false)
    setSyncMsg({ type: 'success', text: 'Vault sync triggered. Temporal workflow started — PPS & Stop Cheque data will refresh within ~45 seconds.' })
  }

  const filteredPPS = MOCK_PPS.filter((r) =>
    !ppsSearch || r.account_display.includes(ppsSearch) || r.cheque_series_from.includes(ppsSearch)
  )
  const filteredStop = MOCK_STOP.filter((r) =>
    !stopSearch || r.account_display.includes(stopSearch) || r.cheque_number.includes(stopSearch)
  )

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>

        {/* Page header */}
        <div className="flex items-start justify-between mb-5">
          <div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>Positive Pay & Stop Cheque</h1>
            <p className={`text-xs mt-0.5 ${th.muted}`}>
              CBS vault data — synced daily at 7:00 AM via Temporal · CBS: {MOCK_SYNC_STATUS.cbs_connector}
            </p>
          </div>
          <button
            onClick={handleManualSync}
            disabled={syncing}
            className={`flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs font-medium transition-all ${
              syncing
                ? 'opacity-60 cursor-not-allowed bg-slate-700 text-slate-300'
                : (isDark ? 'bg-gold-500/20 text-gold-300 border border-gold-500/30 hover:bg-gold-500/30' : 'bg-amber-50 text-amber-700 border border-amber-200 hover:bg-amber-100')
            }`}
          >
            {syncing ? (
              <>
                <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" strokeLinecap="round"/>
                </svg>
                Syncing…
              </>
            ) : (
              <>
                <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" className="w-3.5 h-3.5">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4A7 7 0 1 0 14 8" />
                  <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 1v3h-3" />
                </svg>
                Sync Now
              </>
            )}
          </button>
        </div>

        {/* Sync message */}
        {syncMsg && (
          <div className={`mb-4 px-4 py-3 rounded-lg text-xs flex items-start gap-3 ${
            syncMsg.type === 'success'
              ? (isDark ? 'bg-emerald-900/30 border border-emerald-700/40 text-emerald-300' : 'bg-emerald-50 border border-emerald-200 text-emerald-700')
              : (isDark ? 'bg-red-900/30 border border-red-700/40 text-red-300' : 'bg-red-50 border border-red-200 text-red-700')
          }`}>
            <span className="text-base mt-0.5">{syncMsg.type === 'success' ? '✓' : '✕'}</span>
            <span>{syncMsg.text}</span>
          </div>
        )}

        {/* Status cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
          {[
            { label: 'Last Sync', value: fmtDate(MOCK_SYNC_STATUS.last_run_at), sub: MOCK_SYNC_STATUS.triggered_by },
            { label: 'PPS Records', value: MOCK_SYNC_STATUS.pps_records_loaded.toLocaleString('en-IN'), sub: 'Active entries' },
            { label: 'Stop Cheques', value: MOCK_SYNC_STATUS.stop_cheque_records_loaded.toLocaleString('en-IN'), sub: 'Active holds' },
            { label: 'Next Scheduled', value: fmtDate(MOCK_SYNC_STATUS.next_scheduled), sub: 'Daily at 07:00 AM' },
          ].map(({ label, value, sub }) => (
            <div key={label} className={`rounded-xl border p-4 ${th.card}`}>
              <div className={`text-[10px] font-semibold uppercase tracking-widest mb-1 ${th.muted}`}>{label}</div>
              <div className={`text-[13px] font-semibold ${th.heading}`}>{value}</div>
              <div className={`text-[10px] mt-0.5 ${th.muted}`}>{sub}</div>
            </div>
          ))}
        </div>

        {/* Tabs */}
        <div className={`flex gap-1 mb-4 p-1 rounded-lg w-fit border ${isDark ? 'bg-white/4 border-white/8' : 'bg-slate-100 border-slate-200'}`}>
          {['pps', 'stop', 'history'].map((t) => {
            const labels = { pps: 'Positive Pay', stop: 'Stop Cheques', history: 'Sync History' }
            return (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`px-3 py-1.5 text-xs rounded-md transition-all font-medium ${
                  tab === t
                    ? (isDark ? 'bg-white/15 text-white' : 'bg-white text-slate-800 shadow-sm')
                    : (isDark ? 'text-slate-400 hover:text-slate-200' : 'text-slate-500 hover:text-slate-700')
                }`}
              >
                {labels[t]}
              </button>
            )
          })}
        </div>

        {/* PPS tab */}
        {tab === 'pps' && (
          <div className={`rounded-xl border overflow-hidden ${th.card}`}>
            <div className={`flex items-center justify-between px-4 py-3 border-b ${th.divider}`}>
              <span className={`text-xs font-semibold ${th.heading}`}>Positive Pay Instructions</span>
              <input
                value={ppsSearch}
                onChange={(e) => setPpsSearch(e.target.value)}
                placeholder="Search account / series…"
                className={`h-7 w-48 px-3 rounded-lg border text-[11px] outline-none ${th.input}`}
              />
            </div>
            <table className="w-full">
              <thead>
                <tr className={`text-[10px] uppercase tracking-wider ${th.muted} ${isDark ? 'bg-white/3' : 'bg-slate-50'}`}>
                  {['Account', 'Series From', 'Series To', 'Amount Range', 'Payee', 'Valid From', 'Valid To', 'Status'].map((h) => (
                    <th key={h} className="px-4 py-2 text-left font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredPPS.map((r, i) => (
                  <tr key={i} className={`text-xs border-t transition-colors ${th.row}`}>
                    <td className={`px-4 py-2.5 font-mono font-semibold ${th.heading}`}>{r.account_display}</td>
                    <td className={`px-4 py-2.5 font-mono ${th.body}`}>{r.cheque_series_from}</td>
                    <td className={`px-4 py-2.5 font-mono ${th.body}`}>{r.cheque_series_to}</td>
                    <td className={`px-4 py-2.5 ${th.body}`}>{r.amount}</td>
                    <td className={`px-4 py-2.5 ${th.body}`}>{r.payee_display}</td>
                    <td className={`px-4 py-2.5 ${th.muted}`}>{r.valid_from}</td>
                    <td className={`px-4 py-2.5 ${th.muted}`}>{r.valid_to}</td>
                    <td className="px-4 py-2.5"><StatusPill status={r.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className={`px-4 py-2 border-t text-[10px] ${th.muted} ${th.divider}`}>
              {filteredPPS.length} records shown · Total in vault: {MOCK_SYNC_STATUS.pps_records_loaded.toLocaleString('en-IN')}
            </div>
          </div>
        )}

        {/* Stop Cheque tab */}
        {tab === 'stop' && (
          <div className={`rounded-xl border overflow-hidden ${th.card}`}>
            <div className={`flex items-center justify-between px-4 py-3 border-b ${th.divider}`}>
              <span className={`text-xs font-semibold ${th.heading}`}>Stop Cheque Instructions</span>
              <input
                value={stopSearch}
                onChange={(e) => setStopSearch(e.target.value)}
                placeholder="Search account / cheque no…"
                className={`h-7 w-48 px-3 rounded-lg border text-[11px] outline-none ${th.input}`}
              />
            </div>
            <table className="w-full">
              <thead>
                <tr className={`text-[10px] uppercase tracking-wider ${th.muted} ${isDark ? 'bg-white/3' : 'bg-slate-50'}`}>
                  {['Account', 'Cheque No.', 'Reason', 'Requested At', 'Status'].map((h) => (
                    <th key={h} className="px-4 py-2 text-left font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredStop.map((r, i) => (
                  <tr key={i} className={`text-xs border-t transition-colors ${th.row}`}>
                    <td className={`px-4 py-2.5 font-mono font-semibold ${th.heading}`}>{r.account_display}</td>
                    <td className={`px-4 py-2.5 font-mono ${th.body}`}>{r.cheque_number}</td>
                    <td className={`px-4 py-2.5 ${th.body}`}>{r.reason}</td>
                    <td className={`px-4 py-2.5 ${th.muted}`}>{fmtDate(r.requested_at)}</td>
                    <td className="px-4 py-2.5"><StatusPill status={r.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className={`px-4 py-2 border-t text-[10px] ${th.muted} ${th.divider}`}>
              {filteredStop.length} records shown · Total in vault: {MOCK_SYNC_STATUS.stop_cheque_records_loaded.toLocaleString('en-IN')}
            </div>
          </div>
        )}

        {/* History tab */}
        {tab === 'history' && (
          <div className={`rounded-xl border overflow-hidden ${th.card}`}>
            <div className={`px-4 py-3 border-b ${th.divider}`}>
              <span className={`text-xs font-semibold ${th.heading}`}>Sync Run History</span>
            </div>
            <table className="w-full">
              <thead>
                <tr className={`text-[10px] uppercase tracking-wider ${th.muted} ${isDark ? 'bg-white/3' : 'bg-slate-50'}`}>
                  {['Run At', 'Triggered By', 'Status', 'PPS Records', 'Stop Records', 'Duration'].map((h) => (
                    <th key={h} className="px-4 py-2 text-left font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {MOCK_SYNC_HISTORY.map((r, i) => (
                  <tr key={i} className={`text-xs border-t transition-colors ${th.row}`}>
                    <td className={`px-4 py-2.5 ${th.heading}`}>{fmtDate(r.run_at)}</td>
                    <td className={`px-4 py-2.5 ${th.body}`}>
                      <span className={`inline-flex px-2 py-0.5 rounded text-[10px] font-medium ${
                        r.triggered_by === 'MANUAL'
                          ? (isDark ? 'bg-violet-900/40 text-violet-300' : 'bg-violet-50 text-violet-700')
                          : (isDark ? 'bg-white/8 text-slate-400' : 'bg-slate-100 text-slate-500')
                      }`}>{r.triggered_by}</span>
                    </td>
                    <td className="px-4 py-2.5"><StatusPill status={r.status} /></td>
                    <td className={`px-4 py-2.5 tabular-nums ${th.body}`}>{r.pps.toLocaleString('en-IN')}</td>
                    <td className={`px-4 py-2.5 tabular-nums ${th.body}`}>{r.stop.toLocaleString('en-IN')}</td>
                    <td className={`px-4 py-2.5 ${th.muted}`}>{r.duration}s</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </AppShell>
  )
}

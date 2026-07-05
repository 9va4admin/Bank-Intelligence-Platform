/**
 * CTSAgencyCC — Agency Command Center
 *
 * Overview dashboard for AGENCY_SB_RELAY deployment mode.
 * Shows all upstream SB connections, clearing session status per SB,
 * lot routing summary, and inward relay status.
 *
 * Only rendered for SB (agency) bank type — smbOnly gate is NOT set;
 * this is an sbOnly page because only the agency itself operates it.
 * SMB users never see this page (AppShell sbOnly gate + useBankContext guard).
 */
import { useState } from 'react'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'
import AppShell from '../../../shared/layout/AppShell'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'

// ── Mock data ──────────────────────────────────────────────────────────────
const MOCK_SB_CONNECTIONS = [
  {
    sb_connection_id: 'sbconn-saraswat',
    sb_name: 'Saraswat Co-operative Bank',
    sb_bank_id: 'saraswat-coop',
    connector_type: 'SFTP_GENERIC',
    is_active: true,
    last_tested_at: '2026-07-05T06:05:00Z',
    last_test_latency_ms: 142,
    smb_count: 4,
  },
  {
    sb_connection_id: 'sbconn-cosmos',
    sb_name: 'Cosmos Co-operative Bank',
    sb_bank_id: 'cosmos-coop',
    connector_type: 'BANCS_API',
    is_active: true,
    last_tested_at: '2026-07-05T06:05:00Z',
    last_test_latency_ms: 87,
    smb_count: 2,
  },
  {
    sb_connection_id: 'sbconn-nelito',
    sb_name: 'Bharat Co-operative Bank',
    sb_bank_id: 'bharat-coop',
    connector_type: 'NELITO_API',
    is_active: false,
    last_tested_at: '2026-07-04T18:30:00Z',
    last_test_latency_ms: null,
    smb_count: 1,
    error_message: 'SFTP timeout — host unreachable',
  },
]

const MOCK_SESSIONS = [
  {
    session_id: 'sess-morning-saraswat',
    sb_bank_id: 'saraswat-coop',
    sb_name: 'Saraswat Co-operative Bank',
    session_type: 'MORNING',
    status: 'SUBMITTED',
    total_instruments: 234,
    sb_reference: 'SB-SFTP-20260705-001',
    opened_at: '2026-07-05T10:00:00Z',
    submitted_at: '2026-07-05T10:42:00Z',
  },
  {
    session_id: 'sess-morning-cosmos',
    sb_bank_id: 'cosmos-coop',
    sb_name: 'Cosmos Co-operative Bank',
    session_type: 'MORNING',
    status: 'SEALED',
    total_instruments: 98,
    sb_reference: null,
    opened_at: '2026-07-05T10:00:00Z',
    submitted_at: null,
  },
  {
    session_id: 'sess-morning-bharat',
    sb_bank_id: 'bharat-coop',
    sb_name: 'Bharat Co-operative Bank',
    session_type: 'MORNING',
    status: 'EXCEPTION',
    total_instruments: 41,
    sb_reference: null,
    opened_at: '2026-07-05T10:00:00Z',
    submitted_at: null,
    failure_reason: 'SB_CONNECTOR_FAILED',
  },
  {
    session_id: 'sess-afternoon-saraswat',
    sb_bank_id: 'saraswat-coop',
    sb_name: 'Saraswat Co-operative Bank',
    session_type: 'AFTERNOON',
    status: 'OPEN',
    total_instruments: 0,
    sb_reference: null,
    opened_at: '2026-07-05T13:00:00Z',
    submitted_at: null,
  },
]

const MOCK_INWARD_STATS = {
  total_received: 187,
  routed: 183,
  crl_misses: 4,
  last_relay_at: '2026-07-05T11:15:00Z',
}

const MOCK_PUSH_SESSIONS = [
  {
    id: 'push-001',
    smb_id: 'testucb',
    smb_name: 'Test UCB',
    file_type: 'STOP_PAYMENTS',
    outcome: 'VAULT_UPDATED',
    records_processed: 12,
    received_at: '2026-07-05T11:45:00Z',
    file_hash: 'abc123',
  },
  {
    id: 'push-002',
    smb_id: 'testucb',
    smb_name: 'Test UCB',
    file_type: 'PPS_ENTRIES',
    outcome: 'VAULT_UPDATED',
    records_processed: 34,
    received_at: '2026-07-05T11:45:01Z',
    file_hash: 'def456',
  },
  {
    id: 'push-003',
    smb_id: 'cosmos-smb',
    smb_name: 'Cosmos SMB',
    file_type: 'SIGNATURES',
    outcome: 'PARSE_FAILED',
    records_processed: 0,
    received_at: '2026-07-05T11:30:00Z',
    failure_reason: 'MISSING_COLUMN:amount',
    file_hash: 'ghi789',
  },
  {
    id: 'push-004',
    smb_id: 'testucb',
    smb_name: 'Test UCB',
    file_type: 'STOP_PAYMENTS',
    outcome: 'DUPLICATE_SKIPPED',
    records_processed: 0,
    received_at: '2026-07-05T11:46:00Z',
    file_hash: 'abc123',
  },
]

// ── Constants ──────────────────────────────────────────────────────────────
const STATUS_D = {
  OPEN:       'bg-slate-700/40 text-slate-300 border-slate-600/40',
  SEALED:     'bg-amber-900/40 text-amber-300 border-amber-700/40',
  SUBMITTED:  'bg-emerald-900/40 text-emerald-300 border-emerald-700/40',
  RECONCILED: 'bg-blue-900/40 text-blue-300 border-blue-700/40',
  EXCEPTION:  'bg-red-900/50 text-red-300 border-red-700/40',
  EMPTY_SESSION: 'bg-slate-700/30 text-slate-400 border-slate-600/30',
}
const STATUS_L = {
  OPEN:       'bg-slate-100 text-slate-600 border-slate-300',
  SEALED:     'bg-amber-100 text-amber-700 border-amber-300',
  SUBMITTED:  'bg-emerald-100 text-emerald-700 border-emerald-300',
  RECONCILED: 'bg-blue-100 text-blue-700 border-blue-300',
  EXCEPTION:  'bg-red-100 text-red-700 border-red-300',
  EMPTY_SESSION: 'bg-slate-50 text-slate-500 border-slate-200',
}

const CONNECTOR_BADGE = {
  SFTP_GENERIC: 'bg-violet-500/15 text-violet-300',
  BANCS_API:    'bg-blue-500/15 text-blue-300',
  NELITO_API:   'bg-teal-500/15 text-teal-300',
}
const CONNECTOR_BADGE_L = {
  SFTP_GENERIC: 'bg-violet-100 text-violet-700',
  BANCS_API:    'bg-blue-100 text-blue-700',
  NELITO_API:   'bg-teal-100 text-teal-700',
}

function fmtTime(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false })
}

// ── Sub-components ─────────────────────────────────────────────────────────
function StatCard({ label, value, sub, accent, isDark }) {
  const th = {
    card: isDark
      ? 'bg-navy-900 border border-white/8'
      : 'bg-white border border-slate-200',
    label: isDark ? 'text-slate-400' : 'text-slate-500',
    value: isDark ? 'text-white' : 'text-slate-900',
    sub: isDark ? 'text-slate-500' : 'text-slate-400',
  }
  return (
    <div className={`rounded-lg p-4 ${th.card}`}>
      <div className={`text-xs uppercase tracking-wider font-semibold ${th.label} mb-1`}>{label}</div>
      <div className={`text-2xl font-bold tabular-nums ${accent || th.value}`}>{value}</div>
      {sub && <div className={`text-xs mt-1 ${th.sub}`}>{sub}</div>}
    </div>
  )
}

function SBConnectionCard({ conn, isDark }) {
  const STATUS = isDark ? STATUS_D : STATUS_L
  const CBADGE = isDark ? CONNECTOR_BADGE : CONNECTOR_BADGE_L
  const th = {
    card: isDark ? 'bg-navy-900 border border-white/8' : 'bg-white border border-slate-200',
    name: isDark ? 'text-white' : 'text-slate-900',
    meta: isDark ? 'text-slate-400' : 'text-slate-500',
    err: isDark ? 'text-red-400' : 'text-red-600',
  }
  return (
    <div className={`rounded-lg p-4 ${th.card}`}>
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <div className={`font-semibold text-sm ${th.name}`}>{conn.sb_name}</div>
          <div className={`text-xs mt-0.5 ${th.meta}`}>{conn.sb_bank_id}</div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className={`text-[10px] font-bold px-2 py-0.5 rounded ${CBADGE[conn.connector_type] || ''}`}>
            {conn.connector_type}
          </span>
          <span className={`text-[10px] font-bold px-2 py-0.5 rounded border ${
            conn.is_active
              ? (isDark ? 'text-emerald-400 border-emerald-700/50 bg-emerald-900/30' : 'text-emerald-700 border-emerald-300 bg-emerald-50')
              : (isDark ? 'text-red-400 border-red-700/50 bg-red-900/30' : 'text-red-700 border-red-300 bg-red-50')
          }`}>
            {conn.is_active ? 'ACTIVE' : 'DOWN'}
          </span>
        </div>
      </div>
      <div className={`flex gap-4 text-xs ${th.meta}`}>
        <span>{conn.smb_count} SMB{conn.smb_count !== 1 ? 's' : ''}</span>
        {conn.last_test_latency_ms != null && (
          <span>{conn.last_test_latency_ms} ms</span>
        )}
        <span>tested {fmtTime(conn.last_tested_at)}</span>
      </div>
      {conn.error_message && (
        <div className={`mt-2 text-xs ${th.err}`}>{conn.error_message}</div>
      )}
    </div>
  )
}

function SessionRow({ session, isDark }) {
  const STATUS = isDark ? STATUS_D : STATUS_L
  const th = {
    row: isDark ? 'border-white/4 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
    body: isDark ? 'text-slate-300' : 'text-slate-700',
    muted: isDark ? 'text-slate-500' : 'text-slate-400',
    err: isDark ? 'text-red-400' : 'text-red-600',
  }
  return (
    <tr className={`border-b ${th.row} transition-colors`}>
      <td className={`py-2.5 px-3 text-xs font-medium ${th.body}`}>{session.sb_name}</td>
      <td className={`py-2.5 px-3 text-xs ${th.muted}`}>{session.session_type}</td>
      <td className="py-2.5 px-3">
        <span className={`text-[10px] font-bold px-2 py-0.5 rounded border ${STATUS[session.status] || ''}`}>
          {session.status}
        </span>
      </td>
      <td className={`py-2.5 px-3 text-xs tabular-nums text-right ${th.body}`}>
        {session.total_instruments.toLocaleString('en-IN')}
      </td>
      <td className={`py-2.5 px-3 text-xs font-mono ${th.muted}`}>
        {session.sb_reference || '—'}
      </td>
      <td className={`py-2.5 px-3 text-xs ${th.muted}`}>
        {session.submitted_at ? fmtTime(session.submitted_at) : fmtTime(session.opened_at)}
      </td>
      <td className={`py-2.5 px-3 text-xs ${th.err}`}>
        {session.failure_reason || ''}
      </td>
    </tr>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────
export default function CTSAgencyCC() {
  const { isDark } = useTheme()
  const { bankName, bankId } = useBankContext()
  const { setHeader } = usePageHeader?.() ?? { setHeader: () => {} }
  const [activeTab, setActiveTab] = useState(0)

  const th = {
    page:    isDark ? 'bg-navy-950' : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border border-white/8' : 'bg-white border border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    faint:   isDark ? 'text-slate-600' : 'text-slate-400',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    th:      isDark ? 'text-slate-500 border-white/6' : 'text-slate-400 border-slate-100',
    tab:     (active) => active
      ? (isDark ? 'bg-white/8 text-white' : 'bg-slate-100 text-slate-900')
      : (isDark ? 'text-slate-400 hover:text-slate-200' : 'text-slate-500 hover:text-slate-800'),
  }

  const totalInstruments = MOCK_SESSIONS.reduce((s, r) => s + r.total_instruments, 0)
  const submittedSessions = MOCK_SESSIONS.filter(s => s.status === 'SUBMITTED').length
  const exceptionSessions = MOCK_SESSIONS.filter(s => s.status === 'EXCEPTION').length
  const activeSBs = MOCK_SB_CONNECTIONS.filter(c => c.is_active).length

  const TABS = ['SB Connections', 'Clearing Sessions', 'Inward Relay', 'SMB Push Sessions']

  const PUSH_OUTCOME_D = {
    VAULT_UPDATED:     'bg-emerald-900/40 text-emerald-300 border-emerald-700/40',
    PARSE_FAILED:      'bg-red-900/50 text-red-300 border-red-700/40',
    VAULT_UPDATE_FAILED: 'bg-red-900/50 text-red-300 border-red-700/40',
    DUPLICATE_SKIPPED: 'bg-slate-700/30 text-slate-400 border-slate-600/30',
  }
  const PUSH_OUTCOME_L = {
    VAULT_UPDATED:     'bg-emerald-100 text-emerald-700 border-emerald-300',
    PARSE_FAILED:      'bg-red-100 text-red-700 border-red-300',
    VAULT_UPDATE_FAILED: 'bg-red-100 text-red-700 border-red-300',
    DUPLICATE_SKIPPED: 'bg-slate-50 text-slate-500 border-slate-200',
  }
  const PUSH_OUTCOME = isDark ? PUSH_OUTCOME_D : PUSH_OUTCOME_L

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5 space-y-5`}>

        {/* Header */}
        <div className="flex items-start justify-between">
          <div>
            <h1 className={`text-lg font-bold ${th.heading}`}>Agency Command Center</h1>
            <p className={`text-xs mt-0.5 ${th.muted}`}>
              {bankName} · AGENCY_SB_RELAY mode · {MOCK_SB_CONNECTIONS.length} Sponsor Banks configured
            </p>
          </div>
          <div className={`text-xs px-3 py-1.5 rounded border ${
            isDark ? 'bg-violet-900/30 text-violet-300 border-violet-700/40' : 'bg-violet-50 text-violet-700 border-violet-300'
          } font-semibold`}>
            AGENCY_SB_RELAY
          </div>
        </div>

        {/* Stat strip */}
        <div className="grid grid-cols-4 gap-3">
          <StatCard
            label="Active SBs"
            value={activeSBs}
            sub={`of ${MOCK_SB_CONNECTIONS.length} configured`}
            accent={activeSBs < MOCK_SB_CONNECTIONS.length ? (isDark ? 'text-amber-400' : 'text-amber-600') : undefined}
            isDark={isDark}
          />
          <StatCard
            label="Today's Instruments"
            value={totalInstruments.toLocaleString('en-IN')}
            sub="across all SBs"
            isDark={isDark}
          />
          <StatCard
            label="Sessions Submitted"
            value={submittedSessions}
            sub={`of ${MOCK_SESSIONS.length} sessions today`}
            accent={isDark ? 'text-emerald-400' : 'text-emerald-600'}
            isDark={isDark}
          />
          <StatCard
            label="Exceptions"
            value={exceptionSessions}
            sub="require manual action"
            accent={exceptionSessions > 0 ? (isDark ? 'text-red-400' : 'text-red-600') : undefined}
            isDark={isDark}
          />
        </div>

        {/* Exception banner */}
        {exceptionSessions > 0 && (
          <div className={`rounded-lg px-4 py-3 flex items-center gap-3 border ${
            isDark ? 'bg-red-950/50 border-red-800/40' : 'bg-red-50 border-red-200'
          }`}>
            <span className="text-base">⚠</span>
            <div>
              <span className={`text-sm font-semibold ${isDark ? 'text-red-300' : 'text-red-700'}`}>
                {exceptionSessions} clearing session{exceptionSessions > 1 ? 's' : ''} failed SB submission
              </span>
              <span className={`text-xs ml-2 ${isDark ? 'text-red-400' : 'text-red-600'}`}>
                Check SB connection health and retry manually
              </span>
            </div>
          </div>
        )}

        {/* Tabs */}
        <div className={`flex gap-1 border-b ${th.divider}`}>
          {TABS.map((tab, i) => (
            <button
              key={tab}
              onClick={() => setActiveTab(i)}
              className={`px-4 py-2 text-xs font-semibold rounded-t transition-colors ${th.tab(activeTab === i)}`}
            >
              {tab}
            </button>
          ))}
        </div>

        {/* Tab 0 — SB Connections */}
        {activeTab === 0 && (
          <div className="space-y-3">
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {MOCK_SB_CONNECTIONS.map(conn => (
                <SBConnectionCard key={conn.sb_connection_id} conn={conn} isDark={isDark} />
              ))}
            </div>
            <div className={`text-xs ${th.faint} mt-2`}>
              Connector types: SFTP_GENERIC — file-drop SFTP · BANCS_API — TCS BaNCS REST · NELITO_API — Nelito FinNext REST
            </div>
          </div>
        )}

        {/* Tab 1 — Clearing Sessions */}
        {activeTab === 1 && (
          <div className={`rounded-lg border ${th.card}`}>
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className={`border-b ${th.th}`}>
                    {['Sponsor Bank', 'Session', 'Status', 'Instruments', 'SB Reference', 'Time', 'Failure'].map(h => (
                      <th key={h} className={`py-2.5 px-3 text-[10px] font-bold uppercase tracking-wider ${th.th}`}>
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {MOCK_SESSIONS.map(session => (
                    <SessionRow key={session.session_id} session={session} isDark={isDark} />
                  ))}
                </tbody>
              </table>
            </div>
            {MOCK_SESSIONS.length === 0 && (
              <div className={`py-10 text-center text-sm ${th.muted}`}>No clearing sessions today yet</div>
            )}
          </div>
        )}

        {/* Tab 2 — Inward Relay */}
        {activeTab === 2 && (
          <div className="grid grid-cols-2 gap-4">
            <div className={`rounded-lg p-5 ${th.card} space-y-4`}>
              <div className={`text-xs font-bold uppercase tracking-wider ${th.muted}`}>Relay Summary — Today</div>
              <div className="space-y-3">
                <div className="flex justify-between">
                  <span className={`text-sm ${th.body}`}>Total received from SBs</span>
                  <span className={`text-sm font-bold tabular-nums ${th.heading}`}>
                    {MOCK_INWARD_STATS.total_received.toLocaleString('en-IN')}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className={`text-sm ${th.body}`}>Routed to PUs</span>
                  <span className={`text-sm font-bold tabular-nums ${isDark ? 'text-emerald-400' : 'text-emerald-700'}`}>
                    {MOCK_INWARD_STATS.routed.toLocaleString('en-IN')}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className={`text-sm ${th.body}`}>CRL misses</span>
                  <span className={`text-sm font-bold tabular-nums ${MOCK_INWARD_STATS.crl_misses > 0 ? (isDark ? 'text-amber-400' : 'text-amber-700') : (isDark ? 'text-slate-400' : 'text-slate-500')}`}>
                    {MOCK_INWARD_STATS.crl_misses}
                  </span>
                </div>
                <div className={`pt-2 border-t ${th.divider} flex justify-between`}>
                  <span className={`text-xs ${th.muted}`}>Last relay</span>
                  <span className={`text-xs font-mono ${th.muted}`}>{fmtTime(MOCK_INWARD_STATS.last_relay_at)}</span>
                </div>
              </div>
            </div>

            <div className={`rounded-lg p-5 ${th.card}`}>
              <div className={`text-xs font-bold uppercase tracking-wider ${th.muted} mb-4`}>IET Note</div>
              <p className={`text-sm ${th.body} leading-relaxed`}>
                Inward instruments forwarded by SBs carry their <strong className={th.heading}>original NGCH timestamp</strong> (the moment the SB's member bank filed with NGCH). ASTRA's IET countdown starts from that timestamp, not from relay receipt.
              </p>
              <p className={`text-sm ${th.body} leading-relaxed mt-3`}>
                CRL misses are routed to <strong className={th.heading}>HUMAN_REVIEW</strong> immediately — never auto-returned.
              </p>
              <div className={`mt-4 px-3 py-2 rounded text-xs font-semibold ${isDark ? 'bg-red-950/40 text-red-300 border border-red-800/40' : 'bg-red-50 text-red-700 border border-red-200'}`}>
                IET breach rate target: 0.000%
              </div>
            </div>
          </div>
        )}

        {/* Tab 3 — SMB Push Sessions */}
        {activeTab === 3 && (
          <div className="space-y-3">
            <p className={`text-xs ${th.muted}`}>
              SMB CBS batch files (stop payments, PPS, signatures) received via SFTP every 15 min.
              Each file is deduplicated by SHA-256 hash before vault update.
            </p>
            <div className={`rounded-lg border ${th.card}`}>
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className={`border-b ${th.th}`}>
                      {['SMB', 'File Type', 'Outcome', 'Records', 'Received', 'Failure'].map(h => (
                        <th key={h} className={`py-2.5 px-3 text-[10px] font-bold uppercase tracking-wider ${th.th}`}>
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {MOCK_PUSH_SESSIONS.map(s => (
                      <tr key={s.id} className={`border-b ${th.row} transition-colors`}>
                        <td className={`py-2.5 px-3 text-xs font-medium ${th.body}`}>{s.smb_name}</td>
                        <td className={`py-2.5 px-3 text-xs font-mono ${th.muted}`}>{s.file_type}</td>
                        <td className="py-2.5 px-3">
                          <span className={`text-[10px] font-bold px-2 py-0.5 rounded border ${PUSH_OUTCOME[s.outcome] || ''}`}>
                            {s.outcome}
                          </span>
                        </td>
                        <td className={`py-2.5 px-3 text-xs tabular-nums text-right ${th.body}`}>
                          {s.records_processed}
                        </td>
                        <td className={`py-2.5 px-3 text-xs ${th.muted}`}>{fmtTime(s.received_at)}</td>
                        <td className={`py-2.5 px-3 text-xs ${isDark ? 'text-red-400' : 'text-red-600'}`}>
                          {s.failure_reason || ''}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <div className={`text-xs ${th.faint}`}>
              No software deployed at SMB premises — SMBs configure their CBS batch export to push CSV files to Agency SFTP. File format: Finacle CSV · BaNCS fixed-width · generic CSV (auto-detected).
            </div>
          </div>
        )}

      </div>
    </AppShell>
  )
}

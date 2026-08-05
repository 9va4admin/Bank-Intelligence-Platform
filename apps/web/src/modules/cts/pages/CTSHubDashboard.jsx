/**
 * Hub Manager Dashboard — /cts/hub
 *
 * SB-only view for the Processing Hub Manager:
 *   - All branch sessions for today's clearing
 *   - Per-branch: connection status, scan counts, current lot fill
 *   - Seal individual lots (Hub Manager action — branch operators cannot do this)
 *   - Seal All Open Lots for clearing window close
 *   - Clearing window countdown + NGCH submission readiness
 *
 * Session lifecycle: sessions auto-open on first scan; Hub Manager seals lots
 * and triggers ClearingSessionWorkflow at window close. No manual session
 * management required from branches.
 */
import { useState, useEffect } from 'react'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'
import AppShell from '../../../shared/layout/AppShell'

// ─── Mock data ────────────────────────────────────────────────────────────────

const CLEARING_WINDOW = {
  session_type: 'MORNING',
  window_open:  '09:00',
  window_close: '12:30',
  ngch_cutoff:  '12:00',
  status: 'ACTIVE',   // UPCOMING | ACTIVE | CLOSING | CLOSED
  close_ts: new Date().setHours(12, 30, 0, 0),
}

const BRANCHES_MOCK = [
  {
    branch_id: 'BRANCH-ANDHERI-01',
    branch_name: 'Andheri (W) Branch',
    hub_type: 'EEH',
    eeh_status: 'CONNECTED',
    eeh_latency_ms: 11,
    session: {
      session_id: 'sess-a01-0731',
      status: 'ACTIVE',
      opened_at: '2026-07-31T09:14:32Z',
      total_uploaded: 247,
      total_accepted: 241,
      total_rejected: 4,
      total_held: 2,
    },
    current_lot: { lot_id: 'LOT-AN01-0007', filled: 18, max: 25, status: 'OPEN' },
    lots_sealed_today: 6,
  },
  {
    branch_id: 'BRANCH-BANDRA-01',
    branch_name: 'Bandra (E) Branch',
    hub_type: 'EEH',
    eeh_status: 'CONNECTED',
    eeh_latency_ms: 8,
    session: {
      session_id: 'sess-b01-0731',
      status: 'ACTIVE',
      opened_at: '2026-07-31T09:22:11Z',
      total_uploaded: 193,
      total_accepted: 190,
      total_rejected: 3,
      total_held: 0,
    },
    current_lot: { lot_id: 'LOT-BA01-0008', filled: 25, max: 25, status: 'OPEN' },
    lots_sealed_today: 7,
  },
  {
    branch_id: 'BRANCH-CHURCH-01',
    branch_name: 'Churchgate Branch',
    hub_type: 'IEH',
    eeh_status: 'CONNECTED',
    eeh_latency_ms: 3,
    session: {
      session_id: 'sess-c01-0731',
      status: 'ACTIVE',
      opened_at: '2026-07-31T09:08:44Z',
      total_uploaded: 312,
      total_accepted: 308,
      total_rejected: 2,
      total_held: 2,
    },
    current_lot: { lot_id: 'LOT-CH01-0013', filled: 9, max: 25, status: 'OPEN' },
    lots_sealed_today: 12,
  },
  {
    branch_id: 'BRANCH-DADAR-01',
    branch_name: 'Dadar Branch',
    hub_type: 'EEH',
    eeh_status: 'CONNECTED',
    eeh_latency_ms: 14,
    session: {
      session_id: 'sess-d01-0731',
      status: 'ACTIVE',
      opened_at: '2026-07-31T09:31:55Z',
      total_uploaded: 88,
      total_accepted: 86,
      total_rejected: 2,
      total_held: 0,
    },
    current_lot: { lot_id: 'LOT-DA01-0004', filled: 13, max: 25, status: 'OPEN' },
    lots_sealed_today: 3,
  },
  {
    branch_id: 'BRANCH-GORE-01',
    branch_name: 'Goregaon Branch',
    hub_type: 'EEH',
    eeh_status: 'WARN',
    eeh_latency_ms: 210,
    session: {
      session_id: 'sess-g01-0731',
      status: 'ACTIVE',
      opened_at: '2026-07-31T09:44:19Z',
      total_uploaded: 41,
      total_accepted: 39,
      total_rejected: 1,
      total_held: 1,
    },
    current_lot: { lot_id: 'LOT-GO01-0002', filled: 16, max: 25, status: 'OPEN' },
    lots_sealed_today: 1,
  },
  {
    branch_id: 'BRANCH-KURLA-01',
    branch_name: 'Kurla Branch',
    hub_type: 'EEH',
    eeh_status: 'DISCONNECTED',
    eeh_latency_ms: null,
    session: null,   // no session — EEH disconnected, no scan yet
    current_lot: null,
    lots_sealed_today: 0,
  },
  {
    branch_id: 'BRANCH-MALAD-01',
    branch_name: 'Malad Branch',
    hub_type: 'EEH',
    eeh_status: 'CONNECTED',
    eeh_latency_ms: 19,
    session: null,   // connected but no scan yet today
    current_lot: null,
    lots_sealed_today: 0,
  },
  {
    branch_id: 'BRANCH-VASHI-01',
    branch_name: 'Vashi Branch',
    hub_type: 'EEH',
    eeh_status: 'CONNECTED',
    eeh_latency_ms: 27,
    session: {
      session_id: 'sess-v01-0731',
      status: 'ACTIVE',
      opened_at: '2026-07-31T09:19:08Z',
      total_uploaded: 156,
      total_accepted: 153,
      total_rejected: 2,
      total_held: 1,
    },
    current_lot: { lot_id: 'LOT-VA01-0007', filled: 22, max: 25, status: 'OPEN' },
    lots_sealed_today: 6,
  },
]

// ─── Helpers ──────────────────────────────────────────────────────────────────

function windowCountdown(closeTs) {
  const now = Date.now()
  const diff = Math.max(0, Math.floor((closeTs - now) / 1000))
  const h = Math.floor(diff / 3600)
  const m = Math.floor((diff % 3600) / 60)
  const s = diff % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

function eehDot(status) {
  if (status === 'CONNECTED') return 'bg-emerald-400'
  if (status === 'WARN')      return 'bg-amber-400'
  return 'bg-red-400'
}

function eehLabel(status, latency) {
  if (status === 'CONNECTED') return `Connected · ${latency}ms`
  if (status === 'WARN')      return `High latency · ${latency}ms`
  return 'Disconnected'
}

function LotBar({ filled, max, isDark }) {
  const pct = Math.min(100, Math.round((filled / max) * 100))
  const full = pct === 100
  const trackCls = isDark ? 'bg-white/10' : 'bg-slate-100'
  const fillCls  = full ? 'bg-amber-400' : 'bg-blue-500'
  return (
    <div className="flex items-center gap-2 min-w-0">
      <div className={`flex-1 h-1.5 rounded-full overflow-hidden ${trackCls}`}>
        <div className={`h-full rounded-full ${fillCls}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs tabular-nums shrink-0">{filled}/{max}</span>
    </div>
  )
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function SummaryCard({ label, value, accent, sub, isDark }) {
  const th = {
    card:  isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    label: isDark ? 'text-slate-400' : 'text-slate-500',
    sub:   isDark ? 'text-slate-500' : 'text-slate-400',
  }
  return (
    <div className={`rounded-lg border p-4 ${th.card}`}>
      <p className={`text-xs font-medium uppercase tracking-wider ${th.label}`}>{label}</p>
      <p className={`mt-1 text-2xl font-bold tabular-nums ${accent}`}>{value}</p>
      {sub && <p className={`mt-0.5 text-xs ${th.sub}`}>{sub}</p>}
    </div>
  )
}

function BranchRow({ branch, onSealLot, isDark }) {
  const { session, current_lot: lot } = branch
  const hasSession = session !== null
  const th = {
    row:     isDark ? 'border-white/5 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
  }

  const sessionLabel = !hasSession
    ? 'No scan yet'
    : `Auto-started ${session.opened_at.slice(11, 16)}`

  const sessionColor = !hasSession
    ? (isDark ? 'text-slate-500' : 'text-slate-400')
    : 'text-emerald-400'

  const lotFull = lot && lot.filled >= lot.max

  return (
    <tr className={`border-b text-sm transition-colors ${th.row}`}>
      {/* Branch */}
      <td className="py-3 px-4">
        <p className={`font-medium ${th.heading}`}>{branch.branch_name}</p>
        <p className={`text-xs mt-0.5 ${th.muted}`}>{branch.hub_type} · {branch.branch_id.slice(-6)}</p>
      </td>

      {/* EEH connection */}
      <td className="py-3 px-4 whitespace-nowrap">
        <span className="flex items-center gap-1.5">
          <span className={`inline-block w-2 h-2 rounded-full ${eehDot(branch.eeh_status)}`} />
          <span className={`text-xs ${th.muted}`}>{eehLabel(branch.eeh_status, branch.eeh_latency_ms)}</span>
        </span>
      </td>

      {/* Session */}
      <td className="py-3 px-4 whitespace-nowrap">
        <span className={`text-xs font-medium ${sessionColor}`}>{sessionLabel}</span>
      </td>

      {/* Scans */}
      <td className="py-3 px-4">
        {hasSession ? (
          <div className="flex gap-3 text-xs tabular-nums">
            <span className={th.body}>{session.total_uploaded} up</span>
            <span className="text-emerald-400">{session.total_accepted} ok</span>
            {session.total_rejected > 0 && <span className="text-red-400">{session.total_rejected} rej</span>}
            {session.total_held > 0 && <span className="text-amber-400">{session.total_held} held</span>}
          </div>
        ) : (
          <span className={`text-xs ${th.muted}`}>—</span>
        )}
      </td>

      {/* Current lot fill */}
      <td className="py-3 px-4 min-w-[160px]">
        {lot ? (
          <div>
            <p className={`text-xs font-mono mb-1 ${th.muted}`}>{lot.lot_id.slice(-10)}</p>
            <LotBar filled={lot.filled} max={lot.max} isDark={isDark} />
          </div>
        ) : (
          <span className={`text-xs ${th.muted}`}>—</span>
        )}
      </td>

      {/* Lots sealed */}
      <td className="py-3 px-4 text-center">
        <span className={`text-sm tabular-nums ${branch.lots_sealed_today > 0 ? (isDark ? 'text-slate-300' : 'text-slate-700') : th.muted}`}>
          {branch.lots_sealed_today}
        </span>
      </td>

      {/* Action */}
      <td className="py-3 px-4">
        {lot ? (
          <button
            onClick={() => onSealLot(branch, lot)}
            className={`text-xs px-3 py-1.5 rounded font-medium transition-colors ${
              lotFull
                ? 'bg-amber-500 hover:bg-amber-600 text-white'
                : 'bg-blue-600 hover:bg-blue-700 text-white'
            }`}
          >
            {lotFull ? 'Seal Full Lot' : 'Seal Lot'}
          </button>
        ) : (
          <span className={`text-xs ${th.muted}`}>—</span>
        )}
      </td>
    </tr>
  )
}

// ─── Seal confirmation modal ──────────────────────────────────────────────────

function SealConfirmModal({ branch, lot, onConfirm, onCancel, isDark }) {
  const th = {
    overlay: 'fixed inset-0 bg-black/60 flex items-center justify-center z-50',
    modal:   isDark ? 'bg-navy-900 border-white/10' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
  }
  return (
    <div className={th.overlay} onClick={onCancel}>
      <div
        className={`rounded-xl border p-6 w-full max-w-md shadow-2xl ${th.modal}`}
        onClick={e => e.stopPropagation()}
      >
        <h2 className={`text-base font-semibold mb-1 ${th.heading}`}>Seal Lot</h2>
        <p className={`text-sm mb-4 ${th.body}`}>
          Seal <span className="font-mono text-blue-400">{lot.lot_id}</span> from{' '}
          <span className="font-medium">{branch.branch_name}</span>?
          Once sealed, no further instruments can be added. The lot will be included
          in the next NGCH submission.
        </p>
        <div className={`text-xs mb-5 ${th.muted}`}>
          {lot.filled} / {lot.max} instruments · Status: {lot.status}
        </div>
        <div className="flex gap-3 justify-end">
          <button
            onClick={onCancel}
            className={`px-4 py-2 text-sm rounded border ${isDark ? 'border-white/15 text-slate-300 hover:bg-white/5' : 'border-slate-200 text-slate-600 hover:bg-slate-50'} transition-colors`}
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="px-4 py-2 text-sm rounded bg-blue-600 hover:bg-blue-700 text-white font-medium transition-colors"
          >
            Confirm Seal
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function CTSHubDashboard() {
  const { isDark } = useTheme()
  const { bankId, bankName, isDemo } = useBankContext()
  const [branches, setBranches] = useState(isDemo ? BRANCHES_MOCK : [])
  const [countdown, setCountdown] = useState(windowCountdown(CLEARING_WINDOW.close_ts))
  const [sealTarget, setSealTarget] = useState(null)   // { branch, lot }
  const [sealAllPending, setSealAllPending] = useState(false)
  const [toast, setToast] = useState(null)

  // Live countdown
  useEffect(() => {
    const t = setInterval(() => setCountdown(windowCountdown(CLEARING_WINDOW.close_ts)), 1000)
    return () => clearInterval(t)
  }, [])

  // Auto-clear toast
  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 3500)
    return () => clearTimeout(t)
  }, [toast])

  const th = {
    page:    isDark ? 'bg-navy-950'              : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'               : 'text-slate-900',
    body:    isDark ? 'text-slate-300'           : 'text-slate-700',
    muted:   isDark ? 'text-slate-400'           : 'text-slate-500',
    divider: isDark ? 'border-white/8'           : 'border-slate-200',
    thead:   isDark ? 'bg-white/3 border-white/6': 'bg-slate-50 border-slate-200',
    theadTx: isDark ? 'text-slate-400'           : 'text-slate-500',
  }

  // Derived stats
  const activeBranches  = branches.filter(b => b.session?.status === 'ACTIVE').length
  const noSessionCount  = branches.filter(b => !b.session).length
  const totalUploaded   = branches.reduce((s, b) => s + (b.session?.total_uploaded ?? 0), 0)
  const totalHeld       = branches.reduce((s, b) => s + (b.session?.total_held ?? 0), 0)
  const totalSealed     = branches.reduce((s, b) => s + b.lots_sealed_today, 0)
  const openLots        = branches.filter(b => b.current_lot?.status === 'OPEN')

  function handleSealLot(branch, lot) {
    setSealTarget({ branch, lot })
  }

  function confirmSeal() {
    const { branch, lot } = sealTarget
    setBranches(prev => prev.map(b =>
      b.branch_id !== branch.branch_id ? b : {
        ...b,
        current_lot: null,
        lots_sealed_today: b.lots_sealed_today + 1,
      }
    ))
    setToast(`Lot ${lot.lot_id.slice(-10)} sealed — ${branch.branch_name}`)
    setSealTarget(null)
  }

  function handleSealAll() {
    setSealAllPending(true)
  }

  function confirmSealAll() {
    setBranches(prev => prev.map(b => ({
      ...b,
      lots_sealed_today: b.lots_sealed_today + (b.current_lot ? 1 : 0),
      current_lot: null,
    })))
    setToast(`All ${openLots.length} open lots sealed — ready for NGCH submission`)
    setSealAllPending(false)
  }

  const windowStatusColor = CLEARING_WINDOW.status === 'ACTIVE'
    ? 'text-emerald-400' : CLEARING_WINDOW.status === 'CLOSING' ? 'text-amber-400' : th.muted

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>

        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>Hub Manager</h1>
            <p className={`text-sm ${th.muted}`}>{bankName} · {new Date().toLocaleDateString('en-IN', { dateStyle: 'long' })}</p>
          </div>

          {/* Clearing window badge */}
          <div className={`rounded-lg border px-4 py-2.5 flex items-center gap-4 ${th.card}`}>
            <div>
              <p className={`text-xs font-medium uppercase tracking-wider ${th.muted}`}>Clearing Window</p>
              <p className={`text-sm font-semibold ${windowStatusColor}`}>
                {CLEARING_WINDOW.session_type} · {CLEARING_WINDOW.window_open}–{CLEARING_WINDOW.window_close}
              </p>
            </div>
            <div className="text-right">
              <p className={`text-xs ${th.muted}`}>Window closes in</p>
              <p className={`text-lg font-mono font-bold tabular-nums ${th.heading}`}>{countdown}</p>
            </div>
          </div>
        </div>

        {/* Summary cards */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-5">
          <SummaryCard
            label="Branches Active"
            value={activeBranches}
            accent={isDark ? 'text-emerald-400' : 'text-emerald-600'}
            sub={`${noSessionCount} not yet started`}
            isDark={isDark}
          />
          <SummaryCard
            label="Total Uploaded"
            value={totalUploaded.toLocaleString('en-IN')}
            accent={isDark ? 'text-white' : 'text-slate-900'}
            sub="instruments today"
            isDark={isDark}
          />
          <SummaryCard
            label="On Hold"
            value={totalHeld}
            accent={totalHeld > 0 ? 'text-amber-400' : (isDark ? 'text-slate-400' : 'text-slate-500')}
            sub="pending resolution"
            isDark={isDark}
          />
          <SummaryCard
            label="Lots Sealed"
            value={totalSealed}
            accent={isDark ? 'text-blue-400' : 'text-blue-600'}
            sub="across all branches"
            isDark={isDark}
          />
          <SummaryCard
            label="Open Lots"
            value={openLots.length}
            accent={openLots.length > 0 ? 'text-amber-400' : (isDark ? 'text-slate-400' : 'text-slate-500')}
            sub="awaiting seal"
            isDark={isDark}
          />
        </div>

        {/* Branch session table */}
        <div className={`rounded-lg border overflow-hidden mb-5 ${th.card}`}>
          <div className={`flex items-center justify-between px-4 py-3 border-b ${th.divider}`}>
            <h2 className={`text-sm font-semibold ${th.heading}`}>Branch Sessions — Today</h2>
            {openLots.length > 0 && (
              <button
                onClick={handleSealAll}
                className="text-xs px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded font-medium transition-colors"
              >
                Seal All Open Lots ({openLots.length})
              </button>
            )}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className={`text-xs font-medium uppercase tracking-wider border-b ${th.thead} ${th.theadTx}`}>
                  <th className="py-2.5 px-4 text-left">Branch</th>
                  <th className="py-2.5 px-4 text-left">EEH / IEH</th>
                  <th className="py-2.5 px-4 text-left">Session</th>
                  <th className="py-2.5 px-4 text-left">Scans Today</th>
                  <th className="py-2.5 px-4 text-left">Current Lot</th>
                  <th className="py-2.5 px-4 text-center">Sealed</th>
                  <th className="py-2.5 px-4 text-left">Action</th>
                </tr>
              </thead>
              <tbody>
                {branches.map(branch => (
                  <BranchRow
                    key={branch.branch_id}
                    branch={branch}
                    onSealLot={handleSealLot}
                    isDark={isDark}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* NGCH readiness strip */}
        <div className={`rounded-lg border px-4 py-3 flex items-center justify-between ${th.card}`}>
          <div>
            <p className={`text-xs font-medium uppercase tracking-wider ${th.muted}`}>NGCH Submission Readiness</p>
            <p className={`text-sm mt-0.5 ${th.body}`}>
              {openLots.length > 0
                ? `${openLots.length} open lot${openLots.length > 1 ? 's' : ''} must be sealed before submission`
                : 'All lots sealed — ready to trigger ClearingSessionWorkflow'
              }
            </p>
          </div>
          <button
            disabled={openLots.length > 0}
            className={`text-xs px-4 py-2 rounded font-medium transition-colors ${
              openLots.length > 0
                ? (isDark ? 'bg-white/5 text-slate-500 cursor-not-allowed' : 'bg-slate-100 text-slate-400 cursor-not-allowed')
                : 'bg-emerald-600 hover:bg-emerald-700 text-white'
            }`}
          >
            Submit to NGCH
          </button>
        </div>

      </div>

      {/* Seal single lot modal */}
      {sealTarget && (
        <SealConfirmModal
          branch={sealTarget.branch}
          lot={sealTarget.lot}
          onConfirm={confirmSeal}
          onCancel={() => setSealTarget(null)}
          isDark={isDark}
        />
      )}

      {/* Seal all lots modal */}
      {sealAllPending && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setSealAllPending(false)}>
          <div
            className={`rounded-xl border p-6 w-full max-w-md shadow-2xl ${th.card}`}
            onClick={e => e.stopPropagation()}
          >
            <h2 className={`text-base font-semibold mb-1 ${th.heading}`}>Seal All Open Lots</h2>
            <p className={`text-sm mb-4 ${th.body}`}>
              Seal all <span className="font-bold text-blue-400">{openLots.length}</span> open lots across{' '}
              {openLots.length} branches? This marks the end of the{' '}
              <span className="font-medium">{CLEARING_WINDOW.session_type}</span> clearing window
              and prepares the batch for NGCH submission.
            </p>
            <p className={`text-xs mb-5 ${th.muted}`}>
              Branches: {openLots.map(b => b.branch_name.split(' ')[0]).join(', ')}
            </p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setSealAllPending(false)}
                className={`px-4 py-2 text-sm rounded border ${isDark ? 'border-white/15 text-slate-300 hover:bg-white/5' : 'border-slate-200 text-slate-600 hover:bg-slate-50'} transition-colors`}
              >
                Cancel
              </button>
              <button
                onClick={confirmSealAll}
                className="px-4 py-2 text-sm rounded bg-blue-600 hover:bg-blue-700 text-white font-medium transition-colors"
              >
                Seal All &amp; Proceed
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50">
          <div className="bg-emerald-600 text-white text-sm px-5 py-2.5 rounded-full shadow-lg font-medium">
            ✓ {toast}
          </div>
        </div>
      )}

    </AppShell>
  )
}

/**
 * CTSHoldQueue — Ops Manager view of all inward instruments on hold.
 *
 * Route: /cts/hold-queue  (permission: cts:view_queue)
 * Role:  ops_manager, ops_reviewer
 *
 * Shows:
 *  - All instruments currently on hold with IET countdown (clock never pauses)
 *  - Hold duration, held_by, hold_reason, branch_recommendation
 *  - Release Hold button → returns instrument to review queue
 *  - CRITICAL: IET countdown shown in red when < 30 minutes remaining
 */
import { useState, useEffect } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'

// ─── Demo data ────────────────────────────────────────────────────────────────

const _now = () => Date.now() / 1000

const DEMO_HOLDS = [
  {
    instrument_id:          'INST-2026-001847',
    bank_id:                'saraswat-coop',
    held_by:                'reviewer.priya@saraswat',
    held_at:                _now() - 18 * 60,        // held 18 min ago
    iet_deadline:           _now() + 42 * 60,        // 42 min remaining
    hold_reason:            'Signature looks different from CBS record — branch asked to confirm drawer identity',
    branch_notified_at:     _now() - 17 * 60,
    branch_recommendation:  null,
    amount_display:         '₹[1L–5L]',
    payee_display:          'R***',
    account_display:        '****4521',
    queue_tier:             'high_value',
  },
  {
    instrument_id:          'INST-2026-001855',
    bank_id:                'saraswat-coop',
    held_by:                'reviewer.rahul@saraswat',
    held_at:                _now() - 5 * 60,
    iet_deadline:           _now() + 22 * 60,        // 22 min — approaching IET
    hold_reason:            'Account shows stop payment in CBS but customer claims it was cancelled — branch verifying',
    branch_notified_at:     _now() - 4.5 * 60,
    branch_recommendation:  'RETURN',
    amount_display:         '₹[<1L]',
    payee_display:          'M***',
    account_display:        '****8812',
    queue_tier:             'standard',
  },
  {
    instrument_id:          'INST-2026-001862',
    bank_id:                'saraswat-coop',
    held_by:                'reviewer.anita@saraswat',
    held_at:                _now() - 45 * 60,
    iet_deadline:           _now() + 105 * 60,
    hold_reason:            'High-value instrument — branch manager sign-off required per policy',
    branch_notified_at:     _now() - 44 * 60,
    branch_recommendation:  'CONFIRM',
    amount_display:         '₹[>1Cr]',
    payee_display:          'A***',
    account_display:        '****0071',
    queue_tier:             'very_high',
  },
]

// ─── IET Countdown ────────────────────────────────────────────────────────────

function useCountdown(deadlines) {
  const [remaining, setRemaining] = useState(() =>
    Object.fromEntries(deadlines.map(([id, d]) => [id, Math.max(0, d - _now())]))
  )
  useEffect(() => {
    const t = setInterval(() => {
      setRemaining(Object.fromEntries(deadlines.map(([id, d]) => [id, Math.max(0, d - _now())])))
    }, 1000)
    return () => clearInterval(t)
  }, [deadlines])
  return remaining
}

function fmtCountdown(secs) {
  if (secs <= 0) return 'EXPIRED'
  const m = Math.floor(secs / 60)
  const s = Math.floor(secs % 60)
  return `${m}m ${String(s).padStart(2, '0')}s`
}

function countdownColor(secs, isDark) {
  if (secs <= 0)        return 'text-red-500 font-bold'
  if (secs <= 30 * 60) return 'text-red-400 font-semibold'
  if (secs <= 60 * 60) return 'text-amber-400 font-semibold'
  return isDark ? 'text-emerald-400' : 'text-emerald-600'
}

// ─── Tier badge ───────────────────────────────────────────────────────────────

const TIER_BADGE = {
  standard:   'bg-slate-700/60 text-slate-300 border-slate-600/40',
  high_value: 'bg-amber-900/50 text-amber-300 border-amber-700/40',
  very_high:  'bg-red-900/50 text-red-300 border-red-700/40',
}
const TIER_BADGE_L = {
  standard:   'bg-slate-100 text-slate-600 border-slate-300',
  high_value: 'bg-amber-50 text-amber-700 border-amber-200',
  very_high:  'bg-red-50 text-red-700 border-red-200',
}
const TIER_LABEL = { standard: 'Standard', high_value: 'High Value', very_high: 'Very High' }

// ─── Recommendation badge ─────────────────────────────────────────────────────

function RecBadge({ rec, isDark }) {
  if (!rec) return <span className={isDark ? 'text-slate-500 text-xs' : 'text-slate-400 text-xs'}>Awaiting…</span>
  const cls = rec === 'CONFIRM'
    ? (isDark ? 'bg-emerald-900/50 text-emerald-300 border-emerald-700/40' : 'bg-emerald-50 text-emerald-700 border-emerald-200')
    : (isDark ? 'bg-red-900/50 text-red-300 border-red-700/40' : 'bg-red-50 text-red-700 border-red-200')
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded border ${cls}`}>
      Branch: {rec}
    </span>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function CTSHoldQueue() {
  const { isDark } = useTheme()
  const { bankId, bankName, hasPermission } = useBankContext()
  const { setHeader } = usePageHeader?.() ?? {}

  useEffect(() => {
    setHeader?.({ title: 'Inward Hold Queue', subtitle: 'Instruments awaiting branch confirmation — IET clock running' })
  }, [])

  const [holds, setHolds] = useState(DEMO_HOLDS)
  const [releasing, setReleasing] = useState(null)

  const deadlines = holds.map(h => [h.instrument_id, h.iet_deadline])
  const remaining = useCountdown(deadlines)

  const th = {
    page:    isDark ? 'bg-navy-950'        : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'         : 'text-slate-900',
    body:    isDark ? 'text-slate-300'     : 'text-slate-700',
    muted:   isDark ? 'text-slate-400'     : 'text-slate-500',
    faint:   isDark ? 'text-slate-600'     : 'text-slate-400',
    divider: isDark ? 'border-white/8'     : 'border-slate-200',
    row:     isDark ? 'border-white/4 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
    input:   isDark ? 'bg-white/5 border-white/10 text-white placeholder-slate-500' : 'bg-white border-slate-200 text-slate-900 placeholder-slate-400',
  }

  function releaseHold(instrumentId) {
    setReleasing(instrumentId)
    setTimeout(() => {
      setHolds(prev => prev.filter(h => h.instrument_id !== instrumentId))
      setReleasing(null)
    }, 800)
  }

  const sortedHolds = [...holds].sort((a, b) => remaining[a.instrument_id] - remaining[b.instrument_id])

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>Inward Hold Queue</h1>
            <p className={`text-xs mt-0.5 ${th.muted}`}>
              {holds.length} instrument{holds.length !== 1 ? 's' : ''} on hold — IET countdown active on all
            </p>
          </div>
          <div className={`text-xs px-3 py-1 rounded-full border ${isDark ? 'border-amber-700/40 bg-amber-900/30 text-amber-300' : 'border-amber-200 bg-amber-50 text-amber-700'}`}>
            IET clock never pauses during hold
          </div>
        </div>

        {holds.length === 0 ? (
          <div className={`text-center py-16 ${th.muted}`}>
            No instruments currently on hold.
          </div>
        ) : (
          <div className="space-y-3">
            {sortedHolds.map(hold => {
              const secs = remaining[hold.instrument_id] ?? 0
              const tierBadge = isDark ? TIER_BADGE[hold.queue_tier] : TIER_BADGE_L[hold.queue_tier]
              return (
                <div
                  key={hold.instrument_id}
                  className={`rounded-xl border p-4 ${th.card}`}
                >
                  {/* Top row */}
                  <div className="flex items-start justify-between gap-4 flex-wrap">
                    <div className="flex items-center gap-3 flex-wrap">
                      <span className={`font-mono text-sm font-semibold ${th.heading}`}>
                        {hold.instrument_id}
                      </span>
                      <span className={`text-xs px-2 py-0.5 rounded border font-medium ${tierBadge}`}>
                        {TIER_LABEL[hold.queue_tier]}
                      </span>
                      <RecBadge rec={hold.branch_recommendation} isDark={isDark} />
                    </div>
                    {/* IET countdown */}
                    <div className="flex items-center gap-2">
                      <span className={`text-xs ${th.muted}`}>IET</span>
                      <span className={`font-mono text-sm tabular-nums ${countdownColor(secs, isDark)}`}>
                        {fmtCountdown(secs)}
                      </span>
                    </div>
                  </div>

                  {/* Details row */}
                  <div className={`mt-3 grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs ${th.muted}`}>
                    <div>
                      <div className={`uppercase tracking-wide text-[10px] mb-0.5 ${th.faint}`}>Account</div>
                      <div className={`font-mono ${th.body}`}>{hold.account_display}</div>
                    </div>
                    <div>
                      <div className={`uppercase tracking-wide text-[10px] mb-0.5 ${th.faint}`}>Amount</div>
                      <div className={th.body}>{hold.amount_display}</div>
                    </div>
                    <div>
                      <div className={`uppercase tracking-wide text-[10px] mb-0.5 ${th.faint}`}>Held By</div>
                      <div className={th.body}>{hold.held_by.split('@')[0]}</div>
                    </div>
                    <div>
                      <div className={`uppercase tracking-wide text-[10px] mb-0.5 ${th.faint}`}>Hold Duration</div>
                      <div className={th.body}>{Math.round((_now() - hold.held_at) / 60)} min ago</div>
                    </div>
                  </div>

                  {/* Hold reason */}
                  <div className={`mt-3 text-xs rounded-lg px-3 py-2 ${isDark ? 'bg-white/3 text-slate-400' : 'bg-slate-50 text-slate-600'}`}>
                    <span className={`font-medium ${th.body}`}>Reason: </span>
                    {hold.hold_reason}
                  </div>

                  {/* Actions */}
                  <div className="mt-3 flex gap-2 flex-wrap">
                    <button
                      onClick={() => releaseHold(hold.instrument_id)}
                      disabled={releasing === hold.instrument_id}
                      className={`text-xs px-3 py-1.5 rounded-lg font-medium transition-colors
                        ${releasing === hold.instrument_id
                          ? (isDark ? 'opacity-50 bg-white/10 text-slate-400' : 'opacity-50 bg-slate-100 text-slate-400')
                          : (isDark ? 'bg-violet-600 hover:bg-violet-500 text-white' : 'bg-violet-600 hover:bg-violet-700 text-white')
                        }`}
                    >
                      {releasing === hold.instrument_id ? 'Releasing…' : 'Release Hold'}
                    </button>
                    {hold.branch_recommendation === 'RETURN' && (
                      <span className={`text-xs px-3 py-1.5 rounded-lg border font-medium ${isDark ? 'border-red-700/40 text-red-400 bg-red-900/20' : 'border-red-200 text-red-600 bg-red-50'}`}>
                        Branch recommends RETURN
                      </span>
                    )}
                    {hold.branch_recommendation === 'CONFIRM' && (
                      <span className={`text-xs px-3 py-1.5 rounded-lg border font-medium ${isDark ? 'border-emerald-700/40 text-emerald-400 bg-emerald-900/20' : 'border-emerald-200 text-emerald-600 bg-emerald-50'}`}>
                        Branch recommends CONFIRM
                      </span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </AppShell>
  )
}

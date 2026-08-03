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
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'

// ─── IET Countdown ────────────────────────────────────────────────────────────

const _now = () => Date.now() / 1000

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
  const { bankId } = useBankContext()
  const { setHeader } = usePageHeader?.() ?? {}
  const queryClient = useQueryClient()

  useEffect(() => {
    setHeader?.({ title: 'Inward Hold Queue', subtitle: 'Instruments awaiting branch confirmation — IET clock running' })
  }, [])

  const th = {
    page:    isDark ? 'bg-navy-950'        : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'         : 'text-slate-900',
    body:    isDark ? 'text-slate-300'     : 'text-slate-700',
    muted:   isDark ? 'text-slate-400'     : 'text-slate-500',
    faint:   isDark ? 'text-slate-600'     : 'text-slate-400',
    divider: isDark ? 'border-white/8'     : 'border-slate-200',
  }

  const { data, isLoading, isError } = useQuery({
    queryKey: ['cts-holds', bankId],
    queryFn: async () => {
      const res = await fetch('/api/v1/cts/holds', { credentials: 'include' })
      if (!res.ok) throw new Error('Failed to load holds')
      return res.json()
    },
    refetchInterval: 15_000,
  })

  const holds = data?.items ?? []

  const releaseMutation = useMutation({
    mutationFn: async (instrumentId) => {
      const res = await fetch(`/api/v1/cts/holds/${instrumentId}/release`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({}),
      })
      if (!res.ok) throw new Error('Failed to release hold')
      return res.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cts-holds', bankId] })
    },
  })

  const deadlines = holds.map(h => [h.instrument_id, h.iet_deadline])
  const remaining = useCountdown(deadlines)

  const sortedHolds = [...holds].sort((a, b) =>
    (remaining[a.instrument_id] ?? 0) - (remaining[b.instrument_id] ?? 0)
  )

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>Inward Hold Queue</h1>
            <p className={`text-xs mt-0.5 ${th.muted}`}>
              {isLoading ? 'Loading…' : `${holds.length} instrument${holds.length !== 1 ? 's' : ''} on hold — IET countdown active on all`}
            </p>
          </div>
          <div className={`text-xs px-3 py-1 rounded-full border ${isDark ? 'border-amber-700/40 bg-amber-900/30 text-amber-300' : 'border-amber-200 bg-amber-50 text-amber-700'}`}>
            IET clock never pauses during hold
          </div>
        </div>

        {isLoading && (
          <div className={`text-center py-16 ${th.muted}`}>Loading hold queue…</div>
        )}

        {isError && (
          <div className={`text-center py-16 text-red-400`}>Failed to load hold queue. Retry in 15s.</div>
        )}

        {!isLoading && !isError && holds.length === 0 && (
          <div className={`text-center py-16 ${th.muted}`}>
            No instruments currently on hold.
          </div>
        )}

        {!isLoading && !isError && holds.length > 0 && (
          <div className="space-y-3">
            {sortedHolds.map(hold => {
              const secs = remaining[hold.instrument_id] ?? 0
              const tierBadge = isDark ? TIER_BADGE[hold.queue_tier] : TIER_BADGE_L[hold.queue_tier]
              const isReleasing = releaseMutation.isPending && releaseMutation.variables === hold.instrument_id
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
                        {TIER_LABEL[hold.queue_tier] ?? hold.queue_tier}
                      </span>
                      <RecBadge rec={hold.branch_recommendation} isDark={isDark} />
                    </div>
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
                      onClick={() => releaseMutation.mutate(hold.instrument_id)}
                      disabled={isReleasing}
                      className={`text-xs px-3 py-1.5 rounded-lg font-medium transition-colors
                        ${isReleasing
                          ? (isDark ? 'opacity-50 bg-white/10 text-slate-400' : 'opacity-50 bg-slate-100 text-slate-400')
                          : (isDark ? 'bg-violet-600 hover:bg-violet-500 text-white' : 'bg-violet-600 hover:bg-violet-700 text-white')
                        }`}
                    >
                      {isReleasing ? 'Releasing…' : 'Release Hold'}
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

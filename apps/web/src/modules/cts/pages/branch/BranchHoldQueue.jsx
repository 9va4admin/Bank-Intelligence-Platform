/**
 * BranchHoldQueue — Branch Manager view of inward instruments on hold.
 *
 * Route: /branch/hold-queue  (permission: cts:view_hold_queue)
 * Role:  branch_manager
 *
 * Shows instruments from this branch's accounts that ops_reviewers have placed
 * on hold for branch confirmation. Branch manager can add a recommendation
 * (CONFIRM or RETURN) back to the ops team.
 *
 * The final pay/return decision rests with the drawee bank's ops_reviewer.
 */
import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import AppShell from '../../../../shared/layout/AppShell'
import { useTheme } from '../../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../../shared/context/BankContext'
import { usePageHeader } from '../../../../shared/layout/PageHeaderContext'

const _now = () => Date.now() / 1000

// ─── IET countdown hook ───────────────────────────────────────────────────────

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

// ─── Recommendation form for a single hold ───────────────────────────────────

function RecommendationPanel({ hold, isDark, th, onSubmit, isSubmitting }) {
  const [editing, setEditing] = useState(false)
  const [localNote, setLocalNote] = useState(hold.branch_note ?? '')
  const [localRec, setLocalRec] = useState(hold.branch_recommendation ?? null)

  function handleSubmit(rec) {
    onSubmit(hold.instrument_id, localNote, rec)
    setEditing(false)
  }

  if (hold.branch_recommendation && !editing) {
    return (
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-3">
          <span className={`text-xs font-medium px-2 py-0.5 rounded border ${
            hold.branch_recommendation === 'CONFIRM'
              ? (isDark ? 'border-emerald-700/40 bg-emerald-900/30 text-emerald-300' : 'border-emerald-200 bg-emerald-50 text-emerald-700')
              : (isDark ? 'border-red-700/40 bg-red-900/30 text-red-300' : 'border-red-200 bg-red-50 text-red-700')
          }`}>
            Your Recommendation: {hold.branch_recommendation}
          </span>
          {hold.branch_note && (
            <span className={`text-xs ${th.muted}`}>"{hold.branch_note}"</span>
          )}
        </div>
        <button
          onClick={() => { setLocalNote(hold.branch_note ?? ''); setLocalRec(hold.branch_recommendation); setEditing(true) }}
          className={`text-xs ${isDark ? 'text-slate-400 hover:text-slate-200' : 'text-slate-500 hover:text-slate-700'} underline`}
        >
          Edit
        </button>
      </div>
    )
  }

  if (editing || !hold.branch_recommendation) {
    return (
      <div className="space-y-2">
        <p className={`text-xs font-medium ${th.body}`}>Your recommendation to the clearing bank</p>
        <textarea
          value={localNote}
          onChange={e => setLocalNote(e.target.value)}
          placeholder="Add notes for the reviewing officer (optional)…"
          rows={2}
          className={`w-full text-xs rounded-lg border px-3 py-2 resize-none focus:outline-none ${th.input}`}
        />
        <div className="flex gap-2 flex-wrap">
          <button
            onClick={() => handleSubmit('CONFIRM')}
            disabled={isSubmitting}
            className={`text-xs px-3 py-1.5 rounded-lg font-medium transition-colors ${isDark ? 'bg-emerald-700 hover:bg-emerald-600 text-white' : 'bg-emerald-600 hover:bg-emerald-700 text-white'}`}
          >
            {isSubmitting ? 'Saving…' : 'Recommend CONFIRM'}
          </button>
          <button
            onClick={() => handleSubmit('RETURN')}
            disabled={isSubmitting}
            className={`text-xs px-3 py-1.5 rounded-lg font-medium transition-colors ${isDark ? 'bg-red-700 hover:bg-red-600 text-white' : 'bg-red-600 hover:bg-red-700 text-white'}`}
          >
            {isSubmitting ? 'Saving…' : 'Recommend RETURN'}
          </button>
          {editing && (
            <button
              onClick={() => setEditing(false)}
              className={`text-xs px-3 py-1.5 rounded-lg ${isDark ? 'text-slate-400 hover:text-slate-300' : 'text-slate-500 hover:text-slate-700'}`}
            >
              Cancel
            </button>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="flex items-center justify-between">
      <span className={`text-xs ${th.muted}`}>No recommendation sent yet</span>
      <button
        onClick={() => { setLocalNote(''); setLocalRec(null); setEditing(true) }}
        className={`text-xs px-3 py-1.5 rounded-lg font-medium ${isDark ? 'bg-violet-700 hover:bg-violet-600 text-white' : 'bg-violet-600 hover:bg-violet-700 text-white'}`}
      >
        Add Recommendation
      </button>
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function BranchHoldQueue() {
  const { isDark } = useTheme()
  const { bankId, branchCode } = useBankContext()
  const { setHeader } = usePageHeader?.() ?? {}
  const queryClient = useQueryClient()

  useEffect(() => {
    setHeader?.({ title: 'Inward Hold Queue', subtitle: 'Instruments awaiting your branch confirmation' })
  }, [])

  const th = {
    page:    isDark ? 'bg-navy-950'        : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'         : 'text-slate-900',
    body:    isDark ? 'text-slate-300'     : 'text-slate-700',
    muted:   isDark ? 'text-slate-400'     : 'text-slate-500',
    faint:   isDark ? 'text-slate-600'     : 'text-slate-400',
    divider: isDark ? 'border-white/8'     : 'border-slate-200',
    input:   isDark ? 'bg-white/5 border-white/10 text-white placeholder-slate-500 focus:border-violet-500' : 'bg-white border-slate-200 text-slate-900 placeholder-slate-400 focus:border-violet-400',
  }

  const { data, isLoading, isError } = useQuery({
    queryKey: ['branch-holds', bankId],
    queryFn: async () => {
      const res = await fetch('/api/v1/cts/holds', { credentials: 'include' })
      if (!res.ok) throw new Error('Failed to load holds')
      return res.json()
    },
    refetchInterval: 20_000,
  })

  const holds = data?.items ?? []

  const recMutation = useMutation({
    mutationFn: async ({ instrumentId, note, rec }) => {
      const res = await fetch(`/api/v1/cts/holds/${instrumentId}/recommendation`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ branch_note: note, branch_recommendation: rec }),
      })
      if (!res.ok) throw new Error('Failed to save recommendation')
      return res.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['branch-holds', bankId] })
    },
  })

  const deadlines = holds.map(h => [h.instrument_id, h.iet_deadline])
  const remaining = useCountdown(deadlines)

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        {/* Header */}
        <div className="mb-5">
          <h1 className={`text-lg font-semibold ${th.heading}`}>Inward Hold Queue</h1>
          <p className={`text-xs mt-0.5 ${th.muted}`}>
            {isLoading ? 'Loading…' : `${holds.length} instrument${holds.length !== 1 ? 's' : ''} awaiting your confirmation`}
            {branchCode && <span className="ml-2 font-mono">· {branchCode}</span>}
          </p>
        </div>

        {/* Info callout */}
        <div className={`mb-4 rounded-lg border px-4 py-3 text-xs ${isDark ? 'border-amber-700/40 bg-amber-900/20 text-amber-300' : 'border-amber-200 bg-amber-50 text-amber-700'}`}>
          The clearing bank is waiting for your confirmation. Please respond before the IET deadline —
          the bank cannot extend the timer. Your recommendation will help the reviewing officer make
          the right decision. <strong>The final pay/return decision rests with the clearing bank.</strong>
        </div>

        {isLoading && (
          <div className={`text-center py-16 ${th.muted}`}>Loading hold queue…</div>
        )}

        {isError && (
          <div className={`text-center py-16 text-red-400`}>Failed to load hold queue. Retry in 20s.</div>
        )}

        {!isLoading && !isError && holds.length === 0 && (
          <div className={`text-center py-16 ${th.muted}`}>
            No instruments currently awaiting your branch confirmation.
          </div>
        )}

        {!isLoading && !isError && holds.length > 0 && (
          <div className="space-y-4">
            {holds.map(hold => {
              const secs = remaining[hold.instrument_id] ?? 0
              const isSubmitting = recMutation.isPending && recMutation.variables?.instrumentId === hold.instrument_id

              return (
                <div key={hold.instrument_id} className={`rounded-xl border p-4 ${th.card}`}>
                  {/* Top row */}
                  <div className="flex items-start justify-between gap-4 flex-wrap">
                    <span className={`font-mono text-sm font-semibold ${th.heading}`}>
                      {hold.instrument_id}
                    </span>
                    <div className="flex items-center gap-2">
                      <span className={`text-xs ${th.muted}`}>IET deadline</span>
                      <span className={`font-mono text-sm tabular-nums ${countdownColor(secs, isDark)}`}>
                        {fmtCountdown(secs)}
                      </span>
                    </div>
                  </div>

                  {/* Instrument details */}
                  <div className={`mt-3 grid grid-cols-2 sm:grid-cols-3 gap-3 text-xs ${th.muted}`}>
                    <div>
                      <div className={`uppercase tracking-wide text-[10px] mb-0.5 ${th.faint}`}>Account</div>
                      <div className={`font-mono ${th.body}`}>{hold.account_display}</div>
                    </div>
                    <div>
                      <div className={`uppercase tracking-wide text-[10px] mb-0.5 ${th.faint}`}>Amount</div>
                      <div className={th.body}>{hold.amount_display}</div>
                    </div>
                    <div>
                      <div className={`uppercase tracking-wide text-[10px] mb-0.5 ${th.faint}`}>Payee</div>
                      <div className={th.body}>{hold.payee_display}</div>
                    </div>
                  </div>

                  {/* Hold reason */}
                  <div className={`mt-3 text-xs rounded-lg px-3 py-2 ${isDark ? 'bg-white/3 text-slate-400' : 'bg-slate-50 text-slate-600'}`}>
                    <span className={`font-medium ${th.body}`}>Clearing bank asks: </span>
                    {hold.hold_reason}
                  </div>

                  {/* Branch recommendation section */}
                  <div className={`mt-3 pt-3 border-t ${th.divider}`}>
                    <RecommendationPanel
                      hold={hold}
                      isDark={isDark}
                      th={th}
                      isSubmitting={isSubmitting}
                      onSubmit={(instrumentId, note, rec) =>
                        recMutation.mutate({ instrumentId, note, rec })
                      }
                    />
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

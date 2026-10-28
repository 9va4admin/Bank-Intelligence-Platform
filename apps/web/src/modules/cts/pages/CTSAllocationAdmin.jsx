/**
 * CTS Allocation Control Panel — Admin view of all active reviewer claims.
 *
 * Shows who holds which instrument, with the ability to force-release a claim
 * (ops_manager only) or change the allocation_mode config key via a quick-action
 * link to the config page.
 *
 * Real data: GET /api/v1/cts/allocation/status (refetches every 30s).
 * Force-release: DELETE /v1/cts/admin/review/{instrument_id}/claim.
 * Assign / reassign: POST /v1/cts/admin/review/{instrument_id}/assign  { reviewer_id }.
 * Unassigned work: GET /v1/cts/queue (items whose assigned_to is empty).
 * Roles: ops_manager, bank_it_admin.
 */
import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'
import AppShell from '../../../shared/layout/AppShell'

const REFETCH_MS = 30_000

const MOCK_CLAIMS = [
  { instrument_id: 'CHQ-IN-20260811-0142', reviewer_id: 'ananya.krishnan', reviewer_name: 'Ananya Krishnan', claimed_at: '2026-08-11T09:31:00Z', tier: 1, reason: 'SIGNATURE_MISMATCH' },
  { instrument_id: 'CHQ-IN-20260811-0157', reviewer_id: 'rahul.menon',     reviewer_name: 'Rahul Menon',     claimed_at: '2026-08-11T09:38:00Z', tier: 2, reason: 'AMOUNT_MISMATCH'    },
  { instrument_id: 'CHQ-IN-20260811-0163', reviewer_id: 'ananya.krishnan', reviewer_name: 'Ananya Krishnan', claimed_at: '2026-08-11T09:44:00Z', tier: 1, reason: 'HIGH_VALUE_DUAL_APPROVAL' },
]

function ModeTag({ mode, isDark }) {
  const colors = {
    SELF:   isDark ? 'bg-slate-700/60 text-slate-300' : 'bg-slate-100 text-slate-600',
    HYBRID: isDark ? 'bg-blue-900/60 text-blue-300'  : 'bg-blue-50 text-blue-700',
    AUTO:   isDark ? 'bg-violet-900/60 text-violet-300' : 'bg-violet-50 text-violet-700',
  }
  const cls = colors[mode] || colors.SELF
  return (
    <span className={`inline-flex text-xs px-2 py-0.5 rounded font-mono font-medium ${cls}`}>
      {mode || '—'}
    </span>
  )
}

// Current time in seconds, refreshed on an interval, so countdowns never call Date.now() during render.
function useNowSeconds(intervalMs = 15_000) {
  const [now, setNow] = useState(() => Date.now() / 1000)
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now() / 1000), intervalMs)
    return () => clearInterval(t)
  }, [intervalMs])
  return now
}

function ReviewerSelect({ reviewers, onPick, disabled, isDark, label = 'Reassign…' }) {
  return (
    <select
      value=""
      disabled={disabled || reviewers.length === 0}
      onChange={(e) => e.target.value && onPick(e.target.value)}
      className={`text-xs px-2 py-1 rounded border ${isDark ? 'bg-navy-900 border-white/10 text-slate-300' : 'bg-white border-slate-300 text-slate-700'}`}
    >
      <option value="">{reviewers.length === 0 ? 'no one online' : label}</option>
      {reviewers.map(r => (
        <option key={r.reviewer_id} value={r.reviewer_id}>{r.reviewer_id} ({r.load ?? 0} held)</option>
      ))}
    </select>
  )
}

export default function CTSAllocationAdmin() {
  const { isDark } = useTheme()
  const { bankId, isDemo } = useBankContext()
  const qc = useQueryClient()
  const nowSec = useNowSeconds()

  const th = {
    page:    isDark ? 'bg-navy-950'        : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8'  : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'         : 'text-slate-900',
    body:    isDark ? 'text-slate-300'     : 'text-slate-700',
    muted:   isDark ? 'text-slate-400'     : 'text-slate-500',
    divider: isDark ? 'border-white/8'     : 'border-slate-200',
    row:     isDark ? 'border-white/4 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
    th:      isDark ? 'text-slate-500 bg-navy-900/80 text-xs font-medium uppercase tracking-wider'
                    : 'text-slate-400 bg-slate-50 text-xs font-medium uppercase tracking-wider',
    badge: {
      SELF:   isDark ? 'bg-slate-700/60 text-slate-300' : 'bg-slate-100 text-slate-600',
      HYBRID: isDark ? 'bg-blue-900/60 text-blue-300'   : 'bg-blue-50 text-blue-700',
      AUTO:   isDark ? 'bg-violet-900/60 text-violet-300': 'bg-violet-50 text-violet-700',
    },
  }

  // --- allocation status query ---
  const { data: statusData, isLoading, isError, dataUpdatedAt } = useQuery({
    queryKey: ['allocation-status', bankId],
    queryFn: async () => {
      if (isDemo) return { active_claims: MOCK_CLAIMS }
      const res = await fetch(`/v1/cts/allocation/status?bank_id=${bankId}`, { credentials: 'include' })
      if (!res.ok) throw new Error('Failed to load allocation status')
      return res.json()
    },
    enabled: true,
    refetchInterval: isDemo ? false : REFETCH_MS,
    staleTime: 10_000,
    retry: false,
  })

  // --- active (online) reviewers query — who has an active heartbeat right now ---
  const { data: reviewersData } = useQuery({
    queryKey: ['active-reviewers', bankId],
    queryFn: async () => {
      if (isDemo) return {
        active_reviewers: [
          { reviewer_id: 'ananya.krishnan', expires_at: Date.now() / 1000 + 240 },
          { reviewer_id: 'rahul.menon',     expires_at: Date.now() / 1000 + 180 },
        ],
      }
      const res = await fetch(`/v1/cts/allocation/reviewers?bank_id=${bankId}`, { credentials: 'include' })
      if (!res.ok) return {}
      return res.json()
    },
    enabled: true,
    refetchInterval: isDemo ? false : REFETCH_MS,
    staleTime: 10_000,
    retry: false,
  })

  // --- config query for current allocation_mode ---
  const { data: cfgData } = useQuery({
    queryKey: ['cts-config-alloc-mode', bankId],
    queryFn: async () => {
      if (isDemo) return { allocation_mode: 'HYBRID' }
      const res = await fetch(`/v1/admin/config/keys?prefix=allocation&bank_id=${bankId}`, { credentials: 'include' })
      if (!res.ok) return {}
      return res.json()
    },
    enabled: true,
    staleTime: 30_000,
    retry: false,
  })

  const allocationMode = statusData?.allocation_mode ?? cfgData?.allocation_mode ?? '—'
  const strategy = statusData?.allocation_strategy
  const maxPer = statusData?.max_per_reviewer

  // --- admin force-release mutation (separate endpoint from reviewer self-unclaim) ---
  // --- unassigned work: queue items nobody holds, most urgent first (the queue API sorts by IET deadline) ---
  const { data: queueData } = useQuery({
    queryKey: ['allocation-unassigned', bankId],
    queryFn: async () => {
      if (isDemo) return { items: [] }
      const res = await fetch('/v1/cts/queue?limit=100', { credentials: 'include' })
      if (!res.ok) return { items: [] }
      return res.json()
    },
    enabled: true,
    refetchInterval: isDemo ? false : REFETCH_MS,
    staleTime: 10_000,
    retry: false,
  })

  // --- admin assign / reassign: pinned to the chosen reviewer, audited, never moved by the rebalancer ---
  const assignMutation = useMutation({
    mutationFn: async ({ instrumentId, reviewerId }) => {
      const res = await fetch(`/v1/cts/admin/review/${instrumentId}/assign`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reviewer_id: reviewerId }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || 'Assign failed')
      }
      return res.json()
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['allocation-status', bankId] })
      qc.invalidateQueries({ queryKey: ['allocation-unassigned', bankId] })
      qc.invalidateQueries({ queryKey: ['active-reviewers', bankId] })
    },
  })

  const releaseMutation = useMutation({
    mutationFn: async (instrumentId) => {
      const res = await fetch(`/v1/cts/admin/review/${instrumentId}/claim`, {
        method: 'DELETE',
        credentials: 'include',
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || 'Release failed')
      }
      return res.json()
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['allocation-status', bankId] })
    },
  })

  const claims = statusData?.active_claims ?? []
  const unassigned = (queueData?.items ?? []).filter(i => !i.assigned_to)
  const onlineReviewers = reviewersData?.active_reviewers ?? []
  const lastUpdated = dataUpdatedAt
    ? new Date(dataUpdatedAt).toLocaleTimeString('en-IN', { hour12: false })
    : '—'

  function fmtExpiresIn(expires_at) {
    const secs = Math.max(0, Math.round(expires_at - nowSec))
    if (secs <= 0) return 'expired'
    const m = Math.floor(secs / 60), s = secs % 60
    return `${m}m ${String(s).padStart(2, '0')}s`
  }

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        {/* Page header */}
        <div className="flex items-start justify-between mb-5">
          <div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>Allocation Control Panel</h1>
            <p className={`text-sm mt-0.5 ${th.muted}`}>
              Active reviewer claims across the inward human review queue.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 text-xs">
              <span className={th.muted}>Mode:</span>
              <ModeTag mode={allocationMode} isDark={isDark} />
              {strategy && allocationMode !== 'SELF' && (
                <span className={th.muted}>
                  {strategy === 'LEAST_LOADED' ? 'least loaded' : 'random'}{maxPer ? `, max ${maxPer} each` : ''}
                </span>
              )}
              <Link
                to="/admin/config/operations"
                className="text-blue-400 hover:underline text-xs"
              >
                Change →
              </Link>
            </div>
            <span className={`text-xs ${th.muted}`}>Updated {lastUpdated}</span>
          </div>
        </div>

        {/* Summary row */}
        <div className={`border rounded-lg p-4 mb-5 flex items-center gap-8 flex-wrap ${th.card}`}>
          <div>
            <div className={`text-2xl font-bold ${th.heading}`}>
              {isLoading ? '…' : claims.length}
            </div>
            <div className={`text-xs ${th.muted} mt-0.5`}>Active Claims</div>
          </div>
          <div className={`h-8 w-px ${th.divider}`} />
          <div>
            <div className={`text-sm font-semibold ${isDark ? 'text-emerald-400' : 'text-emerald-600'}`}>
              {onlineReviewers.length}
            </div>
            <div className={`text-xs ${th.muted}`}>reviewers online now</div>
          </div>
          <div className={`h-8 w-px ${th.divider}`} />
          <div>
            <div className={`text-sm ${th.body}`}>
              {[...new Set(claims.map(c => c.reviewer_id))].length}
            </div>
            <div className={`text-xs ${th.muted}`}>with active claims</div>
          </div>
          {isError && (
            <div className="ml-auto text-xs text-red-400">
              Failed to load — retrying in 30s
            </div>
          )}
        </div>

        {/* Online reviewers panel */}
        <div className={`border rounded-lg p-4 mb-5 ${th.card}`}>
          <div className={`text-xs font-semibold uppercase tracking-wider mb-3 ${th.muted}`}>
            Reviewers Online Now
            <span className={`ml-2 font-normal normal-case ${th.muted}`}>
              (heartbeat expires after 5 min of inactivity)
            </span>
          </div>
          {onlineReviewers.length === 0 ? (
            <p className={`text-sm ${th.muted}`}>
              No reviewers currently active. In AUTO/HYBRID mode, auto-assign will queue
              instruments until a reviewer opens the review queue page.
            </p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {onlineReviewers.map(r => (
                <div
                  key={r.reviewer_id}
                  className={`flex items-center gap-2 text-xs px-3 py-1.5 rounded-full border ${isDark ? 'bg-emerald-900/20 border-emerald-700/40 text-emerald-300' : 'bg-emerald-50 border-emerald-200 text-emerald-700'}`}
                >
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  <span className="font-medium">{r.reviewer_id}</span>
                  <span title="claims held now">{r.load ?? 0} held</span>
                  {r.zones?.length > 0 && !r.zones.includes('ALL') && (
                    <span className="font-mono" title="clearing zones">{r.zones.join('/')}</span>
                  )}
                  <span className={`font-mono ${isDark ? 'text-emerald-600' : 'text-emerald-500'}`}>
                    {fmtExpiresIn(r.expires_at)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Claims table */}
        <div className={`border rounded-lg overflow-hidden ${th.card}`}>
          <table className="w-full border-collapse">
            <thead>
              <tr>
                {['Instrument ID', 'Claimed By', 'Tier', 'Reassign to', 'Actions'].map(h => (
                  <th key={h} className={`px-4 py-2.5 text-left border-b ${th.divider} ${th.th}`}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {claims.length === 0 && !isLoading && (
                <tr>
                  <td colSpan={5} className={`px-4 py-8 text-center text-sm ${th.muted}`}>
                    No active claims — all instruments are unclaimed.
                  </td>
                </tr>
              )}
              {isLoading && (
                <tr>
                  <td colSpan={5} className={`px-4 py-8 text-center text-sm ${th.muted}`}>
                    Loading…
                  </td>
                </tr>
              )}
              {claims.map(claim => {
                const isReleasing = releaseMutation.isPending &&
                  releaseMutation.variables === claim.instrument_id
                return (
                  <tr key={claim.instrument_id} className={`border-b transition-colors ${th.row}`}>
                    <td className={`px-4 py-3 font-mono text-xs ${th.body}`}>
                      {claim.instrument_id}
                    </td>
                    <td className={`px-4 py-3 text-sm ${th.body}`}>
                      {claim.reviewer_id}
                    </td>
                    <td className={`px-4 py-3 text-xs ${th.muted}`}>
                      {claim.tier || 'standard'}
                    </td>
                    <td className="px-4 py-3">
                      <ReviewerSelect
                        reviewers={onlineReviewers.filter(r => r.reviewer_id !== claim.reviewer_id)}
                        disabled={assignMutation.isPending}
                        isDark={isDark}
                        onPick={(reviewerId) => assignMutation.mutate({ instrumentId: claim.instrument_id, reviewerId })}
                      />
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => releaseMutation.mutate(claim.instrument_id)}
                        disabled={isReleasing}
                        className={`text-xs px-2.5 py-1 rounded border transition-colors ${
                          isReleasing
                            ? 'opacity-50 cursor-not-allowed'
                            : isDark
                              ? 'border-red-700/50 text-red-400 hover:bg-red-900/30'
                              : 'border-red-300 text-red-600 hover:bg-red-50'
                        }`}
                      >
                        {isReleasing ? 'Releasing…' : 'Force Release'}
                      </button>
                      {releaseMutation.isError &&
                        releaseMutation.variables === claim.instrument_id && (
                        <span className="ml-2 text-xs text-red-400">
                          {releaseMutation.error?.message}
                        </span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {/* Unassigned work */}
        <div className={`border rounded-lg overflow-hidden mt-5 ${th.card}`}>
          <div className={`px-4 py-2.5 text-xs font-semibold uppercase tracking-wider border-b ${th.divider} ${th.muted}`}>
            Unassigned in the queue ({unassigned.length}) <span className="font-normal normal-case">most urgent first</span>
          </div>
          <table className="w-full border-collapse">
            <tbody>
              {unassigned.length === 0 && (
                <tr><td className={`px-4 py-6 text-center text-sm ${th.muted}`}>Nothing is waiting for an owner.</td></tr>
              )}
              {unassigned.slice(0, 25).map(item => {
                const mins = item.iet_deadline ? Math.round((item.iet_deadline - nowSec) / 60) : null
                return (
                  <tr key={item.instrument_id} className={`border-b ${th.row}`}>
                    <td className={`px-4 py-3 font-mono text-xs ${th.body}`}>{item.instrument_id}</td>
                    <td className={`px-4 py-3 text-xs ${th.muted}`}>{item.clearing_zone !== 'UNKNOWN' ? item.clearing_zone : ''}</td>
                    <td className={`px-4 py-3 text-xs ${mins !== null && mins <= 30 ? 'text-red-400 font-semibold' : th.muted}`}>
                      {mins === null ? '' : mins <= 0 ? 'IET passed' : `IET in ${mins} min`}
                    </td>
                    <td className="px-4 py-3">
                      <ReviewerSelect
                        reviewers={onlineReviewers}
                        label="Assign to…"
                        disabled={assignMutation.isPending}
                        isDark={isDark}
                        onPick={(reviewerId) => assignMutation.mutate({ instrumentId: item.instrument_id, reviewerId })}
                      />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        {assignMutation.isError && (
          <p className="text-xs text-red-400 mt-2">{assignMutation.error?.message}</p>
        )}

        <p className={`text-xs mt-3 ${th.muted}`}>
          Assign and Reassign pin the cheque to that reviewer: automatic rebalancing never moves it. Both are audited.
          Force Release removes a stale claim immediately.
          The reviewer will see a "Claim lost" notice on their next action.
          This is audited to Immudb.
        </p>
      </div>
    </AppShell>
  )
}

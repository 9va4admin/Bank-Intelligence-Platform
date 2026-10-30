/**
 * CTS Allocation Control Panel — Admin view of all active reviewer claims.
 *
 * Shows who holds which instrument, with the ability to force-release a claim
 * (ops_manager only) or change the allocation_mode config key via a quick-action
 * link to the config page.
 *
 * Real data: GET /api/v1/cts/allocation/status (refetches every 30s).
 * Force-release: DELETE /api/v1/cts/review/{instrument_id}/claim.
 * Roles: ops_manager, bank_it_admin.
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'
import AppShell from '../../../shared/layout/AppShell'
import { msg } from '../../../shared/messages'

const REFETCH_MS = 30_000

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

export default function CTSAllocationAdmin() {
  const { isDark } = useTheme()
  const { bankId } = useBankContext()
  const qc = useQueryClient()

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
      const res = await fetch('/api/v1/cts/allocation/status', { credentials: 'include' })
      if (!res.ok) throw new Error(msg('UI_ALLOCATIONADMIN_FAILED_TO_LOAD_ALLOCATION_STATUS_2'))
      return res.json()
    },
    refetchInterval: REFETCH_MS,
    staleTime: 10_000,
  })

  // --- config query for current allocation_mode ---
  const { data: cfgData } = useQuery({
    queryKey: ['cts-config-alloc-mode', bankId],
    queryFn: async () => {
      const res = await fetch('/api/v1/admin/config/keys?prefix=allocation', { credentials: 'include' })
      if (!res.ok) return {}
      return res.json()
    },
    staleTime: 30_000,
  })

  const allocationMode = cfgData?.allocation_mode ?? '—'

  // --- force-release mutation ---
  const releaseMutation = useMutation({
    mutationFn: async (instrumentId) => {
      const res = await fetch(`/api/v1/cts/review/${instrumentId}/claim`, {
        method: 'DELETE',
        credentials: 'include',
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || msg('UI_ALLOCATIONADMIN_RELEASE_FAILED_2'))
      }
      return res.json()
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['allocation-status', bankId] })
    },
  })

  const claims = statusData?.active_claims ?? []
  const lastUpdated = dataUpdatedAt
    ? new Date(dataUpdatedAt).toLocaleTimeString('en-IN', { hour12: false })
    : '—'

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        {/* Page header */}
        <div className="flex items-start justify-between mb-5">
          <div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>{msg('UI_ALLOCATIONADMIN_ALLOCATION_CONTROL_PANEL_2')}</h1>
            <p className={`text-sm mt-0.5 ${th.muted}`}>
             {msg('UI_ALLOCATIONADMIN_ACTIVE_REVIEWER_CLAIMS_ACROSS_THE_2')}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 text-xs">
              <span className={th.muted}>{msg('UI_ALLOCATIONADMIN_MODE_2')}</span>
              <ModeTag mode={allocationMode} isDark={isDark} />
              <Link
                to="/admin/config/operations"
                className="text-blue-400 hover:underline text-xs"
              >
               {msg('UI_ALLOCATIONADMIN_CHANGE_2')}
              </Link>
            </div>
            <span className={`text-xs ${th.muted}`}>{msg('UI_ALLOCATIONADMIN_UPDATED_2', { lastUpdated })}</span>
          </div>
        </div>

        {/* Summary row */}
        <div className={`border rounded-lg p-4 mb-5 flex items-center gap-8 ${th.card}`}>
          <div>
            <div className={`text-2xl font-bold ${th.heading}`}>
              {isLoading ? '…' : claims.length}
            </div>
            <div className={`text-xs ${th.muted} mt-0.5`}>{msg('UI_ALLOCATIONADMIN_ACTIVE_CLAIMS_2')}</div>
          </div>
          <div className={`h-8 w-px ${th.divider}`} />
          <div>
            <div className={`text-sm ${th.body}`}>
              {msg('UI_ALLOCATIONADMIN_REVIEWER_2', { count: [...new Set(claims.map(c => c.reviewer_id))].length, value: claims.length !== 1 ? 's' : '' })}
            </div>
            <div className={`text-xs ${th.muted}`}>{msg('UI_ALLOCATIONADMIN_WITH_CLAIMS')}</div>
          </div>
          {isError && (
            <div className="ml-auto text-xs text-red-400">
             {msg('UI_ALLOCATIONADMIN_FAILED_TO_LOAD_RETRYING_IN_2')}
            </div>
          )}
        </div>

        {/* Claims table */}
        <div className={`border rounded-lg overflow-hidden ${th.card}`}>
          <table className="w-full border-collapse">
            <thead>
              <tr>
                {[msg('UI_COMMON_INSTRUMENT_ID_2'), msg('UI_ALLOCATIONADMIN_CLAIMED_BY_2'), msg('UI_ALLOCATIONADMIN_TIER_2'), msg('UI_COMMON_ACTIONS_2')].map(h => (
                  <th key={h} className={`px-4 py-2.5 text-left border-b ${th.divider} ${th.th}`}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {claims.length === 0 && !isLoading && (
                <tr>
                  <td colSpan={4} className={`px-4 py-8 text-center text-sm ${th.muted}`}>
                   {msg('UI_ALLOCATIONADMIN_NO_ACTIVE_CLAIMS_ALL_INSTRUMENTS_2')}
                  </td>
                </tr>
              )}
              {isLoading && (
                <tr>
                  <td colSpan={4} className={`px-4 py-8 text-center text-sm ${th.muted}`}>
                   {msg('UI_OPSDASHBOARD_LOADING')}
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
                      {claim.tier || msg('UI_ALLOCATIONADMIN_STANDARD_2')}
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
                        {isReleasing ? msg('UI_ALLOCATIONADMIN_RELEASING_2') : msg('UI_ALLOCATIONADMIN_FORCE_RELEASE_2')}
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

        <p className={`text-xs mt-3 ${th.muted}`}>
         {msg('UI_ALLOCATIONADMIN_FORCE_RELEASE_REMOVES_A_STALE')}
        </p>
      </div>
    </AppShell>
  )
}

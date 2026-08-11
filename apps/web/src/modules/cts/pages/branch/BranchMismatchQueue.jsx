/**
 * Branch Portal — Mismatch Queue (/branch/mismatch)
 *
 * Branch manager / supervisor screen. Lists outward instruments HELD due to
 * Vision LLM ↔ scanner data mismatch. Supervisor can GO_AHEAD (proceed to lot)
 * or REJECT (return to drawer). Sends Temporal signal to MismatchResolutionWorkflow.
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTheme } from '../../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../../shared/context/BankContext'
import AppShell from '../../../../shared/layout/AppShell'

const MOCK_MISMATCHES = [
  {
    mismatch_id: 'MISM-20260619-001',
    instrument_id: 'INS-20260619-00101',
    held_at: '8m ago',
    scanner_amount: '₹45,000',
    vision_amount: '₹45,500',
    mismatch_fields: ['amount'],
    payee_display: 'R***',
    account_display: '****9210',
  },
  {
    mismatch_id: 'MISM-20260619-002',
    instrument_id: 'INS-20260619-00148',
    held_at: '14m ago',
    scanner_amount: '₹1,25,000',
    vision_amount: '₹1,52,000',
    mismatch_fields: ['amount', 'date'],
    payee_display: 'S***',
    account_display: '****4521',
  },
]

// ─── Mismatch card ────────────────────────────────────────────────────────────

function MismatchCard({ item, isDark, onResolve, isResolving }) {
  const [note, setNote] = useState('')

  const th = {
    card:    isDark ? 'bg-navy-900 border-amber-500/30' : 'bg-white border-amber-300',
    heading: isDark ? 'text-white' : 'text-slate-900',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    input:   isDark ? 'bg-navy-950 border-white/10 text-slate-300 placeholder-slate-600'
                    : 'bg-slate-50 border-slate-200 text-slate-700 placeholder-slate-400',
  }

  return (
    <div className={`rounded-lg border p-4 mb-3 ${th.card}`}>
      <div className="flex items-start justify-between mb-3">
        <div>
          <span className={`text-xs font-mono ${th.muted}`}>{item.mismatch_id}</span>
          <span className="mx-2 text-amber-400">·</span>
          <span className={`text-xs font-mono ${th.muted}`}>{item.instrument_id}</span>
          <span className="mx-2 text-amber-400">·</span>
          <span className={`text-xs ${th.muted}`}>Held {item.held_at}</span>
        </div>
        <span className="inline-flex items-center text-xs px-2 py-0.5 rounded border bg-amber-500/15 text-amber-400 border-amber-500/30">
          HELD
        </span>
      </div>

      {/* Mismatch detail */}
      <div className="grid grid-cols-2 gap-4 mb-3">
        <div>
          <p className={`text-xs font-medium uppercase tracking-wider mb-1 ${th.muted}`}>
            Scanner Read
          </p>
          <p className={`text-lg font-bold tabular-nums ${isDark ? 'text-white' : 'text-slate-900'}`}>
            {item.scanner_amount}
          </p>
          <p className={`text-xs mt-0.5 ${th.muted}`}>
            Fields: {(item.mismatch_fields ?? []).join(', ')}
          </p>
        </div>
        <div>
          <p className={`text-xs font-medium uppercase tracking-wider mb-1 ${th.muted}`}>
            Vision LLM Read
          </p>
          <p className="text-lg font-bold tabular-nums text-red-400">{item.vision_amount}</p>
          <p className={`text-xs mt-0.5 ${th.muted}`}>Mismatch detected</p>
        </div>
      </div>

      <div className="mb-3 text-xs">
        <span className={th.muted}>Payee: </span>
        <span className={`font-medium ${isDark ? 'text-slate-300' : 'text-slate-700'}`}>
          {item.payee_display}
        </span>
      </div>

      {/* Supervisor note */}
      <input
        type="text"
        placeholder="Supervisor note (optional)"
        value={note}
        onChange={e => setNote(e.target.value)}
        className={`w-full text-xs px-3 py-2 rounded border mb-3 outline-none focus:ring-1 focus:ring-blue-500/40 ${th.input}`}
      />

      {/* Resolution buttons */}
      <div className="flex gap-2">
        <button
          onClick={() => onResolve(item.mismatch_id, 'GO_AHEAD', note)}
          disabled={isResolving}
          className="flex-1 py-1.5 bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white text-xs font-medium rounded transition-colors"
        >
          {isResolving ? '…' : 'Go Ahead (trust scanner)'}
        </button>
        <button
          onClick={() => onResolve(item.mismatch_id, 'REJECTED', note)}
          disabled={isResolving}
          className="flex-1 py-1.5 bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white text-xs font-medium rounded transition-colors"
        >
          {isResolving ? '…' : 'Reject (return to drawer)'}
        </button>
      </div>
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function BranchMismatchQueue() {
  const { isDark } = useTheme()
  const { bankId, isDemo } = useBankContext()
  const queryClient = useQueryClient()
  const [resolved, setResolved] = useState([])

  const th = {
    page:    isDark ? 'bg-navy-950'  : 'bg-slate-50',
    heading: isDark ? 'text-white'   : 'text-slate-900',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
  }

  const { data, isLoading, isError } = useQuery({
    queryKey: ['branch-mismatches', bankId],
    queryFn: async () => {
      const res = await fetch(`/v1/cts/mismatches?bank_id=${bankId}`, { credentials: 'include' })
      if (!res.ok) throw new Error('Failed to load mismatches')
      return res.json()
    },
    enabled: !isDemo,
    refetchInterval: isDemo ? false : 15_000,
    retry: false,
  })

  const raw = isDemo ? MOCK_MISMATCHES : (data?.items ?? [])
  const mismatches = raw.filter(m => !resolved.find(r => r.mismatch_id === m.mismatch_id))

  const resolveMutation = useMutation({
    mutationFn: async ({ mismatchId, action, note }) => {
      const res = await fetch(`/v1/cts/mismatches/${mismatchId}/resolve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ action, note }),
      })
      if (!res.ok) throw new Error('Failed to resolve mismatch')
      return res.json()
    },
    onSuccess: (data, { mismatchId, action }) => {
      setResolved(prev => [...prev, {
        mismatch_id: mismatchId,
        action,
        resolved_at: new Date().toLocaleTimeString(),
      }])
      queryClient.invalidateQueries({ queryKey: ['branch-mismatches', bankId] })
    },
  })

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        <div className="flex items-center gap-4 mb-5">
          <Link to="/branch" className={`text-sm ${th.muted} hover:text-blue-400 transition-colors`}>
            ← Dashboard
          </Link>
          <h1 className={`text-lg font-semibold ${th.heading}`}>Mismatch Queue</h1>
          {!isLoading && mismatches.length > 0 && (
            <span className="text-xs bg-amber-500/20 text-amber-400 border border-amber-500/30 rounded px-2 py-0.5">
              {mismatches.length} pending
            </span>
          )}
        </div>

        {isLoading && (
          <div className={`text-center py-12 ${th.muted} text-sm`}>Loading…</div>
        )}

        {isError && (
          <div className="text-center py-12 text-amber-400/70 text-sm">Backend not reachable — retrying every 15s.</div>
        )}

        {!isLoading && !isError && mismatches.length === 0 && resolved.length === 0 && (
          <div className={`text-center py-12 ${th.muted} text-sm`}>
            No held items. All mismatches resolved.
          </div>
        )}

        {mismatches.map(item => (
          <MismatchCard
            key={item.mismatch_id}
            item={item}
            isDark={isDark}
            isResolving={resolveMutation.isPending && resolveMutation.variables?.mismatchId === item.mismatch_id}
            onResolve={(mismatchId, action, note) =>
              resolveMutation.mutate({ mismatchId, action, note })
            }
          />
        ))}

        {resolved.length > 0 && (
          <div className="mt-4">
            <h2 className={`text-sm font-medium mb-2 ${th.muted}`}>Resolved this session</h2>
            {resolved.map(r => (
              <div key={r.mismatch_id} className={`rounded-lg border p-3 mb-2 ${th.card}`}>
                <div className="flex items-center justify-between text-xs">
                  <span className={`font-mono ${th.muted}`}>{r.mismatch_id}</span>
                  <span className={r.action === 'GO_AHEAD' ? 'text-emerald-400' : 'text-red-400'}>
                    {r.action === 'GO_AHEAD' ? 'Proceeded' : 'Rejected'}
                  </span>
                  <span className={th.muted}>{r.resolved_at}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </AppShell>
  )
}

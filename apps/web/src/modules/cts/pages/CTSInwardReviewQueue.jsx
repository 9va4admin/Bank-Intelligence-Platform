/**
 * CTSInwardReviewQueue — Human review working queue for inward instruments.
 *
 * Route: /cts/inward/review-queue  (permission: cts:view_queue)
 * Role:  ops_reviewer, ops_manager
 *
 * Per instrument:
 *  - CLAIM  → locks instrument to this reviewer (LockService, Redis SET NX EX)
 *  - HOLD   → pauses for branch consultation (IET clock never pauses)
 *  - CONFIRM→ STP confirm (PAY)
 *  - RETURN → return to drawer with reason
 *
 * Tier filter: All / Standard / High Value / Very High
 * IET countdown live-ticks every second, turns red ≤ 30 min
 */
import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'

// ─── Constants ────────────────────────────────────────────────────────────────

const TIERS = ['all', 'standard', 'high_value', 'very_high']

const _T = (offsetMins) => Math.floor(Date.now() / 1000) + offsetMins * 60
const MOCK_REVIEW_ITEMS = [
  { instrument_id: 'INS-20260619-00142', queue_tier: 'high_value',  status: 'CLAIMED',  claimed_by: 'reviewer@saraswat.coop', iet_deadline: _T(38), account_display: '****4521', amount_display: '₹[1L–5L]',  payee_display: 'M***', risk_flags: ['HIGH_VALUE', 'ALTERATION_SUSPECTED'], ai_summary: 'Ink inconsistency detected in payee field. Confidence 0.71.' },
  { instrument_id: 'INS-20260619-00143', queue_tier: 'standard',    status: 'PENDING',  claimed_by: null,                    iet_deadline: _T(102), account_display: '****7832', amount_display: '₹[<1L]',    payee_display: 'P***', risk_flags: [],                                   ai_summary: null },
  { instrument_id: 'INS-20260619-00144', queue_tier: 'very_high',   status: 'ON_HOLD',  claimed_by: 'reviewer@saraswat.coop', iet_deadline: _T(22),  account_display: '****9210', amount_display: '₹[>1Cr]',   payee_display: 'R***', risk_flags: ['VERY_HIGH_VALUE', 'STOP_PAYMENT'], ai_summary: 'Stop payment instruction found. Routing to ops_manager.' },
  { instrument_id: 'INS-20260619-00145', queue_tier: 'standard',    status: 'PENDING',  claimed_by: null,                    iet_deadline: _T(145), account_display: '****3301', amount_display: '₹[<1L]',    payee_display: 'K***', risk_flags: [],                                   ai_summary: null },
  { instrument_id: 'INS-20260619-00146', queue_tier: 'high_value',  status: 'PENDING',  claimed_by: null,                    iet_deadline: _T(55),  account_display: '****6644', amount_display: '₹[5L–10L]', payee_display: 'A***', risk_flags: ['DORMANT_ACCOUNT'],                  ai_summary: 'Account dormant for 14 months. Manual verification required.' },
]
const TIER_LABEL = { all: 'All', standard: 'Standard', high_value: 'High Value', very_high: 'Very High' }

const RETURN_REASONS = [
  { code: 'FUNDS_INSUFFICIENT', label: 'Insufficient Funds' },
  { code: 'ACCOUNT_CLOSED',    label: 'Account Closed' },
  { code: 'STOP_PAYMENT',      label: 'Stop Payment Issued' },
  { code: 'SIGNATURE_DIFFER',  label: 'Signature Mismatch' },
  { code: 'ALTERATION',        label: 'Alteration Detected' },
  { code: 'ACCOUNT_FROZEN',    label: 'Account Frozen' },
  { code: 'STALE_CHEQUE',      label: 'Stale Cheque (> 3 months)' },
  { code: 'AMOUNT_MISMATCH',   label: 'Amount in Words / Figures Mismatch' },
]

// ─── IET Countdown helpers ────────────────────────────────────────────────────

const _now = () => Date.now() / 1000

function useTickingCountdowns(items) {
  const [remaining, setRemaining] = useState({})
  const itemsRef = useRef(items)
  itemsRef.current = items  // always fresh, no stale closure

  useEffect(() => {
    function recompute() {
      const map = {}
      for (const it of itemsRef.current) {
        map[it.instrument_id] = Math.max(0, it.iet_deadline - _now())
      }
      setRemaining(map)
    }
    recompute()
    const t = setInterval(recompute, 1000)
    return () => clearInterval(t)
  }, []) // mount-only — reads fresh items via ref each tick; no dependency on items reference
  return remaining
}

function fmtCountdown(secs) {
  if (secs <= 0) return 'EXPIRED'
  const h = Math.floor(secs / 3600)
  const m = Math.floor((secs % 3600) / 60)
  const s = Math.floor(secs % 60)
  if (h > 0) return `${h}h ${m}m`
  return `${m}m ${String(s).padStart(2, '0')}s`
}

function ietColor(secs, isDark) {
  if (secs <= 0)        return 'text-red-500 font-bold animate-pulse'
  if (secs <= 30 * 60) return 'text-red-400 font-semibold'
  if (secs <= 60 * 60) return 'text-amber-400'
  return isDark ? 'text-emerald-400' : 'text-emerald-600'
}

// ─── Badge components ─────────────────────────────────────────────────────────

const TIER_D = {
  standard:   'bg-slate-700/60 text-slate-300 border-slate-600/40',
  high_value: 'bg-amber-900/50 text-amber-300 border-amber-700/40',
  very_high:  'bg-red-900/50   text-red-300   border-red-700/40',
}
const TIER_L = {
  standard:   'bg-slate-100 text-slate-600 border-slate-300',
  high_value: 'bg-amber-50  text-amber-700 border-amber-200',
  very_high:  'bg-red-50    text-red-700   border-red-200',
}

function TierBadge({ tier, isDark }) {
  const cls = isDark ? TIER_D[tier] : TIER_L[tier]
  return (
    <span className={`text-xs px-2 py-0.5 rounded border font-medium ${cls}`}>
      {TIER_LABEL[tier] ?? tier}
    </span>
  )
}

function StatusBadge({ status, claimedBy, isDark }) {
  if (status === 'CLAIMED') {
    return (
      <span className={`text-xs px-2 py-0.5 rounded border font-medium ${isDark ? 'bg-violet-900/40 text-violet-300 border-violet-700/40' : 'bg-violet-50 text-violet-700 border-violet-200'}`}>
        Claimed · {(claimedBy ?? '').split('@')[0]}
      </span>
    )
  }
  if (status === 'ON_HOLD') {
    return (
      <span className={`text-xs px-2 py-0.5 rounded border font-medium ${isDark ? 'bg-amber-900/40 text-amber-300 border-amber-700/40' : 'bg-amber-50 text-amber-700 border-amber-200'}`}>
        On Hold
      </span>
    )
  }
  return (
    <span className={`text-xs px-2 py-0.5 rounded border font-medium ${isDark ? 'bg-blue-900/40 text-blue-300 border-blue-700/40' : 'bg-blue-50 text-blue-700 border-blue-200'}`}>
      Pending
    </span>
  )
}

// ─── Hold Modal ───────────────────────────────────────────────────────────────

function HoldModal({ instrument, onConfirm, onCancel, isDark }) {
  const [reason, setReason] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')

  const th = {
    overlay: 'fixed inset-0 z-50 flex items-center justify-center bg-black/60',
    modal:   isDark ? 'bg-navy-900 border border-white/10 rounded-2xl p-6 w-full max-w-md shadow-2xl'
                    : 'bg-white border border-slate-200 rounded-2xl p-6 w-full max-w-md shadow-2xl',
    label:   isDark ? 'text-xs font-medium text-slate-400 mb-1 block' : 'text-xs font-medium text-slate-500 mb-1 block',
    input:   isDark ? 'w-full rounded-lg bg-white/5 border border-white/10 text-slate-200 text-sm px-3 py-2 focus:outline-none focus:border-violet-500'
                    : 'w-full rounded-lg bg-white border border-slate-200 text-slate-800 text-sm px-3 py-2 focus:outline-none focus:border-violet-400',
    heading: isDark ? 'text-base font-semibold text-white' : 'text-base font-semibold text-slate-900',
    sub:     isDark ? 'text-xs text-slate-400' : 'text-xs text-slate-500',
  }

  return (
    <div className={th.overlay}>
      <div className={th.modal}>
        <h2 className={th.heading}>Place Hold</h2>
        <p className={`${th.sub} mt-1 mb-4`}>
          Instrument <span className="font-mono">{instrument.instrument_id}</span> will pause in queue.
          <span className="text-amber-400 ml-1">IET clock continues running.</span>
        </p>

        <div className="space-y-3">
          <div>
            <label className={th.label}>Hold Reason *</label>
            <textarea
              rows={3}
              value={reason}
              onChange={e => setReason(e.target.value)}
              placeholder="Describe why branch consultation is needed…"
              className={th.input}
            />
          </div>
          <div>
            <label className={th.label}>Branch Email *</label>
            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="mgr@branch.bank.com"
              className={th.input}
            />
          </div>
          <div>
            <label className={th.label}>Branch WhatsApp (optional)</label>
            <input
              type="tel"
              value={phone}
              onChange={e => setPhone(e.target.value)}
              placeholder="+919876543210"
              className={th.input}
            />
          </div>
        </div>

        <div className="flex gap-2 mt-5 justify-end">
          <button
            onClick={onCancel}
            className={`text-sm px-4 py-1.5 rounded-lg border font-medium transition-colors ${isDark ? 'border-white/10 text-slate-400 hover:bg-white/5' : 'border-slate-200 text-slate-600 hover:bg-slate-50'}`}
          >
            Cancel
          </button>
          <button
            disabled={!reason.trim() || !email.trim()}
            onClick={() => onConfirm({ reason, email, phone })}
            className="text-sm px-4 py-1.5 rounded-lg font-medium bg-amber-500 hover:bg-amber-400 text-white transition-colors disabled:opacity-40"
          >
            Place Hold
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Return Modal ─────────────────────────────────────────────────────────────

function ReturnModal({ instrument, onConfirm, onCancel, isDark }) {
  const [reason, setReason] = useState('')

  const th = {
    overlay: 'fixed inset-0 z-50 flex items-center justify-center bg-black/60',
    modal:   isDark ? 'bg-navy-900 border border-white/10 rounded-2xl p-6 w-full max-w-md shadow-2xl'
                    : 'bg-white border border-slate-200 rounded-2xl p-6 w-full max-w-md shadow-2xl',
    label:   isDark ? 'text-xs font-medium text-slate-400 mb-1 block' : 'text-xs font-medium text-slate-500 mb-1 block',
    select:  isDark ? 'w-full rounded-lg bg-white/5 border border-white/10 text-slate-200 text-sm px-3 py-2 focus:outline-none focus:border-red-500'
                    : 'w-full rounded-lg bg-white border border-slate-200 text-slate-800 text-sm px-3 py-2 focus:outline-none focus:border-red-400',
    heading: isDark ? 'text-base font-semibold text-white' : 'text-base font-semibold text-slate-900',
  }

  return (
    <div className={th.overlay}>
      <div className={th.modal}>
        <h2 className={th.heading}>Return Instrument</h2>
        <p className={`text-xs mt-1 mb-4 ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>
          Instrument <span className="font-mono">{instrument.instrument_id}</span> will be returned to drawer.
        </p>
        <div>
          <label className={th.label}>Return Reason *</label>
          <select value={reason} onChange={e => setReason(e.target.value)} className={th.select}>
            <option value="">— Select reason —</option>
            {RETURN_REASONS.map(r => (
              <option key={r.code} value={r.code}>{r.label}</option>
            ))}
          </select>
        </div>
        <div className="flex gap-2 mt-5 justify-end">
          <button
            onClick={onCancel}
            className={`text-sm px-4 py-1.5 rounded-lg border font-medium ${isDark ? 'border-white/10 text-slate-400 hover:bg-white/5' : 'border-slate-200 text-slate-600 hover:bg-slate-50'}`}
          >
            Cancel
          </button>
          <button
            disabled={!reason}
            onClick={() => onConfirm(reason)}
            className="text-sm px-4 py-1.5 rounded-lg font-medium bg-red-600 hover:bg-red-500 text-white transition-colors disabled:opacity-40"
          >
            Confirm Return
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Row action buttons ───────────────────────────────────────────────────────

function ActionRow({ item, onClaim, onHold, onConfirm, onReturn, isDark, loadingId }) {
  const busy = loadingId === item.instrument_id
  const isClaimed = item.status === 'CLAIMED'
  const isOnHold = item.status === 'ON_HOLD'
  const claimedByMe = item.claimed_by_me

  const btn = (label, onClick, variant) => {
    const variants = {
      violet: isDark ? 'bg-violet-600 hover:bg-violet-500 text-white' : 'bg-violet-600 hover:bg-violet-700 text-white',
      amber:  isDark ? 'bg-amber-600 hover:bg-amber-500 text-white'  : 'bg-amber-600 hover:bg-amber-700 text-white',
      green:  isDark ? 'bg-emerald-600 hover:bg-emerald-500 text-white' : 'bg-emerald-600 hover:bg-emerald-700 text-white',
      red:    isDark ? 'bg-red-700 hover:bg-red-600 text-white' : 'bg-red-600 hover:bg-red-700 text-white',
      ghost:  isDark ? 'border border-white/10 text-slate-400 hover:bg-white/5' : 'border border-slate-200 text-slate-600 hover:bg-slate-50',
    }
    return (
      <button
        disabled={busy}
        onClick={onClick}
        className={`text-xs px-3 py-1.5 rounded-lg font-medium transition-colors ${busy ? 'opacity-40 cursor-not-allowed' : ''} ${variants[variant]}`}
      >
        {busy ? '…' : label}
      </button>
    )
  }

  // Claimed by someone else — show read-only
  if (isClaimed && !claimedByMe) {
    return (
      <div className={`text-xs ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>
        Locked by another reviewer
      </div>
    )
  }

  // On hold — no actions until released
  if (isOnHold) {
    return (
      <div className={`text-xs ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>
        On hold — release from Hold Queue to resume
      </div>
    )
  }

  // Not yet claimed — show CLAIM
  if (!isClaimed) {
    return btn('Claim', () => onClaim(item), 'violet')
  }

  // Claimed by me — show HOLD, CONFIRM (PAY), RETURN
  return (
    <div className="flex gap-2 flex-wrap">
      {btn('Hold', () => onHold(item), 'amber')}
      {btn('Confirm (Pay)', () => onConfirm(item), 'green')}
      {btn('Return', () => onReturn(item), 'red')}
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function CTSInwardReviewQueue() {
  const { isDark } = useTheme()
  const { bankId, isDemo } = useBankContext()
  const { setHeader } = usePageHeader?.() ?? {}
  const queryClient = useQueryClient()

  const [tierFilter, setTierFilter] = useState('all')
  const [holdTarget, setHoldTarget] = useState(null)
  const [returnTarget, setReturnTarget] = useState(null)
  const [loadingId, setLoadingId] = useState(null)
  const [toast, setToast] = useState(null)

  useEffect(() => {
    setHeader?.({
      title: 'Inward Human Review Queue',
      subtitle: 'Claim, Hold, Confirm or Return — IET countdown active on all instruments',
    })
  }, [])

  const th = {
    page:    isDark ? 'bg-navy-950'        : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'         : 'text-slate-900',
    body:    isDark ? 'text-slate-300'     : 'text-slate-700',
    muted:   isDark ? 'text-slate-400'     : 'text-slate-500',
    faint:   isDark ? 'text-slate-600'     : 'text-slate-400',
    divider: isDark ? 'border-white/8'     : 'border-slate-200',
    tab:     (active) => active
      ? (isDark ? 'bg-white/8 text-white border-white/15' : 'bg-slate-100 text-slate-900 border-slate-300')
      : (isDark ? 'text-slate-400 border-transparent hover:border-white/10 hover:text-slate-300'
                : 'text-slate-500 border-transparent hover:text-slate-700'),
  }

  const showToast = useCallback((msg, type = 'success') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3500)
  }, [])

  // ── Data fetch ──────────────────────────────────────────────────────────────

  const { data, isLoading, isError } = useQuery({
    queryKey: ['cts-review-queue', bankId, tierFilter],
    queryFn: async () => {
      const url = tierFilter === 'all'
        ? `/v1/cts/review/queue?bank_id=${bankId}`
        : `/v1/cts/review/queue?bank_id=${bankId}&tier=${tierFilter}`
      const res = await fetch(url, { credentials: 'include' })
      if (!res.ok) throw new Error('Failed to load review queue')
      return res.json()
    },
    refetchInterval: 15_000,
    enabled: !isDemo,  // in DEMO mode serve mock data; real API call only in POC/PROD
    retry: false,
  })

  const items = useMemo(
    () => isDemo ? MOCK_REVIEW_ITEMS : (data?.items ?? []),
    [isDemo, data]
  )
  const remaining = useTickingCountdowns(items)

  // Sort by IET deadline ascending (most urgent first)
  const sorted = [...items].sort((a, b) => (remaining[a.instrument_id] ?? 0) - (remaining[b.instrument_id] ?? 0))

  // ── Mutations ───────────────────────────────────────────────────────────────

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['cts-review-queue', bankId] })

  async function apiPost(url, body) {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(body ?? {}),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.message ?? `HTTP ${res.status}`)
    }
    return res.json()
  }

  async function handleClaim(item) {
    setLoadingId(item.instrument_id)
    try {
      await apiPost(`/v1/cts/review/${item.instrument_id}/claim`)
      invalidate()
      showToast(`Claimed ${item.instrument_id}`)
    } catch (e) {
      showToast(e.message, 'error')
    } finally {
      setLoadingId(null)
    }
  }

  async function handleHoldConfirm({ reason, email, phone }) {
    const item = holdTarget
    setHoldTarget(null)
    setLoadingId(item.instrument_id)
    try {
      await apiPost(`/v1/cts/holds/${item.instrument_id}`, {
        hold_reason: reason,
        iet_deadline: item.iet_deadline,
        branch_email: email,
        branch_phone: phone || undefined,
      })
      invalidate()
      queryClient.invalidateQueries({ queryKey: ['cts-holds', bankId] })
      showToast(`Hold placed on ${item.instrument_id}`)
    } catch (e) {
      showToast(e.message, 'error')
    } finally {
      setLoadingId(null)
    }
  }

  async function handleConfirm(item) {
    setLoadingId(item.instrument_id)
    try {
      await apiPost(`/v1/cts/review/${item.instrument_id}/confirm`)
      invalidate()
      showToast(`Confirmed (PAY) ${item.instrument_id}`)
    } catch (e) {
      showToast(e.message, 'error')
    } finally {
      setLoadingId(null)
    }
  }

  async function handleReturnConfirm(returnReason) {
    const item = returnTarget
    setReturnTarget(null)
    setLoadingId(item.instrument_id)
    try {
      await apiPost(`/v1/cts/review/${item.instrument_id}/return`, { return_reason: returnReason })
      invalidate()
      showToast(`Returned ${item.instrument_id} — ${returnReason}`)
    } catch (e) {
      showToast(e.message, 'error')
    } finally {
      setLoadingId(null)
    }
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5 relative`}>

        {/* Toast */}
        {toast && (
          <div className={`fixed top-4 right-4 z-50 text-sm px-4 py-2 rounded-xl shadow-lg font-medium transition-all
            ${toast.type === 'error'
              ? 'bg-red-600 text-white'
              : (isDark ? 'bg-emerald-700 text-white' : 'bg-emerald-500 text-white')
            }`}>
            {toast.msg}
          </div>
        )}

        {/* Modals */}
        {holdTarget && (
          <HoldModal
            instrument={holdTarget}
            onConfirm={handleHoldConfirm}
            onCancel={() => setHoldTarget(null)}
            isDark={isDark}
          />
        )}
        {returnTarget && (
          <ReturnModal
            instrument={returnTarget}
            onConfirm={handleReturnConfirm}
            onCancel={() => setReturnTarget(null)}
            isDark={isDark}
          />
        )}

        {/* Header */}
        <div className="flex items-center justify-between flex-wrap gap-3 mb-5">
          <div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>Inward Human Review Queue</h1>
            <p className={`text-xs mt-0.5 ${th.muted}`}>
              {isLoading ? 'Loading…' : `${items.length} instrument${items.length !== 1 ? 's' : ''} awaiting review`}
            </p>
          </div>
          <div className={`text-xs px-3 py-1 rounded-full border ${isDark ? 'border-amber-700/40 bg-amber-900/30 text-amber-300' : 'border-amber-200 bg-amber-50 text-amber-700'}`}>
            IET countdown active — STP threshold from config_service
          </div>
        </div>

        {/* Tier filter tabs */}
        <div className={`flex gap-1 mb-5 border-b ${th.divider}`}>
          {TIERS.map(t => (
            <button
              key={t}
              onClick={() => setTierFilter(t)}
              className={`text-xs px-3 py-2 border-b-2 -mb-px font-medium transition-colors ${th.tab(tierFilter === t)}`}
            >
              {TIER_LABEL[t]}
            </button>
          ))}
        </div>

        {/* States */}
        {isLoading && <div className={`text-center py-16 ${th.muted}`}>Loading queue…</div>}
        {isError && <div className="text-center py-16 text-amber-400/70">Backend not reachable — retrying every 15s.</div>}
        {!isLoading && !isError && items.length === 0 && (
          <div className={`text-center py-16 ${th.muted}`}>No instruments in review queue for this tier.</div>
        )}

        {/* Instrument rows */}
        {!isLoading && !isError && sorted.length > 0 && (
          <div className="space-y-3">
            {sorted.map(item => {
              const secs = remaining[item.instrument_id] ?? 0
              return (
                <div
                  key={item.instrument_id}
                  className={`rounded-xl border p-4 ${th.card} ${secs <= 30 * 60 && secs > 0 ? (isDark ? 'border-red-800/50' : 'border-red-200') : ''}`}
                >
                  {/* Top row */}
                  <div className="flex items-start justify-between gap-4 flex-wrap">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={`font-mono text-sm font-semibold ${th.heading}`}>
                        {item.instrument_id}
                      </span>
                      <TierBadge tier={item.queue_tier} isDark={isDark} />
                      <StatusBadge status={item.status} claimedBy={item.claimed_by} isDark={isDark} />
                    </div>
                    <div className="flex items-center gap-1.5">
                      <span className={`text-xs ${th.muted}`}>IET</span>
                      <span className={`font-mono text-sm tabular-nums ${ietColor(secs, isDark)}`}>
                        {fmtCountdown(secs)}
                      </span>
                    </div>
                  </div>

                  {/* Details */}
                  <div className={`mt-3 grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs ${th.muted}`}>
                    <div>
                      <div className={`uppercase tracking-wide text-[10px] mb-0.5 ${th.faint}`}>Account</div>
                      <div className={`font-mono ${th.body}`}>{item.account_display ?? '****????'}</div>
                    </div>
                    <div>
                      <div className={`uppercase tracking-wide text-[10px] mb-0.5 ${th.faint}`}>Amount</div>
                      <div className={th.body}>{item.amount_display ?? '—'}</div>
                    </div>
                    <div>
                      <div className={`uppercase tracking-wide text-[10px] mb-0.5 ${th.faint}`}>Payee</div>
                      <div className={th.body}>{item.payee_display ?? '—'}</div>
                    </div>
                    <div>
                      <div className={`uppercase tracking-wide text-[10px] mb-0.5 ${th.faint}`}>Risk Flags</div>
                      <div className={`${th.body} truncate`}>{(item.risk_flags ?? []).join(', ') || 'None'}</div>
                    </div>
                  </div>

                  {/* AI summary if present */}
                  {item.ai_summary && (
                    <div className={`mt-3 text-xs rounded-lg px-3 py-2 ${isDark ? 'bg-white/3 text-slate-400' : 'bg-slate-50 text-slate-600'}`}>
                      <span className={`font-medium ${th.body}`}>AI: </span>
                      {item.ai_summary}
                    </div>
                  )}

                  {/* Actions */}
                  <div className="mt-3">
                    <ActionRow
                      item={item}
                      onClaim={handleClaim}
                      onHold={setHoldTarget}
                      onConfirm={handleConfirm}
                      onReturn={setReturnTarget}
                      isDark={isDark}
                      loadingId={loadingId}
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

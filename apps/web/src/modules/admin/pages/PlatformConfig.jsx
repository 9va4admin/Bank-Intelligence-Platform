/**
 * PlatformConfig — Layer 2 deployment topology config, bank_it_admin only.
 *
 * Route: /admin/config/platform  (permission: config:layer2:change)
 * Role:  bank_it_admin only (no ops_manager access)
 *
 * Layer 2 lives in infra/helm/values/banks/{bank_id}/*.yaml and requires
 * a Helm upgrade (no hot-reload). Changes go through:
 *   bank_it_admin raises request → ASTRA vendor reviews → CAB approval
 *   → ArgoCD updates targetRevision → rolling deploy.
 *
 * Submit: POST /v1/admin/config/platform/change-request
 *   → Immudb (CONFIG_L2_CHANGE_REQUESTED) → notification to ASTRA support
 * Change Requests: GET /v1/admin/config/platform/change-requests
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'

// ─── Layer 2 config schema (UI metadata — values are from last Helm deploy) ─────

const PLATFORM_META = [
  { key: 'cts.namespace',               label: 'CTS Namespace',                  type: 'string',  category: 'Kubernetes', editable: false,
    desc: 'Kubernetes namespace for all CTS workloads. Follows convention astra-cts-{bank_id}. Separate ResourceQuota and LimitRange enforced.' },
  { key: 'ej.namespace',                label: 'EJ Namespace',                   type: 'string',  category: 'Kubernetes', editable: false,
    desc: 'Kubernetes namespace for all EJ workloads. Istio AuthorizationPolicy blocks cross-namespace CTS↔EJ traffic.' },
  { key: 'cts.workers.min_replicas',    label: 'CTS Worker Min Replicas',        type: 'integer', category: 'Kubernetes', editable: true,
    desc: 'Minimum number of warm CTS agent worker pods. KEDA scales up from this baseline on Kafka lag > 10. Never set to 0 — cold start latency would breach IET.' },
  { key: 'cts.workers.max_replicas',    label: 'CTS Worker Max Replicas',        type: 'integer', category: 'Kubernetes', editable: true,
    desc: 'Maximum CTS worker pods KEDA can scale to. Should match expected peak batch size. 500 pods → 500 parallel cheque agents → entire batch < 600ms p99.' },
  { key: 'redis.cts.cluster_size',      label: 'CTS Redis Cluster Size',         type: 'integer', category: 'Redis',      editable: false,
    desc: 'Number of Redis nodes in the CTS cluster (Signature Vault + PPS Vault). 6 = 3 primaries + 3 replicas (3+3 across 2 DCs). Must be ≥ 6 for active-active.' },
  { key: 'redis.cts.max_memory_gb',     label: 'CTS Redis Max Memory (GB)',      type: 'integer', category: 'Redis',      editable: true,
    desc: 'Maximum memory per CTS Redis node. Vault warm size depends on number of active accounts. Raise before VaultSyncWorkflow reports evictions.' },
  { key: 'yugabyte.replication_factor', label: 'YugabyteDB Replication Factor', type: 'integer', category: 'YugabyteDB', editable: false,
    desc: 'YSQL replication factor across YugabyteDB nodes. RF=3 means any 1 node can fail without data loss. Minimum for active-active DC setup. Do not lower.' },
  { key: 'yugabyte.pgbouncer_cts_max_connections', label: 'CTS pgbouncer Max Connections', type: 'integer', category: 'YugabyteDB', editable: true,
    desc: 'Maximum connections pgbouncer-cts pool can hold open. Each CTS worker pod uses up to 10. 500 pods × 10 = 5000 connection requests → pooled to 200 DB connections.' },
  { key: 'kafka.min_insync_replicas',   label: 'Kafka Min In-Sync Replicas',    type: 'integer', category: 'Kafka',      editable: false,
    desc: 'Minimum replicas that must acknowledge before a Kafka write is considered durable. min.insync.replicas=2 with replication-factor=3 means 1 broker can fail without data loss.' },
  { key: 'kafka.cts.retention_hours',   label: 'CTS Topic Retention (hours)',    type: 'integer', category: 'Kafka',      editable: true,
    desc: 'Message retention on cts.* topics. 48 hours gives a recovery window if the Temporal worker is down during a DC failover. Must be > IET window (3 hours).' },
  { key: 'temporal.cts.task_queue_partitions', label: 'CTS Task Queue Partitions', type: 'integer', category: 'Temporal', editable: true,
    desc: 'Number of Temporal task queue partitions for CTS processing. Higher = better parallelism for large batches. Each partition served by dedicated worker threads.' },
  { key: 'temporal.namespace',          label: 'Temporal Namespace',             type: 'string',  category: 'Temporal',   editable: false,
    desc: 'Temporal namespace for CTS workflows. Isolated from EJ namespace — workflow IDs, history, and schedules do not cross module boundaries.' },
  { key: 'platform.min_tls_version',    label: 'Minimum TLS Version',           type: 'string',  category: 'Platform Constraints', editable: false, layer1: true,
    desc: 'Minimum TLS version for all inter-service and external connections. Layer 1 — LOCKED by ASTRA platform. Cannot be overridden by any bank configuration.' },
  { key: 'platform.audit_trail_enabled', label: 'Audit Trail',                  type: 'string',  category: 'Platform Constraints', editable: false, layer1: true,
    desc: 'Immudb cryptographic audit trail. Layer 1 — always on. Cannot be disabled. Tampering is cryptographically detectable via Merkle tree verification.' },
  { key: 'platform.hsm_required',       label: 'HSM Required for PKI',          type: 'string',  category: 'Platform Constraints', editable: false, layer1: true,
    desc: 'All NGCH PKI signing must use FIPS 140-2 Level 3 HSM. No software-held private keys permitted. Layer 1 — LOCKED.' },
  { key: 'platform.iet_watchdog_enabled', label: 'IET Watchdog',                type: 'string',  category: 'Platform Constraints', editable: false, layer1: true,
    desc: 'IETWatchdogWorkflow spawned as first child of every ChequeProcessingWorkflow. Fires emergency NGCH filing at T-30s. Layer 1 — LOCKED. Cannot be disabled.' },
]

// Default display values (from last Helm deploy — read-only display, actual values in values.yaml)
const PLATFORM_DEFAULTS = {
  'cts.namespace':                      'astra-cts-{bank_id}',
  'ej.namespace':                       'astra-ej-{bank_id}',
  'cts.workers.min_replicas':           '2',
  'cts.workers.max_replicas':           '500',
  'redis.cts.cluster_size':             '6',
  'redis.cts.max_memory_gb':            '32',
  'yugabyte.replication_factor':        '3',
  'yugabyte.pgbouncer_cts_max_connections': '200',
  'kafka.min_insync_replicas':          '2',
  'kafka.cts.retention_hours':          '48',
  'temporal.cts.task_queue_partitions': '4',
  'temporal.namespace':                 'astra-cts-{bank_id}',
  'platform.min_tls_version':           'TLS 1.3',
  'platform.audit_trail_enabled':       'true',
  'platform.hsm_required':              'true',
  'platform.iet_watchdog_enabled':      'true',
}

const CATEGORIES = ['All', 'Kubernetes', 'Redis', 'YugabyteDB', 'Kafka', 'Temporal', 'Platform Constraints']

// ─── API helpers ──────────────────────────────────────────────────────────────

async function fetchLayer2Requests() {
  const res = await fetch('/v1/admin/config/platform/change-requests', { credentials: 'include' })
  if (!res.ok) return { requests: [] }
  return res.json()
}

async function postLayer2Request({ config_key, current_value, requested_value, reason, cab_ticket }) {
  const res = await fetch('/v1/admin/config/platform/change-request', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ config_key, current_value, requested_value, reason, cab_ticket }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function PlatformConfig() {
  const { isDark } = useTheme()
  const { bankId } = useBankContext()
  const queryClient = useQueryClient()

  const [cat, setCat] = useState('All')
  const [tab, setTab] = useState('config')
  const [requesting, setRequesting] = useState(null)
  const [reqVal, setReqVal] = useState('')
  const [reqNote, setReqNote] = useState('')
  const [cabTicket, setCabTicket] = useState('')
  const [reasonErr, setReasonErr] = useState('')
  const [submitted, setSubmitted] = useState(null)
  const [submitError, setSubmitError] = useState(null)

  const th = {
    page:    isDark ? 'bg-transparent' : 'bg-slate-50',
    card:    isDark ? 'bg-white/3 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'         : 'text-slate-900',
    body:    isDark ? 'text-slate-300'     : 'text-slate-700',
    muted:   isDark ? 'text-slate-400'     : 'text-slate-500',
    faint:   isDark ? 'text-slate-600'     : 'text-slate-400',
    divider: isDark ? 'border-white/8'     : 'border-slate-200',
    row:     isDark ? 'border-white/5 hover:bg-white/3' : 'border-slate-100 hover:bg-slate-50',
    input:   isDark ? 'bg-white/5 border-white/10 text-white focus:border-sky-500' : 'bg-white border-slate-300 text-slate-900 focus:border-sky-500',
  }

  // Fetch Layer 2 change requests from DB
  const { data: requestsData, isLoading: requestsLoading } = useQuery({
    queryKey: ['admin-layer2-requests', bankId],
    queryFn: fetchLayer2Requests,
    enabled: tab === 'change-requests',
    staleTime: 15_000,
  })

  // Submit mutation
  const submitMutation = useMutation({
    mutationFn: postLayer2Request,
    onSuccess: (data) => {
      setSubmitted(data.request_id)
      setRequesting(null)
      setReqNote('')
      setReqVal('')
      setCabTicket('')
      setSubmitError(null)
      queryClient.invalidateQueries({ queryKey: ['admin-layer2-requests', bankId] })
    },
    onError: (err) => {
      setSubmitError(err.message)
    },
  })

  const configItems = PLATFORM_META.map(m => ({
    ...m,
    value: PLATFORM_DEFAULTS[m.key] ?? '—',
  }))
  const displayed = configItems.filter(c => cat === 'All' || c.category === cat)
  const l2Requests = requestsData?.requests ?? []

  function openRequest(cfg) {
    setRequesting(cfg)
    setReqVal(String(cfg.value))
    setReqNote('')
    setCabTicket('')
    setReasonErr('')
    setSubmitError(null)
  }

  function doSubmitRequest() {
    if (!reqNote.trim() || reqNote.trim().length < 10) {
      setReasonErr('Reason must be at least 10 characters')
      return
    }
    if (!cabTicket.trim()) {
      setReasonErr('CAB ticket reference is required')
      return
    }
    setReasonErr('')
    submitMutation.mutate({
      config_key: requesting.key,
      current_value: String(requesting.value),
      requested_value: reqVal,
      reason: reqNote.trim(),
      cab_ticket: cabTicket.trim(),
    })
  }

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>

        {/* Header */}
        <div className="mb-5">
          <div className="flex items-center gap-3 mb-1">
            <h1 className={`text-lg font-semibold ${th.heading}`}>Platform Config</h1>
            <span className={`text-xs px-2 py-0.5 rounded border font-medium ${isDark ? 'border-sky-700/40 bg-sky-900/30 text-sky-300' : 'border-sky-200 bg-sky-50 text-sky-700'}`}>
              Layer 2
            </span>
          </div>
          <p className={`text-xs ${th.muted}`}>
            Deployment topology and infrastructure settings. Changes require ASTRA vendor review, CAB approval, and a
            Helm upgrade (no hot-reload). Layer 1 platform constraints are shown read-only for reference.
          </p>
        </div>

        {/* Lifecycle callout */}
        <div className={`mb-5 rounded-lg border px-4 py-3 text-xs leading-relaxed ${isDark ? 'border-sky-700/30 bg-sky-900/15 text-sky-300' : 'border-sky-200 bg-sky-50 text-sky-700'}`}>
          <strong>Change process:</strong> bank_it_admin raises request below → ASTRA vendor reviews → CAB approval (your bank's process) →
          ArgoCD updates <code className="font-mono">targetRevision</code> → Alembic pre-upgrade job → rolling deploy → smoke tests.
          Rollback in &lt; 10 minutes if smoke tests fail.
        </div>

        {/* Tabs */}
        <div className={`flex gap-1 mb-5 border-b ${th.divider}`}>
          {[['config', 'Current Config'], ['change-requests', 'Change Requests']].map(([id, label]) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={`px-4 py-2 text-xs font-medium transition-colors border-b-2 -mb-px ${tab === id ? 'border-sky-500 text-sky-400' : `border-transparent ${th.muted}`}`}
            >
              {label}
            </button>
          ))}
        </div>

        {tab === 'config' && (
          <>
            {submitted && (
              <div className={`mb-4 rounded-lg border px-4 py-3 text-xs ${isDark ? 'border-emerald-700/40 bg-emerald-900/20 text-emerald-300' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>
                Change request raised (ref: {submitted}). ASTRA vendor will review and schedule a maintenance window for the Helm upgrade.
                Audit record written to Immudb. Notification sent to ASTRA support.
              </div>
            )}

            {/* Category filter */}
            <div className="flex gap-1.5 flex-wrap mb-4">
              {CATEGORIES.map(c => (
                <button
                  key={c}
                  onClick={() => setCat(c)}
                  className={`px-3 h-7 rounded-lg text-xs font-medium transition-all border ${
                    cat === c
                      ? 'bg-sky-600 text-white border-sky-600'
                      : `${th.card} ${th.muted}`
                  }`}
                >
                  {c}
                </button>
              ))}
            </div>

            {/* Config cards */}
            <div className="space-y-3">
              {displayed.map(cfg => (
                <div key={cfg.key} className={`rounded-xl border px-5 py-4 ${th.card}`}>
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className={`font-medium text-sm ${th.heading}`}>{cfg.label}</span>
                        {cfg.layer1 ? (
                          <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${isDark ? 'bg-red-900/30 text-red-400' : 'bg-red-100 text-red-600'}`}>Layer 1</span>
                        ) : (
                          <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${isDark ? 'bg-white/5 text-slate-400' : 'bg-slate-100 text-slate-500'}`}>Layer 2</span>
                        )}
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${isDark ? 'bg-white/5 text-slate-500' : 'bg-slate-50 text-slate-400'}`}>
                          {cfg.category}
                        </span>
                        {!cfg.editable && (
                          <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${isDark ? 'bg-white/5 text-slate-500' : 'bg-slate-100 text-slate-400'}`}>
                            READ-ONLY
                          </span>
                        )}
                      </div>
                      <p className={`text-xs mt-1 leading-relaxed ${th.muted}`}>{cfg.desc}</p>
                      <p className={`text-[11px] mt-0.5 font-mono ${th.faint}`}>{cfg.key}</p>
                    </div>

                    <div className="flex items-center gap-3 shrink-0">
                      <div className="text-right">
                        <div className={`text-xl font-bold tabular-nums ${th.heading}`}>
                          {cfg.type === 'integer' && !isNaN(parseInt(cfg.value, 10))
                            ? parseInt(cfg.value, 10).toLocaleString('en-IN')
                            : cfg.value}
                        </div>
                      </div>
                      {cfg.editable && !cfg.layer1 && (
                        <button
                          onClick={() => openRequest(cfg)}
                          className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all border ${isDark ? 'bg-sky-700/40 text-sky-300 hover:bg-sky-700/60 border-sky-700/40' : 'bg-sky-50 text-sky-700 hover:bg-sky-100 border-sky-200'}`}
                        >
                          Request Change
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}

        {tab === 'change-requests' && (
          <div className={`rounded-xl border overflow-hidden ${th.card}`}>
            {requestsLoading ? (
              <div className={`px-5 py-8 text-xs text-center ${th.muted}`}>Loading change requests…</div>
            ) : l2Requests.length === 0 ? (
              <div className={`px-5 py-8 text-xs text-center ${th.muted}`}>No Layer 2 change requests on record.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className={`border-b ${th.divider}`}>
                      {['Config Key', 'Current', 'Requested', 'By', 'CAB Ticket', 'Submitted At', 'Status'].map(h => (
                        <th key={h} className={`px-4 py-3 text-left font-medium whitespace-nowrap ${th.muted}`}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {l2Requests.map((r, i) => (
                      <tr key={r.request_id ?? i} className={`border-b transition-colors ${th.row}`}>
                        <td className={`px-4 py-3 font-mono text-[11px] ${th.body}`}>{r.config_key}</td>
                        <td className={`px-4 py-3 ${th.muted} line-through`}>{r.current_value}</td>
                        <td className={`px-4 py-3 font-semibold ${isDark ? 'text-sky-300' : 'text-sky-700'}`}>{r.requested_value}</td>
                        <td className={`px-4 py-3 ${th.body}`}>{r.submitted_by}</td>
                        <td className={`px-4 py-3 font-mono text-[11px] ${isDark ? 'text-sky-400' : 'text-sky-600'}`}>{r.cab_ticket}</td>
                        <td className={`px-4 py-3 font-mono text-[11px] whitespace-nowrap ${th.muted}`}>
                          {r.submitted_at ? new Date(r.submitted_at).toLocaleString('en-IN') : '—'}
                        </td>
                        <td className="px-4 py-3">
                          <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold whitespace-nowrap ${
                            r.status === 'DEPLOYED'
                              ? (isDark ? 'bg-emerald-900/40 text-emerald-300' : 'bg-emerald-100 text-emerald-700')
                              : r.status === 'REJECTED'
                                ? (isDark ? 'bg-red-900/40 text-red-300' : 'bg-red-100 text-red-700')
                                : (isDark ? 'bg-amber-900/40 text-amber-300' : 'bg-amber-100 text-amber-700')
                          }`}>
                            {r.status === 'PENDING_ASTRA_REVIEW' ? 'PENDING REVIEW' : r.status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Change request modal */}
      {requesting && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.65)' }}>
          <div className={`w-full max-w-lg rounded-2xl border p-6 shadow-2xl ${isDark ? 'bg-[#0e1428] border-white/10' : 'bg-white border-slate-200'}`}>
            <div className="flex items-center justify-between mb-4">
              <h3 className={`font-semibold ${th.heading}`}>Request Change — {requesting.label}</h3>
              <button onClick={() => setRequesting(null)} className={`${th.muted} text-lg leading-none`}>✕</button>
            </div>

            <p className={`text-xs mb-4 leading-relaxed ${th.muted}`}>{requesting.desc}</p>

            <div className="space-y-3 mb-4">
              <div>
                <label className={`text-xs font-medium ${th.muted}`}>Requested value</label>
                <input
                  type={requesting.type === 'integer' ? 'number' : 'text'}
                  value={reqVal}
                  onChange={e => setReqVal(e.target.value)}
                  className={`w-full mt-1 h-9 px-3 rounded-lg border text-sm outline-none transition-colors ${th.input}`}
                />
              </div>
              <div>
                <label className={`text-xs font-medium ${th.muted}`}>CAB ticket reference <span className="text-red-400">*</span></label>
                <input
                  type="text"
                  value={cabTicket}
                  onChange={e => { setCabTicket(e.target.value); setReasonErr('') }}
                  placeholder="e.g. CAB-2026-0921"
                  className={`w-full mt-1 h-9 px-3 rounded-lg border text-sm outline-none transition-colors ${th.input}`}
                />
              </div>
              <div>
                <label className={`text-xs font-medium ${th.muted}`}>Reason / business justification <span className="text-red-400">*</span></label>
                <textarea
                  value={reqNote}
                  onChange={e => { setReqNote(e.target.value); setReasonErr('') }}
                  placeholder="Explain why this change is needed and the impact assessment… (min 10 chars)"
                  rows={3}
                  className={`w-full mt-1 text-xs rounded-lg border px-3 py-2 resize-none outline-none transition-colors ${th.input}`}
                />
                {reasonErr && <p className="text-[11px] mt-1 text-red-400">{reasonErr}</p>}
              </div>
            </div>

            {submitError && (
              <div className={`mb-3 rounded-lg border px-3 py-2 text-xs ${isDark ? 'border-red-700/40 bg-red-900/20 text-red-300' : 'border-red-200 bg-red-50 text-red-700'}`}>
                {submitError}
              </div>
            )}

            <div className={`mb-4 p-3 rounded-lg text-xs leading-relaxed ${isDark ? 'bg-sky-900/20 border border-sky-700/40 text-sky-300' : 'bg-sky-50 border border-sky-200 text-sky-800'}`}>
              This request will be sent to ASTRA vendor support for review and audited in Immudb.
              A maintenance window will be scheduled for the Helm upgrade after CAB approval.
              Rollback is automatic if post-upgrade smoke tests fail.
            </div>

            <div className="flex gap-2">
              <button
                onClick={() => setRequesting(null)}
                className={`flex-1 px-3 py-2 rounded-lg text-xs font-medium ${isDark ? 'bg-white/5 text-slate-300 hover:bg-white/10' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'}`}
              >
                Cancel
              </button>
              <button
                onClick={doSubmitRequest}
                disabled={submitMutation.isPending}
                className={`flex-1 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${submitMutation.isPending ? 'opacity-60 cursor-not-allowed bg-sky-700 text-white' : 'bg-sky-600 hover:bg-sky-500 text-white'}`}
              >
                {submitMutation.isPending ? 'Raising request…' : 'Raise Change Request'}
              </button>
            </div>
          </div>
        </div>
      )}
    </AppShell>
  )
}

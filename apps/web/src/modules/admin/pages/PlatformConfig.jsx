/**
 * PlatformConfig — Layer 2 deployment topology config, bank_it_admin only.
 *
 * Route: /admin/config/platform  (permission: config:layer2:change)
 * Role:  bank_it_admin (maker) + bank_it_admin-peer or ASTRA vendor (checker)
 *
 * Layer 2 lives in infra/helm/values/banks/{bank_id}/*.yaml and requires
 * a Helm upgrade (no hot-reload). Changes go through:
 *   bank_it_admin raises change request → ASTRA vendor reviews → CAB approval
 *   → ArgoCD updates targetRevision → rolling deploy.
 *
 * This page shows current deployed values (read from config_service Layer 2 snapshot)
 * and allows raising a change request to ASTRA. It does NOT allow direct editing.
 */
import { useState } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'

// ─── Layer 2 config keys (infrastructure / deployment topology) ────────────────

const PLATFORM_CONFIG = [
  // ── Kubernetes / Namespace ──────────────────────────────────────────────
  {
    key: 'cts.namespace',
    label: 'CTS Namespace',
    value: 'astra-cts-saraswat-coop',
    type: 'string',
    category: 'Kubernetes',
    desc: 'Kubernetes namespace for all CTS workloads. Follows convention astra-cts-{bank_id}. Separate ResourceQuota and LimitRange enforced.',
    editable: false,
  },
  {
    key: 'ej.namespace',
    label: 'EJ Namespace',
    value: 'astra-ej-saraswat-coop',
    type: 'string',
    category: 'Kubernetes',
    desc: 'Kubernetes namespace for all EJ workloads. Istio AuthorizationPolicy blocks cross-namespace CTS↔EJ traffic.',
    editable: false,
  },
  {
    key: 'cts.workers.min_replicas',
    label: 'CTS Worker Min Replicas',
    value: 2,
    type: 'integer',
    category: 'Kubernetes',
    desc: 'Minimum number of warm CTS agent worker pods. KEDA scales up from this baseline on Kafka lag > 10. Never set to 0 — cold start latency would breach IET.',
    editable: true,
  },
  {
    key: 'cts.workers.max_replicas',
    label: 'CTS Worker Max Replicas',
    value: 500,
    type: 'integer',
    category: 'Kubernetes',
    desc: 'Maximum CTS worker pods KEDA can scale to. Should match expected peak batch size. 500 pods → 500 parallel cheque agents → entire batch < 600ms p99.',
    editable: true,
  },

  // ── Redis ───────────────────────────────────────────────────────────────
  {
    key: 'redis.cts.cluster_size',
    label: 'CTS Redis Cluster Size',
    value: 6,
    type: 'integer',
    category: 'Redis',
    desc: 'Number of Redis nodes in the CTS cluster (Signature Vault + PPS Vault). 6 = 3 primaries + 3 replicas (3+3 across 2 DCs). Must be ≥ 6 for active-active.',
    editable: false,
  },
  {
    key: 'redis.cts.max_memory_gb',
    label: 'CTS Redis Max Memory (GB)',
    value: 32,
    type: 'integer',
    category: 'Redis',
    desc: 'Maximum memory per CTS Redis node. Vault warm size depends on number of active accounts. Raise before VaultSyncWorkflow reports evictions.',
    editable: true,
  },

  // ── YugabyteDB ──────────────────────────────────────────────────────────
  {
    key: 'yugabyte.replication_factor',
    label: 'YugabyteDB Replication Factor',
    value: 3,
    type: 'integer',
    category: 'YugabyteDB',
    desc: 'YSQL replication factor across YugabyteDB nodes. RF=3 means any 1 node can fail without data loss. Minimum for active-active DC setup. Do not lower.',
    editable: false,
  },
  {
    key: 'yugabyte.pgbouncer_cts_max_connections',
    label: 'CTS pgbouncer Max Connections',
    value: 200,
    type: 'integer',
    category: 'YugabyteDB',
    desc: 'Maximum connections pgbouncer-cts pool can hold open. Each CTS worker pod uses up to 10. 500 pods × 10 = 5000 connection requests → pooled to 200 DB connections.',
    editable: true,
  },

  // ── Kafka ───────────────────────────────────────────────────────────────
  {
    key: 'kafka.min_insync_replicas',
    label: 'Kafka Min In-Sync Replicas',
    value: 2,
    type: 'integer',
    category: 'Kafka',
    desc: 'Minimum replicas that must acknowledge before a Kafka write is considered durable. min.insync.replicas=2 with replication-factor=3 means 1 broker can fail without data loss.',
    editable: false,
  },
  {
    key: 'kafka.cts.retention_hours',
    label: 'CTS Topic Retention (hours)',
    value: 48,
    type: 'integer',
    category: 'Kafka',
    desc: 'Message retention on cts.* topics. 48 hours gives a recovery window if the Temporal worker is down during a DC failover. Must be > IET window (3 hours).',
    editable: true,
  },

  // ── Temporal ────────────────────────────────────────────────────────────
  {
    key: 'temporal.cts.task_queue_partitions',
    label: 'CTS Task Queue Partitions',
    value: 4,
    type: 'integer',
    category: 'Temporal',
    desc: 'Number of Temporal task queue partitions for CTS processing. Higher = better parallelism for large batches. Each partition served by dedicated worker threads.',
    editable: true,
  },
  {
    key: 'temporal.namespace',
    label: 'Temporal Namespace',
    value: 'astra-cts-saraswat-coop',
    type: 'string',
    category: 'Temporal',
    desc: 'Temporal namespace for CTS workflows. Isolated from EJ namespace — workflow IDs, history, and schedules do not cross module boundaries.',
    editable: false,
  },

  // ── Platform Constraints (Layer 1 — read-only display) ─────────────────
  {
    key: 'platform.min_tls_version',
    label: 'Minimum TLS Version',
    value: 'TLS 1.3',
    type: 'string',
    category: 'Platform Constraints',
    desc: 'Minimum TLS version for all inter-service and external connections. Layer 1 — LOCKED by ASTRA platform. Cannot be overridden by any bank configuration.',
    editable: false,
    layer1: true,
  },
  {
    key: 'platform.audit_trail_enabled',
    label: 'Audit Trail',
    value: 'true',
    type: 'string',
    category: 'Platform Constraints',
    desc: 'Immudb cryptographic audit trail. Layer 1 — always on. Cannot be disabled. Tampering is cryptographically detectable via Merkle tree verification.',
    editable: false,
    layer1: true,
  },
  {
    key: 'platform.hsm_required',
    label: 'HSM Required for PKI',
    value: 'true',
    type: 'string',
    category: 'Platform Constraints',
    desc: 'All NGCH PKI signing must use FIPS 140-2 Level 3 HSM. No software-held private keys permitted. Layer 1 — LOCKED.',
    editable: false,
    layer1: true,
  },
  {
    key: 'platform.iet_watchdog_enabled',
    label: 'IET Watchdog',
    value: 'true',
    type: 'string',
    category: 'Platform Constraints',
    desc: 'IETWatchdogWorkflow spawned as first child of every ChequeProcessingWorkflow. Fires emergency NGCH filing at T-30s. Layer 1 — LOCKED. Cannot be disabled.',
    editable: false,
    layer1: true,
  },
]

const CATEGORIES = ['All', 'Kubernetes', 'Redis', 'YugabyteDB', 'Kafka', 'Temporal', 'Platform Constraints']

const CHANGE_REQUESTS = [
  { key: 'cts.workers.max_replicas', old: '200', new: '500', by: 'itadmin@svcb', astra_reviewer: 'support@astra.in', at: '2026-07-20 11:05', status: 'DEPLOYED', cab_ticket: 'CAB-2026-0847' },
  { key: 'redis.cts.max_memory_gb',  old: '16',  new: '32',  by: 'itadmin@svcb', astra_reviewer: 'support@astra.in', at: '2026-07-20 11:05', status: 'DEPLOYED', cab_ticket: 'CAB-2026-0847' },
  { key: 'kafka.cts.retention_hours', old: '24', new: '48',  by: 'itadmin@svcb', astra_reviewer: null,               at: '2026-08-02 16:30', status: 'PENDING_ASTRA_REVIEW', cab_ticket: 'CAB-2026-0921' },
]

// ─── Component ─────────────────────────────────────────────────────────────────

export default function PlatformConfig() {
  const { isDark } = useTheme()
  const { bankId, bankName } = useBankContext()
  const [cat, setCat] = useState('All')
  const [tab, setTab] = useState('config')
  const [requesting, setRequesting] = useState(null)
  const [reqNote, setReqNote] = useState('')
  const [reqVal, setReqVal] = useState('')
  const [submitted, setSubmitted] = useState(false)

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

  const displayed = PLATFORM_CONFIG.filter(c => cat === 'All' || c.category === cat)

  function openRequest(cfg) {
    setRequesting(cfg)
    setReqVal(String(cfg.value))
    setReqNote('')
    setSubmitted(false)
  }

  function submitRequest() {
    setTimeout(() => {
      setSubmitted(true)
      setRequesting(null)
    }, 700)
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
                Change request raised. ASTRA vendor will review and schedule a maintenance window for the Helm upgrade.
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
                          {typeof cfg.value === 'number' ? cfg.value.toLocaleString('en-IN') : cfg.value}
                        </div>
                      </div>
                      {cfg.editable && !cfg.layer1 && (
                        <button
                          onClick={() => openRequest(cfg)}
                          className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${isDark ? 'bg-sky-700/40 text-sky-300 hover:bg-sky-700/60 border border-sky-700/40' : 'bg-sky-50 text-sky-700 hover:bg-sky-100 border border-sky-200'}`}
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
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className={`border-b ${th.divider}`}>
                    {['Config Key', 'Old', 'Requested', 'By', 'ASTRA Reviewer', 'CAB Ticket', 'Timestamp', 'Status'].map(h => (
                      <th key={h} className={`px-4 py-3 text-left font-medium whitespace-nowrap ${th.muted}`}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {CHANGE_REQUESTS.map((c, i) => (
                    <tr key={i} className={`border-b transition-colors ${th.row}`}>
                      <td className={`px-4 py-3 font-mono text-[11px] ${th.body}`}>{c.key}</td>
                      <td className={`px-4 py-3 ${th.muted} line-through`}>{c.old}</td>
                      <td className={`px-4 py-3 font-semibold ${isDark ? 'text-sky-300' : 'text-sky-700'}`}>{c.new}</td>
                      <td className={`px-4 py-3 ${th.body}`}>{c.by}</td>
                      <td className={`px-4 py-3 ${th.body}`}>{c.astra_reviewer ?? <span className={th.muted}>Unassigned</span>}</td>
                      <td className={`px-4 py-3 font-mono text-[11px] ${isDark ? 'text-sky-400' : 'text-sky-600'}`}>{c.cab_ticket}</td>
                      <td className={`px-4 py-3 font-mono text-[11px] whitespace-nowrap ${th.muted}`}>{c.at}</td>
                      <td className="px-4 py-3">
                        <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold whitespace-nowrap ${
                          c.status === 'DEPLOYED'
                            ? (isDark ? 'bg-emerald-900/40 text-emerald-300' : 'bg-emerald-100 text-emerald-700')
                            : (isDark ? 'bg-amber-900/40 text-amber-300' : 'bg-amber-100 text-amber-700')
                        }`}>
                          {c.status === 'PENDING_ASTRA_REVIEW' ? 'PENDING REVIEW' : c.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
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

            <div className="space-y-3">
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
                <label className={`text-xs font-medium ${th.muted}`}>Reason / business justification</label>
                <textarea
                  value={reqNote}
                  onChange={e => setReqNote(e.target.value)}
                  placeholder="Explain why this change is needed and the impact assessment…"
                  rows={3}
                  className={`w-full mt-1 text-xs rounded-lg border px-3 py-2 resize-none outline-none transition-colors ${th.input}`}
                />
              </div>
            </div>

            <div className={`mt-4 p-3 rounded-lg text-xs leading-relaxed ${isDark ? 'bg-sky-900/20 border border-sky-700/40 text-sky-300' : 'bg-sky-50 border border-sky-200 text-sky-800'}`}>
              This request will be sent to ASTRA vendor support for review. A maintenance window will be
              scheduled for the Helm upgrade after CAB approval. Rollback is automatic if post-upgrade
              smoke tests fail.
            </div>

            <div className="flex gap-2 mt-4">
              <button
                onClick={() => setRequesting(null)}
                className={`flex-1 px-3 py-2 rounded-lg text-xs font-medium ${isDark ? 'bg-white/5 text-slate-300 hover:bg-white/10' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'}`}
              >
                Cancel
              </button>
              <button
                onClick={submitRequest}
                disabled={!reqNote.trim()}
                className={`flex-1 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${!reqNote.trim() ? 'opacity-50 cursor-not-allowed bg-sky-700 text-white' : 'bg-sky-600 hover:bg-sky-500 text-white'}`}
              >
                Raise Change Request
              </button>
            </div>
          </div>
        </div>
      )}
    </AppShell>
  )
}

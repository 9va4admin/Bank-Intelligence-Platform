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
import InfoTooltip from '../../../shared/components/InfoTooltip'
import { msg } from '../../../shared/messages'

// ─── Layer 2 config schema (UI metadata — values are from last Helm deploy) ─────

const PLATFORM_META = [
  { key: 'cts.namespace',               label: msg('UI_PLATFORMCONFIG_CTS_NAMESPACE_2'),                  type: 'string',  category: msg('UI_PLATFORMCONFIG_KUBERNETES_2'), editable: false,
    desc: msg('UI_PLATFORMCONFIG_KUBERNETES_NAMESPACE_FOR_ALL_CTS_2', { bank_id: '{bank_id}' }) },
  { key: 'ej.namespace',                label: msg('UI_PLATFORMCONFIG_EJ_NAMESPACE'),                   type: 'string',  category: msg('UI_PLATFORMCONFIG_KUBERNETES_2'), editable: false,
    desc: msg('UI_PLATFORMCONFIG_KUBERNETES_NAMESPACE_FOR_ALL_EJ') },
  { key: 'cts.workers.min_replicas',    label: msg('UI_PLATFORMCONFIG_CTS_WORKER_MIN_REPLICAS_2'),        type: 'integer', category: msg('UI_PLATFORMCONFIG_KUBERNETES_2'), editable: true,
    desc: msg('UI_PLATFORMCONFIG_MINIMUM_NUMBER_OF_WARM_CTS_2') },
  { key: 'cts.workers.max_replicas',    label: msg('UI_PLATFORMCONFIG_CTS_WORKER_MAX_REPLICAS_2'),        type: 'integer', category: msg('UI_PLATFORMCONFIG_KUBERNETES_2'), editable: true,
    desc: msg('UI_PLATFORMCONFIG_MAXIMUM_CTS_WORKER_PODS_KEDA_2') },
  { key: 'redis.cts.cluster_size',      label: msg('UI_PLATFORMCONFIG_CTS_REDIS_CLUSTER_SIZE_2'),         type: 'integer', category: msg('UI_PLATFORMCONFIG_REDIS_2'),      editable: false,
    desc: msg('UI_PLATFORMCONFIG_NUMBER_OF_REDIS_NODES_IN_2') },
  { key: 'redis.cts.max_memory_gb',     label: msg('UI_PLATFORMCONFIG_CTS_REDIS_MAX_MEMORY_GB_2'),      type: 'integer', category: msg('UI_PLATFORMCONFIG_REDIS_2'),      editable: true,
    desc: msg('UI_PLATFORMCONFIG_MAXIMUM_MEMORY_PER_CTS_REDIS_2') },
  { key: 'yugabyte.replication_factor', label: msg('UI_PLATFORMCONFIG_YUGABYTEDB_REPLICATION_FACTOR_2'), type: 'integer', category: msg('UI_PLATFORMCONFIG_YUGABYTEDB_2'), editable: false,
    desc: msg('UI_PLATFORMCONFIG_YSQL_REPLICATION_FACTOR_ACROSS_YUGAB_2') },
  { key: 'yugabyte.pgbouncer_cts_max_connections', label: msg('UI_PLATFORMCONFIG_CTS_PGBOUNCER_MAX_CONNECTIONS_2'), type: 'integer', category: msg('UI_PLATFORMCONFIG_YUGABYTEDB_2'), editable: true,
    desc: msg('UI_PLATFORMCONFIG_MAXIMUM_CONNECTIONS_PGBOUNCER_CTS_PO_2') },
  { key: 'kafka.min_insync_replicas',   label: msg('UI_PLATFORMCONFIG_KAFKA_MIN_IN_SYNC_REPLICAS_2'),    type: 'integer', category: msg('UI_PLATFORMCONFIG_KAFKA_2'),      editable: false,
    desc: msg('UI_PLATFORMCONFIG_MINIMUM_REPLICAS_THAT_MUST_ACKNOWLED_2') },
  { key: 'kafka.cts.retention_hours',   label: msg('UI_PLATFORMCONFIG_CTS_TOPIC_RETENTION_HOURS_2'),    type: 'integer', category: msg('UI_PLATFORMCONFIG_KAFKA_2'),      editable: true,
    desc: msg('UI_PLATFORMCONFIG_MESSAGE_RETENTION_ON_CTS_TOPICS_2') },
  { key: 'temporal.cts.task_queue_partitions', label: msg('UI_PLATFORMCONFIG_CTS_TASK_QUEUE_PARTITIONS_2'), type: 'integer', category: msg('UI_PLATFORMCONFIG_TEMPORAL_2'), editable: true,
    desc: msg('UI_PLATFORMCONFIG_NUMBER_OF_TEMPORAL_TASK_QUEUE_2') },
  { key: 'temporal.namespace',          label: msg('UI_PLATFORMCONFIG_TEMPORAL_NAMESPACE_2'),             type: 'string',  category: msg('UI_PLATFORMCONFIG_TEMPORAL_2'),   editable: false,
    desc: msg('UI_PLATFORMCONFIG_TEMPORAL_NAMESPACE_FOR_CTS_WORKFLOWS_2') },
  { key: 'platform.min_tls_version',    label: msg('UI_PLATFORMCONFIG_MINIMUM_TLS_VERSION_2'),           type: 'string',  category: msg('UI_PLATFORMCONFIG_PLATFORM_CONSTRAINTS_2'), editable: false, layer1: true,
    desc: msg('UI_PLATFORMCONFIG_MINIMUM_TLS_VERSION_FOR_ALL_2') },
  { key: 'platform.audit_trail_enabled', label: msg('UI_COMMON_AUDIT_TRAIL_2'),                  type: 'string',  category: msg('UI_PLATFORMCONFIG_PLATFORM_CONSTRAINTS_2'), editable: false, layer1: true,
    desc: msg('UI_PLATFORMCONFIG_IMMUDB_CRYPTOGRAPHIC_AUDIT_TRAIL_LAY_2') },
  { key: 'platform.hsm_required',       label: msg('UI_PLATFORMCONFIG_HSM_REQUIRED_FOR_PKI_2'),          type: 'string',  category: msg('UI_PLATFORMCONFIG_PLATFORM_CONSTRAINTS_2'), editable: false, layer1: true,
    desc: msg('UI_PLATFORMCONFIG_ALL_NGCH_PKI_SIGNING_MUST_2') },
  { key: 'platform.iet_watchdog_enabled', label: msg('UI_PLATFORMCONFIG_IET_WATCHDOG_2'),                type: 'string',  category: msg('UI_PLATFORMCONFIG_PLATFORM_CONSTRAINTS_2'), editable: false, layer1: true,
    desc: msg('UI_PLATFORMCONFIG_IETWATCHDOGWORKFLOW_SPAWNED_AS_FIRST_2') },
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
      setReasonErr(msg('UI_OPERATIONSCONFIG_REASON_MUST_BE_AT_LEAST_2'))
      return
    }
    if (!cabTicket.trim()) {
      setReasonErr(msg('UI_PLATFORMCONFIG_CAB_TICKET_REFERENCE_IS_REQUIRED_2'))
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
            <h1 className={`text-lg font-semibold ${th.heading}`}>{msg('UI_PLATFORMCONFIG_PLATFORM_CONFIG_2')}</h1>
            <span className={`text-xs px-2 py-0.5 rounded border font-medium ${isDark ? 'border-sky-700/40 bg-sky-900/30 text-sky-300' : 'border-sky-200 bg-sky-50 text-sky-700'}`}>
             {msg('UI_PLATFORMCONFIG_LAYER_2_2')}
            </span>
          </div>
          <p className={`text-xs ${th.muted}`}>
           {msg('UI_PLATFORMCONFIG_DEPLOYMENT_TOPOLOGY_AND_INFRASTRUCTU_2')}
          </p>
        </div>

        {/* Lifecycle callout */}
        <div className={`mb-5 rounded-lg border px-4 py-3 text-xs leading-relaxed ${isDark ? 'border-sky-700/30 bg-sky-900/15 text-sky-300' : 'border-sky-200 bg-sky-50 text-sky-700'}`}>
          <strong>{msg('UI_PLATFORMCONFIG_CHANGE_PROCESS_2')}</strong> {msg('UI_PLATFORMCONFIG_BANK_IT_ADMIN_RAISES_REQUEST_2')} <code className="font-mono">{msg('UI_PLATFORMCONFIG_TARGETREVISION_2')}</code> {msg('UI_PLATFORMCONFIG_ALEMBIC_PRE_UPGRADE_JOB_ROLLING_2')}
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
               {msg('UI_PLATFORMCONFIG_CHANGE_REQUEST_RAISED_REF_ASTRA_2', { submitted })}
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
                        <InfoTooltip text={cfg.desc} isDark={isDark} />
                        {cfg.layer1 ? (
                          <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${isDark ? 'bg-red-900/30 text-red-400' : 'bg-red-100 text-red-600'}`}>{msg('UI_PLATFORMCONFIG_LAYER_1_2')}</span>
                        ) : (
                          <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${isDark ? 'bg-white/5 text-slate-400' : 'bg-slate-100 text-slate-500'}`}>{msg('UI_PLATFORMCONFIG_LAYER_2_2')}</span>
                        )}
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${isDark ? 'bg-white/5 text-slate-500' : 'bg-slate-50 text-slate-400'}`}>
                          {cfg.category}
                        </span>
                        {!cfg.editable && (
                          <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${isDark ? 'bg-white/5 text-slate-500' : 'bg-slate-100 text-slate-400'}`}>
                           {msg('UI_PLATFORMCONFIG_READ_ONLY_2')}
                          </span>
                        )}
                      </div>
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
                         {msg('UI_PLATFORMCONFIG_REQUEST_CHANGE_3')}
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
              <div className={`px-5 py-8 text-xs text-center ${th.muted}`}>{msg('UI_PLATFORMCONFIG_LOADING_CHANGE_REQUESTS_2')}</div>
            ) : l2Requests.length === 0 ? (
              <div className={`px-5 py-8 text-xs text-center ${th.muted}`}>{msg('UI_PLATFORMCONFIG_NO_LAYER_2_CHANGE_REQUESTS_2')}</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className={`border-b ${th.divider}`}>
                      {[msg('UI_COMMON_CONFIG_KEY_2'), msg('UI_PLATFORMCONFIG_CURRENT_2'), msg('UI_PLATFORMCONFIG_REQUESTED_2'), msg('UI_PLATFORMCONFIG_BY_2'), msg('UI_PLATFORMCONFIG_CAB_TICKET_2'), msg('UI_OPERATIONSCONFIG_SUBMITTED_AT_2'), msg('UI_COMMON_STATUS_2')].map(h => (
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
                            {r.status === 'PENDING_ASTRA_REVIEW' ? msg('UI_PLATFORMCONFIG_PENDING_REVIEW_2') : r.status}
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
              <h3 className={`font-semibold ${th.heading}`}>{msg('UI_PLATFORMCONFIG_REQUEST_CHANGE_4', { label: requesting.label })}</h3>
              <button onClick={() => setRequesting(null)} className={`${th.muted} text-lg leading-none`}>✕</button>
            </div>

            <p className={`text-xs mb-4 leading-relaxed ${th.muted}`}>{requesting.desc}</p>

            <div className="space-y-3 mb-4">
              <div>
                <label className={`text-xs font-medium ${th.muted}`}>{msg('UI_PLATFORMCONFIG_REQUESTED_VALUE_2')}</label>
                <input
                  type={requesting.type === 'integer' ? 'number' : 'text'}
                  value={reqVal}
                  onChange={e => setReqVal(e.target.value)}
                  className={`w-full mt-1 h-9 px-3 rounded-lg border text-sm outline-none transition-colors ${th.input}`}
                />
              </div>
              <div>
                <label className={`text-xs font-medium ${th.muted}`}>{msg('UI_PLATFORMCONFIG_CAB_TICKET_REFERENCE_2')} <span className="text-red-400">*</span></label>
                <input
                  type="text"
                  value={cabTicket}
                  onChange={e => { setCabTicket(e.target.value); setReasonErr('') }}
                  placeholder={msg('UI_PLATFORMCONFIG_E_G_CAB_2026_0921_2')}
                  className={`w-full mt-1 h-9 px-3 rounded-lg border text-sm outline-none transition-colors ${th.input}`}
                />
              </div>
              <div>
                <label className={`text-xs font-medium ${th.muted}`}>{msg('UI_PLATFORMCONFIG_REASON_BUSINESS_JUSTIFICATION_2')} <span className="text-red-400">*</span></label>
                <textarea
                  value={reqNote}
                  onChange={e => { setReqNote(e.target.value); setReasonErr('') }}
                  placeholder={msg('UI_PLATFORMCONFIG_EXPLAIN_WHY_THIS_CHANGE_IS_2')}
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
             {msg('UI_PLATFORMCONFIG_THIS_REQUEST_WILL_BE_SENT_2')}
            </div>

            <div className="flex gap-2">
              <button
                onClick={() => setRequesting(null)}
                className={`flex-1 px-3 py-2 rounded-lg text-xs font-medium ${isDark ? 'bg-white/5 text-slate-300 hover:bg-white/10' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'}`}
              >
               {msg('UI_COMMON_CANCEL_2')}
              </button>
              <button
                onClick={doSubmitRequest}
                disabled={submitMutation.isPending}
                className={`flex-1 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${submitMutation.isPending ? 'opacity-60 cursor-not-allowed bg-sky-700 text-white' : 'bg-sky-600 hover:bg-sky-500 text-white'}`}
              >
                {submitMutation.isPending ? msg('UI_PLATFORMCONFIG_RAISING_REQUEST_2') : msg('UI_PLATFORMCONFIG_RAISE_CHANGE_REQUEST_2')}
              </button>
            </div>
          </div>
        </div>
      )}
    </AppShell>
  )
}

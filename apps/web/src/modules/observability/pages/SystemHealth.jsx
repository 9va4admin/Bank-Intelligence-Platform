/**
 * ASTRA System Health — infrastructure connectivity at a glance.
 *
 * Panels: Redis CTS, Redis EJ, YugabyteDB, HashiCorp Vault,
 *         Kafka consumer lag, Temporal workers.
 *
 * Access: ops_manager, bank_it_admin.
 * No PII. All panels degrade gracefully (200 + degraded=true when dep unavailable).
 */
import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'
import AppShell from '../../../shared/layout/AppShell'
import { msg } from '../../../shared/messages'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''
const REFRESH_MS = 60_000

function useSystemHealth(bankId, { enabled = true } = {}) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)
  const [lastFetch, setLastFetch] = useState(null)

  const load = useCallback(async () => {
    if (!enabled) return
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/v1/ops/system`, { credentials: 'include' })
      if (!res.ok) throw new Error(msg('UI_COMMON_HTTP', { status: res.status }))
      setData(await res.json())
      setLastFetch(new Date())
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [bankId, enabled])

  useEffect(() => {
    if (!enabled) return
    load()
    const t = setInterval(load, REFRESH_MS)
    return () => clearInterval(t)
  }, [load, enabled])

  return { data, loading, error, lastFetch, reload: load }
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatusDot({ ok }) {
  return (
    <span className={`w-2 h-2 rounded-full flex-shrink-0 ${ok ? 'bg-emerald-400' : 'bg-red-400 animate-pulse'}`} />
  )
}

function HealthCard({ title, icon, children, isDark, alert }) {
  const th = {
    card:    isDark ? 'bg-navy-900 border-white/8'  : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'                  : 'text-slate-900',
  }
  const ring = alert === 'critical'
    ? 'ring-2 ring-red-500/50'
    : alert === 'warn'
    ? 'ring-2 ring-amber-500/40'
    : ''
  return (
    <div className={`rounded-xl border px-5 py-4 ${th.card} ${ring}`}>
      <div className="flex items-center gap-2 mb-4">
        {icon && <span className="text-base">{icon}</span>}
        <h2 className={`text-sm font-semibold ${th.heading}`}>{title}</h2>
      </div>
      {children}
    </div>
  )
}

function ConnRow({ label, ok, value, isDark }) {
  const th = {
    label: isDark ? 'text-slate-400' : 'text-slate-500',
    value: isDark ? 'text-white'     : 'text-slate-900',
    divider: isDark ? 'border-white/5' : 'border-slate-100',
  }
  return (
    <div className={`flex items-center justify-between py-2 border-b last:border-0 ${th.divider}`}>
      <span className={`text-xs ${th.label}`}>{label}</span>
      {value !== undefined
        ? <span className={`text-sm font-medium tabular-nums ${th.value}`}>{value}</span>
        : <span className={`text-sm font-medium ${ok
            ? (isDark ? 'text-emerald-300' : 'text-emerald-700')
            : (isDark ? 'text-red-300'     : 'text-red-700')
          }`}>{ok ? msg('UI_COMMON_YES') : msg('UI_COMMON_NO')}</span>
      }
    </div>
  )
}

function DegradedNote({ isDark }) {
  return (
    <p className={`text-xs italic ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>
     {msg('UI_SYSTEMHEALTH_CLIENT_UNAVAILABLE_SIGNAL_DEGRADED')}
    </p>
  )
}

function HitRateBar({ pct, isDark }) {
  const color = pct >= 95 ? 'bg-emerald-400' : pct >= 80 ? 'bg-amber-400' : 'bg-red-400'
  return (
    <div className="mt-3">
      <div className={`h-1.5 rounded-full overflow-hidden ${isDark ? 'bg-white/8' : 'bg-slate-100'}`}>
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <p className={`text-[10px] mt-1 ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>
       {msg('UI_SYSTEMHEALTH_VAULT_HIT_RATE_TARGET_95')}
      </p>
    </div>
  )
}

function KafkaGroupRow({ group, isDark }) {
  const th = {
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    heading: isDark ? 'text-white'     : 'text-slate-900',
    badge:   isDark ? 'bg-white/8 text-slate-300' : 'bg-slate-100 text-slate-600',
    lag:     group.total_lag > 1000 ? 'text-red-400' : group.total_lag > 100 ? 'text-amber-400' : (isDark ? 'text-emerald-300' : 'text-emerald-700'),
  }
  return (
    <div className={`flex items-center justify-between py-1.5 border-b last:border-0 ${isDark ? 'border-white/5' : 'border-slate-100'}`}>
      <div className="min-w-0 flex items-center gap-2">
        <span className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${th.badge}`}>{group.topic_prefix}</span>
        <span className={`text-xs truncate ${th.muted}`}>{group.group_id}</span>
      </div>
      <span className={`text-xs font-semibold tabular-nums ml-2 ${th.lag}`}>
        {group.total_lag.toLocaleString('en-IN')}
      </span>
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function SystemHealth() {
  const { isDark } = useTheme()
  const { bankId, isDemo: isDemoBuild } = useBankContext()
  // VITE_BRANCH_MASTER_LIVE=true: read the real backend even in a DEMO build (otherwise this page stays on its placeholder).
  const isDemo = isDemoBuild && import.meta.env.VITE_BRANCH_MASTER_LIVE !== 'true'
  const { data, loading, error, lastFetch, reload } = useSystemHealth(bankId, { enabled: !isDemo })

  const th = {
    page:    isDark ? 'bg-navy-950'                 : 'bg-slate-50',
    heading: isDark ? 'text-white'                  : 'text-slate-900',
    muted:   isDark ? 'text-slate-400'              : 'text-slate-500',
    label:   isDark ? 'text-slate-400'              : 'text-slate-500',
    value:   isDark ? 'text-white'                  : 'text-slate-900',
    divider: isDark ? 'border-white/8'              : 'border-slate-100',
  }

  const redisCts  = data?.redis_cts  ?? { connected: false, hit_rate_pct: 0, degraded: true }
  const yb        = data?.yugabyte   ?? { connected: false, pool_size: 0, active_connections: 0, degraded: true }
  const vault     = data?.vault      ?? { connected: false, seal_status: 'UNKNOWN', degraded: true }
  const kafka     = data?.kafka      ?? { connected: false, groups: [], total_lag: 0, degraded: true }
  const temporal  = data?.temporal   ?? { connected: false, degraded: true }

  const vaultAlert = vault.connected && vault.seal_status === 'sealed' ? 'critical' : undefined
  const kafkaAlert = kafka.total_lag > 1000 ? 'warn' : undefined

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>

        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div>
            <div className="flex items-center gap-2 mb-0.5">
              <Link to="/ops/dashboard" className={`text-xs ${th.muted} hover:underline`}>{msg('UI_COMMON_OPS_DASHBOARD')}</Link>
              <span className={`text-xs ${th.muted}`}>/</span>
              <span className={`text-xs ${th.muted}`}>{msg('UI_COMMON_SYSTEM_HEALTH')}</span>
            </div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>{msg('UI_COMMON_SYSTEM_HEALTH')}</h1>
            <p className={`text-xs mt-0.5 ${th.muted}`}>
              {msg('UI_SYSTEMHEALTH_AUTO_REFRESH_60S', { value: lastFetch ? msg('UI_OPSDASHBOARD_UPDATED', { lastFetch: lastFetch.toLocaleTimeString() }) : msg('UI_OPSDASHBOARD_LOADING') })}
            </p>
          </div>
          <button
            onClick={reload}
            disabled={loading}
            className={`text-xs px-3 py-1.5 rounded-lg border font-medium transition-opacity disabled:opacity-50
              ${isDark ? 'border-white/12 text-slate-300 hover:bg-white/5' : 'border-slate-200 text-slate-700 hover:bg-slate-50'}`}
          >
            {loading ? msg('UI_OPSDASHBOARD_REFRESHING') : msg('UI_COMMON_REFRESH')}
          </button>
        </div>

        {error && (
          <div className={`text-sm px-4 py-3 rounded-xl mb-4 border
            ${isDark ? 'bg-red-900/10 border-red-700/30 text-red-400' : 'bg-red-50 border-red-200 text-red-700'}`}>
            {error}
          </div>
        )}

        {/* Infrastructure grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 mb-4">

          {/* Redis CTS */}
          <HealthCard title={msg('UI_SMOKETEST_REDIS_CTS')} icon="🟥" isDark={isDark}>
            <div className="flex items-center gap-2 mb-3">
              <StatusDot ok={redisCts.connected} />
              <span className={`text-sm font-medium ${redisCts.connected
                ? (isDark ? 'text-emerald-300' : 'text-emerald-700')
                : (isDark ? 'text-red-300'     : 'text-red-700')
              }`}>
                {redisCts.degraded ? msg('UI_SYSTEMHEALTH_UNAVAILABLE') : redisCts.connected ? msg('UI_SYSTEMHEALTH_CONNECTED') : msg('UI_HUBDASHBOARD_DISCONNECTED')}
              </span>
            </div>
            {redisCts.degraded ? <DegradedNote isDark={isDark} /> : (
              <>
                <ConnRow label={msg('UI_SYSTEMHEALTH_HIT_RATE')} value={`${redisCts.hit_rate_pct.toFixed(1)}%`} isDark={isDark} />
                <HitRateBar pct={redisCts.hit_rate_pct} isDark={isDark} />
              </>
            )}
          </HealthCard>

          {/* YugabyteDB */}
          <HealthCard title={msg('UI_SYSTEMHEALTH_YUGABYTEDB_CTS_POOL')} icon="🐘" isDark={isDark}>
            <div className="flex items-center gap-2 mb-3">
              <StatusDot ok={yb.connected} />
              <span className={`text-sm font-medium ${yb.connected
                ? (isDark ? 'text-emerald-300' : 'text-emerald-700')
                : (isDark ? 'text-red-300'     : 'text-red-700')
              }`}>
                {yb.degraded ? msg('UI_SYSTEMHEALTH_UNAVAILABLE') : yb.connected ? msg('UI_SYSTEMHEALTH_CONNECTED') : msg('UI_HUBDASHBOARD_DISCONNECTED')}
              </span>
            </div>
            {yb.degraded ? <DegradedNote isDark={isDark} /> : (
              <div className={`border-t ${th.divider} pt-3`}>
                <ConnRow label={msg('UI_SYSTEMHEALTH_POOL_SIZE')}    value={yb.pool_size}           isDark={isDark} />
                <ConnRow label={msg('UI_SYSTEMHEALTH_ACTIVE_CONNS')} value={yb.active_connections}  isDark={isDark} />
                <ConnRow label={msg('UI_SYSTEMHEALTH_IDLE_CONNS')}   value={Math.max(0, yb.pool_size - yb.active_connections)} isDark={isDark} />
              </div>
            )}
          </HealthCard>

          {/* HashiCorp Vault */}
          <HealthCard title={msg('UI_SYSTEMHEALTH_HASHICORP_VAULT')} icon="🔐" isDark={isDark} alert={vaultAlert}>
            <div className="flex items-center gap-2 mb-3">
              <StatusDot ok={vault.connected && vault.seal_status === 'unsealed'} />
              <span className={`text-sm font-medium ${
                vault.degraded ? (isDark ? 'text-slate-400' : 'text-slate-500')
                : vault.seal_status === 'sealed' ? 'text-red-400'
                : (isDark ? 'text-emerald-300' : 'text-emerald-700')
              }`}>
                {vault.degraded
                  ? msg('UI_SYSTEMHEALTH_UNAVAILABLE')
                  : vault.seal_status === 'unsealed' ? msg('UI_SYSTEMHEALTH_UNSEALED')
                  : vault.seal_status === 'sealed'   ? msg('UI_SYSTEMHEALTH_SEALED_ACTION_REQUIRED')
                  : msg('UI_SYSTEMHEALTH_UNKNOWN_STATE')
                }
              </span>
            </div>
            {vault.degraded ? <DegradedNote isDark={isDark} /> : (
              <div className={`border-t ${th.divider} pt-3`}>
                <ConnRow label={msg('UI_SYSTEMHEALTH_SEAL_STATUS')} value={vault.seal_status} isDark={isDark} />
              </div>
            )}
            {!vault.degraded && vault.seal_status === 'sealed' && (
              <p className="text-xs text-red-400 mt-2">
               {msg('UI_SYSTEMHEALTH_ALL_SECRETS_UNAVAILABLE_UNSEAL_VAULT')}
              </p>
            )}
          </HealthCard>

          {/* Kafka consumer groups */}
          <HealthCard title={msg('UI_SYSTEMHEALTH_KAFKA_CONSUMER_GROUPS')} icon="📨" isDark={isDark} alert={kafkaAlert}>
            <div className="flex items-center gap-2 mb-3">
              <StatusDot ok={kafka.connected && kafka.total_lag < 1000} />
              <span className={`text-sm font-medium ${kafka.connected
                ? kafka.total_lag > 1000
                  ? 'text-amber-400'
                  : (isDark ? 'text-emerald-300' : 'text-emerald-700')
                : (isDark ? 'text-red-300' : 'text-red-700')
              }`}>
                {kafka.degraded
                  ? msg('UI_SYSTEMHEALTH_UNAVAILABLE')
                  : kafka.connected
                  ? msg('UI_SYSTEMHEALTH_CONNECTED_TOTAL_LAG', { total_lag: kafka.total_lag.toLocaleString('en-IN') })
                  : msg('UI_HUBDASHBOARD_DISCONNECTED')
                }
              </span>
            </div>
            {kafka.degraded ? <DegradedNote isDark={isDark} /> : (
              <div className={`border-t ${th.divider} pt-3 space-y-0`}>
                {kafka.groups.length === 0 ? (
                  <p className={`text-xs ${th.muted}`}>{msg('UI_SYSTEMHEALTH_NO_CONSUMER_GROUPS_REGISTERED_YET')}</p>
                ) : (
                  kafka.groups.map(g => (
                    <KafkaGroupRow key={g.group_id} group={g} isDark={isDark} />
                  ))
                )}
              </div>
            )}
          </HealthCard>

          {/* Temporal */}
          <HealthCard title={msg('UI_SYSTEMHEALTH_TEMPORAL_WORKFLOW_ENGINE')} icon="⏱" isDark={isDark}>
            <div className="flex items-center gap-2 mb-3">
              <StatusDot ok={temporal.connected} />
              <span className={`text-sm font-medium ${temporal.connected
                ? (isDark ? 'text-emerald-300' : 'text-emerald-700')
                : (isDark ? 'text-red-300'     : 'text-red-700')
              }`}>
                {temporal.degraded ? msg('UI_SYSTEMHEALTH_UNAVAILABLE') : temporal.connected ? msg('UI_SYSTEMHEALTH_CONNECTED') : msg('UI_HUBDASHBOARD_DISCONNECTED')}
              </span>
            </div>
            {temporal.degraded ? <DegradedNote isDark={isDark} /> : (
              <div className={`border-t ${th.divider} pt-3`}>
                <ConnRow label={msg('UI_SYSTEMHEALTH_NAMESPACE')} value="default"       isDark={isDark} />
                <ConnRow label={msg('UI_SYSTEMHEALTH_REACHABLE')} ok={temporal.connected} isDark={isDark} />
              </div>
            )}
          </HealthCard>

        </div>

        {/* Footer note */}
        <p className={`text-xs mt-2 ${th.muted}`}>
         {msg('UI_SYSTEMHEALTH_OTEL_INSTRUMENTATION_ACTIVE_IN_ALL')}
          <code className={`mx-1 px-1.5 py-0.5 rounded text-[10px] ${isDark ? 'bg-white/8' : 'bg-slate-100'}`}>
           {msg('UI_SYSTEMHEALTH_ASTRA_OBSERVABILITY')}
          </code>
         {msg('UI_SYSTEMHEALTH_HELM_CHART')}
        </p>

      </div>
    </AppShell>
  )
}

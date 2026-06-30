import { useState, useCallback } from 'react'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'
import AppShell from '../../../shared/layout/AppShell'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

function useSecurityViolations() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/v1/admin/security-violations?limit=100`, {
        headers: { Authorization: 'Bearer test-token-saraswat-coop' },
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setData(await res.json())
    } catch (e) {
      setError(e.message)
      // Fallback to demo data so the page is useful in demo mode
      setData(DEMO_DATA)
    } finally {
      setLoading(false)
    }
  }, [])

  const reinstate = useCallback(async (userId) => {
    try {
      await fetch(`${API_BASE}/v1/admin/security-violations/${userId}/reinstate`, {
        method: 'POST',
        headers: { Authorization: 'Bearer test-token-saraswat-coop' },
      })
      await load()
    } catch {
      // reload anyway
      await load()
    }
  }, [load])

  return { data, loading, error, load, reinstate }
}

const SEVERITY_META = {
  TenantIsolationError: { label: 'Tenant Isolation',  color: 'red',    icon: '⛔' },
  BankIsolationError:   { label: 'Bank Isolation',    color: 'red',    icon: '⛔' },
  AccessDeniedError:    { label: 'Access Denied',     color: 'amber',  icon: '⚠' },
  EngagementExpiredError: { label: 'Engagement Expired', color: 'slate', icon: 'ℹ' },
}

function sev(violationType, isDark) {
  const m = SEVERITY_META[violationType] ?? { label: violationType, color: 'slate', icon: '?' }
  const col = m.color
  const dark = {
    red:   'bg-red-900/40 text-red-300 border-red-700/50',
    amber: 'bg-amber-900/40 text-amber-300 border-amber-700/50',
    slate: 'bg-slate-800 text-slate-300 border-slate-600',
  }
  const light = {
    red:   'bg-red-50 text-red-700 border-red-300',
    amber: 'bg-amber-50 text-amber-700 border-amber-300',
    slate: 'bg-slate-100 text-slate-600 border-slate-300',
  }
  return `${m.icon}  ${m.label}|${isDark ? dark[col] : light[col]}`
}

function relTime(isoStr) {
  if (!isoStr) return '—'
  const diff = Math.floor((Date.now() - new Date(isoStr).getTime()) / 1000)
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return new Date(isoStr).toLocaleDateString('en-IN')
}

const DEMO_DATA = {
  total: 3,
  suspended_count: 2,
  bank_id: 'saraswat-coop',
  violations: [
    {
      id: 'demo-1',
      timestamp_iso: new Date(Date.now() - 4 * 60 * 1000).toISOString(),
      violation_type: 'TenantIsolationError',
      suspended: true,
      user_id: 'smb-user-kjsb-07',
      bank_id: 'smb-mh-kjsb',
      bank_type: 'SMB',
      role: 'smb_editor',
      endpoint: '/v1/cts/smb/saraswat-coop/vault-sync',
      method: 'POST',
      client_ip: '10.42.3.21',
      request_id: 'req-abcd1234',
    },
    {
      id: 'demo-2',
      timestamp_iso: new Date(Date.now() - 28 * 60 * 1000).toISOString(),
      violation_type: 'BankIsolationError',
      suspended: true,
      user_id: 'smb-user-mucb-03',
      bank_id: 'smb-gj-mucb',
      bank_type: 'SMB',
      role: 'smb_admin',
      endpoint: '/v1/cts/inward/list?bank_id=smb-mh-kjsb',
      method: 'GET',
      client_ip: '10.42.7.88',
      request_id: 'req-efgh5678',
    },
    {
      id: 'demo-3',
      timestamp_iso: new Date(Date.now() - 2 * 3600 * 1000).toISOString(),
      violation_type: 'AccessDeniedError',
      suspended: false,
      user_id: 'reviewer-vasavi-12',
      bank_id: 'smb-mh-vasavi',
      bank_type: 'SMB',
      role: 'smb_viewer',
      endpoint: '/v1/admin/thresholds',
      method: 'POST',
      client_ip: '10.42.1.5',
      request_id: 'req-ijkl9012',
    },
  ],
}

export default function SecurityViolations() {
  const { isDark } = useTheme()
  const { bankName, isSB } = useBankContext()
  const { data, loading, error, load, reinstate } = useSecurityViolations()
  const [loaded, setLoaded] = useState(false)
  const [reinstating, setReinstating] = useState(null)

  if (!loaded) {
    return (
      <AppShell>
        <div className={`flex-1 overflow-y-auto px-6 py-8 ${isDark ? 'bg-navy-950' : 'bg-slate-50'}`}>
          <div className={`max-w-3xl mx-auto rounded-2xl border p-8 text-center ${isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200'}`}>
            <div className="text-3xl mb-3">🛡</div>
            <h1 className={`text-lg font-semibold mb-1 ${isDark ? 'text-white' : 'text-slate-900'}`}>Security Violation Log</h1>
            <p className={`text-sm mb-6 ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>
              Real-time log of unauthorised API access attempts. Accounts that attempt cross-bank data access are suspended immediately.
            </p>
            {!isSB && (
              <p className={`text-sm px-4 py-3 rounded-lg mb-6 ${isDark ? 'bg-amber-900/30 text-amber-300 border border-amber-700/40' : 'bg-amber-50 text-amber-700 border border-amber-200'}`}>
                This view is available to your Sponsor Bank's IT administrator.
              </p>
            )}
            <button
              onClick={() => { setLoaded(true); load() }}
              className="px-5 py-2 rounded-lg text-sm font-semibold bg-red-600 text-white hover:bg-red-500 transition-colors"
            >
              Load violation log
            </button>
          </div>
        </div>
      </AppShell>
    )
  }

  const violations = data?.violations ?? []
  const suspendedCount = data?.suspended_count ?? 0

  const th = {
    page:    isDark ? 'bg-navy-950' : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    row:     isDark ? 'border-white/4 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    badge:   isDark ? 'bg-red-900/40 text-red-300 border border-red-700/50' : 'bg-red-50 text-red-700 border border-red-200',
    ok:      isDark ? 'bg-emerald-900/30 text-emerald-300 border border-emerald-700/40' : 'bg-emerald-50 text-emerald-700 border border-emerald-200',
  }

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>

        {/* Header */}
        <div className="flex items-start justify-between gap-4 mb-5">
          <div>
            <div className="flex items-center gap-2 mb-0.5">
              <span className="text-red-500 text-lg">🛡</span>
              <h1 className={`text-lg font-semibold ${th.heading}`}>Security Violation Log</h1>
            </div>
            <p className={`text-xs ${th.muted}`}>{bankName} · bank_it_admin access only</p>
          </div>
          <button
            onClick={load}
            disabled={loading}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${isDark ? 'border-white/10 text-slate-300 hover:text-white hover:bg-white/8' : 'border-slate-200 text-slate-600 hover:bg-slate-100'} disabled:opacity-40`}
          >
            {loading ? 'Loading…' : '↻ Refresh'}
          </button>
        </div>

        {/* Summary stats */}
        <div className="grid grid-cols-3 gap-3 mb-5">
          {[
            { label: 'Total incidents', value: data?.total ?? 0, accent: isDark ? 'text-white' : 'text-slate-900' },
            { label: 'Accounts suspended', value: suspendedCount, accent: 'text-red-500' },
            { label: 'Requires action', value: violations.filter(v => v.suspended).length, accent: 'text-amber-500' },
          ].map(s => (
            <div key={s.label} className={`rounded-xl border p-4 ${th.card}`}>
              <div className={`text-2xl font-bold tabular-nums ${s.accent}`}>{s.value}</div>
              <div className={`text-xs mt-0.5 ${th.muted}`}>{s.label}</div>
            </div>
          ))}
        </div>

        {/* Violation list */}
        <div className={`rounded-xl border overflow-hidden ${th.card}`}>
          <div className={`px-4 py-3 border-b flex items-center justify-between ${th.divider}`}>
            <span className={`text-xs font-semibold uppercase tracking-wide ${th.muted}`}>Incidents</span>
            {error && <span className="text-xs text-amber-400">⚠ API unavailable — showing demo data</span>}
          </div>

          {violations.length === 0 && !loading && (
            <div className={`px-4 py-10 text-center text-sm ${th.muted}`}>No security violations recorded.</div>
          )}

          {violations.map((v) => {
            const sevStr = sev(v.violation_type, isDark)
            const [sevLabel, sevClass] = sevStr.split('|')
            return (
              <div key={v.id} className={`px-4 py-3.5 border-b last:border-0 ${th.row} ${th.divider}`}>
                <div className="flex items-start gap-3">
                  {/* Severity badge */}
                  <span className={`shrink-0 mt-0.5 text-[11px] font-semibold px-2 py-0.5 rounded-full border ${sevClass}`}>
                    {sevLabel.trim()}
                  </span>

                  {/* Main detail */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={`text-xs font-medium ${th.heading}`}>{v.user_id}</span>
                      <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${isDark ? 'bg-white/5 text-slate-400' : 'bg-slate-100 text-slate-500'}`}>{v.role}</span>
                      <span className={`text-[10px] ${th.muted}`}>·</span>
                      <span className={`text-[10px] ${th.muted}`}>{v.bank_id}</span>
                      <span className={`text-[10px] ${th.muted}`}>{v.bank_type}</span>
                    </div>
                    <div className={`text-[11px] mt-0.5 font-mono truncate ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>
                      {v.method} {v.endpoint}
                    </div>
                    <div className={`text-[10px] mt-1 ${th.muted}`}>
                      IP {v.client_ip} · {relTime(v.timestamp_iso)}
                      {v.request_id && <span className="ml-2 opacity-50">req:{v.request_id.slice(-8)}</span>}
                    </div>
                  </div>

                  {/* Status + action */}
                  <div className="shrink-0 flex flex-col items-end gap-1.5">
                    {v.suspended ? (
                      <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${th.badge}`}>
                        SUSPENDED
                      </span>
                    ) : (
                      <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${th.ok}`}>
                        ACTIVE
                      </span>
                    )}
                    {v.suspended && (
                      <button
                        onClick={async () => {
                          setReinstating(v.user_id)
                          await reinstate(v.user_id)
                          setReinstating(null)
                        }}
                        disabled={reinstating === v.user_id}
                        className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${isDark ? 'border-white/10 text-slate-400 hover:text-white hover:border-white/20' : 'border-slate-200 text-slate-500 hover:text-slate-700'} disabled:opacity-40`}
                      >
                        {reinstating === v.user_id ? 'Reinstating…' : 'Reinstate'}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            )
          })}
        </div>

        {/* Policy note */}
        <p className={`text-[10px] mt-4 text-center ${th.muted}`}>
          Cross-bank access attempts trigger immediate account suspension per ASTRA security policy.
          Reinstatement requires bank_it_admin authority and is logged to the immutable audit trail.
        </p>

      </div>
    </AppShell>
  )
}

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'

// ── Constants ────────────────────────────────────────────────────────────────

const CONNECTION_TYPES = [
  {
    type: 'SB_CBS',
    label: 'Sponsor Bank CBS',
    icon: '🏦',
    desc: 'Core Banking System for this bank (Finacle / BaNCS / FlexCube). Feeds Signature Vault and PPS Vault via VaultSyncWorkflow.',
    requiresVendor: true,
  },
  {
    type: 'SIGNATURE_VAULT',
    label: 'Signature Vault',
    icon: '✍️',
    desc: 'Redis Cluster endpoint for the Signature Vault (CTS Redis). Warmed by CBS sync every 15 minutes.',
    requiresVendor: false,
  },
  {
    type: 'PPS_VAULT',
    label: 'Positive Pay Vault',
    icon: '🔒',
    desc: 'Redis Cluster endpoint for the PPS Vault. Required for Positive Pay cheque validation before NGCH filing.',
    requiresVendor: false,
  },
  {
    type: 'CANCELLED_LEAF',
    label: 'Cancelled Leaf Filter',
    icon: '🚫',
    desc: 'Redis Bloom Filter fed by DeltaVaultSyncWorkflow every 15 minutes. Catches cancelled cheque serials before GPU inference.',
    requiresVendor: false,
  },
]

const CBS_VENDORS = ['finacle', 'bancs', 'flexcube']

const MOCK_CONNECTIONS = [
  {
    id: 'conn-001',
    connection_type: 'SB_CBS',
    cbs_vendor: 'finacle',
    endpoint_url_masked: 'https://cbs.saraswat.internal/***',
    vault_secret_ref: 'secret/astra/saraswat-coop/cbs/finacle',
    status: 'ACTIVE',
    last_tested_at: '2026-07-01T08:15:00Z',
    last_test_latency_ms: 38,
    last_sync_at: '2026-07-01T06:00:00Z',
    vault_record_count: 94320,
    error_message: null,
    created_at: '2026-06-15T10:00:00Z',
    created_by: 'itadmin@saraswat.internal',
  },
  {
    id: 'conn-004',
    connection_type: 'SIGNATURE_VAULT',
    cbs_vendor: null,
    endpoint_url_masked: 'redis://redis-cts.astra-cts-saraswat-coop/***',
    vault_secret_ref: 'secret/astra/saraswat-coop/redis/cts/auth_token',
    status: 'ACTIVE',
    last_tested_at: '2026-07-01T08:14:00Z',
    last_test_latency_ms: 3,
    last_sync_at: '2026-07-01T07:45:00Z',
    vault_record_count: 94320,
    error_message: null,
    created_at: '2026-06-15T10:05:00Z',
    created_by: 'itadmin@saraswat.internal',
  },
  {
    id: 'conn-005',
    connection_type: 'PPS_VAULT',
    cbs_vendor: null,
    endpoint_url_masked: 'redis://redis-cts.astra-cts-saraswat-coop/***',
    vault_secret_ref: 'secret/astra/saraswat-coop/redis/cts/auth_token',
    status: 'PENDING',
    last_tested_at: null,
    last_test_latency_ms: null,
    last_sync_at: null,
    vault_record_count: null,
    error_message: null,
    created_at: '2026-06-30T14:00:00Z',
    created_by: 'itadmin@saraswat.internal',
  },
  {
    id: 'conn-006',
    connection_type: 'CANCELLED_LEAF',
    cbs_vendor: null,
    endpoint_url_masked: 'redis://redis-cts.astra-cts-saraswat-coop/***',
    vault_secret_ref: 'secret/astra/saraswat-coop/redis/cts/auth_token',
    status: 'ACTIVE',
    last_tested_at: '2026-07-01T07:45:00Z',
    last_test_latency_ms: 2,
    last_sync_at: '2026-07-01T07:45:00Z',
    vault_record_count: 4821,
    error_message: null,
    created_at: '2026-06-15T10:10:00Z',
    created_by: 'itadmin@saraswat.internal',
  },
]

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmtDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })
}

function fmtLatency(ms) {
  if (ms == null) return '—'
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`
}

function fmtCount(n) {
  if (n == null) return '—'
  return n.toLocaleString('en-IN')
}

function getTypeInfo(type) {
  return CONNECTION_TYPES.find(ct => ct.type === type) || { label: type, icon: '🔗', desc: '' }
}

// ── Status badge ─────────────────────────────────────────────────────────────

const STATUS_D = {
  ACTIVE:       'bg-emerald-900/50 text-emerald-300 border-emerald-700/40',
  PENDING:      'bg-amber-900/40   text-amber-300   border-amber-700/40',
  ERROR:        'bg-red-900/50     text-red-300     border-red-700/40',
  UNCONFIGURED: 'bg-slate-800      text-slate-400   border-slate-700',
}
const STATUS_L = {
  ACTIVE:       'bg-emerald-50 text-emerald-700 border-emerald-200',
  PENDING:      'bg-amber-50   text-amber-700   border-amber-200',
  ERROR:        'bg-red-50     text-red-700     border-red-200',
  UNCONFIGURED: 'bg-slate-100  text-slate-500   border-slate-200',
}

function StatusBadge({ status, isDark }) {
  const cls = isDark ? (STATUS_D[status] || STATUS_D.UNCONFIGURED) : (STATUS_L[status] || STATUS_L.UNCONFIGURED)
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${cls}`}>
      {status === 'ACTIVE' && '● '}
      {status === 'ERROR' && '✕ '}
      {status === 'PENDING' && '○ '}
      {status}
    </span>
  )
}

// ── Form modal ────────────────────────────────────────────────────────────────

function ConnectionFormModal({ isDark, onClose, onSave, editRow }) {
  const [form, setForm] = useState({
    connection_type: editRow?.connection_type || 'SB_CBS',
    cbs_vendor: editRow?.cbs_vendor || '',
    endpoint_url: '',
    vault_secret_ref: editRow?.vault_secret_ref || '',
  })
  const [saving, setSaving] = useState(false)

  const typeInfo = getTypeInfo(form.connection_type)
  const th = {
    bg:      isDark ? 'bg-navy-900'  : 'bg-white',
    overlay: 'bg-black/60',
    label:   isDark ? 'text-slate-300' : 'text-slate-700',
    input:   isDark
      ? 'bg-navy-950 border-white/10 text-white placeholder-slate-500 focus:border-violet-500'
      : 'bg-white border-slate-300 text-slate-900 placeholder-slate-400 focus:border-violet-500',
    heading: isDark ? 'text-white' : 'text-slate-900',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
  }

  function set(k, v) { setForm(f => ({ ...f, [k]: v })) }

  async function handleSave() {
    setSaving(true)
    await onSave(form)
    setSaving(false)
  }

  return (
    <div className={`fixed inset-0 z-50 flex items-center justify-center ${th.overlay}`} onClick={onClose}>
      <div
        className={`${th.bg} border border-white/10 rounded-xl w-full max-w-lg mx-4 p-6 shadow-2xl`}
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-5">
          <h3 className={`text-base font-semibold ${th.heading}`}>
            {editRow ? 'Edit MCP Connection' : 'Add MCP Connection'}
          </h3>
          <button onClick={onClose} className={`${th.muted} hover:text-white text-xl leading-none`}>×</button>
        </div>

        <div className="space-y-4">
          {/* Connection Type */}
          {!editRow && (
            <div>
              <label className={`block text-xs font-medium mb-1 ${th.label}`}>Connection Type</label>
              <select
                value={form.connection_type}
                onChange={e => set('connection_type', e.target.value)}
                className={`w-full rounded-lg border px-3 py-2 text-sm outline-none ${th.input}`}
              >
                {CONNECTION_TYPES.map(ct => (
                  <option key={ct.type} value={ct.type}>{ct.icon} {ct.label}</option>
                ))}
              </select>
              <p className={`mt-1 text-xs ${th.muted}`}>{typeInfo.desc}</p>
            </div>
          )}

          {/* CBS Vendor — only for SB_CBS */}
          {form.connection_type === 'SB_CBS' && (
            <div>
              <label className={`block text-xs font-medium mb-1 ${th.label}`}>CBS Vendor</label>
              <select
                value={form.cbs_vendor}
                onChange={e => set('cbs_vendor', e.target.value)}
                className={`w-full rounded-lg border px-3 py-2 text-sm outline-none ${th.input}`}
              >
                <option value="">— select vendor —</option>
                {CBS_VENDORS.map(v => <option key={v} value={v}>{v.charAt(0).toUpperCase() + v.slice(1)}</option>)}
              </select>
            </div>
          )}

          {/* Endpoint URL */}
          <div>
            <label className={`block text-xs font-medium mb-1 ${th.label}`}>Endpoint URL</label>
            <input
              type="text"
              value={form.endpoint_url}
              onChange={e => set('endpoint_url', e.target.value)}
              placeholder={
                form.connection_type === 'SB_CBS'
                  ? 'https://cbs.bank.internal/finacle/api'
                  : 'redis://redis-cts.astra-cts-bank-id:6379'
              }
              className={`w-full rounded-lg border px-3 py-2 text-sm outline-none font-mono ${th.input}`}
            />
            <p className={`mt-1 text-xs ${th.muted}`}>Stored encrypted (AES-256). Never returned in API responses.</p>
          </div>

          {/* Vault Secret Ref */}
          <div>
            <label className={`block text-xs font-medium mb-1 ${th.label}`}>Vault Secret Path</label>
            <input
              type="text"
              value={form.vault_secret_ref}
              onChange={e => set('vault_secret_ref', e.target.value)}
              placeholder="secret/astra/bank-id/cbs/finacle"
              className={`w-full rounded-lg border px-3 py-2 text-sm outline-none font-mono ${th.input}`}
            />
            <p className={`mt-1 text-xs ${th.muted}`}>HashiCorp Vault path to credentials. Rotated every 24h.</p>
          </div>
        </div>

        <div className="flex gap-3 mt-6">
          <button
            onClick={onClose}
            className={`flex-1 py-2 rounded-lg text-sm font-medium border ${isDark ? 'border-white/10 text-slate-300 hover:bg-white/5' : 'border-slate-200 text-slate-600 hover:bg-slate-50'}`}
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex-1 py-2 rounded-lg text-sm font-medium bg-violet-600 hover:bg-violet-700 text-white disabled:opacity-50"
          >
            {saving ? 'Saving…' : editRow ? 'Update' : 'Add Connection'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Connection card ───────────────────────────────────────────────────────────

function ConnectionCard({ conn, isDark, onTest, onSync, onEdit, onDelete, testing, syncing }) {
  const [showDetails, setShowDetails] = useState(false)
  const typeInfo = getTypeInfo(conn.connection_type)
  const th = {
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    detail:  isDark ? 'bg-navy-950 border-white/6' : 'bg-slate-50 border-slate-100',
    mono:    isDark ? 'text-slate-300 bg-white/4' : 'text-slate-700 bg-slate-100',
  }

  const canSync = conn.connection_type === 'SB_CBS' && conn.status === 'ACTIVE'

  return (
    <div className={`rounded-xl border p-4 ${th.card}`}>
      {/* Header row */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0">
          <span className="text-2xl flex-shrink-0 mt-0.5">{typeInfo.icon}</span>
          <div className="min-w-0">
            <div className={`text-sm font-semibold ${th.heading}`}>
              {typeInfo.label}
            </div>
            {conn.cbs_vendor && (
              <div className={`text-xs mt-0.5 ${th.muted}`}>{conn.cbs_vendor.charAt(0).toUpperCase() + conn.cbs_vendor.slice(1)} connector</div>
            )}
          </div>
        </div>
        <StatusBadge status={conn.status} isDark={isDark} />
      </div>

      {/* Error banner */}
      {conn.error_message && (
        <div className={`mt-3 rounded-lg px-3 py-2 text-xs border ${isDark ? 'bg-red-900/20 border-red-700/30 text-red-300' : 'bg-red-50 border-red-200 text-red-700'}`}>
          <span className="font-medium">Error: </span>{conn.error_message}
        </div>
      )}

      {/* Metrics row */}
      <div className={`mt-3 grid grid-cols-3 gap-3 text-xs ${th.muted}`}>
        <div>
          <div className="font-medium mb-0.5">Last Tested</div>
          <div>{fmtDate(conn.last_tested_at)}</div>
          {conn.last_test_latency_ms != null && (
            <div className="mt-0.5 text-emerald-400">{fmtLatency(conn.last_test_latency_ms)}</div>
          )}
        </div>
        <div>
          <div className="font-medium mb-0.5">Last Sync</div>
          <div>{fmtDate(conn.last_sync_at)}</div>
        </div>
        <div>
          <div className="font-medium mb-0.5">Records</div>
          <div>{fmtCount(conn.vault_record_count)}</div>
        </div>
      </div>

      {/* Details toggle */}
      {showDetails && (
        <div className={`mt-3 rounded-lg border p-3 text-xs space-y-1.5 ${th.detail}`}>
          <div className="flex gap-2">
            <span className={th.muted + ' w-28 flex-shrink-0'}>Endpoint</span>
            <code className={`px-1 rounded text-xs break-all ${th.mono}`}>{conn.endpoint_url_masked || '—'}</code>
          </div>
          <div className="flex gap-2">
            <span className={th.muted + ' w-28 flex-shrink-0'}>Vault Path</span>
            <code className={`px-1 rounded text-xs break-all ${th.mono}`}>{conn.vault_secret_ref || '—'}</code>
          </div>
          <div className="flex gap-2">
            <span className={th.muted + ' w-28 flex-shrink-0'}>Created</span>
            <span className={th.body}>{fmtDate(conn.created_at)} by {conn.created_by}</span>
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center gap-2 mt-3">
        <button
          onClick={() => onTest(conn.id)}
          disabled={testing}
          className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition ${isDark ? 'border-white/10 text-slate-300 hover:bg-white/5 disabled:opacity-40' : 'border-slate-200 text-slate-700 hover:bg-slate-50 disabled:opacity-40'}`}
        >
          {testing ? 'Testing…' : '⚡ Test'}
        </button>
        {canSync && (
          <button
            onClick={() => onSync(conn.id)}
            disabled={syncing}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition ${isDark ? 'border-white/10 text-slate-300 hover:bg-white/5 disabled:opacity-40' : 'border-slate-200 text-slate-700 hover:bg-slate-50 disabled:opacity-40'}`}
          >
            {syncing ? 'Syncing…' : '↻ Sync Vault'}
          </button>
        )}
        <button
          onClick={() => onEdit(conn)}
          className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition ${isDark ? 'border-white/10 text-slate-300 hover:bg-white/5' : 'border-slate-200 text-slate-700 hover:bg-slate-50'}`}
        >
          ✏️ Edit
        </button>
        <button
          onClick={() => setShowDetails(s => !s)}
          className={`ml-auto text-xs ${th.muted} hover:underline`}
        >
          {showDetails ? 'Hide details' : 'Details'}
        </button>
        <button
          onClick={() => onDelete(conn.id)}
          className="text-xs text-red-400 hover:text-red-300"
        >
          ✕
        </button>
      </div>
    </div>
  )
}

// ── Preflight banner ──────────────────────────────────────────────────────────

function PreflightBanner({ connections, isDark }) {
  const nonActive = connections.filter(c => c.status !== 'ACTIVE')
  const allActive = nonActive.length === 0 && connections.length > 0
  const empty = connections.length === 0

  if (empty) return null

  return (
    <div className={`rounded-xl border p-4 flex items-start gap-3 ${
      allActive
        ? isDark ? 'bg-emerald-900/20 border-emerald-700/30' : 'bg-emerald-50 border-emerald-200'
        : isDark ? 'bg-amber-900/20 border-amber-700/30' : 'bg-amber-50 border-amber-200'
    }`}>
      <span className="text-xl flex-shrink-0">{allActive ? '✅' : '⚠️'}</span>
      <div>
        <div className={`text-sm font-semibold ${allActive
          ? isDark ? 'text-emerald-300' : 'text-emerald-700'
          : isDark ? 'text-amber-300' : 'text-amber-700'
        }`}>
          {allActive
            ? 'Pre-flight check passed — clearing sessions can open'
            : `Pre-flight check blocked — ${nonActive.length} connection${nonActive.length > 1 ? 's' : ''} not ACTIVE`
          }
        </div>
        {!allActive && (
          <div className={`mt-1 text-xs ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>
            {nonActive.map(c => `${getTypeInfo(c.connection_type).label}: ${c.status}`).join(' · ')}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function CTSMCPConfig() {
  const { isDark } = useTheme()
  const { bankId, bankName } = useBankContext()
  const queryClient = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const [editRow, setEditRow] = useState(null)
  const [testing, setTesting] = useState({})
  const [syncing, setSyncing] = useState({})
  const [toast, setToast] = useState(null)

  function showToast(msg, type = 'info') {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3500)
  }

  const th = {
    page:    isDark ? 'bg-navy-950' : 'bg-slate-50',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
  }

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['mcp-connections', bankId] })

  const { data: connData } = useQuery({
    queryKey: ['mcp-connections', bankId],
    queryFn: async () => {
      const res = await fetch('/api/v1/admin/mcp-connections/', { credentials: 'include' })
      if (!res.ok) throw new Error('Failed to load connections')
      return res.json()
    },
    staleTime: 30_000,
    refetchInterval: 30_000,
  })
  const connections = connData?.connections ?? MOCK_CONNECTIONS

  const saveMutation = useMutation({
    mutationFn: async (form) => {
      const url = editRow
        ? `/api/v1/admin/mcp-connections/${encodeURIComponent(editRow.id)}`
        : '/api/v1/admin/mcp-connections/'
      const res = await fetch(url, {
        method: editRow ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(form),
      })
      if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || 'Save failed') }
      return res.json()
    },
    onSuccess: () => {
      invalidate()
      showToast(editRow ? 'Connection updated — status reset to PENDING. Run Test to activate.' : 'Connection added. Run Test to verify connectivity and activate.', 'info')
      setShowForm(false)
      setEditRow(null)
    },
    onError: (err) => showToast(err.message || 'Save failed', 'error'),
  })

  function handleSave(form) { return saveMutation.mutateAsync(form) }

  const testMutation = useMutation({
    mutationFn: async (id) => {
      const res = await fetch(`/api/v1/admin/mcp-connections/${encodeURIComponent(id)}/test`, {
        method: 'POST', credentials: 'include',
      })
      if (!res.ok) throw new Error('Test request failed')
      return res.json()
    },
    onSuccess: (data) => {
      invalidate()
      setTesting(t => ({ ...t, [data.connection_id]: false }))
      showToast(
        data.success
          ? `Connection tested successfully (${data.latency_ms} ms)`
          : `Connection test failed — ${data.error || 'check endpoint and credentials'}`,
        data.success ? 'success' : 'error',
      )
    },
    onError: (_, id) => {
      setTesting(t => ({ ...t, [id]: false }))
      showToast('Connection test request failed', 'error')
    },
  })

  function handleTest(id) {
    setTesting(t => ({ ...t, [id]: true }))
    testMutation.mutate(id)
  }

  const syncMutation = useMutation({
    mutationFn: async (id) => {
      const res = await fetch(`/api/v1/admin/mcp-connections/${encodeURIComponent(id)}/sync`, {
        method: 'POST', credentials: 'include',
      })
      if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || 'Sync trigger failed') }
      return res.json()
    },
    onSuccess: (data) => {
      invalidate()
      setSyncing(s => ({ ...s, [data.connection_id]: false }))
      showToast(`Vault sync triggered — workflow ${data.workflow_id}`, 'success')
    },
    onError: (err, id) => {
      setSyncing(s => ({ ...s, [id]: false }))
      showToast(err.message || 'Sync trigger failed', 'error')
    },
  })

  function handleSync(id) {
    setSyncing(s => ({ ...s, [id]: true }))
    syncMutation.mutate(id)
  }

  const deleteMutation = useMutation({
    mutationFn: async (id) => {
      const res = await fetch(`/api/v1/admin/mcp-connections/${encodeURIComponent(id)}`, {
        method: 'DELETE', credentials: 'include',
      })
      if (!res.ok) throw new Error('Delete failed')
    },
    onSuccess: () => { invalidate(); showToast('Connection removed', 'info') },
    onError: () => showToast('Failed to remove connection', 'error'),
  })

  function handleEdit(conn) { setEditRow(conn); setShowForm(true) }
  function handleDelete(id) { deleteMutation.mutate(id) }

  const cbsConns   = connections.filter(c => c.connection_type === 'SB_CBS')
  const vaultConns = connections.filter(c => c.connection_type !== 'SB_CBS')

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        {/* Page header */}
        <div className="flex items-start justify-between mb-5">
          <div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>MCP Connection Setup</h1>
            <p className={`text-sm mt-0.5 ${th.muted}`}>
              Configure CBS and vault MCP connections for {bankName || bankId}. All connections must be ACTIVE before clearing sessions can open.
            </p>
          </div>
          <button
            onClick={() => { setEditRow(null); setShowForm(true) }}
            className="flex-shrink-0 px-4 py-2 rounded-lg text-sm font-medium bg-violet-600 hover:bg-violet-700 text-white"
          >
            + Add Connection
          </button>
        </div>

        {/* Pre-flight banner */}
        <div className="mb-5">
          <PreflightBanner connections={connections} isDark={isDark} />
        </div>

        {/* CBS Connections section */}
        {cbsConns.length > 0 && (
          <div className="mb-6">
            <h2 className={`text-xs font-semibold uppercase tracking-wider mb-3 ${th.muted}`}>
              CBS Connection — Core Banking System
            </h2>
            <div className="space-y-3">
              {cbsConns.map(conn => (
                <ConnectionCard
                  key={conn.id}
                  conn={conn}
                  isDark={isDark}
                  onTest={handleTest}
                  onSync={handleSync}
                  onEdit={handleEdit}
                  onDelete={handleDelete}
                  testing={!!testing[conn.id]}
                  syncing={!!syncing[conn.id]}
                />
              ))}
            </div>
          </div>
        )}

        {/* Vault / Micro-DB connections section */}
        {vaultConns.length > 0 && (
          <div className="mb-6">
            <h2 className={`text-xs font-semibold uppercase tracking-wider mb-3 ${th.muted}`}>
              Vault &amp; Micro-DB Connections — Redis / Bloom Filter
            </h2>
            <div className="space-y-3">
              {vaultConns.map(conn => (
                <ConnectionCard
                  key={conn.id}
                  conn={conn}
                  isDark={isDark}
                  onTest={handleTest}
                  onSync={handleSync}
                  onEdit={handleEdit}
                  onDelete={handleDelete}
                  testing={!!testing[conn.id]}
                  syncing={!!syncing[conn.id]}
                />
              ))}
            </div>
          </div>
        )}

        {/* Empty state */}
        {connections.length === 0 && (
          <div className={`rounded-xl border p-10 text-center ${th.card}`}>
            <div className="text-4xl mb-3">🔗</div>
            <div className={`text-sm font-medium mb-1 ${th.heading}`}>No MCP connections configured</div>
            <div className={`text-xs mb-4 ${th.muted}`}>
              Add CBS and vault connections to enable clearing session operations.
            </div>
            <button
              onClick={() => { setEditRow(null); setShowForm(true) }}
              className="px-4 py-2 rounded-lg text-sm font-medium bg-violet-600 hover:bg-violet-700 text-white"
            >
              + Add First Connection
            </button>
          </div>
        )}

        {/* Quick-reference guide */}
        <div className={`mt-6 rounded-xl border p-4 ${th.card}`}>
          <h3 className={`text-xs font-semibold uppercase tracking-wider mb-3 ${th.muted}`}>Setup Guide</h3>
          <div className="grid grid-cols-1 gap-2">
            {CONNECTION_TYPES.map((ct, i) => (
              <div key={ct.type} className="flex items-start gap-2">
                <span className={`text-xs font-bold w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5 ${isDark ? 'bg-violet-900/50 text-violet-300' : 'bg-violet-100 text-violet-700'}`}>
                  {i + 1}
                </span>
                <div>
                  <div className={`text-xs font-medium ${th.body}`}>{ct.icon} {ct.label}</div>
                  <div className={`text-xs ${th.muted}`}>{ct.desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Form modal */}
      {showForm && (
        <ConnectionFormModal
          isDark={isDark}
          onClose={() => { setShowForm(false); setEditRow(null) }}
          onSave={handleSave}
          editRow={editRow}
        />
      )}

      {/* Toast */}
      {toast && (
        <div className={`fixed bottom-6 left-1/2 -translate-x-1/2 z-50 px-5 py-3 rounded-xl text-sm font-medium shadow-2xl ${
          toast.type === 'success' ? 'bg-emerald-600 text-white'
          : toast.type === 'error' ? 'bg-red-600 text-white'
          : isDark ? 'bg-navy-800 text-white border border-white/10' : 'bg-white text-slate-900 border border-slate-200'
        }`}>
          {toast.msg}
        </div>
      )}
    </AppShell>
  )
}

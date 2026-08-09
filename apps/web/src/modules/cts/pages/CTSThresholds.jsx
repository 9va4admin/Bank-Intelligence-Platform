import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'
import { BANK_CONFIG } from '../../../shared/config/bank.config'

const USE_MOCK = BANK_CONFIG.deployment_mode === 'DEMO'

function getCsrf() { return sessionStorage.getItem('astra-csrf') || '' }

async function apiFetch(path, opts = {}) {
  const res = await fetch(path, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': getCsrf(), ...opts.headers },
    ...opts,
  })
  if (!res.ok) {
    const b = await res.json().catch(() => ({}))
    throw new Error(b.detail || `HTTP ${res.status}`)
  }
  if (res.status === 204) return null
  return res.json()
}

// Schema: labels, types, constraints — static, not from API
const THRESHOLD_SCHEMA = [
  {
    key: 'iet_minutes',
    label: 'IET Window',
    defaultValue: 180,
    unit: 'minutes',
    type: 'integer',
    min: 60, max: 240,
    warn: true,
    editable: true,
    category: 'IET & Timing',
    desc: 'RBI-mandated Item Expiry Time window. Cheques not decided within this window are deemed approved. Default: 180 min (3 hours).',
  },
  {
    key: 'stp_auto_confirm_threshold',
    label: 'STP Auto-Confirm Score',
    defaultValue: 0.92,
    unit: 'score (0–1)',
    type: 'float',
    min: 0.85, max: 0.99,
    warn: false,
    editable: true,
    category: 'Fraud Scoring',
    desc: 'Fraud probability below this score triggers automatic NGCH CONFIRM filing (Straight-Through Processing). Raise to reduce STP rate; lower to increase human review load.',
  },
  {
    key: 'human_review_fraud_threshold',
    label: 'Human Review Trigger Score',
    defaultValue: 0.72,
    unit: 'score (0–1)',
    type: 'float',
    min: 0.50, max: 0.90,
    warn: false,
    editable: true,
    category: 'Fraud Scoring',
    desc: 'Fraud probability above this score routes the cheque to ops reviewer queue instead of auto-confirm. Must be lower than STP threshold.',
  },
  {
    key: 'high_value_amount_threshold',
    label: 'High-Value Cheque Limit',
    defaultValue: 500000,
    unit: '₹',
    type: 'integer',
    min: 100000, max: 10000000,
    warn: false,
    editable: true,
    category: 'Amount Controls',
    desc: 'Cheques above this amount trigger dual ops_reviewer approval before NGCH filing. Aligns with RBI high-value transaction monitoring norms.',
  },
  {
    key: 'ocr_min_confidence',
    label: 'OCR Minimum Confidence',
    defaultValue: 0.90,
    unit: 'score (0–1)',
    type: 'float',
    min: 0.80, max: 0.99,
    warn: false,
    editable: true,
    category: 'AI Confidence',
    desc: 'GOT-OCR2.0 confidence below this threshold routes the cheque to human review for manual MICR/field verification.',
  },
  {
    key: 'signature_min_match_score',
    label: 'Signature Match Minimum',
    defaultValue: 0.87,
    unit: 'score (0–1)',
    type: 'float',
    min: 0.75, max: 0.99,
    warn: false,
    editable: true,
    category: 'AI Confidence',
    desc: 'Siamese network match score below this routes to human review for manual signature comparison. Lower = more human review; higher = more STP risk.',
  },
  {
    key: 'vault_miss_action',
    label: 'Vault Miss Action',
    defaultValue: 'HUMAN_REVIEW',
    unit: '',
    type: 'enum',
    layer: 1,
    warn: true,
    editable: false,
    category: 'Security',
    desc: 'Action when signature or PPS vault has no record for the account. LOCKED to HUMAN_REVIEW by platform constraint — cannot be changed to AUTO_RETURN.',
  },
  {
    key: 'iet_watchdog_trigger_seconds',
    label: 'IET Watchdog Trigger',
    defaultValue: 30,
    unit: 'seconds before IET',
    type: 'integer',
    min: 15, max: 120,
    layer: 1,
    warn: true,
    editable: false,
    category: 'IET & Timing',
    desc: 'IETWatchdogWorkflow fires emergency NGCH filing at this many seconds before IET deadline. LOCKED — changing this risks IET breach.',
  },
]

const MOCK_CHANGES = [
  { change_id: 'chg-1', config_key: 'stp_auto_confirm_threshold',   new_value: '0.92', reason: 'Align with Q2 risk review', status: 'APPROVED',          submitted_by: 'ops_manager@svcb', actioned_by: 'itadmin@svcb', submitted_at: '2026-06-18T14:32:00Z', actioned_at: '2026-06-18T16:00:00Z' },
  { change_id: 'chg-2', config_key: 'human_review_fraud_threshold', new_value: '0.72', reason: 'Reduce false positives after model retrain', status: 'APPROVED', submitted_by: 'ops_manager@svcb', actioned_by: 'itadmin@svcb', submitted_at: '2026-06-15T09:11:00Z', actioned_at: '2026-06-15T10:30:00Z' },
  { change_id: 'chg-3', config_key: 'high_value_amount_threshold',  new_value: '500000', reason: 'Board resolution to raise threshold', status: 'APPROVED', submitted_by: 'ops_manager@svcb', actioned_by: 'itadmin@svcb', submitted_at: '2026-06-10T11:45:00Z', actioned_at: '2026-06-10T14:00:00Z' },
  { change_id: 'chg-4', config_key: 'ocr_min_confidence',           new_value: '0.90', reason: 'Match updated GOT-OCR2.0 confidence calibration', status: 'PENDING_APPROVAL', submitted_by: 'ops_manager@svcb', actioned_by: null, submitted_at: '2026-06-24T16:20:00Z', actioned_at: null },
]

const CATEGORIES = ['All', 'IET & Timing', 'Fraud Scoring', 'Amount Controls', 'AI Confidence', 'Security']

function parseValue(schema, raw) {
  if (raw === undefined || raw === null) return schema.defaultValue
  if (schema.type === 'float') return parseFloat(raw) || schema.defaultValue
  if (schema.type === 'integer') return parseInt(raw, 10) || schema.defaultValue
  return raw
}

function formatValue(schema, value) {
  if (schema.type === 'float') return (typeof value === 'number' ? value : parseFloat(value)).toFixed(2)
  if (schema.type === 'integer') return (typeof value === 'number' ? value : parseInt(value, 10)).toLocaleString()
  return String(value)
}

function fmtDate(iso) {
  if (!iso) return '—'
  try { return new Date(iso).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) }
  catch { return iso }
}

export default function CTSThresholds() {
  const { bankId } = useBankContext()
  const { isDark } = useTheme()
  const qc = useQueryClient()
  const [cat, setCat] = useState('All')
  const [editing, setEditing] = useState(null)
  const [editVal, setEditVal] = useState('')
  const [editReason, setEditReason] = useState('')
  const [submitError, setSubmitError] = useState('')
  const [tab, setTab] = useState('thresholds')

  const th = {
    page:    isDark ? 'bg-transparent' : 'bg-slate-50',
    card:    isDark ? 'bg-white/3 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    row:     isDark ? 'border-white/5 hover:bg-white/3' : 'border-slate-100 hover:bg-slate-50',
    input:   isDark ? 'bg-white/5 border-white/10 text-white placeholder-slate-500 focus:border-cyan-500' : 'bg-white border-slate-300 text-slate-900 focus:border-cyan-500',
  }

  // Live threshold values from API
  const { data: liveData } = useQuery({
    queryKey: ['admin-thresholds', bankId],
    queryFn: () => USE_MOCK
      ? Promise.resolve({ thresholds: [], total: 0, bank_id: bankId })
      : apiFetch('/v1/admin/config/thresholds'),
    staleTime: 30_000,
  })

  // Build thresholds array: schema + live values overlaid
  const liveMap = {}
  for (const t of (liveData?.thresholds ?? [])) {
    liveMap[t.config_key] = t.current_value
  }
  const thresholds = THRESHOLD_SCHEMA.map(s => ({
    ...s,
    value: parseValue(s, liveMap[s.key]),
  }))

  // Change log from API
  const { data: changesData, refetch: refetchChanges } = useQuery({
    queryKey: ['admin-threshold-changes', bankId],
    queryFn: () => USE_MOCK
      ? Promise.resolve({ changes: MOCK_CHANGES, total: MOCK_CHANGES.length, bank_id: bankId })
      : apiFetch('/v1/admin/config/thresholds/changes'),
    staleTime: 15_000,
  })
  const changes = changesData?.changes ?? []

  const submitMut = useMutation({
    mutationFn: (body) => USE_MOCK
      ? Promise.resolve({ change_id: `chg-${Date.now()}`, status: 'PENDING_APPROVAL', ...body })
      : apiFetch('/v1/admin/config/thresholds', { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-thresholds', bankId] })
      qc.invalidateQueries({ queryKey: ['admin-threshold-changes', bankId] })
      setEditing(null)
      setEditVal('')
      setEditReason('')
      setSubmitError('')
    },
    onError: (err) => setSubmitError(err.message),
  })

  const openEdit = (t) => {
    setEditing(t)
    setEditVal(String(t.value))
    setEditReason('')
    setSubmitError('')
  }

  const handleSubmit = () => {
    if (!editReason.trim() || editReason.trim().length < 10) {
      setSubmitError('Reason must be at least 10 characters.')
      return
    }
    submitMut.mutate({ config_key: editing.key, new_value: editVal, reason: editReason.trim() })
  }

  const displayed = thresholds.filter(t => cat === 'All' || t.category === cat)

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        {/* Header */}
        <div className="mb-5">
          <h1 className={`text-lg font-semibold ${th.heading}`}>Thresholds & Rules</h1>
          <p className={`text-xs mt-0.5 ${th.muted}`}>Layer 3 business rules — live hot-reload within 30 seconds. All changes require maker-checker approval.</p>
        </div>

        {/* Tabs */}
        <div className={`flex gap-1 mb-5 border-b ${th.divider}`}>
          {['thresholds', 'change-log'].map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-4 py-2 text-xs font-medium capitalize transition-colors border-b-2 -mb-px ${tab === t ? 'border-cyan-500 text-cyan-400' : `border-transparent ${th.muted} hover:${th.body}`}`}
            >
              {t === 'change-log' ? 'Change Log' : 'Thresholds'}
            </button>
          ))}
        </div>

        {tab === 'thresholds' && (
          <>
            {/* Category filter */}
            <div className="flex gap-1.5 flex-wrap mb-4">
              {CATEGORIES.map(c => (
                <button key={c} onClick={() => setCat(c)} className={`px-3 h-7 rounded-lg text-xs font-medium transition-all border ${cat === c ? 'bg-cyan-600 text-white border-cyan-600' : `${th.card} ${th.muted}`}`}>{c}</button>
              ))}
            </div>

            {/* Threshold cards */}
            <div className="space-y-3">
              {displayed.map(t => (
                <div key={t.key} className={`rounded-xl border px-5 py-4 ${th.card}`}>
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className={`font-medium text-sm ${th.heading}`}>{t.label}</span>
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${isDark ? 'bg-white/5 text-slate-400' : 'bg-slate-100 text-slate-500'}`}>
                          Layer {t.layer ?? 3}
                        </span>
                        {t.warn && (
                          <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${isDark ? 'bg-amber-900/40 text-amber-300' : 'bg-amber-100 text-amber-700'}`}>
                            CRITICAL
                          </span>
                        )}
                        {!t.editable && (
                          <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${isDark ? 'bg-red-900/30 text-red-300' : 'bg-red-100 text-red-600'}`}>
                            LOCKED
                          </span>
                        )}
                      </div>
                      <p className={`text-xs mt-1 ${th.muted}`}>{t.desc}</p>
                    </div>
                    <div className="flex items-center gap-3 shrink-0">
                      <div className="text-right">
                        <div className={`text-xl font-bold tabular-nums ${t.warn ? (isDark ? 'text-amber-300' : 'text-amber-600') : th.heading}`}>
                          {formatValue(t, t.value)}
                        </div>
                        <div className={`text-[10px] ${th.muted}`}>{t.unit}</div>
                      </div>
                      {t.editable && (
                        <button
                          onClick={() => openEdit(t)}
                          className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${isDark ? 'bg-white/5 text-slate-300 hover:bg-white/10' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'}`}
                        >
                          Edit
                        </button>
                      )}
                    </div>
                  </div>
                  {t.type !== 'enum' && t.editable && (
                    <div className="mt-3">
                      <div className={`h-1.5 rounded-full overflow-hidden ${isDark ? 'bg-white/8' : 'bg-slate-100'}`}>
                        <div
                          className="h-full bg-cyan-500 rounded-full transition-all"
                          style={{ width: `${Math.min(100, Math.max(0, ((t.value - t.min) / (t.max - t.min)) * 100))}%` }}
                        />
                      </div>
                      <div className={`flex justify-between mt-1 text-[10px] ${th.muted}`}>
                        <span>{formatValue(t, t.min)}</span>
                        <span>{formatValue(t, t.max)}</span>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </>
        )}

        {tab === 'change-log' && (
          <div className={`rounded-xl border overflow-hidden ${th.card}`}>
            {changes.length === 0 ? (
              <div className={`px-6 py-10 text-center text-sm ${th.muted}`}>No threshold changes recorded yet.</div>
            ) : (
              <table className="w-full text-xs">
                <thead>
                  <tr className={`border-b ${th.divider}`}>
                    {['Config Key', 'New Value', 'Reason', 'Submitted By', 'Approved By', 'Submitted', 'Status'].map(h => (
                      <th key={h} className={`px-4 py-3 text-left font-medium ${th.muted}`}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {changes.map((c) => (
                    <tr key={c.change_id} className={`border-b transition-colors ${th.row}`}>
                      <td className={`px-4 py-3 font-mono text-[11px] ${th.body}`}>{c.config_key}</td>
                      <td className={`px-4 py-3 font-semibold ${isDark ? 'text-cyan-300' : 'text-cyan-700'}`}>{c.new_value}</td>
                      <td className={`px-4 py-3 ${th.muted} max-w-[200px] truncate`} title={c.reason}>{c.reason}</td>
                      <td className={`px-4 py-3 ${th.body}`}>{c.submitted_by}</td>
                      <td className={`px-4 py-3 ${th.body}`}>{c.actioned_by ?? <span className={th.muted}>Pending…</span>}</td>
                      <td className={`px-4 py-3 font-mono text-[11px] ${th.muted}`}>{fmtDate(c.submitted_at)}</td>
                      <td className="px-4 py-3">
                        <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${
                          c.status === 'APPROVED'
                            ? (isDark ? 'bg-emerald-900/40 text-emerald-300' : 'bg-emerald-100 text-emerald-700')
                            : c.status === 'REJECTED'
                              ? (isDark ? 'bg-red-900/40 text-red-300' : 'bg-red-100 text-red-700')
                              : (isDark ? 'bg-amber-900/40 text-amber-300' : 'bg-amber-100 text-amber-700')
                        }`}>
                          {c.status === 'PENDING_APPROVAL' ? 'PENDING' : c.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {/* Edit modal */}
        {editing && (
          <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.6)' }}>
            <div className={`w-full max-w-md rounded-2xl border p-6 shadow-2xl ${isDark ? 'bg-[#0e1428] border-white/10' : 'bg-white border-slate-200'}`}>
              <div className="flex items-center justify-between mb-4">
                <h3 className={`font-semibold ${th.heading}`}>Edit — {editing.label}</h3>
                <button onClick={() => setEditing(null)} className={th.muted}>✕</button>
              </div>
              <p className={`text-xs mb-4 ${th.muted}`}>{editing.desc}</p>

              <div className="space-y-3">
                <div>
                  <label className={`text-xs ${th.muted}`}>New Value ({editing.unit})</label>
                  <input
                    type="number"
                    value={editVal}
                    onChange={e => setEditVal(e.target.value)}
                    min={editing.min}
                    max={editing.max}
                    step={editing.type === 'float' ? 0.01 : 1}
                    className={`w-full mt-1 h-9 px-3 rounded-lg border text-sm outline-none transition-colors ${th.input}`}
                  />
                  {editing.min !== undefined && (
                    <p className={`text-[10px] mt-1 ${th.muted}`}>Range: {editing.min} – {editing.max}</p>
                  )}
                </div>

                <div>
                  <label className={`text-xs ${th.muted}`}>Reason for change <span className="text-red-400">*</span></label>
                  <textarea
                    value={editReason}
                    onChange={e => { setEditReason(e.target.value); setSubmitError('') }}
                    rows={3}
                    placeholder="Describe why this value is being changed (min. 10 characters)…"
                    className={`w-full mt-1 px-3 py-2 rounded-lg border text-sm outline-none transition-colors resize-none ${th.input}`}
                  />
                </div>
              </div>

              {submitError && (
                <p className="mt-2 text-xs text-red-400">{submitError}</p>
              )}

              <div className={`mt-4 p-3 rounded-lg text-xs ${isDark ? 'bg-amber-900/20 border border-amber-700/40 text-amber-300' : 'bg-amber-50 border border-amber-200 text-amber-800'}`}>
                ⚠ This change will be submitted to bank_it_admin for approval. It goes live via Kafka hot-reload within 30 seconds of approval.
              </div>
              <div className="flex gap-2 mt-4">
                <button
                  onClick={() => setEditing(null)}
                  className={`flex-1 px-3 py-2 rounded-lg text-xs font-medium ${isDark ? 'bg-white/5 text-slate-300' : 'bg-slate-100 text-slate-700'}`}
                >
                  Cancel
                </button>
                <button
                  onClick={handleSubmit}
                  disabled={submitMut.isPending}
                  className="flex-1 px-3 py-2 rounded-lg text-xs font-medium bg-cyan-600 hover:bg-cyan-500 text-white disabled:opacity-50"
                >
                  {submitMut.isPending ? 'Submitting…' : 'Submit for Approval'}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  )
}

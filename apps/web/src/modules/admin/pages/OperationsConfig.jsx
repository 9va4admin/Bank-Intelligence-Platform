/**
 * OperationsConfig — Layer 3 operational config, ops_manager maker-checker.
 *
 * Route: /admin/config/operations  (permission: config:layer3:submit)
 * Role:  ops_manager (submit) → bank_it_admin (approve)
 *
 * Data: live from GET /v1/admin/config/thresholds
 * Submit: POST /v1/admin/config/thresholds → Immudb + Kafka + notification
 * Change log: GET /v1/admin/config/thresholds/changes
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'
import InfoTooltip from '../../../shared/components/InfoTooltip'
import { msg } from '../../../shared/messages'

// ─── UI metadata schema (labels, types, options — not from API) ───────────────

const CONFIG_META = {
  stp_mode: {
    label: msg('UI_OPERATIONSCONFIG_STP_MODE'), unit: '', type: 'enum',
    options: ['FULL_MANUAL', 'SUPERVISED', 'SELECTIVE', 'FULL_STP'],
    defaultVal: 'SUPERVISED', category: 'STP Pipeline',
    desc: msg('UI_OPERATIONSCONFIG_CONTROLS_WHEN_AI_STP_CONFIRM'),
    warn: true, editable: true,
  },
  stp_auto_confirm_threshold: {
    label: msg('UI_OPERATIONSCONFIG_STP_AUTO_CONFIRM_SCORE'), unit: 'score (0–1)', type: 'float',
    min: 0.85, max: 0.99, defaultVal: '0.92', category: 'STP Pipeline',
    desc: msg('UI_OPERATIONSCONFIG_FRAUD_PROBABILITY_BELOW_THIS_SCORE'),
    warn: false, editable: true,
  },
  human_review_fraud_threshold: {
    label: msg('UI_OPERATIONSCONFIG_HUMAN_REVIEW_TRIGGER_SCORE'), unit: 'score (0–1)', type: 'float',
    min: 0.50, max: 0.90, defaultVal: '0.72', category: 'STP Pipeline',
    desc: msg('UI_OPERATIONSCONFIG_FRAUD_PROBABILITY_ABOVE_THIS_SCORE'),
    warn: false, editable: true,
  },
  queue_tier_high_value_threshold: {
    label: msg('UI_OPERATIONSCONFIG_HIGH_VALUE_QUEUE_THRESHOLD'), unit: '₹', type: 'integer',
    min: 50000, max: 500000, defaultVal: '100000', category: 'Queue Segmentation',
    desc: msg('UI_OPERATIONSCONFIG_CHEQUES_ABOVE_THIS_AMOUNT_ARE', { bank_id: '{bank_id}' }),
    warn: false, editable: true,
  },
  queue_tier_very_high_threshold: {
    label: msg('UI_OPERATIONSCONFIG_VERY_HIGH_VALUE_QUEUE_THRESHOLD'), unit: '₹', type: 'integer',
    min: 500000, max: 50000000, defaultVal: '1000000', category: 'Queue Segmentation',
    desc: msg('UI_OPERATIONSCONFIG_CHEQUES_ABOVE_THIS_AMOUNT_ARE_2', { bank_id: '{bank_id}' }),
    warn: false, editable: true,
  },
  allocation_mode: {
    label: msg('UI_OPERATIONSCONFIG_REVIEWER_ALLOCATION_MODE'), unit: '', type: 'enum',
    options: ['SELF', 'HYBRID', 'AUTO'], defaultVal: 'HYBRID', category: 'Allocation',
    desc: msg('UI_OPERATIONSCONFIG_CONTROLS_HOW_INWARD_CHEQUES_ARE'),
    warn: false, editable: true,
  },
  allocation_lock_ttl_minutes: {
    label: msg('UI_OPERATIONSCONFIG_REVIEW_LOCK_TTL'), unit: 'minutes', type: 'integer',
    min: 5, max: 60, defaultVal: '10', category: 'Allocation',
    desc: msg('UI_OPERATIONSCONFIG_REDIS_LOCK_DURATION_FOR_REVIEWER'),
    warn: false, editable: true,
  },
  iet_minutes: {
    label: msg('UI_COMMON_IET_WINDOW'), unit: 'minutes', type: 'integer',
    min: 60, max: 240, defaultVal: '180', category: 'IET & Timing',
    desc: msg('UI_OPERATIONSCONFIG_RBI_MANDATED_ITEM_EXPIRY_TIME'),
    warn: true, editable: true,
  },
  ocr_min_confidence: {
    label: msg('UI_OPERATIONSCONFIG_OCR_MINIMUM_CONFIDENCE'), unit: 'score (0–1)', type: 'float',
    min: 0.80, max: 0.99, defaultVal: '0.90', category: 'AI Confidence',
    desc: msg('UI_OPERATIONSCONFIG_GOT_OCR2_0_CONFIDENCE_BELOW'),
    warn: false, editable: true,
  },
  signature_min_match_score: {
    label: msg('UI_OPERATIONSCONFIG_SIGNATURE_MATCH_MINIMUM'), unit: 'score (0–1)', type: 'float',
    min: 0.75, max: 0.99, defaultVal: '0.87', category: 'AI Confidence',
    desc: msg('UI_OPERATIONSCONFIG_SIAMESE_NETWORK_MATCH_SCORE_BELOW'),
    warn: false, editable: true,
  },
  high_value_amount_threshold: {
    label: msg('UI_OPERATIONSCONFIG_HIGH_VALUE_DUAL_APPROVAL_LIMIT'), unit: '₹', type: 'integer',
    min: 100000, max: 10000000, defaultVal: '500000', category: 'Amount Controls',
    desc: msg('UI_OPERATIONSCONFIG_CHEQUES_ABOVE_THIS_AMOUNT_REQUIRE'),
    warn: false, editable: true,
  },
  vault_miss_action: {
    label: msg('UI_COMMON_VAULT_MISS_ACTION'), unit: '', type: 'enum',
    options: [], defaultVal: 'HUMAN_REVIEW', category: 'Security',
    desc: msg('UI_OPERATIONSCONFIG_ACTION_WHEN_SIGNATURE_OR_PPS'),
    warn: true, editable: false,
  },
  outward_frozen_payee_action: {
    label: msg('UI_OPERATIONSCONFIG_OUTWARD_FROZEN_PAYEE'), unit: '', type: 'enum',
    options: ['HUMAN_REVIEW', 'AUTO_RETURN'], defaultVal: 'HUMAN_REVIEW', category: 'Outward Processing',
    desc: msg('UI_OPERATIONSCONFIG_WHEN_A_DEPOSITOR_S_PAYEE'),
    warn: false, editable: true,
  },
  outward_dormant_payee_action: {
    label: msg('UI_OPERATIONSCONFIG_OUTWARD_DORMANT_PAYEE'), unit: '', type: 'enum',
    options: ['HUMAN_REVIEW', 'AUTO_RETURN'], defaultVal: 'HUMAN_REVIEW', category: 'Outward Processing',
    desc: msg('UI_OPERATIONSCONFIG_WHEN_THE_PAYEE_ACCOUNT_IS'),
    warn: false, editable: true,
  },
  outward_npa_payee_action: {
    label: msg('UI_OPERATIONSCONFIG_OUTWARD_NPA_PAYEE'), unit: '', type: 'enum',
    options: ['HUMAN_REVIEW', 'AUTO_RETURN'], defaultVal: 'HUMAN_REVIEW', category: 'Outward Processing',
    desc: msg('UI_OPERATIONSCONFIG_WHEN_THE_PAYEE_ACCOUNT_IS_2'),
    warn: true, editable: true,
  },
  rear_image_required: {
    label: msg('UI_OPERATIONSCONFIG_REQUIRE_REAR_CHEQUE_IMAGE'), unit: '', type: 'enum',
    options: ['false', 'true'], defaultVal: 'false', category: 'Outward Processing',
    desc: msg('UI_OPERATIONSCONFIG_ENFORCE_CTS_2010_DPI_AND'),
    warn: false, editable: true,
  },
}

const ENUM_DESCRIPTIONS = {
  stp_mode: {
    FULL_MANUAL: 'Every cheque goes to human review — AI only recommends',
    SUPERVISED:  'Human confirms every STP_CONFIRM before filing',
    SELECTIVE:   'Auto-file high-confidence; human reviews borderline cases',
    FULL_STP:    'All STP_CONFIRM decisions auto-file without human review',
  },
  allocation_mode: {
    SELF:   'Reviewers manually claim from the queue — no auto-assignment',
    HYBRID: 'Claim manually or system assigns unclaimed items',
    AUTO:   'System assigns all items via round-robin',
  },
  outward_frozen_payee_action: {
    HUMAN_REVIEW: 'Instrument sent to mismatch queue — ops reviewer decides',
    AUTO_RETURN:  'Instrument rejected at teller window immediately',
  },
  outward_dormant_payee_action: {
    HUMAN_REVIEW: 'Instrument sent to mismatch queue — ops reviewer verifies reactivation',
    AUTO_RETURN:  'Instrument rejected at teller window immediately',
  },
  outward_npa_payee_action: {
    HUMAN_REVIEW: 'Instrument sent to mismatch queue — ops reviewer confirms return (recommended)',
    AUTO_RETURN:  'Instrument rejected immediately — use only after compliance sign-off',
  },
  rear_image_required: {
    false: 'Blank / missing rear image is accepted — no quality check on back of cheque',
    true:  'Rear image must meet CTS-2010 DPI (≥200) and IQA (≥0.70) — enable only if bank endorses reverse',
  },
}

const CATEGORIES = ['All', 'STP Pipeline', 'Queue Segmentation', 'Allocation', 'IET & Timing', 'AI Confidence', 'Amount Controls', 'Outward Processing', 'Security']

// ─── API helpers ──────────────────────────────────────────────────────────────

async function fetchThresholds() {
  const res = await fetch('/v1/admin/config/thresholds', { credentials: 'include' })
  if (!res.ok) throw new Error(msg('UI_OPERATIONSCONFIG_FAILED_TO_LOAD_THRESHOLDS'))
  return res.json()
}

async function fetchChanges() {
  const res = await fetch('/v1/admin/config/thresholds/changes', { credentials: 'include' })
  if (!res.ok) return { changes: [] }
  return res.json()
}

async function postThresholdChange({ config_key, new_value, reason }) {
  const res = await fetch('/v1/admin/config/thresholds', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ config_key, new_value, reason }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function OperationsConfig() {
  const { isDark } = useTheme()
  const { bankId } = useBankContext()
  const queryClient = useQueryClient()

  const [cat, setCat] = useState('All')
  const [tab, setTab] = useState('config')
  const [editing, setEditing] = useState(null)
  const [editVal, setEditVal] = useState('')
  const [reason, setReason] = useState('')
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
    input:   isDark ? 'bg-white/5 border-white/10 text-white focus:border-violet-500' : 'bg-white border-slate-300 text-slate-900 focus:border-violet-500',
    select:  isDark ? 'bg-[#0e1428] border-white/10 text-white' : 'bg-white border-slate-300 text-slate-900',
  }

  // Live config values from API
  const { data: thresholdsData, isLoading } = useQuery({
    queryKey: ['admin-thresholds', bankId],
    queryFn: fetchThresholds,
    staleTime: 30_000,
  })

  // Change log from API (only when tab is active)
  const { data: changesData, isLoading: changesLoading } = useQuery({
    queryKey: ['admin-config-changes', bankId],
    queryFn: fetchChanges,
    enabled: tab === 'change-log',
    staleTime: 10_000,
  })

  // Submit mutation
  const submitMutation = useMutation({
    mutationFn: postThresholdChange,
    onSuccess: (data) => {
      setSubmitted(data.config_key)
      setEditing(null)
      setReason('')
      setSubmitError(null)
      queryClient.invalidateQueries({ queryKey: ['admin-config-changes', bankId] })
    },
    onError: (err) => {
      setSubmitError(err.message)
    },
  })

  // Merge API values over schema metadata
  const apiMap = Object.fromEntries(
    (thresholdsData?.thresholds ?? []).map(t => [t.config_key, t])
  )
  const configItems = Object.entries(CONFIG_META).map(([key, meta]) => {
    const api = apiMap[key]
    const layerNum = api?.layer === 'LAYER_1' ? 1 : api?.layer === 'LAYER_2' ? 2 : 3
    return { ...meta, key, value: api?.current_value ?? meta.defaultVal, layer: layerNum }
  })

  const displayed = configItems.filter(c => cat === 'All' || c.category === cat)
  const changes = changesData?.changes ?? []

  function openEdit(cfg) {
    setEditing(cfg)
    setEditVal(String(cfg.value))
    setReason('')
    setReasonErr('')
    setSubmitted(null)
    setSubmitError(null)
  }

  function submitChange() {
    if (!reason.trim() || reason.trim().length < 10) {
      setReasonErr('Reason must be at least 10 characters')
      return
    }
    setReasonErr('')
    submitMutation.mutate({
      config_key: editing.key,
      new_value: editVal,
      reason: reason.trim(),
    })
  }

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>

        {/* Header */}
        <div className="mb-5">
          <div className="flex items-center gap-3 mb-1">
            <h1 className={`text-lg font-semibold ${th.heading}`}>{msg('UI_OPERATIONSCONFIG_OPERATIONS_CONFIG')}</h1>
            <span className={`text-xs px-2 py-0.5 rounded border font-medium ${isDark ? 'border-violet-700/40 bg-violet-900/30 text-violet-300' : 'border-violet-200 bg-violet-50 text-violet-700'}`}>
             {msg('UI_OPERATIONSCONFIG_LAYER_3')}
            </span>
          </div>
          <p className={`text-xs ${th.muted}`}>
           {msg('UI_OPERATIONSCONFIG_BUSINESS_RULES_AND_OPERATIONAL_MODES')}
          </p>
        </div>

        {/* Tabs */}
        <div className={`flex gap-1 mb-5 border-b ${th.divider}`}>
          {[['config', 'Config'], ['change-log', 'Change Log']].map(([id, label]) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={`px-4 py-2 text-xs font-medium transition-colors border-b-2 -mb-px ${tab === id ? 'border-violet-500 text-violet-400' : `border-transparent ${th.muted}`}`}
            >
              {label}
            </button>
          ))}
        </div>

        {tab === 'config' && (
          <>
            {submitted && (
              <div className={`mb-4 rounded-lg border px-4 py-3 text-xs ${isDark ? 'border-emerald-700/40 bg-emerald-900/20 text-emerald-300' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>
               {msg('UI_OPERATIONSCONFIG_CHANGE_SUBMITTED_FOR_BANK_IT')}
              </div>
            )}

            {isLoading && (
              <div className={`mb-4 text-xs ${th.muted}`}>{msg('UI_OPERATIONSCONFIG_LOADING_LIVE_CONFIG_VALUES')}</div>
            )}

            {/* Category filter */}
            <div className="flex gap-1.5 flex-wrap mb-4">
              {CATEGORIES.map(c => (
                <button
                  key={c}
                  onClick={() => setCat(c)}
                  className={`px-3 h-7 rounded-lg text-xs font-medium transition-all border ${
                    cat === c
                      ? 'bg-violet-600 text-white border-violet-600'
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
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${isDark ? 'bg-white/5 text-slate-400' : 'bg-slate-100 text-slate-500'}`}>
                         {msg('UI_OPERATIONSCONFIG_LAYER', { layer: cfg.layer })}
                        </span>
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${isDark ? 'bg-white/5 text-slate-500' : 'bg-slate-50 text-slate-400'}`}>
                          {cfg.category}
                        </span>
                        {cfg.warn && (
                          <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${isDark ? 'bg-amber-900/40 text-amber-300' : 'bg-amber-100 text-amber-700'}`}>
                           {msg('UI_OPERATIONSCONFIG_HIGH_IMPACT')}
                          </span>
                        )}
                        {!cfg.editable && (
                          <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${isDark ? 'bg-red-900/30 text-red-400' : 'bg-red-100 text-red-600'}`}>
                           {msg('UI_OPERATIONSCONFIG_LOCKED')}
                          </span>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center gap-3 shrink-0">
                      <div className="text-right">
                        <div className={`text-xl font-bold tabular-nums ${cfg.warn ? (isDark ? 'text-amber-300' : 'text-amber-600') : th.heading}`}>
                          {cfg.type === 'float'
                            ? parseFloat(cfg.value).toFixed(2)
                            : cfg.type === 'integer'
                              ? parseInt(cfg.value, 10).toLocaleString('en-IN')
                              : cfg.value}
                        </div>
                        {cfg.unit && <div className={`text-[10px] ${th.muted}`}>{cfg.unit}</div>}
                      </div>
                      {cfg.editable && (
                        <button
                          onClick={() => openEdit(cfg)}
                          className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${isDark ? 'bg-white/5 text-slate-300 hover:bg-white/10' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'}`}
                        >
                         {msg('UI_COMMON_EDIT')}
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Range bar for numeric */}
                  {(cfg.type === 'float' || cfg.type === 'integer') && cfg.editable && cfg.min !== undefined && (
                    <div className="mt-3">
                      <div className={`h-1.5 rounded-full overflow-hidden ${isDark ? 'bg-white/8' : 'bg-slate-100'}`}>
                        <div
                          className="h-full bg-violet-500 rounded-full transition-all"
                          style={{ width: `${Math.min(100, Math.max(0, ((parseFloat(cfg.value) - cfg.min) / (cfg.max - cfg.min)) * 100))}%` }}
                        />
                      </div>
                      <div className={`flex justify-between mt-1 text-[10px] ${th.muted}`}>
                        <span>{cfg.type === 'float' ? cfg.min.toFixed(2) : cfg.min.toLocaleString('en-IN')}</span>
                        <span>{cfg.type === 'float' ? cfg.max.toFixed(2) : cfg.max.toLocaleString('en-IN')}</span>
                      </div>
                    </div>
                  )}

                  {/* Enum option pills */}
                  {cfg.type === 'enum' && cfg.options && cfg.options.length > 0 && (
                    <div className="mt-3 flex gap-2 flex-wrap">
                      {cfg.options.map(opt => (
                        <span
                          key={opt}
                          className={`text-xs px-2 py-0.5 rounded border font-mono ${
                            opt === cfg.value
                              ? (isDark ? 'border-violet-600/60 bg-violet-900/40 text-violet-300' : 'border-violet-300 bg-violet-50 text-violet-700')
                              : `${isDark ? 'border-white/8 text-slate-500' : 'border-slate-200 text-slate-400'}`
                          }`}
                        >
                          {opt === cfg.value ? '● ' : ''}{opt}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </>
        )}

        {tab === 'change-log' && (
          <div className={`rounded-xl border overflow-hidden ${th.card}`}>
            {changesLoading ? (
              <div className={`px-5 py-8 text-xs text-center ${th.muted}`}>{msg('UI_OPERATIONSCONFIG_LOADING_CHANGE_HISTORY')}</div>
            ) : changes.length === 0 ? (
              <div className={`px-5 py-8 text-xs text-center ${th.muted}`}>{msg('UI_OPERATIONSCONFIG_NO_CONFIG_CHANGES_ON_RECORD')}</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className={`border-b ${th.divider}`}>
                      {[msg('UI_COMMON_CONFIG_KEY'), msg('UI_COMMON_NEW_VALUE'), msg('UI_COMMON_REASON'), msg('UI_COMMON_SUBMITTED_BY'), msg('UI_COMMON_APPROVED_BY'), msg('UI_OPERATIONSCONFIG_SUBMITTED_AT'), msg('UI_COMMON_STATUS')].map(h => (
                        <th key={h} className={`px-4 py-3 text-left font-medium whitespace-nowrap ${th.muted}`}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {changes.map((c, i) => (
                      <tr key={c.change_id ?? i} className={`border-b transition-colors ${th.row}`}>
                        <td className={`px-4 py-3 font-mono text-[11px] ${th.body}`}>{c.config_key}</td>
                        <td className={`px-4 py-3 font-semibold ${isDark ? 'text-violet-300' : 'text-violet-700'}`}>{c.new_value}</td>
                        <td className={`px-4 py-3 max-w-xs truncate ${th.muted}`} title={c.reason}>{c.reason}</td>
                        <td className={`px-4 py-3 ${th.body}`}>{c.submitted_by}</td>
                        <td className={`px-4 py-3 ${th.body}`}>{c.actioned_by ?? <span className={th.muted}>{msg('UI_OPERATIONSCONFIG_PENDING')}</span>}</td>
                        <td className={`px-4 py-3 font-mono text-[11px] whitespace-nowrap ${th.muted}`}>
                          {c.submitted_at ? new Date(c.submitted_at).toLocaleString('en-IN') : '—'}
                        </td>
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
              </div>
            )}
          </div>
        )}
      </div>

      {/* Edit modal */}
      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.65)' }}>
          <div className={`w-full max-w-md rounded-2xl border p-6 shadow-2xl ${isDark ? 'bg-[#0e1428] border-white/10' : 'bg-white border-slate-200'}`}>
            <div className="flex items-center justify-between mb-4">
              <h3 className={`font-semibold ${th.heading}`}>{msg('UI_OPERATIONSCONFIG_EDIT', { label: editing.label })}</h3>
              <button onClick={() => setEditing(null)} className={`${th.muted} hover:${th.body} text-lg leading-none`}>✕</button>
            </div>

            <p className={`text-xs mb-4 leading-relaxed ${th.muted}`}>{editing.desc}</p>

            {editing.type === 'enum' ? (
              <div className="space-y-2 mb-4">
                <label className={`text-xs font-medium ${th.muted}`}>{msg('UI_OPERATIONSCONFIG_SELECT_VALUE')}</label>
                <select
                  value={editVal}
                  onChange={e => setEditVal(e.target.value)}
                  className={`w-full h-9 px-3 rounded-lg border text-sm outline-none ${th.select}`}
                >
                  {editing.options.map(opt => (
                    <option key={opt} value={opt}>{opt}</option>
                  ))}
                </select>
                {ENUM_DESCRIPTIONS[editing.key]?.[editVal] && (
                  <p className={`text-[11px] ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>
                    {ENUM_DESCRIPTIONS[editing.key][editVal]}
                  </p>
                )}
              </div>
            ) : (
              <div className="mb-4">
                <label className={`text-xs font-medium ${th.muted}`}>{msg('UI_OPERATIONSCONFIG_NEW_VALUE', { unit: editing.unit })}</label>
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
                  <p className={`text-[10px] mt-1 ${th.muted}`}>
                   {msg('UI_OPERATIONSCONFIG_RANGE', { value: editing.type === 'float' ? editing.min.toFixed(2) : editing.min.toLocaleString('en-IN'), value2: editing.type === 'float' ? editing.max.toFixed(2) : editing.max.toLocaleString('en-IN') })}
                  </p>
                )}
              </div>
            )}

            {/* Reason — required by maker-checker API */}
            <div className="mb-4">
              <label className={`text-xs font-medium ${th.muted}`}>{msg('UI_OPERATIONSCONFIG_REASON_FOR_CHANGE')} <span className="text-red-400">*</span></label>
              <textarea
                value={reason}
                onChange={e => { setReason(e.target.value); setReasonErr('') }}
                rows={2}
                placeholder={msg('UI_OPERATIONSCONFIG_WHY_IS_THIS_CHANGE_NEEDED')}
                className={`w-full mt-1 px-3 py-2 rounded-lg border text-sm outline-none transition-colors resize-none ${th.input}`}
              />
              {reasonErr && <p className="text-[11px] mt-1 text-red-400">{reasonErr}</p>}
            </div>

            {submitError && (
              <div className={`mb-3 rounded-lg border px-3 py-2 text-xs ${isDark ? 'border-red-700/40 bg-red-900/20 text-red-300' : 'border-red-200 bg-red-50 text-red-700'}`}>
                {submitError}
              </div>
            )}

            <div className={`mb-4 p-3 rounded-lg text-xs leading-relaxed ${isDark ? 'bg-amber-900/20 border border-amber-700/40 text-amber-300' : 'bg-amber-50 border border-amber-200 text-amber-800'}`}>
             {msg('UI_OPERATIONSCONFIG_THIS_CHANGE_WILL_BE_SUBMITTED')}
            </div>

            <div className="flex gap-2">
              <button
                onClick={() => setEditing(null)}
                className={`flex-1 px-3 py-2 rounded-lg text-xs font-medium ${isDark ? 'bg-white/5 text-slate-300 hover:bg-white/10' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'}`}
              >
               {msg('UI_COMMON_CANCEL')}
              </button>
              <button
                onClick={submitChange}
                disabled={submitMutation.isPending}
                className={`flex-1 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${submitMutation.isPending ? 'opacity-60 cursor-not-allowed bg-violet-700 text-white' : 'bg-violet-600 hover:bg-violet-500 text-white'}`}
              >
                {submitMutation.isPending ? 'Submitting…' : 'Submit for Approval'}
              </button>
            </div>
          </div>
        </div>
      )}
    </AppShell>
  )
}

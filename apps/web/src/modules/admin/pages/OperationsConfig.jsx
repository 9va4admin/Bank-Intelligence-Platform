/**
 * OperationsConfig — Layer 3 operational config, ops_manager maker-checker.
 *
 * Route: /admin/config/operations  (permission: config:layer3:submit)
 * Role:  ops_manager (submit) → bank_it_admin (approve)
 *
 * Covers all Phase C/D/E/F config keys added by the CTS pipeline improvements:
 *  - STP mode (Phase C)
 *  - Queue tier thresholds (Phase D)
 *  - Allocation mode & lock TTL (Phase E)
 *  - Standard AI + IET thresholds
 *
 * All changes are hot-reloaded within 30 seconds of bank_it_admin approval
 * via the platform.config.changed Kafka event → config_service Redis invalidation.
 */
import { useState } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'

// ─── Config schema ─────────────────────────────────────────────────────────────

const OPS_CONFIG = [
  // ── STP Pipeline (Phase C) ──────────────────────────────────────────────
  {
    key: 'stp_mode',
    label: 'STP Mode',
    value: 'SUPERVISED',
    unit: '',
    type: 'enum',
    options: ['FULL_MANUAL', 'SUPERVISED', 'SELECTIVE', 'FULL_STP'],
    layer: 3,
    category: 'STP Pipeline',
    desc: 'Controls when AI STP_CONFIRM decisions auto-file to NGCH. FULL_MANUAL = every cheque goes to human review. SUPERVISED = AI recommends, human confirms. SELECTIVE = AI auto-files low-risk, human reviews the rest. FULL_STP = all STP_CONFIRM decisions auto-file without review.',
    warn: true,
    editable: true,
  },
  {
    key: 'stp_auto_confirm_threshold',
    label: 'STP Auto-Confirm Score',
    value: 0.92,
    unit: 'score (0–1)',
    type: 'float',
    min: 0.85, max: 0.99,
    layer: 3,
    category: 'STP Pipeline',
    desc: 'Fraud probability below this score qualifies a cheque for STP_CONFIRM. Only applies when stp_mode is SELECTIVE or FULL_STP.',
    warn: false,
    editable: true,
  },
  {
    key: 'human_review_fraud_threshold',
    label: 'Human Review Trigger Score',
    value: 0.72,
    unit: 'score (0–1)',
    type: 'float',
    min: 0.50, max: 0.90,
    layer: 3,
    category: 'STP Pipeline',
    desc: 'Fraud probability above this score routes the cheque to the ops reviewer queue instead of auto-confirm. Must be lower than STP threshold.',
    warn: false,
    editable: true,
  },

  // ── Queue Segmentation (Phase D) ────────────────────────────────────────
  {
    key: 'queue_tier_high_value_threshold',
    label: 'High-Value Queue Threshold',
    value: 100000,
    unit: '₹',
    type: 'integer',
    min: 50000, max: 500000,
    layer: 3,
    category: 'Queue Segmentation',
    desc: 'Cheques above this amount are routed to the High Value Kafka topic (cts.inward.{bank_id}.high_value) and a dedicated Temporal task queue, isolating high-value processing from standard throughput.',
    warn: false,
    editable: true,
  },
  {
    key: 'queue_tier_very_high_threshold',
    label: 'Very High-Value Queue Threshold',
    value: 1000000,
    unit: '₹',
    type: 'integer',
    min: 500000, max: 50000000,
    layer: 3,
    category: 'Queue Segmentation',
    desc: 'Cheques above this amount are routed to the Very High Value Kafka topic (cts.inward.{bank_id}.very_high). These instruments get the highest-priority worker pods and dedicated vLLM inference slots.',
    warn: false,
    editable: true,
  },

  // ── Allocation (Phase E) ────────────────────────────────────────────────
  {
    key: 'allocation_mode',
    label: 'Reviewer Allocation Mode',
    value: 'HYBRID',
    unit: '',
    type: 'enum',
    options: ['SELF', 'HYBRID', 'AUTO'],
    layer: 3,
    category: 'Allocation',
    desc: 'Controls how inward cheques are assigned to ops_reviewers. SELF = reviewers manually claim from queue. HYBRID = reviewers can claim manually or system auto-assigns unclaimed items. AUTO = system auto-assigns all using round-robin over available reviewers.',
    warn: false,
    editable: true,
  },
  {
    key: 'allocation_lock_ttl_minutes',
    label: 'Review Lock TTL',
    value: 10,
    unit: 'minutes',
    type: 'integer',
    min: 5, max: 60,
    layer: 3,
    category: 'Allocation',
    desc: 'Redis lock duration for reviewer-claimed instruments. If a reviewer claims an instrument and does not submit a decision within this window, the lock expires and the instrument becomes claimable again.',
    warn: false,
    editable: true,
  },

  // ── IET & Timing ────────────────────────────────────────────────────────
  {
    key: 'iet_minutes',
    label: 'IET Window',
    value: 180,
    unit: 'minutes',
    type: 'integer',
    min: 60, max: 240,
    layer: 3,
    category: 'IET & Timing',
    desc: 'RBI-mandated Item Expiry Time window. Cheques not decided within this window are deemed approved and must be paid. Default: 180 min (3 hours). Do not lower without verifying operational capacity.',
    warn: true,
    editable: true,
  },

  // ── AI Confidence ───────────────────────────────────────────────────────
  {
    key: 'ocr_min_confidence',
    label: 'OCR Minimum Confidence',
    value: 0.90,
    unit: 'score (0–1)',
    type: 'float',
    min: 0.80, max: 0.99,
    layer: 3,
    category: 'AI Confidence',
    desc: 'GOT-OCR2.0 confidence below this threshold routes the cheque to human review for manual MICR / field verification.',
    warn: false,
    editable: true,
  },
  {
    key: 'signature_min_match_score',
    label: 'Signature Match Minimum',
    value: 0.87,
    unit: 'score (0–1)',
    type: 'float',
    min: 0.75, max: 0.99,
    layer: 3,
    category: 'AI Confidence',
    desc: 'Siamese network match score below this routes to human review for manual signature comparison. Lower = more human review load; higher = more STP risk.',
    warn: false,
    editable: true,
  },

  // ── Amount Controls ─────────────────────────────────────────────────────
  {
    key: 'high_value_amount_threshold',
    label: 'High-Value Dual-Approval Limit',
    value: 500000,
    unit: '₹',
    type: 'integer',
    min: 100000, max: 10000000,
    layer: 3,
    category: 'Amount Controls',
    desc: 'Cheques above this amount require dual ops_reviewer approval before NGCH filing, regardless of AI confidence score. Aligns with RBI high-value transaction monitoring norms.',
    warn: false,
    editable: true,
  },

  // ── Security (Locked) ───────────────────────────────────────────────────
  {
    key: 'vault_miss_action',
    label: 'Vault Miss Action',
    value: 'HUMAN_REVIEW',
    unit: '',
    type: 'enum',
    layer: 1,
    category: 'Security',
    desc: 'Action when signature or PPS vault has no record for an account. LOCKED to HUMAN_REVIEW by platform constraint (Layer 1) — cannot be changed to AUTO_RETURN by any role.',
    warn: true,
    editable: false,
  },
]

const CHANGE_LOG = [
  { key: 'stp_mode',              old: 'FULL_MANUAL', new: 'SUPERVISED', by: 'ops_manager@svcb', approved: 'itadmin@svcb', at: '2026-08-01 10:14', status: 'LIVE' },
  { key: 'allocation_mode',       old: 'SELF',        new: 'HYBRID',     by: 'ops_manager@svcb', approved: 'itadmin@svcb', at: '2026-08-01 10:15', status: 'LIVE' },
  { key: 'stp_auto_confirm_threshold', old: '0.90',   new: '0.92',       by: 'ops_manager@svcb', approved: 'itadmin@svcb', at: '2026-07-18 14:32', status: 'LIVE' },
  { key: 'ocr_min_confidence',    old: '0.88',        new: '0.90',       by: 'ops_manager@svcb', approved: null,           at: '2026-08-03 09:20', status: 'PENDING_APPROVAL' },
]

const CATEGORIES = ['All', 'STP Pipeline', 'Queue Segmentation', 'Allocation', 'IET & Timing', 'AI Confidence', 'Amount Controls', 'Security']

const ENUM_DESCRIPTIONS = {
  stp_mode: {
    FULL_MANUAL:  'Every cheque goes to human review — AI only recommends',
    SUPERVISED:   'Human confirms every STP_CONFIRM before filing',
    SELECTIVE:    'Auto-file high-confidence; human reviews borderline cases',
    FULL_STP:     'All STP_CONFIRM decisions auto-file without human review',
  },
  allocation_mode: {
    SELF:   'Reviewers manually claim from the queue — no auto-assignment',
    HYBRID: 'Claim manually or system assigns unclaimed items',
    AUTO:   'System assigns all items via round-robin',
  },
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function OperationsConfig() {
  const { isDark } = useTheme()
  const { bankId, bankName } = useBankContext()
  const [cat, setCat] = useState('All')
  const [tab, setTab] = useState('config')
  const [editing, setEditing] = useState(null)
  const [editVal, setEditVal] = useState('')
  const [pendingSubmit, setPendingSubmit] = useState(false)
  const [submitted, setSubmitted] = useState(null)

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

  const displayed = OPS_CONFIG.filter(c => cat === 'All' || c.category === cat)

  function openEdit(cfg) {
    setEditing(cfg)
    setEditVal(String(cfg.value))
    setSubmitted(null)
  }

  function submitChange() {
    setPendingSubmit(true)
    setTimeout(() => {
      setPendingSubmit(false)
      setSubmitted(editing.key)
      setEditing(null)
    }, 700)
  }

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>

        {/* Header */}
        <div className="mb-5">
          <div className="flex items-center gap-3 mb-1">
            <h1 className={`text-lg font-semibold ${th.heading}`}>Operations Config</h1>
            <span className={`text-xs px-2 py-0.5 rounded border font-medium ${isDark ? 'border-violet-700/40 bg-violet-900/30 text-violet-300' : 'border-violet-200 bg-violet-50 text-violet-700'}`}>
              Layer 3
            </span>
          </div>
          <p className={`text-xs ${th.muted}`}>
            Business rules and operational modes — hot-reloaded within 30 seconds of bank_it_admin approval.
            All changes require maker-checker: ops_manager submits → bank_it_admin approves.
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
            {/* Submitted toast */}
            {submitted && (
              <div className={`mb-4 rounded-lg border px-4 py-3 text-xs ${isDark ? 'border-emerald-700/40 bg-emerald-900/20 text-emerald-300' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>
                Change submitted for bank_it_admin approval. It will go live within 30 seconds of approval.
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
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${isDark ? 'bg-white/5 text-slate-400' : 'bg-slate-100 text-slate-500'}`}>
                          Layer {cfg.layer}
                        </span>
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${isDark ? 'bg-white/5 text-slate-500' : 'bg-slate-50 text-slate-400'}`}>
                          {cfg.category}
                        </span>
                        {cfg.warn && (
                          <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${isDark ? 'bg-amber-900/40 text-amber-300' : 'bg-amber-100 text-amber-700'}`}>
                            HIGH IMPACT
                          </span>
                        )}
                        {!cfg.editable && (
                          <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${isDark ? 'bg-red-900/30 text-red-400' : 'bg-red-100 text-red-600'}`}>
                            LOCKED
                          </span>
                        )}
                      </div>
                      <p className={`text-xs mt-1 leading-relaxed ${th.muted}`}>{cfg.desc}</p>
                    </div>

                    <div className="flex items-center gap-3 shrink-0">
                      <div className="text-right">
                        <div className={`text-xl font-bold tabular-nums ${cfg.warn ? (isDark ? 'text-amber-300' : 'text-amber-600') : th.heading}`}>
                          {cfg.type === 'float'
                            ? Number(cfg.value).toFixed(2)
                            : cfg.type === 'integer'
                              ? Number(cfg.value).toLocaleString('en-IN')
                              : cfg.value}
                        </div>
                        {cfg.unit && <div className={`text-[10px] ${th.muted}`}>{cfg.unit}</div>}
                      </div>
                      {cfg.editable && (
                        <button
                          onClick={() => openEdit(cfg)}
                          className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${isDark ? 'bg-white/5 text-slate-300 hover:bg-white/10' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'}`}
                        >
                          Edit
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
                          style={{ width: `${((cfg.value - cfg.min) / (cfg.max - cfg.min)) * 100}%` }}
                        />
                      </div>
                      <div className={`flex justify-between mt-1 text-[10px] ${th.muted}`}>
                        <span>{cfg.type === 'float' ? cfg.min.toFixed(2) : cfg.min.toLocaleString('en-IN')}</span>
                        <span>{cfg.type === 'float' ? cfg.max.toFixed(2) : cfg.max.toLocaleString('en-IN')}</span>
                      </div>
                    </div>
                  )}

                  {/* Enum option pills */}
                  {cfg.type === 'enum' && cfg.options && (
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
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className={`border-b ${th.divider}`}>
                    {['Config Key', 'Old Value', 'New Value', 'Submitted By', 'Approved By', 'Timestamp', 'Status'].map(h => (
                      <th key={h} className={`px-4 py-3 text-left font-medium whitespace-nowrap ${th.muted}`}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {CHANGE_LOG.map((c, i) => (
                    <tr key={i} className={`border-b transition-colors ${th.row}`}>
                      <td className={`px-4 py-3 font-mono text-[11px] ${th.body}`}>{c.key}</td>
                      <td className={`px-4 py-3 ${th.muted} line-through`}>{c.old}</td>
                      <td className={`px-4 py-3 font-semibold ${isDark ? 'text-violet-300' : 'text-violet-700'}`}>{c.new}</td>
                      <td className={`px-4 py-3 ${th.body}`}>{c.by}</td>
                      <td className={`px-4 py-3 ${th.body}`}>{c.approved ?? <span className={th.muted}>Pending…</span>}</td>
                      <td className={`px-4 py-3 font-mono text-[11px] whitespace-nowrap ${th.muted}`}>{c.at}</td>
                      <td className="px-4 py-3">
                        <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${
                          c.status === 'LIVE'
                            ? (isDark ? 'bg-emerald-900/40 text-emerald-300' : 'bg-emerald-100 text-emerald-700')
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
          </div>
        )}
      </div>

      {/* Edit modal */}
      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.65)' }}>
          <div className={`w-full max-w-md rounded-2xl border p-6 shadow-2xl ${isDark ? 'bg-[#0e1428] border-white/10' : 'bg-white border-slate-200'}`}>
            <div className="flex items-center justify-between mb-4">
              <h3 className={`font-semibold ${th.heading}`}>Edit — {editing.label}</h3>
              <button onClick={() => setEditing(null)} className={`${th.muted} hover:${th.body} text-lg leading-none`}>✕</button>
            </div>

            <p className={`text-xs mb-4 leading-relaxed ${th.muted}`}>{editing.desc}</p>

            {editing.type === 'enum' ? (
              <div className="space-y-2">
                <label className={`text-xs font-medium ${th.muted}`}>Select value</label>
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
              <div>
                <label className={`text-xs font-medium ${th.muted}`}>New value ({editing.unit})</label>
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
                    Range: {editing.type === 'float' ? editing.min.toFixed(2) : editing.min.toLocaleString('en-IN')} – {editing.type === 'float' ? editing.max.toFixed(2) : editing.max.toLocaleString('en-IN')}
                  </p>
                )}
              </div>
            )}

            <div className={`mt-4 p-3 rounded-lg text-xs leading-relaxed ${isDark ? 'bg-amber-900/20 border border-amber-700/40 text-amber-300' : 'bg-amber-50 border border-amber-200 text-amber-800'}`}>
              ⚠ This change will be submitted to bank_it_admin for approval (maker-checker).
              It goes live via Kafka hot-reload within 30 seconds of approval.
            </div>

            <div className="flex gap-2 mt-4">
              <button
                onClick={() => setEditing(null)}
                className={`flex-1 px-3 py-2 rounded-lg text-xs font-medium ${isDark ? 'bg-white/5 text-slate-300 hover:bg-white/10' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'}`}
              >
                Cancel
              </button>
              <button
                onClick={submitChange}
                disabled={pendingSubmit}
                className={`flex-1 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${pendingSubmit ? 'opacity-60 cursor-not-allowed bg-violet-700 text-white' : 'bg-violet-600 hover:bg-violet-500 text-white'}`}
              >
                {pendingSubmit ? 'Submitting…' : 'Submit for Approval'}
              </button>
            </div>
          </div>
        </div>
      )}
    </AppShell>
  )
}

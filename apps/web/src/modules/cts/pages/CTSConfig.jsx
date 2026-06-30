import { useState } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'
import { useBankContext } from '../../../shared/context/BankContext'
import { getReturnReasons, saveReturnReasons, getDefaultReturnReasons } from '../data/returnReasons'

const LAYER3_CONFIG = [
  { key: 'iet_minutes',                  label: 'IET Window',                value: 180,      unit: 'minutes', desc: 'RBI mandated clearing window. Breach = deemed approval.',       editable: true,  warn: true  },
  { key: 'stp_auto_confirm_threshold',   label: 'STP Auto-Confirm Threshold',value: 0.92,     unit: 'score',   desc: 'Fraud score below this → automatic NGCH confirm filing.',      editable: true,  warn: false },
  { key: 'human_review_fraud_threshold', label: 'Human Review Threshold',    value: 0.72,     unit: 'score',   desc: 'Fraud score above this → routed to ops reviewer queue.',        editable: true,  warn: false },
  { key: 'high_value_amount_threshold',  label: 'High-Value Limit',          value: 500000,   unit: '₹',       desc: 'Cheques above this amount require dual ops_reviewer approval.', editable: true,  warn: false },
  { key: 'vault_miss_action',            label: 'Vault Miss Action',         value: 'HUMAN_REVIEW', unit: '', desc: 'Action on signature/PPS vault miss. Cannot be changed to AUTO_RETURN.', editable: false, warn: true },
]

const LAYER2_CONFIG = [
  { key: 'module_cts_enabled',   label: 'CTS Module',       value: 'true' },
  { key: 'cbs_connector_type',   label: 'CBS Connector',    value: 'finacle' },
  { key: 'max_agent_swarm_size', label: 'Max Agent Swarm',  value: '500' },
  { key: 'clearing_zones',       label: 'Clearing Zones',   value: 'MUMBAI, DELHI' },
  { key: 'gpu_profile',          label: 'GPU Profile',      value: 'production (4×A100)' },
]

const LAYER1_CONFIG = [
  { key: 'min_tls_version',      label: 'Min TLS Version',   value: '1.3',  desc: 'Non-overridable. Enforced by Istio service mesh.' },
  { key: 'audit_trail_enabled',  label: 'Audit Trail',       value: 'true', desc: 'Cannot be disabled. Cryptographic Immudb writes on every decision.' },
  { key: 'exactly_once_ngch',    label: 'Exactly-Once NGCH', value: 'true', desc: 'Temporal idempotency. Duplicate filings are impossible by design.' },
  { key: 'iet_watchdog_enabled', label: 'IET Watchdog',      value: 'true', desc: 'Emergency filing at T-30s. Non-overridable.' },
  { key: 'hsm_required',         label: 'HSM Signing',       value: 'true', desc: 'All audit events signed with FIPS 140-2 Level 3 HSM.' },
]

const MOCK_CHANGE_LOG = [
  { key: 'stp_auto_confirm_threshold',   old: 0.90,   new: 0.92,   by: 'ops_manager@svcb', approvedBy: 'itadmin@svcb', at: '2026-06-18 14:32', status: 'APPROVED' },
  { key: 'human_review_fraud_threshold', old: 0.75,   new: 0.72,   by: 'ops_manager@svcb', approvedBy: 'itadmin@svcb', at: '2026-06-15 09:11', status: 'APPROVED' },
  { key: 'high_value_amount_threshold',  old: 300000, new: 500000, by: 'ops_manager@svcb', approvedBy: 'itadmin@svcb', at: '2026-06-10 11:45', status: 'APPROVED' },
]

function nowStr() {
  const d = new Date()
  const pad = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export default function CTSConfig() {
  const { bankId, bankName, bankIfsc, bankType, isSB, isSMB } = useBankContext()
  const { isDark } = useTheme()
  const [values, setValues] = useState(
    Object.fromEntries(LAYER3_CONFIG.map(c => [c.key, c.value]))
  )
  const [draftValues, setDraftValues] = useState(
    Object.fromEntries(LAYER3_CONFIG.map(c => [c.key, c.value]))
  )
  const [pendingChanges, setPendingChanges] = useState([])
  const [changeLog, setChangeLog] = useState(MOCK_CHANGE_LOG)

  // Return reasons management
  const [returnReasons, setReturnReasons] = useState(() => getReturnReasons())
  const [newReasonGroup, setNewReasonGroup] = useState(Object.keys(getDefaultReturnReasons())[0])
  const [newReasonText, setNewReasonText] = useState('')
  const [reasonGroups] = useState(() => Object.keys(getDefaultReturnReasons()))

  function addReason() {
    const text = newReasonText.trim()
    if (!text) return
    const updated = {
      ...returnReasons,
      [newReasonGroup]: [...(returnReasons[newReasonGroup] || []), text].sort((a, b) => a.localeCompare(b)),
    }
    setReturnReasons(updated)
    saveReturnReasons(updated)
    setNewReasonText('')
  }

  function removeReason(group, reason) {
    const updated = {
      ...returnReasons,
      [group]: returnReasons[group].filter(r => r !== reason),
    }
    setReturnReasons(updated)
    saveReturnReasons(updated)
  }

  function resetReasons() {
    const defaults = getDefaultReturnReasons()
    setReturnReasons(defaults)
    saveReturnReasons(defaults)
  }

  function handleSubmit(key) {
    const cfg = LAYER3_CONFIG.find(c => c.key === key)
    if (!cfg) return
    const oldValue = values[key]
    const newValue = draftValues[key]
    if (String(oldValue) === String(newValue)) return
    // Replace any existing pending for this key
    setPendingChanges(prev => [
      ...prev.filter(p => p.key !== key),
      { key, oldValue, newValue, submittedAt: nowStr(), submittedBy: 'ops_manager@svcb' },
    ])
  }

  function handleApprove(key) {
    const pending = pendingChanges.find(p => p.key === key)
    if (!pending) return
    setValues(v => ({ ...v, [key]: pending.newValue }))
    setDraftValues(v => ({ ...v, [key]: pending.newValue }))
    setChangeLog(prev => [
      {
        key,
        old: pending.oldValue,
        new: pending.newValue,
        by: pending.submittedBy,
        approvedBy: 'itadmin@svcb',
        at: nowStr(),
        status: 'APPROVED',
      },
      ...prev,
    ])
    setPendingChanges(prev => prev.filter(p => p.key !== key))
  }

  function handleReject(key) {
    const pending = pendingChanges.find(p => p.key === key)
    if (!pending) return
    setDraftValues(v => ({ ...v, [key]: values[key] }))
    setPendingChanges(prev => prev.filter(p => p.key !== key))
  }

  const th = {
    page:      isDark ? 'bg-navy-950' : 'bg-slate-50',
    card:      isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    cardFaint: isDark ? 'bg-navy-900/40 border-white/5' : 'bg-slate-50 border-slate-100',
    cardAmber: isDark ? 'bg-amber-900/20 border-amber-500/40' : 'bg-amber-50 border-amber-300',
    heading:   isDark ? 'text-white' : 'text-slate-900',
    body:      isDark ? 'text-slate-300' : 'text-slate-700',
    muted:     isDark ? 'text-slate-400' : 'text-slate-500',
    faint:     isDark ? 'text-slate-600' : 'text-slate-400',
    divider:   isDark ? 'border-white/8' : 'border-slate-200',
    row:       isDark ? 'border-white/4 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
    tblHead:   isDark ? 'bg-white/3 text-slate-400' : 'bg-slate-100 text-slate-500',
    tblRow:    isDark ? 'border-white/5 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
    select:    isDark ? 'bg-navy-900 border-white/10 text-white' : 'bg-white border-slate-300 text-slate-900',
    input:     isDark ? 'bg-navy-800 border-white/10 text-white' : 'bg-white border-slate-300 text-slate-900',
    meta:      isDark ? 'bg-white/10 text-slate-500' : 'bg-slate-100 text-slate-500',
    btn:       isDark ? 'bg-gold-400/10 text-gold-400 hover:bg-gold-400/20' : 'bg-amber-100 text-amber-700 hover:bg-amber-200',
    btnGreen:  isDark ? 'bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 border border-emerald-500/30' : 'bg-emerald-50 text-emerald-700 hover:bg-emerald-100 border border-emerald-300',
    btnRed:    isDark ? 'bg-red-500/10 text-red-400 hover:bg-red-500/20 border border-red-500/30' : 'bg-red-50 text-red-700 hover:bg-red-100 border border-red-300',
    l1label:   isDark ? 'text-slate-500' : 'text-slate-400',
    l1val:     isDark ? 'bg-white/10 text-slate-500' : 'bg-slate-100 text-slate-500',
    l2val:     isDark ? 'bg-sky-500/10 text-sky-400' : 'bg-sky-50 text-sky-700',
  }

  usePageHeader({
    subtitle: 'Layer 3 business rules · Layer 2 topology · Layer 1 platform constraints',
    actions: (
      <div className={`text-[10px] ${th.meta} px-3 py-1.5 rounded-lg`}>
        Maker-Checker required · Changes hot-reload in &lt;30s
      </div>
    ),
  })

  return (
    <AppShell>
      <div className={`${th.page} px-6 py-5`}>

        {/* Checker Approve section — only if pending changes */}
        {pendingChanges.length > 0 && (
          <div className={`border rounded-xl px-5 py-4 mb-6 ${th.cardAmber}`}>
            <div className="flex items-center gap-2 mb-3">
              <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse" />
              <span className="text-sm font-semibold text-amber-500">Pending Approval</span>
              <span className={`text-xs ${th.muted}`}>— requires checker sign-off (itadmin@svcb)</span>
            </div>
            <div className="space-y-2">
              {pendingChanges.map(p => {
                const cfg = LAYER3_CONFIG.find(c => c.key === p.key)
                return (
                  <div key={p.key} className={`flex items-center justify-between rounded-lg px-4 py-3 border ${isDark ? 'bg-white/3 border-white/8' : 'bg-white border-slate-200'}`}>
                    <div className="flex-1">
                      <div className={`text-sm font-medium ${th.heading}`}>{cfg?.label ?? p.key}</div>
                      <div className={`text-xs ${th.muted} mt-0.5`}>
                        <span className="font-mono">{String(p.oldValue)}</span>
                        <span className={`mx-2 ${th.faint}`}>→</span>
                        <span className="font-mono text-amber-500">{String(p.newValue)}</span>
                        <span className={`ml-3 ${th.faint}`}>by {p.submittedBy} at {p.submittedAt}</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 ml-4">
                      <button
                        onClick={() => handleApprove(p.key)}
                        className={`px-3 py-1.5 text-xs rounded-lg transition-colors ${th.btnGreen}`}
                      >
                        Approve
                      </button>
                      <button
                        onClick={() => handleReject(p.key)}
                        className={`px-3 py-1.5 text-xs rounded-lg transition-colors ${th.btnRed}`}
                      >
                        Reject
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* Layer 3 — editable */}
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-3">
            <span className="text-xs font-semibold text-amber-500 uppercase tracking-widest">Layer 3</span>
            <span className={`text-xs ${th.faint}`}>Business Rules / Thresholds — Admin UI controlled</span>
          </div>
          <div className="space-y-3">
            {LAYER3_CONFIG.map(c => {
              const isPending = pendingChanges.some(p => p.key === c.key)
              return (
                <div key={c.key} className={`border rounded-xl px-5 py-4 ${th.card}`}>
                  <div className="flex items-center justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <span className={`text-sm font-medium ${th.heading}`}>{c.label}</span>
                        {c.warn && <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-500 uppercase tracking-wide">Protected</span>}
                        {isPending && (
                          <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-400/15 text-amber-400 border border-amber-400/30 uppercase tracking-wide">
                            Pending Approval
                          </span>
                        )}
                      </div>
                      <div className={`text-[11px] ${th.faint}`}>{c.desc}</div>
                    </div>
                    <div className="flex items-center gap-3 ml-6">
                      {c.editable ? (
                        <>
                          <input
                            type="text"
                            value={draftValues[c.key]}
                            onChange={e => setDraftValues(v => ({ ...v, [c.key]: e.target.value }))}
                            className={`w-28 border rounded-lg px-3 py-1.5 text-sm text-right font-mono focus:outline-none ${th.input}`}
                          />
                          {c.unit && <span className={`text-xs ${th.faint} w-12`}>{c.unit}</span>}
                          <button
                            onClick={() => handleSubmit(c.key)}
                            className={`px-3 py-1.5 text-xs rounded-lg transition-colors ${th.btn}`}
                          >
                            Submit
                          </button>
                        </>
                      ) : (
                        <span className="font-mono text-sm text-amber-500 bg-amber-500/10 px-3 py-1.5 rounded-lg">{c.value}</span>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* Layer 2 — read only deployment topology */}
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-3">
            <span className="text-xs font-semibold text-sky-400 uppercase tracking-widest">Layer 2</span>
            <span className={`text-xs ${th.faint}`}>Deployment Topology — Helm values, requires ArgoCD sync</span>
          </div>
          <div className="space-y-2">
            {LAYER2_CONFIG.map(c => (
              <div key={c.key} className={`border rounded-xl px-5 py-3 flex items-center justify-between ${th.cardFaint}`}>
                <div>
                  <span className={`text-sm ${th.body}`}>{c.label}</span>
                  <div className={`text-[10px] ${th.faint} mt-0.5`}>
                    Read-only · Change via PR to infra/helm/values/banks/svcb/ → ArgoCD sync
                  </div>
                </div>
                <span className={`font-mono text-xs px-3 py-1 rounded-lg ${th.l2val}`}>{c.value}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Layer 1 — read only */}
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-3">
            <span className={`text-xs font-semibold ${th.l1label} uppercase tracking-widest`}>Layer 1</span>
            <span className={`text-xs ${th.faint}`}>Platform Constraints — non-overridable, set by ASTRA vendor</span>
          </div>
          <div className="space-y-2">
            {LAYER1_CONFIG.map(c => (
              <div key={c.key} className={`border rounded-xl px-5 py-3 flex items-center justify-between ${th.cardFaint}`}>
                <div>
                  <span className={`text-sm ${th.body}`}>{c.label}</span>
                  <div className={`text-[10px] ${th.faint} mt-0.5`}>{c.desc}</div>
                </div>
                <span className={`font-mono text-xs px-3 py-1 rounded-lg ${th.l1val}`}>{c.value}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Return Reason Management */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <span className={`text-xs font-semibold ${th.muted} uppercase tracking-widest`}>Return Reasons</span>
              <span className={`text-xs ${th.faint}`}>Shown to ops reviewers in the human review queue</span>
            </div>
            <button
              type="button"
              onClick={resetReasons}
              className={`text-[10px] px-3 py-1.5 rounded-lg border transition-colors ${isDark ? 'border-white/10 text-slate-400 hover:text-slate-200 hover:border-white/20' : 'border-slate-200 text-slate-500 hover:text-slate-700 hover:border-slate-300'}`}
            >
              Reset to defaults
            </button>
          </div>

          {/* Add new reason */}
          <div className={`flex items-center gap-2 mb-4 p-3 rounded-xl border ${th.card}`}>
            <select
              value={newReasonGroup}
              onChange={e => setNewReasonGroup(e.target.value)}
              className={`text-xs px-3 py-2 rounded-lg border shrink-0 ${isDark ? 'bg-white/5 border-white/10 text-slate-200' : 'bg-white border-slate-200 text-slate-700'}`}
            >
              {reasonGroups.map(g => <option key={g} value={g}>{g}</option>)}
            </select>
            <input
              type="text"
              value={newReasonText}
              onChange={e => setNewReasonText(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && addReason()}
              placeholder="Enter new return reason…"
              className={`flex-1 text-xs px-3 py-2 rounded-lg border outline-none ${isDark ? 'bg-white/5 border-white/10 text-slate-200 placeholder:text-slate-600' : 'bg-white border-slate-200 text-slate-700 placeholder:text-slate-400'}`}
            />
            <button
              type="button"
              onClick={addReason}
              disabled={!newReasonText.trim()}
              className="text-xs px-4 py-2 rounded-lg bg-emerald-600 text-white font-medium disabled:opacity-40 disabled:cursor-not-allowed hover:bg-emerald-500 transition-colors"
            >
              Add
            </button>
          </div>

          {/* Grouped reason lists */}
          <div className="grid grid-cols-2 gap-4">
            {Object.entries(returnReasons).sort(([a], [b]) => a.localeCompare(b)).map(([group, reasons]) => (
              <div key={group} className={`rounded-xl border ${th.card} overflow-hidden`}>
                <div className={`px-4 py-2.5 border-b ${th.divider} flex items-center justify-between`}>
                  <span className={`text-[10px] font-semibold uppercase tracking-widest ${th.muted}`}>{group}</span>
                  <span className={`text-[10px] ${th.faint}`}>{reasons.length} reasons</span>
                </div>
                <div className="divide-y" style={{ borderColor: isDark ? 'rgba(255,255,255,0.05)' : '#f1f5f9' }}>
                  {[...reasons].sort((a, b) => a.localeCompare(b)).map(reason => (
                    <div key={reason} className={`flex items-center justify-between px-4 py-2 group ${isDark ? 'hover:bg-white/3' : 'hover:bg-slate-50'}`}>
                      <span className={`text-xs ${th.body}`}>{reason}</span>
                      <button
                        type="button"
                        onClick={() => removeReason(group, reason)}
                        className={`text-[10px] opacity-0 group-hover:opacity-100 transition-opacity px-2 py-0.5 rounded border ${isDark ? 'border-red-700/50 text-red-400 hover:bg-red-900/20' : 'border-red-200 text-red-500 hover:bg-red-50'}`}
                      >
                        Remove
                      </button>
                    </div>
                  ))}
                  {reasons.length === 0 && (
                    <div className={`px-4 py-4 text-xs text-center ${th.faint}`}>No reasons — add one above</div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Recent Changes audit log */}
        <div>
          <div className="flex items-center gap-2 mb-3">
            <span className={`text-xs font-semibold ${th.muted} uppercase tracking-widest`}>Recent Changes</span>
            <span className={`text-xs ${th.faint}`}>Immudb-backed audit trail · HSM signed</span>
          </div>
          <div className={`border rounded-xl overflow-hidden ${th.card}`}>
            <table className="w-full text-xs">
              <thead>
                <tr className={th.tblHead}>
                  <th className="text-left px-4 py-2.5 font-medium">Config Key</th>
                  <th className="text-right px-4 py-2.5 font-medium">Old Value</th>
                  <th className="text-right px-4 py-2.5 font-medium">New Value</th>
                  <th className="text-left px-4 py-2.5 font-medium">Submitted By</th>
                  <th className="text-left px-4 py-2.5 font-medium">Approved By</th>
                  <th className="text-left px-4 py-2.5 font-medium">Timestamp</th>
                  <th className="text-center px-4 py-2.5 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {changeLog.map((entry, i) => (
                  <tr key={i} className={`border-t ${th.tblRow}`}>
                    <td className={`px-4 py-2.5 font-mono ${th.body}`}>{entry.key}</td>
                    <td className={`px-4 py-2.5 text-right font-mono ${th.muted}`}>{String(entry.old)}</td>
                    <td className="px-4 py-2.5 text-right font-mono text-emerald-500">{String(entry.new)}</td>
                    <td className={`px-4 py-2.5 ${th.muted}`}>{entry.by}</td>
                    <td className={`px-4 py-2.5 ${th.muted}`}>{entry.approvedBy}</td>
                    <td className={`px-4 py-2.5 ${th.faint}`}>{entry.at}</td>
                    <td className="px-4 py-2.5 text-center">
                      <span className="text-[9px] px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-500 border border-emerald-500/20 uppercase tracking-wide">
                        {entry.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

      </div>
    </AppShell>
  )
}

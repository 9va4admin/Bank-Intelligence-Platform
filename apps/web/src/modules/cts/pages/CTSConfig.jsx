import { useState } from 'react'
import { useTheme } from '../../../shared/theme/ThemeContext'
import AppShell from '../../../shared/layout/AppShell'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'

const LAYER3_CONFIG = [
  { key: 'iet_minutes',                  label: 'IET Window',                value: 180,      unit: 'minutes', desc: 'RBI mandated clearing window. Breach = deemed approval.',       editable: true,  warn: true  },
  { key: 'stp_auto_confirm_threshold',   label: 'STP Auto-Confirm Threshold',value: 0.92,     unit: 'score',   desc: 'Fraud score below this → automatic NGCH confirm filing.',      editable: true,  warn: false },
  { key: 'human_review_fraud_threshold', label: 'Human Review Threshold',    value: 0.72,     unit: 'score',   desc: 'Fraud score above this → routed to ops reviewer queue.',        editable: true,  warn: false },
  { key: 'high_value_amount_threshold',  label: 'High-Value Limit',          value: 500000,   unit: '₹',       desc: 'Cheques above this amount require dual ops_reviewer approval.', editable: true,  warn: false },
  { key: 'vault_miss_action',            label: 'Vault Miss Action',         value: 'HUMAN_REVIEW', unit: '', desc: 'Action on signature/PPS vault miss. Cannot be changed to AUTO_RETURN.', editable: false, warn: true },
]

const LAYER1_CONFIG = [
  { key: 'min_tls_version',      label: 'Min TLS Version',   value: '1.3',  desc: 'Non-overridable. Enforced by Istio service mesh.' },
  { key: 'audit_trail_enabled',  label: 'Audit Trail',       value: 'true', desc: 'Cannot be disabled. Cryptographic Immudb writes on every decision.' },
  { key: 'exactly_once_ngch',    label: 'Exactly-Once NGCH', value: 'true', desc: 'Temporal idempotency. Duplicate filings are impossible by design.' },
  { key: 'iet_watchdog_enabled', label: 'IET Watchdog',      value: 'true', desc: 'Emergency filing at T-30s. Non-overridable.' },
  { key: 'hsm_required',         label: 'HSM Signing',       value: 'true', desc: 'All audit events signed with FIPS 140-2 Level 3 HSM.' },
]

export default function CTSConfig() {
  const [values, setValues] = useState(
    Object.fromEntries(LAYER3_CONFIG.map(c => [c.key, c.value]))
  )
  const [saved, setSaved] = useState(null)
  const { isDark } = useTheme()

  function handleSave(key) {
    setSaved(key)
    setTimeout(() => setSaved(null), 2000)
  }

  const th = {
    page:      'bg-slate-50 dark:bg-transparent',
    card:      'bg-white border-slate-200 dark:bg-white/4 dark:border-white/8',
    cardFaint: 'bg-slate-50 border-slate-100 dark:bg-navy-900/40 dark:border-white/5',
    heading:   'text-slate-900 dark:text-white',
    body:      'text-slate-700 dark:text-slate-400',
    faint:     'text-slate-400 dark:text-slate-600',
    meta:      'bg-slate-100 text-slate-500 dark:bg-white/4 dark:text-slate-500',
    input:     isDark
                 ? 'bg-white/5 border-white/10 text-white focus:border-amber-400/50'
                 : 'bg-slate-50 border-slate-300 text-slate-900 focus:border-amber-500',
    btn:       isDark
                 ? 'bg-gold-400/10 text-gold-400 hover:bg-gold-400/20'
                 : 'bg-amber-100 text-amber-700 hover:bg-amber-200',
    l1label:   'text-slate-400 dark:text-slate-500',
    l1val:     'bg-slate-100 text-slate-500 dark:bg-white/4 dark:text-slate-500',
  }

  usePageHeader({
    subtitle: 'Layer 3 business rules · Layer 1 platform constraints',
    actions: (
      <div className={`text-[10px] ${th.meta} px-3 py-1.5 rounded-lg`}>
        Maker-Checker required · Changes hot-reload in &lt;30s
      </div>
    ),
  })

  return (
    <AppShell>
      <div className={`${th.page} px-6 py-5`}>

        {/* Layer 3 — editable */}
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-3">
            <span className="text-xs font-semibold text-amber-500 uppercase tracking-widest">Layer 3</span>
            <span className={`text-xs ${th.faint}`}>Business Rules / Thresholds — Admin UI controlled</span>
          </div>
          <div className="space-y-3">
            {LAYER3_CONFIG.map(c => (
              <div key={c.key} className={`border rounded-xl px-5 py-4 ${th.card}`}>
                <div className="flex items-center justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`text-sm font-medium ${th.heading}`}>{c.label}</span>
                      {c.warn && <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-500 uppercase tracking-wide">Protected</span>}
                    </div>
                    <div className={`text-[11px] ${th.faint}`}>{c.desc}</div>
                  </div>
                  <div className="flex items-center gap-3 ml-6">
                    {c.editable ? (
                      <>
                        <input
                          type="text"
                          value={values[c.key]}
                          onChange={e => setValues(v => ({ ...v, [c.key]: e.target.value }))}
                          className={`w-28 border rounded-lg px-3 py-1.5 text-sm text-right font-mono focus:outline-none ${th.input}`}
                        />
                        {c.unit && <span className={`text-xs ${th.faint} w-12`}>{c.unit}</span>}
                        <button
                          onClick={() => handleSave(c.key)}
                          className={`px-3 py-1.5 text-xs rounded-lg transition-colors ${th.btn}`}
                        >
                          {saved === c.key ? '✓ Saved' : 'Submit'}
                        </button>
                      </>
                    ) : (
                      <span className="font-mono text-sm text-amber-500 bg-amber-500/10 px-3 py-1.5 rounded-lg">{c.value}</span>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Layer 1 — read only */}
        <div>
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
      </div>
    </AppShell>
  )
}

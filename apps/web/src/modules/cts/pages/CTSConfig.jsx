import { useState } from 'react'
import AppShell from '../../../shared/layout/AppShell'

const LAYER3_CONFIG = [
  { key: 'iet_minutes',                    label: 'IET Window',                value: 180,  unit: 'minutes',  desc: 'RBI mandated clearing window. Breach = deemed approval.',        editable: true,  warn: true  },
  { key: 'stp_auto_confirm_threshold',     label: 'STP Auto-Confirm Threshold',value: 0.92, unit: 'score',   desc: 'Fraud score below this → automatic NGCH confirm filing.',       editable: true,  warn: false },
  { key: 'human_review_fraud_threshold',   label: 'Human Review Threshold',    value: 0.72, unit: 'score',   desc: 'Fraud score above this → routed to ops reviewer queue.',         editable: true,  warn: false },
  { key: 'high_value_amount_threshold',    label: 'High-Value Limit',          value: 500000, unit: '₹',    desc: 'Cheques above this amount require dual ops_reviewer approval.',  editable: true,  warn: false },
  { key: 'vault_miss_action',              label: 'Vault Miss Action',         value: 'HUMAN_REVIEW', unit: '', desc: 'Action on signature/PPS vault miss. Cannot be changed to AUTO_RETURN.', editable: false, warn: true },
]

const LAYER1_CONFIG = [
  { key: 'min_tls_version',        label: 'Min TLS Version',        value: '1.3',  desc: 'Non-overridable. Enforced by Istio service mesh.' },
  { key: 'audit_trail_enabled',    label: 'Audit Trail',            value: 'true', desc: 'Cannot be disabled. Cryptographic Immudb writes on every decision.' },
  { key: 'exactly_once_ngch',      label: 'Exactly-Once NGCH',      value: 'true', desc: 'Temporal idempotency. Duplicate filings are impossible by design.' },
  { key: 'iet_watchdog_enabled',   label: 'IET Watchdog',           value: 'true', desc: 'Emergency filing at T-30s. Non-overridable.' },
  { key: 'hsm_required',           label: 'HSM Signing',            value: 'true', desc: 'All audit events signed with FIPS 140-2 Level 3 HSM.' },
]

export default function CTSConfig() {
  const [values, setValues] = useState(
    Object.fromEntries(LAYER3_CONFIG.map(c => [c.key, c.value]))
  )
  const [saved, setSaved] = useState(null)

  function handleSave(key) {
    setSaved(key)
    setTimeout(() => setSaved(null), 2000)
  }

  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto bg-navy-950 px-6 py-5">
        <div className="flex items-center justify-between mb-5">
          <h1 className="text-lg font-semibold text-white">Config</h1>
          <div className="text-[10px] text-slate-600 bg-white/4 px-3 py-1.5 rounded-lg">
            Maker-Checker required · Changes hot-reload in &lt;30s
          </div>
        </div>

        {/* Layer 3 — editable */}
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-3">
            <span className="text-xs font-semibold text-gold-400 uppercase tracking-widest">Layer 3</span>
            <span className="text-xs text-slate-600">Business Rules / Thresholds — Admin UI controlled</span>
          </div>
          <div className="space-y-3">
            {LAYER3_CONFIG.map(c => (
              <div key={c.key} className="bg-navy-900 border border-white/8 rounded-xl px-5 py-4">
                <div className="flex items-center justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-sm font-medium text-white">{c.label}</span>
                      {c.warn && <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-400/10 text-amber-400 uppercase tracking-wide">Protected</span>}
                    </div>
                    <div className="text-[11px] text-slate-600">{c.desc}</div>
                  </div>
                  <div className="flex items-center gap-3 ml-6">
                    {c.editable ? (
                      <>
                        <input
                          type="text"
                          value={values[c.key]}
                          onChange={e => setValues(v => ({ ...v, [c.key]: e.target.value }))}
                          className="w-28 bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-sm text-white text-right font-mono focus:outline-none focus:border-gold-400/50"
                        />
                        {c.unit && <span className="text-xs text-slate-600 w-12">{c.unit}</span>}
                        <button
                          onClick={() => handleSave(c.key)}
                          className="px-3 py-1.5 bg-gold-400/10 text-gold-400 text-xs rounded-lg hover:bg-gold-400/20 transition-colors"
                        >
                          {saved === c.key ? '✓ Saved' : 'Submit'}
                        </button>
                      </>
                    ) : (
                      <span className="font-mono text-sm text-amber-400 bg-amber-400/10 px-3 py-1.5 rounded-lg">{c.value}</span>
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
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-widest">Layer 1</span>
            <span className="text-xs text-slate-600">Platform Constraints — non-overridable, set by ASTRA vendor</span>
          </div>
          <div className="space-y-2">
            {LAYER1_CONFIG.map(c => (
              <div key={c.key} className="bg-navy-900/40 border border-white/5 rounded-xl px-5 py-3 flex items-center justify-between">
                <div>
                  <span className="text-sm text-slate-400">{c.label}</span>
                  <div className="text-[10px] text-slate-600 mt-0.5">{c.desc}</div>
                </div>
                <span className="font-mono text-xs text-slate-500 bg-white/4 px-3 py-1 rounded-lg">{c.value}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </AppShell>
  )
}

const ACTIVITIES = [
  { step: '01', name: 'Image Validation', detail: 'CTS 2010 standard check', model: 'Rule-based' },
  { step: '02', name: 'MICR OCR', detail: 'Bank code, account, serial', model: 'GOT-OCR2.0' },
  { step: '03', name: 'Alteration Detection', detail: 'Tampering, overwriting, corrections', model: 'Qwen2-VL 72B' },
  { step: '04', name: 'Signature Verification', detail: 'Siamese network vs CBS specimens', model: 'PyTorch SNN' },
  { step: '05', name: 'Positive Pay Check', detail: 'Amount + payee vs bank instruction', model: 'Redis Vault' },
  { step: '06', name: 'CBS Balance Check', detail: 'Live balance via CBS connector', model: 'CBS API' },
  { step: '07', name: 'Fraud Scoring', detail: 'XGBoost ensemble + SHAP rationale', model: 'XGBoost' },
  { step: '08', name: 'Decision + NGCH Filing', detail: 'Confirm / Return / Human Review', model: 'Temporal' },
]

const INVARIANTS = [
  { label: '0.000%', desc: 'IET breach rate — enforced by watchdog at T-30s' },
  { label: '<600ms', desc: 'End-to-end wall clock (p99), 500 cheques in parallel' },
  { label: 'Zero', desc: 'Duplicate NGCH filings — Temporal exactly-once' },
  { label: 'Always', desc: 'SHAP rationale before any auto-decision' },
]

export default function CTSModule() {
  return (
    <section id="cts" className="py-24 px-6 relative overflow-hidden">
      {/* Background accent */}
      <div className="absolute right-0 top-1/2 -translate-y-1/2 w-[500px] h-[500px] rounded-full bg-blue-600/6 blur-3xl pointer-events-none" />

      <div className="max-w-7xl mx-auto relative">
        <div className="grid lg:grid-cols-2 gap-12 items-start">

          {/* Left: copy */}
          <div>
            <div className="inline-flex items-center gap-2 glass-gold rounded-full px-4 py-1.5 mb-6">
              <span className="w-1.5 h-1.5 rounded-full bg-gold-400" />
              <span className="text-xs font-semibold text-gold-400 uppercase tracking-wide">Module 1 — CTS</span>
            </div>

            <h2 className="text-3xl sm:text-4xl font-bold text-white mb-5 leading-tight">
              One AI Agent Per Cheque.
              <br />
              <span className="text-gradient-blue">500 Cheques = 500 Parallel Agents.</span>
            </h2>

            <p className="text-slate-400 leading-relaxed mb-8">
              ASTRA spins up one Temporal workflow per inward cheque. Each agent runs all 8 processing
              steps — OCR, alteration detection, signature verification, fraud scoring — in under 600ms
              wall clock. The IET watchdog fires at T-30 seconds regardless. No IET breach. Ever.
            </p>

            {/* Invariant stats */}
            <div className="grid grid-cols-2 gap-4 mb-8">
              {INVARIANTS.map(({ label, desc }) => (
                <div key={label} className="glass rounded-xl p-4">
                  <div className="text-xl font-bold text-gradient-blue mb-1">{label}</div>
                  <div className="text-xs text-slate-500 leading-tight">{desc}</div>
                </div>
              ))}
            </div>

            {/* Who buys */}
            <div className="glass rounded-xl p-5">
              <div className="text-xs text-slate-500 uppercase tracking-wide mb-3">Target Buyers</div>
              <div className="flex flex-wrap gap-2">
                {['Urban Co-op Banks', 'Regional Rural Banks', 'Mid-tier Private Banks', 'Small Finance Banks'].map(b => (
                  <span key={b} className="text-xs bg-white/5 border border-white/8 text-slate-300 px-3 py-1.5 rounded-full">
                    {b}
                  </span>
                ))}
              </div>
            </div>
          </div>

          {/* Right: pipeline visual */}
          <div className="space-y-2">
            <div className="text-xs text-slate-500 uppercase tracking-wide mb-4">Processing Pipeline — per cheque</div>
            {ACTIVITIES.map(({ step, name, detail, model }, i) => (
              <div
                key={step}
                className="flex items-center gap-4 glass rounded-xl px-4 py-3 group hover:border-blue-500/30 transition-colors duration-200"
              >
                <div className="w-8 h-8 rounded-lg bg-white/5 flex items-center justify-center flex-shrink-0">
                  <span className="text-xs font-mono text-slate-500">{step}</span>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-white">{name}</div>
                  <div className="text-xs text-slate-500 truncate">{detail}</div>
                </div>
                <div className="text-xs font-mono text-blue-400/70 bg-blue-400/8 px-2 py-1 rounded-md whitespace-nowrap flex-shrink-0">
                  {model}
                </div>
              </div>
            ))}

            {/* Terminal state */}
            <div className="flex gap-2 mt-4">
              {[
                { label: 'STP Confirm', color: 'text-green-400 bg-green-400/10 border-green-500/20' },
                { label: 'STP Return', color: 'text-red-400 bg-red-400/10 border-red-500/20' },
                { label: 'Human Review', color: 'text-amber-400 bg-amber-400/10 border-amber-500/20' },
              ].map(({ label, color }) => (
                <div key={label} className={`flex-1 text-center text-xs font-medium py-2 rounded-lg border ${color}`}>
                  {label}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

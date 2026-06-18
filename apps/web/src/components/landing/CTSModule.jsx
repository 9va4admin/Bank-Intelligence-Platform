const PIPELINE = [
  { step: '01', name: 'Image + MICR OCR', model: 'GOT-OCR2.0', detail: 'MICR line, amount in figures and words, date' },
  { step: '02', name: 'Alteration Detection', model: 'Qwen2-VL 72B', detail: 'Overwriting, erasure, correction fluid detection' },
  { step: '03', name: 'Signature Verification', model: 'Siamese Network', detail: 'vs CBS stored specimen, Vault lookup < 5ms' },
  { step: '04', name: 'Positive Pay Check', model: 'PPS Vault', detail: 'Issuer-submitted cheque details match' },
  { step: '05', name: 'Fraud Scoring', model: 'XGBoost + SHAP', detail: 'Score + human-readable rationale, no black box' },
  { step: '06', name: 'Decision + NGCH Filing', model: 'Temporal Agent', detail: 'STP confirm / STP return / human review queue' },
]

export default function CTSModule() {
  return (
    <section id="cts" className="bg-white py-20 px-6">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="flex flex-col lg:flex-row gap-12 mb-14">
          <div className="lg:w-1/2">
            <span className="inline-block text-xs font-semibold text-teal-600 tracking-widest uppercase mb-3">Module 1 — CTS</span>
            <h2 className="text-3xl sm:text-4xl font-bold text-slate-900 mb-4">
              One AI Agent.<br />One Cheque.<br />
              <span className="text-teal-500">Under 600 Milliseconds.</span>
            </h2>
            <p className="text-slate-500 leading-relaxed mb-4">
              500 inward cheques arrive. ASTRA spawns 500 parallel agents — one per cheque. Every agent runs a complete 6-step pipeline: OCR, alteration detection, signature verification, positive pay, fraud scoring, NGCH filing. All 500 complete in under 600ms wall clock.
            </p>
            <p className="text-slate-500 leading-relaxed">
              The IET watchdog runs as a separate child workflow. At T-30 seconds, it files an emergency return directly to NGCH. IET breach rate: <strong className="text-slate-800">0.000%</strong>. Not a target. A structural guarantee.
            </p>
          </div>

          {/* What If panel */}
          <div className="lg:w-1/2">
            <div className="bg-forest-900 rounded-2xl p-7 text-white h-full">
              <div className="flex items-center gap-2 mb-4">
                <span className="text-lg">💡</span>
                <span className="text-xs font-semibold text-teal-400 tracking-widest uppercase">What If — The Mandate Tightens</span>
              </div>
              <p className="text-slate-300 text-sm mb-5 leading-relaxed">
                Today: T+3 hours (180 min). RBI has already signalled T+30 min next. Possibly T+5 min (real-time clearing) later.
              </p>
              <div className="space-y-3 mb-5">
                {[
                  { label: 'T+3 hrs (today)', value: 'item_expiry_minutes = 180', active: false },
                  { label: 'T+30 min (next phase)', value: 'item_expiry_minutes = 30', active: true },
                  { label: 'T+5 min (real-time)', value: 'item_expiry_minutes = 5', active: false },
                ].map(({ label, value, active }) => (
                  <div key={label} className={`flex items-center justify-between rounded-lg px-4 py-3 ${active ? 'bg-teal-400/15 border border-teal-400/30' : 'bg-white/4'}`}>
                    <span className={`text-xs ${active ? 'text-teal-300' : 'text-slate-400'}`}>{label}</span>
                    <code className={`text-xs font-mono ${active ? 'text-teal-200' : 'text-slate-500'}`}>{value}</code>
                  </div>
                ))}
              </div>
              <div className="border-t border-white/10 pt-4">
                <p className="text-sm text-white font-medium mb-1">For ASTRA: Admin UI config change. Done in 30 seconds.</p>
                <p className="text-sm text-slate-400">For competitors: 18–24 month architectural rebuild. That gap is the opportunity.</p>
              </div>
            </div>
          </div>
        </div>

        {/* Pipeline */}
        <div className="bg-slate-50 rounded-2xl border border-slate-200 p-7">
          <h3 className="text-sm font-semibold text-slate-500 uppercase tracking-widest mb-6">6-Step Agent Pipeline · Exactly Once · IET-Safe</h3>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {PIPELINE.map(({ step, name, model, detail }) => (
              <div key={step} className="bg-white rounded-xl border border-slate-200 p-4 flex items-start gap-3">
                <span className="text-xs font-mono text-teal-500 font-bold pt-0.5">{step}</span>
                <div>
                  <div className="font-medium text-slate-900 text-sm">{name}</div>
                  <div className="text-xs text-teal-600 mb-1">{model}</div>
                  <div className="text-xs text-slate-400">{detail}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Key guarantees */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-5">
          {[
            { val: '0.000%', label: 'IET Breach Rate', color: 'text-teal-500' },
            { val: '<600ms', label: 'Any Batch Size (p99)', color: 'text-sky-500' },
            { val: '500+', label: 'Parallel Agents', color: 'text-violet-500' },
            { val: '100%', label: 'On-Premises, No Cloud', color: 'text-slate-700' },
          ].map(({ val, label, color }) => (
            <div key={label} className="text-center rounded-xl bg-slate-50 border border-slate-200 py-5">
              <div className={`text-2xl font-bold mb-1 ${color}`}>{val}</div>
              <div className="text-xs text-slate-400">{label}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

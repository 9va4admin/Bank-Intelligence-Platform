const OEMS = ['NCR', 'Diebold', 'Wincor', 'Hyosung', 'AGS / GRG']

const WORKFLOW = [
  { step: '01', name: 'OEM Fingerprint', where: 'Edge (Go)', detail: 'Detects format automatically — no manual config per OEM' },
  { step: '02', name: 'Compress + Encrypt', where: 'Edge (Go)', detail: 'gzip ~70% reduction, AES-256, buffered if offline' },
  { step: '03', name: 'LLM Parse → Canonical', where: 'Central', detail: 'Llama 3.3 70B extracts every field across all OEM formats' },
  { step: '04', name: 'Dispute Match', where: 'Central', detail: 'BGE-M3 embeddings match NPCI claim to EJ record in < 1s' },
  { step: '05', name: 'CCTV Evidence', where: 'Central', detail: 'Auto-fetch clip at dispense timestamp, frame-level analysis' },
  { step: '06', name: 'Resolve + Notify', where: 'NPCI / Bank', detail: 'Credit customer within 15 minutes, close NPCI claim' },
]

export default function EJModule() {
  return (
    <section id="ej" className="bg-cream-100 py-20 px-6">
      <div className="max-w-6xl mx-auto">
        <div className="flex flex-col lg:flex-row gap-12 mb-14">
          <div className="lg:w-1/2">
            <span className="inline-block text-xs font-semibold text-sky-600 tracking-widest uppercase mb-3">Module 2 — ATM EJ Intelligence</span>
            <h2 className="text-3xl sm:text-4xl font-bold text-slate-900 mb-4">
              Disputes Resolved in<br />
              <span style={{ color: '#378ADD' }}>48 Hours, Not 45 Days.</span>
            </h2>
            <p className="text-slate-500 leading-relaxed mb-4">
              The EJ (Electronic Journal) is every ATM's transaction diary. No two OEMs write it the same way. ASTRA uses an LLM to read all of them — permanently. One model upgrade covers every format change across every OEM automatically.
            </p>
            <p className="text-slate-500 leading-relaxed">
              When a customer disputes a failed dispense at 10:00 AM, ASTRA matches the NPCI claim to the EJ record, pulls the CCTV timestamp, and credits the customer — all before 10:15 AM. NPCI only sees exceptions.
            </p>
          </div>

          {/* What If panel */}
          <div className="lg:w-1/2">
            <div className="bg-sky-600 rounded-2xl p-7 text-white h-full">
              <div className="flex items-center gap-2 mb-4">
                <span className="text-lg">💡</span>
                <span className="text-xs font-semibold text-sky-200 tracking-widest uppercase">What If — Disputes Resolved Themselves</span>
              </div>

              {/* Before/After */}
              <div className="space-y-3 mb-5">
                <div className="bg-white/10 rounded-xl p-4">
                  <div className="text-xs text-sky-200 font-semibold mb-2 uppercase tracking-wide">Before ASTRA</div>
                  <div className="space-y-1.5 text-sm text-white/80">
                    {['Customer files dispute with bank', 'Bank ops requests EJ from ATM OEM (3–5 days)', 'Manual cross-reference with cash tally (5–7 days)', 'CCTV request from branch DVR (7–10 days)', 'File with NPCI, await response (10–20 days)', 'Credit customer — 45 working days later'].map((t, i) => (
                      <div key={i} className="flex items-start gap-2">
                        <span className="text-sky-300 text-xs mt-0.5">→</span>
                        <span>{t}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="bg-white/15 rounded-xl p-4 border border-white/20">
                  <div className="text-xs text-white font-semibold mb-2 uppercase tracking-wide">After ASTRA</div>
                  <div className="space-y-1.5 text-sm text-white">
                    {['10:00 AM — Customer files dispute', '10:02 AM — ASTRA matches EJ record automatically', '10:08 AM — CCTV confirms no dispense', '10:14 AM — Customer credited, NPCI notified', '10:15 AM — Case closed'].map((t, i) => (
                      <div key={i} className="flex items-start gap-2">
                        <span className="text-white text-xs mt-0.5">✓</span>
                        <span>{t}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className="text-center text-white">
                <span className="text-2xl font-bold">45 days</span>
                <span className="text-sky-300 mx-3">→</span>
                <span className="text-2xl font-bold">15 minutes</span>
              </div>
            </div>
          </div>
        </div>

        {/* OEM support */}
        <div className="bg-white rounded-2xl border border-slate-200 p-7 mb-5">
          <div className="flex flex-wrap items-center justify-between gap-4 mb-6">
            <div>
              <h3 className="font-semibold text-slate-900">All OEMs. One Model. Zero Custom Parsers.</h3>
              <p className="text-sm text-slate-400 mt-1">LLM-based parsing works across all formats — OEM firmware updates no longer break your system.</p>
            </div>
            <div className="flex flex-wrap gap-2">
              {OEMS.map(oem => (
                <span key={oem} className="text-xs font-medium bg-sky-50 text-sky-700 border border-sky-200 px-3 py-1.5 rounded-full">{oem}</span>
              ))}
              <span className="text-xs font-medium bg-slate-100 text-slate-500 border border-slate-200 px-3 py-1.5 rounded-full">+ any new OEM</span>
            </div>
          </div>

          {/* Workflow */}
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {WORKFLOW.map(({ step, name, where, detail }) => (
              <div key={step} className="rounded-xl bg-slate-50 border border-slate-200 p-4 flex items-start gap-3">
                <span className="text-xs font-mono text-sky-500 font-bold pt-0.5">{step}</span>
                <div>
                  <div className="font-medium text-slate-900 text-sm">{name}</div>
                  <div className="text-xs text-sky-600 mb-1">{where}</div>
                  <div className="text-xs text-slate-400">{detail}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}

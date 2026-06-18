const OEMS = ['NCR', 'Diebold', 'Hyosung', 'Nautilus', 'GRG']

const CAPABILITIES = [
  {
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23-.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0112 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5" />
      </svg>
    ),
    title: 'Universal OEM Normalisation',
    desc: 'Llama 3.3 70B parses any EJ format into a canonical transaction schema. One pipeline for all ATM manufacturers.',
  },
  {
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 3v11.25A2.25 2.25 0 006 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0118 16.5h-2.25m-7.5 0h7.5m-7.5 0l-1 3m8.5-3l1 3m0 0l.5 1.5m-.5-1.5h-9.5m0 0l-.5 1.5M9 11.25v1.5M12 9v3.75m3-6v6" />
      </svg>
    ),
    title: 'NPCI Dispute Resolution',
    desc: 'Automatic EJ matching for ATM claims. BGE-M3 embeddings find the canonical record. CCTV evidence packaged automatically.',
  },
  {
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 7.125C2.25 6.504 2.754 6 3.375 6h6c.621 0 1.125.504 1.125 1.125v3.75c0 .621-.504 1.125-1.125 1.125h-6a1.125 1.125 0 01-1.125-1.125v-3.75zM14.25 8.625c0-.621.504-1.125 1.125-1.125h5.25c.621 0 1.125.504 1.125 1.125v8.25c0 .621-.504 1.125-1.125 1.125h-5.25a1.125 1.125 0 01-1.125-1.125v-8.25zM3.75 16.125c0-.621.504-1.125 1.125-1.125h5.25c.621 0 1.125.504 1.125 1.125v2.25c0 .621-.504 1.125-1.125 1.125h-5.25a1.125 1.125 0 01-1.125-1.125v-2.25z" />
      </svg>
    ),
    title: 'Fleet Observability',
    desc: 'Real-time ATM health signals from every EJ log. Predictive maintenance alerts before the machine fails.',
  },
  {
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M8.288 15.038a5.25 5.25 0 017.424 0M5.106 11.856c3.807-3.808 9.98-3.808 13.788 0M1.924 8.674c5.565-5.565 14.587-5.565 20.152 0M12.53 18.22l-.53.53-.53-.53a.75.75 0 011.06 0z" />
      </svg>
    ),
    title: 'Edge + Central Architecture',
    desc: 'Lightweight Go agent at branch compresses and encrypts. Full LLM normalisation at central DC. No GPU at the edge.',
  },
]

export default function EJModule() {
  return (
    <section id="ej" className="py-24 px-6 relative overflow-hidden">
      {/* Background */}
      <div className="absolute left-0 top-1/2 -translate-y-1/2 w-[500px] h-[500px] rounded-full bg-violet-600/6 blur-3xl pointer-events-none" />

      <div className="max-w-7xl mx-auto relative">
        <div className="grid lg:grid-cols-2 gap-12 items-start">

          {/* Left: capabilities */}
          <div className="order-2 lg:order-1 space-y-4">
            {CAPABILITIES.map(({ icon, title, desc }) => (
              <div key={title} className="flex gap-4 glass rounded-xl p-5 group hover:border-violet-500/30 transition-colors duration-200">
                <div className="w-10 h-10 rounded-lg bg-violet-500/10 text-violet-400 flex items-center justify-center flex-shrink-0">
                  {icon}
                </div>
                <div>
                  <div className="text-sm font-semibold text-white mb-1">{title}</div>
                  <div className="text-xs text-slate-400 leading-relaxed">{desc}</div>
                </div>
              </div>
            ))}

            {/* OEM badges */}
            <div className="glass rounded-xl p-5">
              <div className="text-xs text-slate-500 uppercase tracking-wide mb-3">Supported ATM OEMs</div>
              <div className="flex flex-wrap gap-2">
                {OEMS.map(oem => (
                  <span key={oem} className="text-xs font-mono bg-violet-500/10 border border-violet-500/20 text-violet-300 px-3 py-1.5 rounded-full">
                    {oem}
                  </span>
                ))}
                <span className="text-xs text-slate-500 px-3 py-1.5">+ custom via LLM</span>
              </div>
            </div>
          </div>

          {/* Right: copy */}
          <div className="order-1 lg:order-2">
            <div className="inline-flex items-center gap-2 rounded-full px-4 py-1.5 mb-6 bg-violet-500/10 border border-violet-500/20">
              <span className="w-1.5 h-1.5 rounded-full bg-violet-400" />
              <span className="text-xs font-semibold text-violet-400 uppercase tracking-wide">Module 2 — ATM EJ Intelligence</span>
            </div>

            <h2 className="text-3xl sm:text-4xl font-bold text-white mb-5 leading-tight">
              5 OEM Formats.
              <br />
              <span className="text-gradient" style={{ backgroundImage: 'linear-gradient(135deg, #a78bfa 0%, #ffffff 60%)' }}>
                One Canonical Schema.
              </span>
            </h2>

            <p className="text-slate-400 leading-relaxed mb-6">
              ATM Electronic Journal logs are the single source of truth for every dispute,
              every reconciliation, every fleet anomaly. But 2.5 lakh ATMs across 5+ OEMs
              produce completely different formats. Banks drown in manual normalisation.
            </p>

            <p className="text-slate-400 leading-relaxed mb-8">
              ASTRA\'s LLM parser eliminates the problem permanently — understanding any
              OEM format without custom rules or regex. Cross-sell to any bank already running CTS.
              Zero new deployment. One config flag.
            </p>

            {/* Cross-sell callout */}
            <div className="glass-gold rounded-xl p-5 border border-gold-400/15">
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 rounded-lg bg-gold-400/15 flex items-center justify-center flex-shrink-0 mt-0.5">
                  <svg className="w-4 h-4 text-gold-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                </div>
                <div>
                  <div className="text-sm font-semibold text-gold-400 mb-1">Zero-friction cross-sell</div>
                  <div className="text-xs text-slate-400 leading-relaxed">
                    Banks that deploy CTS activate EJ Intelligence with a single Helm config flag.
                    Same cluster. Same ops team. RBI compliance certified once, not twice.
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

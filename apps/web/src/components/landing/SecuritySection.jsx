const PILLARS = [
  {
    icon: (
      <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 21a9.004 9.004 0 008.716-6.747M12 21a9.004 9.004 0 01-8.716-6.747M12 21c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 017.843 4.582M12 3a8.997 8.997 0 00-7.843 4.582m15.686 0A11.953 11.953 0 0112 10.5c-2.998 0-5.74-1.1-7.843-2.918m15.686 0A8.959 8.959 0 0121 12c0 .778-.099 1.533-.284 2.253m0 0A17.919 17.919 0 0112 16.5c-3.162 0-6.133-.815-8.716-2.247m0 0A9.015 9.015 0 013 12c0-1.605.42-3.113 1.157-4.418" />
      </svg>
    ),
    title: '100% On-Premises',
    desc: 'Zero cloud dependencies. Every compute, every model inference, every byte of customer data stays inside the bank\'s data center. RBI data localisation enforced by architecture.',
  },
  {
    icon: (
      <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />
      </svg>
    ),
    title: 'Zero Vendor Access',
    desc: 'No ASTRA engineer has shell or kubectl access to any bank\'s production cluster. Ever. Banks control their own ArgoCD. GitOps pull model — we publish, they deploy.',
  },
  {
    icon: (
      <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
      </svg>
    ),
    title: 'FIPS 140-2 HSM',
    desc: 'Every NGCH submission signed by a hardware security module. No software-held private keys. Signatures are cryptographically bound to the instrument ID and bank IFSC.',
  },
  {
    icon: (
      <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
      </svg>
    ),
    title: 'Cryptographic Audit Trail',
    desc: 'Every decision, every config change, every role assignment written to Immudb — a Merkle-tree immutable ledger. Tampering is mathematically detectable. RBI examiners get time-scoped read-only access.',
  },
  {
    icon: (
      <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
      </svg>
    ),
    title: 'mTLS Zero Trust',
    desc: 'Istio service mesh enforces mutual TLS between every pod. No implicit trust inside the VPC. Every service authenticates with a certificate — no passwords between services.',
  },
  {
    icon: (
      <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
      </svg>
    ),
    title: 'Explainable AI — No Black Box',
    desc: 'Every fraud score has SHAP values computed and stored before filing. Ops reviewers see exactly which features drove the score. RBI requirement met by design, not retrofit.',
  },
]

export default function SecuritySection() {
  return (
    <section id="security" className="py-24 px-6 relative overflow-hidden">
      <div className="absolute inset-0 grid-pattern opacity-30" />
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] rounded-full bg-emerald-600/5 blur-3xl pointer-events-none" />

      <div className="max-w-7xl mx-auto relative">
        <div className="text-center mb-16">
          <div className="inline-flex items-center gap-2 glass rounded-full px-4 py-1.5 mb-4">
            <span className="text-xs font-medium text-slate-400 uppercase tracking-wide">Security</span>
          </div>
          <h2 className="text-3xl sm:text-4xl font-bold text-white mb-4">
            Banking-Grade Security.
            <br />
            <span className="text-gradient" style={{ backgroundImage: 'linear-gradient(135deg, #34d399 0%, #ffffff 60%)' }}>
              Non-Negotiable by Design.
            </span>
          </h2>
          <p className="text-slate-400 max-w-xl mx-auto">
            Every security principle is enforced by architecture — not by policy documents or hope.
            If it can be bypassed, it wasn\'t really a security control.
          </p>
        </div>

        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {PILLARS.map(({ icon, title, desc }) => (
            <div
              key={title}
              className="glass rounded-2xl p-6 group hover:border-emerald-500/20 hover:-translate-y-1 transition-all duration-300"
            >
              <div className="w-10 h-10 rounded-xl bg-emerald-500/10 text-emerald-400 flex items-center justify-center mb-5">
                {icon}
              </div>
              <h3 className="text-base font-semibold text-white mb-2">{title}</h3>
              <p className="text-sm text-slate-400 leading-relaxed">{desc}</p>
            </div>
          ))}
        </div>

        {/* RBI compliance bar */}
        <div className="mt-10 glass rounded-2xl p-6 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div>
            <div className="text-sm font-semibold text-white mb-1">RBI IT Framework Compliant</div>
            <div className="text-xs text-slate-400">Control mapping documented. Every control traceable to implementation. Ready for RBI IS Audit.</div>
          </div>
          <div className="flex gap-3 flex-shrink-0">
            {['RBI IT Framework', 'ISO 27001', 'NPCI Security'].map(badge => (
              <span key={badge} className="text-xs bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 px-3 py-1.5 rounded-full whitespace-nowrap">
                {badge}
              </span>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}

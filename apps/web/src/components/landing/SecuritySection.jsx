const PILLARS = [
  {
    icon: '🔒',
    title: '100% On-Premises',
    body: 'Zero cloud dependencies. Your data never leaves your data center. ASTRA staff have no access to any bank\'s production environment — ever.',
  },
  {
    icon: '🏦',
    title: 'RBI IT Framework',
    body: 'Certified once for RBI compliance across both modules. Full control mapping to RBI circular. Audit trail cryptographically signed via FIPS 140-2 HSM.',
  },
  {
    icon: '🔑',
    title: 'Zero Trust Architecture',
    body: 'Istio service mesh with mTLS between every pod. HashiCorp Vault for dynamic secrets — rotated every 24 hours. No static credentials anywhere.',
  },
  {
    icon: '📊',
    title: 'Explainable AI Only',
    body: 'Every AI decision includes SHAP values and a human-readable rationale. No black-box decisions. Every cheque confirm or return is fully auditable.',
  },
  {
    icon: '🛡',
    title: 'Active-Active Resilience',
    body: 'Two data centers serving live traffic simultaneously. RPO = 0, RTO < 30 seconds on DC failure. Separate air-gapped DC3 for backup only.',
  },
  {
    icon: '📝',
    title: 'Immutable Audit Trail',
    body: 'Every decision, config change, and access event written to Immudb — cryptographically append-only. RBI examiners get time-scoped read-only access.',
  },
]

export default function SecuritySection() {
  return (
    <section id="security" className="bg-white py-20 px-6">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-14">
          <span className="inline-block text-xs font-semibold text-slate-400 tracking-widest uppercase mb-3">Security & Compliance</span>
          <h2 className="text-3xl sm:text-4xl font-bold text-slate-900 mb-4">
            Built for RBI. Owned by the Bank.
          </h2>
          <p className="text-slate-500 max-w-2xl mx-auto text-sm leading-relaxed">
            Banking-grade security is not a feature. It is the foundation. ASTRA is designed for the most stringent regulatory environment in India.
          </p>
        </div>

        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {PILLARS.map(({ icon, title, body }) => (
            <div key={title} className="rounded-2xl border border-slate-200 bg-slate-50 p-6">
              <div className="text-2xl mb-3">{icon}</div>
              <h3 className="font-semibold text-slate-900 mb-2">{title}</h3>
              <p className="text-sm text-slate-500 leading-relaxed">{body}</p>
            </div>
          ))}
        </div>

        {/* Compliance strip */}
        <div className="mt-10 bg-forest-900 rounded-2xl p-7 text-white">
          <div className="grid sm:grid-cols-3 gap-6 text-center">
            {[
              { label: 'Encryption', value: 'AES-256 at rest · TLS 1.3 in transit · Column-level PII' },
              { label: 'HSM', value: 'FIPS 140-2 Level 3 · NGCH PKI signing · Key custody' },
              { label: 'Access', value: 'SAML 2.0 via bank IdP · 7-role RBAC · OPA policy engine' },
            ].map(({ label, value }) => (
              <div key={label}>
                <div className="text-teal-400 text-xs font-semibold tracking-widest uppercase mb-2">{label}</div>
                <div className="text-slate-300 text-sm">{value}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}

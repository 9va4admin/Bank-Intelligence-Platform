const LAYERS = [
  {
    num: '01',
    name: 'Platform Constraints',
    color: 'text-red-400',
    bg: 'bg-red-500/8 border-red-500/20',
    who: 'ASTRA Vendor only',
    how: 'New chart release',
    examples: 'TLS 1.3 minimum · Audit always on · HSM required · Data localisation enforced',
  },
  {
    num: '02',
    name: 'Deployment Topology',
    color: 'text-orange-400',
    bg: 'bg-orange-500/8 border-orange-500/20',
    who: 'Bank IT Admin + ASTRA',
    how: 'PR → ArgoCD sync',
    examples: 'CTS/EJ enabled · CBS connector type · DC count · GPU profile',
  },
  {
    num: '03',
    name: 'Business Rules / Thresholds',
    color: 'text-gold-400',
    bg: 'bg-gold-400/8 border-gold-400/20',
    who: 'Ops Manager (maker) + IT Admin (checker)',
    how: 'Admin UI · Hot-reload < 30s',
    examples: 'IET minutes · Fraud threshold · Auto-confirm score · High-value limit',
  },
  {
    num: '04',
    name: 'Policy Rules (OPA Rego)',
    color: 'text-blue-400',
    bg: 'bg-blue-500/8 border-blue-500/20',
    who: 'Compliance Officer (author) + IT Admin (approve)',
    how: 'Rego policy · OPA hot-reload',
    examples: 'Govt cheques → human review · Account frozen → return immediately',
  },
  {
    num: '05',
    name: 'Secrets (Dynamic)',
    color: 'text-slate-400',
    bg: 'bg-slate-500/8 border-slate-500/20',
    who: 'Vault operator (automated)',
    how: 'HashiCorp Vault · Rotated every 24h',
    examples: 'DB passwords · TLS certs · CBS API keys · WhatsApp key',
  },
]

export default function Architecture() {
  return (
    <section id="architecture" className="py-24 px-6">
      <div className="max-w-7xl mx-auto">
        <div className="text-center mb-16">
          <div className="inline-flex items-center gap-2 glass rounded-full px-4 py-1.5 mb-4">
            <span className="text-xs font-medium text-slate-400 uppercase tracking-wide">Architecture</span>
          </div>
          <h2 className="text-3xl sm:text-4xl font-bold text-white mb-4">
            Five Config Layers.
            <br />
            <span className="text-gradient-blue">Zero Code Changes for Banks.</span>
          </h2>
          <p className="text-slate-400 max-w-xl mx-auto">
            Every bank-specific behaviour is controlled by config — not by custom code.
            Layer 1 is non-overridable. Layers 3 and 4 hot-reload in under 30 seconds without pod restarts.
          </p>
        </div>

        {/* Layer stack */}
        <div className="space-y-3 mb-12">
          {LAYERS.map(({ num, name, color, bg, who, how, examples }) => (
            <div key={num} className={`rounded-xl border ${bg} p-5 group cursor-default`}>
              <div className="flex items-start gap-4">
                <div className={`text-xs font-mono font-bold ${color} w-6 flex-shrink-0 mt-0.5`}>{num}</div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-3 mb-2 flex-wrap">
                    <span className={`text-sm font-semibold ${color}`}>{name}</span>
                    <span className="text-xs text-slate-500 bg-white/4 px-2 py-0.5 rounded-full">{who}</span>
                    <span className="text-xs text-slate-600">{how}</span>
                  </div>
                  <div className="text-xs text-slate-500 leading-relaxed">{examples}</div>
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Deployment model callout */}
        <div className="grid md:grid-cols-3 gap-5">
          {[
            {
              title: 'GitOps Pull Model',
              desc: 'ArgoCD watches our OCI registry. Banks pull upgrades on their schedule through their change management. We publish — they control.',
              icon: '↓',
              color: 'text-blue-400',
            },
            {
              title: 'Independent Chart Versions',
              desc: 'astra-platform, astra-cts, astra-ej versioned independently. A CTS fix ships without forcing EJ banks to upgrade.',
              icon: '⊞',
              color: 'text-violet-400',
            },
            {
              title: 'Rollback in < 10 Minutes',
              desc: 'ArgoCD reverts targetRevision. Alembic downgrade migration runs automatically. SLA: rollback complete in under 10 minutes.',
              icon: '↺',
              color: 'text-gold-400',
            },
          ].map(({ title, desc, icon, color }) => (
            <div key={title} className="glass rounded-2xl p-6">
              <div className={`text-2xl font-mono ${color} mb-4`}>{icon}</div>
              <h3 className="text-sm font-semibold text-white mb-2">{title}</h3>
              <p className="text-xs text-slate-400 leading-relaxed">{desc}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

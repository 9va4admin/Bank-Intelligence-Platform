import { ACCENTS, DoubleBullet, IconTile } from './ui'

// Landing page copy is exempt from the message registry by decision (see CLAUDE.md, message taxonomy).
// Deliberately generic: no product, infrastructure or protocol names are shown publicly at this stage.
const PILLARS = [
  { icon: 'server', accent: 'teal', title: '100% on premises', body: 'No cloud dependencies. Your data, your servers, your network. Nothing leaves the bank.' },
  { icon: 'bank', accent: 'sky', title: 'Built around the RBI IT framework', body: 'Controls are mapped to the RBI’s IT and outsourcing requirements, with evidence kept ready for review.' },
  { icon: 'shield', accent: 'violet', title: 'Zero trust by default', body: 'Every request is authenticated and authorised. No access is assumed because of where it comes from.' },
  { icon: 'search', accent: 'amber', title: 'Explainable AI only', body: 'Every automated decision comes with a reason a person can read, and an audit record.' },
  { icon: 'layers', accent: 'rose', title: 'Active-active resilience', body: 'Two data centres serving live traffic, so one site failing does not stop the bank’s work.' },
  { icon: 'doc', accent: 'teal', title: 'Tamper-evident audit trail', body: 'Every decision, setting change and access is recorded so that any tampering can be detected.' },
]
const STRIP = [
  ['Encryption', 'Data encrypted at rest and in transit, with sensitive fields protected individually'],
  ['Key custody', 'Signing keys held in hardware, never in software'],
  ['Access', 'Your identity provider, role-based access, and approval by a second person for sensitive changes'],
]

export default function SecuritySection() {
  return (
    <section id="security" className="bg-white py-20 px-6">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-14">
          <span className="inline-block text-xs font-semibold text-teal-600 tracking-widest uppercase mb-3">Security and compliance</span>
          <h2 className="text-3xl sm:text-4xl font-bold text-slate-900 mb-4">
            Built for the RBI. <span className="text-teal-500">Owned by the bank.</span>
          </h2>
          <p className="text-slate-500 max-w-2xl mx-auto text-sm leading-relaxed">
            Banking-grade security is not an add-on. It is how the platform is designed, from the first line.
          </p>
        </div>

        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {PILLARS.map(({ icon, accent, title, body }) => (
            <div key={title} className="rounded-2xl border border-slate-200 bg-cream-50 p-6" style={{ borderTop: `3px solid ${ACCENTS[accent]}` }}>
              <div className="mb-3"><IconTile name={icon} accent={accent} size={42} /></div>
              <h3 className="font-semibold text-slate-900 mb-2">{title}</h3>
              <p className="text-sm text-slate-500 leading-relaxed">{body}</p>
            </div>
          ))}
        </div>

        <div className="mt-8 rounded-2xl bg-cream-50 border border-dashed border-slate-300 p-7">
          <div className="grid sm:grid-cols-3 gap-6">
            {STRIP.map(([label, value], i) => (
              <div key={label} className="flex gap-3">
                <DoubleBullet accent={['teal', 'sky', 'violet'][i]} size={16} />
                <div>
                  <div className="text-xs font-semibold tracking-widest uppercase mb-1" style={{ color: ACCENTS[['teal', 'sky', 'violet'][i]] }}>{label}</div>
                  <div className="text-sm text-slate-600 leading-relaxed">{value}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}

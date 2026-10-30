import { msg } from '../../shared/messages'
const TIERS = [
  {
    name: 'Starter SaaS',
    tagline: msg('UI_TECHSTACK_FOR_UCBS_AND_RRBS_WITH'),
    pricing: '₹0.12–0.18 / cheque',
    features: [
      'CTS module only',
      'Shared managed infrastructure (bank-isolated namespace)',
      'Up to 50,000 cheques/month',
      'Standard support (next business day)',
      'RBI compliance reporting included',
    ],
    color: 'border-slate-200',
    badgeColor: 'bg-slate-100 text-slate-600',
    highlight: false,
  },
  {
    name: 'Growth Licence',
    tagline: msg('UI_TECHSTACK_FOR_MID_TIER_BANKS_DEPLOYING'),
    pricing: '₹50L–1.2Cr + 18% AMC',
    features: [
      'CTS module — on-premises deployment',
      'On-premises deployment in bank\'s DC',
      'Unlimited cheques, unlimited ATMs',
      'Priority support (4-hour SLA)',
      'Dedicated ML engineer for model tuning',
      'Bank-specific fraud model training',
    ],
    color: 'border-teal-400',
    badgeColor: 'bg-teal-50 text-teal-700',
    highlight: true,
  },
  {
    name: 'Enterprise Managed',
    tagline: msg('UI_TECHSTACK_FOR_LARGE_BANKS_WITH_ACTIVE'),
    pricing: '₹12–25L / month',
    features: [
      'CTS + full observability stack',
      'Active-active across 2 DCs (RPO = 0)',
      'Dedicated ASTRA engineer on-site',
      'Custom CBS connector development',
      'Regulatory examination support',
      'White-glove onboarding and change management',
    ],
    color: 'border-sky-400',
    badgeColor: 'bg-sky-50 text-sky-700',
    highlight: false,
  },
]

const NORTH_STAR = [
  { label: msg('UI_TECHSTACK_NORTH_STAR_VISION'), value: 'Every instrument, everywhere — cheques, UPI, NACH, IMPS — intelligently processed, always on-premises, never breaching mandate.' },
  { label: msg('UI_TECHSTACK_PHASE_1'), value: 'CTS (now in production readiness)' },
  { label: msg('UI_TECHSTACK_PHASE_2'), value: 'NACH return processing, UPI dispute intelligence' },
  { label: msg('UI_TECHSTACK_PHASE_3'), value: 'Cross-bank fraud intelligence network (consent-gated, federated)' },
]

export default function TechStack() {
  return (
    <section id="commercial" className="bg-white py-20 px-6">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-14">
          <span className="inline-block text-xs font-semibold text-slate-400 tracking-widest uppercase mb-3">{msg('UI_FOOTER_COMMERCIAL_MODEL')}</span>
          <h2 className="text-3xl sm:text-4xl font-bold text-slate-900 mb-4">
           {msg('UI_TECHSTACK_PRICED_FOR_INDIAN_BANKS')}<br />
            <span className="text-teal-500">{msg('UI_TECHSTACK_NOT_SILICON_VALLEY_SAAS')}</span>
          </h2>
          <p className="text-slate-500 max-w-xl mx-auto text-sm">
           {msg('UI_TECHSTACK_THREE_TIERS_FROM_FIRST_TIME')}
          </p>
        </div>

        <div className="grid sm:grid-cols-3 gap-5 mb-14">
          {TIERS.map(({ name, tagline, pricing, features, color, badgeColor, highlight }) => (
            <div key={name} className={`rounded-2xl border-2 p-7 ${color} ${highlight ? 'shadow-lg shadow-teal-400/10' : ''}`}>
              <span className={`inline-block text-xs font-semibold px-2.5 py-1 rounded-full mb-4 ${badgeColor}`}>{name}</span>
              <p className="text-xs text-slate-400 mb-2">{tagline}</p>
              <div className="text-xl font-bold text-slate-900 mb-5">{pricing}</div>
              <ul className="space-y-2.5">
                {features.map(f => (
                  <li key={f} className="flex items-start gap-2 text-sm text-slate-600">
                    <span className={`text-xs mt-0.5 ${highlight ? 'text-teal-500' : 'text-slate-400'}`}>✓</span>
                    {f}
                  </li>
                ))}
              </ul>
              {highlight && (
                <a href="#contact" className="mt-6 block text-center text-sm font-medium bg-teal-400 hover:bg-teal-500 text-forest-900 px-5 py-2.5 rounded-xl transition-colors">
                 {msg('UI_TECHSTACK_GET_PRICING')}
                </a>
              )}
            </div>
          ))}
        </div>

        {/* North Star */}
        <div className="bg-forest-900 rounded-2xl p-8 text-white">
          <div className="mb-6">
            <span className="text-xs font-semibold text-teal-400 tracking-widest uppercase">{msg('UI_TECHSTACK_NORTH_STAR')}</span>
            <h3 className="text-xl font-bold mt-1">{msg('UI_TECHSTACK_ASTRA_S_LONG_TERM_VISION')}</h3>
          </div>
          <div className="space-y-3">
            {NORTH_STAR.map(({ label, value }) => (
              <div key={label} className="flex gap-4 py-3 border-b border-white/8 last:border-0">
                <div className="w-28 flex-shrink-0 text-xs font-semibold text-teal-400">{label}</div>
                <div className="text-sm text-slate-300">{value}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}

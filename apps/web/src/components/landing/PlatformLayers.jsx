import { ACCENTS, DoubleBullet, Icon, IconTile } from './ui'

// Landing page copy is exempt from the message registry by decision (see CLAUDE.md, message taxonomy).
const PRODUCTS = [
  ['cheque', 'sky', 'CTS cheque clearing', true],
  ['shield', 'violet', 'PRAMAAN compliance', false],
  ['search', 'rose', 'Fraud and mule detection', false],
  ['idcard', 'amber', 'KYC and more', false],
]
const SERVICES = [
  ['database', 'Live working copy'],
  ['bolt', 'Event capture'],
  ['layers', 'Decision engine'],
  ['doc', 'Tamper-evident audit'],
  ['scale', 'Configuration and approvals'],
  ['clock', 'Alerts and notifications'],
]
const SOURCES = [
  ['bank', 'Core banking system'],
  ['link', 'Payment rails and channels'],
  ['cheque', 'Scanners and ATMs'],
  ['doc', 'Documents and KYC'],
]
const POINTS = [
  { accent: 'teal', title: 'Beside the CBS, not instead of it', body: 'The core stays the book of record. ASTRA reads its changes and serves the reads, so the core is free for what only it can do.' },
  { accent: 'sky', title: 'Two data centres, both live', body: 'Active-active, so one site failing does not stop clearing.' },
  { accent: 'violet', title: 'Inside the bank, always', body: 'Everything runs in the bank’s own premises and its own network.' },
]

function Connector({ label }) {
  return (
    <div className="flex flex-col items-center py-2" aria-hidden="true">
      <svg width="24" height="34" viewBox="0 0 24 34" fill="none">
        <line x1="12" y1="0" x2="12" y2="26" stroke={ACCENTS.teal} strokeWidth="2" strokeDasharray="4 4" />
        <path d="M6 22l6 8 6-8" stroke={ACCENTS.teal} strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {label && <span className="text-[10px] tracking-widest uppercase text-slate-400 mt-0.5">{label}</span>}
    </div>
  )
}

export default function PlatformLayers() {
  return (
    <section id="platform-layers" className="bg-cream-50 py-20 px-6">
      <div className="max-w-5xl mx-auto">
        <div className="text-center mb-12">
          <span className="inline-block text-xs font-semibold text-teal-600 tracking-widest uppercase mb-3">The platform</span>
          <h2 className="text-3xl sm:text-4xl font-bold text-slate-900 mb-4">
            One platform. <span className="text-teal-500">Many products.</span>
          </h2>
          <p className="text-slate-500 max-w-2xl mx-auto text-sm leading-relaxed">
            Every product shares the same foundation, so each new one is faster to build and cheaper to run.
          </p>
        </div>

        <div className="rounded-3xl bg-cream-50 border border-slate-200 p-5 sm:p-8">
          <div className="text-center text-[11px] font-semibold tracking-widest uppercase text-slate-400 mb-3">Products</div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {PRODUCTS.map(([icon, accent, name, first]) => (
              <div key={name} className="rounded-xl bg-white border px-3 py-4 text-center" style={{ borderColor: first ? ACCENTS[accent] : '#e2e8f0', boxShadow: first ? `0 6px 18px ${ACCENTS[accent]}26` : 'none' }}>
                <div className="flex justify-center mb-2"><IconTile name={icon} accent={accent} size={38} /></div>
                <div className="text-sm font-semibold text-slate-900">{name}</div>
                {first && <div className="text-[10px] font-semibold tracking-widest uppercase mt-1" style={{ color: ACCENTS[accent] }}>First product</div>}
              </div>
            ))}
          </div>

          <Connector />

          <div className="rounded-2xl bg-white p-5" style={{ border: `2px dashed ${ACCENTS.teal}66` }}>
            <div className="flex items-center justify-center gap-2 mb-4">
              <DoubleBullet accent="teal" size={14} />
              <span className="text-[11px] font-semibold tracking-widest uppercase text-teal-600">ASTRA platform</span>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
              {SERVICES.map(([icon, name], i) => (
                <div key={name} className="flex items-center gap-2.5 rounded-lg bg-cream-50 border border-slate-200 px-3 py-2.5">
                  <Icon name={icon} color={ACCENTS[['teal', 'sky', 'violet', 'amber', 'rose', 'teal'][i]]} size={18} />
                  <span className="text-xs text-slate-700">{name}</span>
                </div>
              ))}
            </div>
          </div>

          <Connector label="reads changes, serves reads" />

          <div className="text-center text-[11px] font-semibold tracking-widest uppercase text-slate-400 mb-3">Your systems, unchanged</div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {SOURCES.map(([icon, name]) => (
              <div key={name} className="rounded-xl bg-white border border-slate-200 px-3 py-3 flex items-center justify-center gap-2 text-xs text-slate-600">
                <Icon name={icon} color="#64748b" size={18} />
                {name}
              </div>
            ))}
          </div>
        </div>

        <div className="grid sm:grid-cols-3 gap-4 mt-6">
          {POINTS.map(({ accent, title, body }) => (
            <div key={title} className="rounded-xl bg-white border border-slate-200 p-5" style={{ borderTop: `3px solid ${ACCENTS[accent]}` }}>
              <div className="font-semibold text-slate-900 text-sm mb-1">{title}</div>
              <p className="text-xs text-slate-500 leading-relaxed">{body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

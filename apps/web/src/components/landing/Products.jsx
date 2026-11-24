import { Link } from 'react-router-dom'
import { ACCENTS, DoubleBullet, IconTile } from './ui'

// Landing page copy is exempt from the message registry by decision (see CLAUDE.md, message taxonomy).
const MORE = [
  { icon: 'search', accent: 'rose', name: 'Fraud and mule detection', body: 'Live events across accounts, ranked suspects with plain reasons, a person decides.', status: 'Planned' },
  { icon: 'idcard', accent: 'amber', name: 'KYC automation', body: 'Documents read and checked against records, a reviewer approves.', status: 'Planned' },
  { icon: 'link', accent: 'sky', name: 'Reconciliation', body: 'Cheques, ATM, NACH and UPI matched from one place.', status: 'Planned' },
  { icon: 'bolt', accent: 'teal', name: 'Account validation', body: 'Answer payment pre-checks without calling the CBS each time.', status: 'Planned' },
  { icon: 'doc', accent: 'violet', name: 'ATM electronic journal', body: 'Dispute evidence from ATM journals across OEM formats.', status: 'Separate product', to: '/ej' },
]
const PRAMAAN_POINTS = ['A clock per regulator, on one calendar', 'Filings pre-filled and pre-checked', 'One-click maker-checker approval', 'Timestamped, tamper-evident proof of every filing']

export default function Products() {
  return (
    <section id="products" className="bg-white py-20 px-6">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-12">
          <span className="inline-block text-xs font-semibold text-teal-600 tracking-widest uppercase mb-3">Products on ASTRA</span>
          <h2 className="text-3xl sm:text-4xl font-bold text-slate-900 mb-4">
            Start with the deadline. <span className="text-teal-500">Grow from there.</span>
          </h2>
        </div>

        <div className="grid lg:grid-cols-5 gap-5 mb-5">
          <div className="lg:col-span-3 bg-white rounded-2xl border p-8 shadow-sm" style={{ borderColor: `${ACCENTS.sky}66`, borderTop: `4px solid ${ACCENTS.sky}` }}>
            <div className="flex items-center gap-3 mb-4">
              <IconTile name="cheque" accent="sky" size={46} />
              <span className="inline-block text-xs font-semibold px-2.5 py-1 rounded-full text-white" style={{ background: ACCENTS.sky }}>First product</span>
            </div>
            <h3 className="text-2xl font-bold text-slate-900 mb-3">CTS: cheque clearing, inward and outward</h3>
            <p className="text-slate-600 text-sm leading-relaxed mb-5">
              One AI agent per cheque, designed to decide in under 600 milliseconds, with a watchdog that files before the RBI window closes. Handwriting, signature and fraud checks, with a person reviewing anything uncertain.
            </p>
            <div className="grid grid-cols-3 gap-3 mb-6 text-center">
              {[['0.000%', 'item-expiry breach goal', 'teal'], ['<600ms', 'design target, p99', 'sky'], ['100%', 'on premises', 'violet']].map(([v, l, a]) => (
                <div key={l} className="rounded-xl bg-cream-50 border border-slate-200 py-3">
                  <div className="text-lg font-bold" style={{ color: ACCENTS[a] }}>{v}</div>
                  <div className="text-[11px] text-slate-500 px-1">{l}</div>
                </div>
              ))}
            </div>
            <a href="#cts" className="text-sm font-medium" style={{ color: ACCENTS.sky }}>See how CTS works &rarr;</a>
          </div>

          <div id="pramaan" className="lg:col-span-2 bg-white rounded-2xl border p-8 shadow-sm" style={{ borderColor: `${ACCENTS.violet}66`, borderTop: `4px solid ${ACCENTS.violet}` }}>
            <div className="flex items-center gap-3 mb-4">
              <IconTile name="shield" accent="violet" size={46} />
              <span className="inline-block text-xs font-semibold px-2.5 py-1 rounded-full" style={{ background: `${ACCENTS.violet}1A`, color: ACCENTS.violet }}>Design partners</span>
            </div>
            <h3 className="text-xl font-bold text-slate-900 mb-1">PRAMAAN</h3>
            <div className="text-xs mb-3" style={{ color: ACCENTS.violet }}>proof, by design</div>
            <p className="text-slate-600 text-sm leading-relaxed mb-4">
              Regulatory reporting, incident notification and information exchange on one hub. One integration, every regulator, every deadline.
            </p>
            <ul className="text-sm text-slate-700 space-y-2.5 mb-5">
              {PRAMAAN_POINTS.map((t) => (
                <li key={t} className="flex gap-3"><DoubleBullet accent="violet" />{t}</li>
              ))}
            </ul>
            <p className="text-xs text-slate-400 mb-4">Automate the routine. Approve the critical.</p>
            <a href="#contact" className="text-sm font-medium" style={{ color: ACCENTS.violet }}>Become a design partner &rarr;</a>
          </div>
        </div>

        <div className="grid sm:grid-cols-2 lg:grid-cols-5 gap-3">
          {MORE.map(({ icon, accent, name, body, status, to }) => {
            const card = (
              <div className="h-full rounded-xl bg-white border border-slate-200 p-4 hover:shadow-md transition-shadow" style={{ borderTop: `3px solid ${ACCENTS[accent]}` }}>
                <div className="flex items-center justify-between mb-2">
                  <IconTile name={icon} accent={accent} size={34} />
                  <span className="text-[10px] font-semibold tracking-widest uppercase text-slate-400">{status}</span>
                </div>
                <div className="font-semibold text-slate-900 text-sm mb-1">{name}</div>
                <p className="text-xs text-slate-500 leading-relaxed">{body}</p>
              </div>
            )
            return to ? <Link key={name} to={to} className="block">{card}</Link> : <div key={name}>{card}</div>
          })}
        </div>
      </div>
    </section>
  )
}

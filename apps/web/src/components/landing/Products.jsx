import { Link } from 'react-router-dom'

// Landing page copy is exempt from the message registry by decision (see CLAUDE.md, message taxonomy).
const MORE = [
  { name: 'Fraud and mule detection', body: 'Live events across accounts, ranked suspects with plain reasons, a person decides.', status: 'Planned' },
  { name: 'KYC automation', body: 'Documents read and checked against records, a reviewer approves.', status: 'Planned' },
  { name: 'Reconciliation', body: 'Cheques, ATM, NACH and UPI matched from one place.', status: 'Planned' },
  { name: 'Account validation', body: 'Answer payment pre-checks without calling the CBS each time.', status: 'Planned' },
  { name: 'ATM electronic journal', body: 'Dispute evidence from ATM journals across OEM formats.', status: 'Separate product', to: '/ej' },
]

export default function Products() {
  return (
    <section id="products" className="bg-cream-100 py-20 px-6">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-12">
          <span className="inline-block text-xs font-semibold text-teal-600 tracking-widest uppercase mb-3">Products on ASTRA</span>
          <h2 className="text-3xl sm:text-4xl font-bold text-slate-900 mb-4">
            Start with the deadline. <span className="text-teal-500">Grow from there.</span>
          </h2>
        </div>

        <div className="grid lg:grid-cols-5 gap-5 mb-5">
          <div className="lg:col-span-3 bg-forest-900 text-white rounded-2xl p-8">
            <span className="inline-block text-xs font-semibold px-2.5 py-1 rounded-full bg-teal-400 text-forest-900 mb-4">First product</span>
            <h3 className="text-2xl font-bold mb-3">CTS: cheque clearing, inward and outward</h3>
            <p className="text-slate-300 text-sm leading-relaxed mb-5">
              One AI agent per cheque, decided in under 600 milliseconds, with a watchdog that files before the RBI window closes. Handwriting, signature and fraud checks, with a person reviewing anything uncertain.
            </p>
            <div className="grid grid-cols-3 gap-3 mb-6 text-center">
              {[['0.000%', 'item-expiry breach rate'], ['<600ms', 'any batch size, p99'], ['100%', 'on premises']].map(([v, l]) => (
                <div key={l} className="rounded-xl bg-white/6 py-3">
                  <div className="text-lg font-bold text-teal-400">{v}</div>
                  <div className="text-[11px] text-slate-400 px-1">{l}</div>
                </div>
              ))}
            </div>
            <a href="#cts" className="text-sm font-medium text-teal-300 hover:text-teal-200">See how CTS works &rarr;</a>
          </div>

          <div id="pramaan" className="lg:col-span-2 bg-white rounded-2xl border border-slate-200 p-8">
            <span className="inline-block text-xs font-semibold px-2.5 py-1 rounded-full bg-sky-100 text-sky-700 mb-4">Design partners</span>
            <h3 className="text-xl font-bold text-slate-900 mb-1">PRAMAAN</h3>
            <div className="text-xs text-teal-600 mb-3">proof, by design</div>
            <p className="text-slate-600 text-sm leading-relaxed mb-4">
              Regulatory reporting, incident notification and information exchange on one hub. One integration, every regulator, every deadline.
            </p>
            <ul className="text-sm text-slate-600 space-y-2 mb-5">
              <li>A clock per regulator, on one calendar</li>
              <li>Filings pre-filled and pre-checked</li>
              <li>One-click maker-checker approval</li>
              <li>Timestamped, tamper-evident proof of every filing</li>
            </ul>
            <p className="text-xs text-slate-400 mb-4">Automate the routine. Approve the critical.</p>
            <a href="#contact" className="text-sm font-medium text-teal-600 hover:text-teal-700">Become a design partner &rarr;</a>
          </div>
        </div>

        <div className="grid sm:grid-cols-2 lg:grid-cols-5 gap-3">
          {MORE.map(({ name, body, status, to }) => {
            const card = (
              <div className="h-full rounded-xl bg-white border border-slate-200 p-4">
                <span className="text-[10px] font-semibold tracking-widest uppercase text-slate-400">{status}</span>
                <div className="font-semibold text-slate-900 text-sm mt-1 mb-1">{name}</div>
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

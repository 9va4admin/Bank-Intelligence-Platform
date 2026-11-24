// Landing page copy is exempt from the message registry by decision (see CLAUDE.md, message taxonomy).
const SOURCES = ['Core banking (Finacle, BaNCS, Flexcube)', 'Payment rails and channels', 'Scanners and ATMs', 'Documents and KYC']
const SERVICES = ['Live working copy', 'Event capture', 'Decision engine', 'Tamper-evident audit', 'Configuration and approvals', 'Alerts and notifications']
const POINTS = [
  { title: 'Beside the CBS, not instead of it', body: 'The core stays the book of record. ASTRA reads its changes and serves the reads, so the core is free for what only it can do.' },
  { title: 'Two data centres, both live', body: 'Active-active, so one site failing does not stop clearing.' },
  { title: 'Inside the bank, always', body: 'Everything runs in the bank’s own premises and its own network.' },
]

export default function PlatformLayers() {
  return (
    <section id="platform-layers" className="bg-white py-20 px-6">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-12">
          <span className="inline-block text-xs font-semibold text-teal-600 tracking-widest uppercase mb-3">The platform</span>
          <h2 className="text-3xl sm:text-4xl font-bold text-slate-900 mb-4">
            One platform. <span className="text-teal-500">Many products.</span>
          </h2>
          <p className="text-slate-500 max-w-2xl mx-auto text-sm leading-relaxed">
            Every product shares the same foundation, so each new one is faster to build and cheaper to run.
          </p>
        </div>

        <div className="bg-forest-900 rounded-2xl p-6 sm:p-8 text-white">
          <div className="text-center text-xs font-semibold tracking-widest uppercase text-teal-400 mb-3">Products</div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-3">
            {['CTS cheque clearing', 'PRAMAAN compliance', 'Fraud and mule detection', 'KYC and more'].map((p, i) => (
              <div key={p} className={`rounded-xl px-4 py-4 text-center text-sm font-semibold ${i === 0 ? 'bg-teal-400 text-forest-900' : 'bg-white/8 border border-white/10 text-slate-200'}`}>{p}</div>
            ))}
          </div>

          <div className="text-center text-slate-500 my-2" aria-hidden="true">&#8593;</div>

          <div className="rounded-xl border border-teal-400/40 bg-teal-400/8 p-5 mb-3">
            <div className="text-center text-xs font-semibold tracking-widest uppercase text-teal-300 mb-3">ASTRA platform</div>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {SERVICES.map((s) => (
                <div key={s} className="rounded-lg bg-white/6 px-3 py-2.5 text-center text-xs text-slate-200">{s}</div>
              ))}
            </div>
          </div>

          <div className="text-center text-slate-500 my-2" aria-hidden="true">&#8593;</div>

          <div className="text-center text-xs font-semibold tracking-widest uppercase text-slate-400 mb-3">Your systems, unchanged</div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {SOURCES.map((s) => (
              <div key={s} className="rounded-xl border border-white/10 bg-white/4 px-3 py-3 text-center text-xs text-slate-300">{s}</div>
            ))}
          </div>
        </div>

        <div className="grid sm:grid-cols-3 gap-4 mt-6">
          {POINTS.map(({ title, body }) => (
            <div key={title} className="rounded-xl bg-slate-50 border border-slate-200 p-5">
              <div className="font-semibold text-slate-900 text-sm mb-1">{title}</div>
              <p className="text-xs text-slate-500 leading-relaxed">{body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

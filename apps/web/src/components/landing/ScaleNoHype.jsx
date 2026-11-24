import { ACCENTS, DoubleBullet, IconTile } from './ui'

// Landing page copy is exempt from the message registry by decision (see CLAUDE.md, message taxonomy).
// The diagram is an illustration of the design, not a measurement, and is labelled as such.
const PRINCIPLES = [
  { icon: 'database', accent: 'teal', title: 'Read from a working copy', body: 'Most questions are answered from a live copy beside the CBS, so the CBS is asked only what must be authoritative.' },
  { icon: 'layers', accent: 'sky', title: 'Parallel, not a queue', body: 'One agent per cheque. Adding load adds workers, not waiting.' },
  { icon: 'server', accent: 'violet', title: 'Two sites, both live', body: 'Active-active across two data centres, so a site failing does not stop the work.' },
  { icon: 'clock', accent: 'amber', title: 'The deadline is guarded', body: 'A watchdog files before the window closes, whatever else is happening.' },
]
const PROVEN = ['A failed or timed-out AI step never fails the workflow: it goes to a person (tested on 70 real images with the AI fully unavailable)', 'A duplicate presentment is detected and refused', 'An untrained signature model is never allowed to confirm a cheque automatically']
const TARGETS = ['Decision under 600 ms, 99th percentile, at any batch size', 'Item-expiry breach rate 0.000%', 'Recovery under 30 seconds if a data centre fails, with no data loss']
const PILOT = ['Measure all three targets on the bank’s own GPUs and traffic', 'Count how many CBS calls the working copy removes', 'Prove accuracy on the bank’s own labelled cheques']

function CbsDiagram() {
  const channels = [30, 70, 110, 150]
  return (
    <div className="grid sm:grid-cols-2 gap-4">
      <svg viewBox="0 0 260 190" className="w-full h-auto" role="img" aria-label="Today: every channel calls the core banking system directly">
        <text x="130" y="14" textAnchor="middle" fontSize="11" fill="#64748b" fontWeight="700">TODAY</text>
        {channels.map((y) => (
          <g key={y}>
            <circle cx="24" cy={y + 8} r="9" fill="#fff" stroke="#94a3b8" strokeWidth="2" />
            <circle cx="24" cy={y + 8} r="3.5" fill="#94a3b8" />
            {[-9, 0, 9].map((d) => <line key={d} x1="34" y1={y + 8} x2="176" y2={95 + d * 3} stroke="#cbd5e1" strokeWidth="1.5" />)}
          </g>
        ))}
        <rect x="176" y="55" width="70" height="80" rx="10" fill="#fff" stroke={ACCENTS.rose} strokeWidth="2" />
        <text x="211" y="92" textAnchor="middle" fontSize="12" fill="#0f172a" fontWeight="700">CBS</text>
        <text x="211" y="108" textAnchor="middle" fontSize="9.5" fill={ACCENTS.rose}>every read</text>
        <text x="130" y="184" textAnchor="middle" fontSize="10" fill="#94a3b8">many calls, all to one system</text>
      </svg>
      <svg viewBox="0 0 260 190" className="w-full h-auto" role="img" aria-label="With ASTRA: channels are served by ASTRA, and only a few calls reach the core banking system">
        <text x="130" y="14" textAnchor="middle" fontSize="11" fill={ACCENTS.teal} fontWeight="700">WITH ASTRA</text>
        {channels.map((y) => (
          <g key={y}>
            <circle cx="24" cy={y + 8} r="9" fill="#fff" stroke={ACCENTS.teal} strokeWidth="2" />
            <circle cx="24" cy={y + 8} r="3.5" fill={ACCENTS.teal} />
            <line x1="34" y1={y + 8} x2="100" y2="95" stroke={`${ACCENTS.teal}66`} strokeWidth="1.5" />
          </g>
        ))}
        <rect x="100" y="55" width="62" height="80" rx="10" fill={`${ACCENTS.teal}14`} stroke={ACCENTS.teal} strokeWidth="2" />
        <text x="131" y="92" textAnchor="middle" fontSize="12" fill="#0f172a" fontWeight="700">ASTRA</text>
        <text x="131" y="108" textAnchor="middle" fontSize="9.5" fill={ACCENTS.teal}>most reads</text>
        <line x1="162" y1="95" x2="188" y2="95" stroke={ACCENTS.teal} strokeWidth="2" strokeDasharray="4 3" />
        <rect x="188" y="65" width="58" height="60" rx="10" fill="#fff" stroke="#94a3b8" strokeWidth="2" />
        <text x="217" y="100" textAnchor="middle" fontSize="12" fill="#0f172a" fontWeight="700">CBS</text>
        <text x="130" y="184" textAnchor="middle" fontSize="10" fill="#94a3b8">few calls, only what must be authoritative</text>
      </svg>
    </div>
  )
}

function Column({ title, accent, items }) {
  return (
    <div className="rounded-2xl bg-white border border-slate-200 p-6" style={{ borderTop: `3px solid ${ACCENTS[accent]}` }}>
      <div className="text-xs font-semibold tracking-widest uppercase mb-4" style={{ color: ACCENTS[accent] }}>{title}</div>
      <ul className="space-y-3">{items.map((t) => <li key={t} className="flex gap-3 text-sm text-slate-700 leading-relaxed"><DoubleBullet accent={accent} />{t}</li>)}</ul>
    </div>
  )
}

export default function ScaleNoHype() {
  return (
    <section id="scale-speed" className="bg-white py-20 px-6">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-12">
          <span className="inline-block text-xs font-semibold text-teal-600 tracking-widest uppercase mb-3">Scale and speed</span>
          <h2 className="text-3xl sm:text-4xl font-bold text-slate-900 mb-4">
            Faster because of the design. <span className="text-teal-500">Not because of a claim.</span>
          </h2>
          <p className="text-slate-500 max-w-2xl mx-auto text-sm leading-relaxed">
            Speed comes from doing less in the slow place and more in parallel. Here is how, and exactly what we have and have not proved.
          </p>
        </div>

        <div className="rounded-2xl bg-cream-50 border border-slate-200 p-5 sm:p-6 mb-3">
          <CbsDiagram />
        </div>
        <p className="text-[11px] text-slate-400 text-center mb-8">Illustration of the design. Not a measurement. The reduction in CBS calls is measured at a bank, not claimed in advance.</p>

        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-10">
          {PRINCIPLES.map(({ icon, accent, title, body }) => (
            <div key={title} className="rounded-xl bg-cream-50 border border-slate-200 p-5">
              <div className="mb-3"><IconTile name={icon} accent={accent} size={38} /></div>
              <div className="font-semibold text-slate-900 text-sm mb-1">{title}</div>
              <p className="text-xs text-slate-500 leading-relaxed">{body}</p>
            </div>
          ))}
        </div>

        <div className="text-center mb-5">
          <h3 className="text-xl font-bold text-slate-900">What is proven, what is a target, and what a pilot will prove</h3>
        </div>
        <div className="grid md:grid-cols-3 gap-4">
          <Column title="Proven so far" accent="teal" items={PROVEN} />
          <Column title="Design targets" accent="amber" items={TARGETS} />
          <Column title="To prove at a pilot" accent="violet" items={PILOT} />
        </div>
      </div>
    </section>
  )
}

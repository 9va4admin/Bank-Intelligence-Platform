import { ACCENTS, DoubleBullet } from './ui'

// Landing page copy is exempt from the message registry by decision (see CLAUDE.md, message taxonomy).
// Every figure and quotation here was read from the cited RBI pages (checked 2026-11-24). The per-day figure is derived and says so.
const STATS = [
  { value: '609.5M', label: 'cheques cleared through CTS in FY 2024-25', accent: 'teal' },
  { value: '₹71.13 lakh crore', label: 'value cleared through CTS in FY 2024-25', accent: 'sky' },
  { value: '3 hours', label: 'for a drawee bank to confirm, from January 2026', accent: 'violet' },
  { value: '≈2.4M', label: 'cheques a working day (derived: 609.5M ÷ about 250 days)', accent: 'amber' },
]

function Timeline() {
  // 10:00 to 15:00 on a 0..500 axis. Arrival 10:00-11:00, confirmation window 11:00-14:00, deemed approved at 14:00.
  const x = (h) => 30 + (h - 10) * 88
  return (
    <svg viewBox="0 0 500 150" className="w-full h-auto" role="img" aria-label="Example timeline: cheques received 10 to 11 AM must be confirmed by 2 PM or are deemed approved">
      <line x1={x(10)} y1="78" x2={x(15)} y2="78" stroke="#cbd5e1" strokeWidth="2" strokeDasharray="5 5" />
      <rect x={x(10)} y="62" width={x(11) - x(10)} height="32" rx="6" fill={ACCENTS.sky} opacity="0.9" />
      <text x={(x(10) + x(11)) / 2} y="82" textAnchor="middle" fontSize="11" fill="#fff" fontWeight="600">cheques arrive</text>
      <rect x={x(11)} y="62" width={x(14) - x(11)} height="32" rx="6" fill={ACCENTS.teal} opacity="0.18" stroke={ACCENTS.teal} strokeDasharray="5 4" />
      <text x={(x(11) + x(14)) / 2} y="82" textAnchor="middle" fontSize="11" fill="#0d5039" fontWeight="600">drawee bank must confirm</text>
      <line x1={x(14)} y1="46" x2={x(14)} y2="110" stroke={ACCENTS.rose} strokeWidth="2.5" />
      <circle cx={x(14)} cy="78" r="6" fill="#fff" stroke={ACCENTS.rose} strokeWidth="2.5" />
      <text x={x(14)} y="38" textAnchor="middle" fontSize="11" fill={ACCENTS.rose} fontWeight="700">2:00 PM</text>
      <text x={x(14)} y="126" textAnchor="middle" fontSize="10.5" fill="#475569">not confirmed = deemed approved</text>
      {[10, 11, 12, 13, 14, 15].map((h) => (
        <g key={h}>
          <line x1={x(h)} y1="96" x2={x(h)} y2="102" stroke="#94a3b8" />
          <text x={x(h)} y="142" textAnchor="middle" fontSize="10" fill="#94a3b8">{h}:00</text>
        </g>
      ))}
    </svg>
  )
}

export default function WhyNow() {
  return (
    <section id="why-now" className="bg-white py-12 sm:py-14 px-6">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-8">
          <span className="inline-block text-xs font-semibold text-teal-600 tracking-widest uppercase mb-3">Why this matters now</span>
          <h2 className="text-3xl sm:text-4xl font-bold text-slate-900 mb-4">
            The clock is now <span className="text-teal-500">written into the rules.</span>
          </h2>
          <p className="text-slate-500 max-w-2xl mx-auto text-sm leading-relaxed">
            Since January 2026 a drawee bank has three hours to confirm each cheque. After that, silence counts as approval.
          </p>
        </div>

        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          {STATS.map(({ value, label, accent }) => (
            <div key={label} className="rounded-2xl bg-cream-50 border border-slate-200 p-5 text-center" style={{ borderTop: `3px solid ${ACCENTS[accent]}` }}>
              <div className="text-2xl sm:text-3xl font-bold" style={{ color: ACCENTS[accent] }}>{value}</div>
              <div className="text-xs text-slate-500 mt-1.5 leading-snug">{label}</div>
            </div>
          ))}
        </div>

        <div className="grid lg:grid-cols-5 gap-6">
          <div className="lg:col-span-3 rounded-2xl border border-slate-200 bg-cream-50 p-6">
            <div className="text-xs font-semibold tracking-widest uppercase text-slate-400 mb-3">Example from the RBI circular</div>
            <Timeline />
            <p className="text-xs text-slate-500 leading-relaxed mt-2">
              Cheques received between 10:00 and 11:00 must be confirmed by 14:00. The presenting bank then releases the money to its customer immediately, and not later than one hour after settlement.
            </p>
          </div>

          <div className="lg:col-span-2 rounded-2xl border border-slate-200 p-6 flex flex-col">
            <div className="text-xs font-semibold tracking-widest uppercase text-slate-400 mb-3">In the RBI’s words</div>
            <blockquote className="text-lg font-semibold text-slate-900 leading-snug border-l-4 pl-4" style={{ borderColor: ACCENTS.rose }}>
              &ldquo;shall be treated as deemed approved and included for settlement at 2:00 PM&rdquo;
            </blockquote>
            <p className="text-xs text-slate-500 mt-3 leading-relaxed">
              RBI circular RBI/2025-26/73, 13 August 2025, Annex para 3.2. Phase 2 applies from 3 January 2026.
            </p>
            <ul className="mt-5 space-y-3 text-sm text-slate-700">
              <li className="flex gap-3"><DoubleBullet accent="rose" />A missed window means the bank pays, whatever the fraud risk.</li>
              <li className="flex gap-3"><DoubleBullet accent="amber" />Doing it by hand at this volume does not scale.</li>
              <li className="flex gap-3"><DoubleBullet accent="teal" />So the decision has to be designed to finish inside the window.</li>
            </ul>
          </div>
        </div>

        <p className="text-[11px] text-slate-400 mt-5 text-center">
          Sources: <a className="underline" href="https://www.rbi.org.in/Scripts/BS_ViewMasDirections.aspx?id=12891" target="_blank" rel="noopener noreferrer">RBI circular RBI/2025-26/73</a>
          {' · '}
          <a className="underline" href="https://rbi.org.in/scripts/PSIUserView.aspx?Id=46" target="_blank" rel="noopener noreferrer">RBI Payment System Indicators, March 2025 (provisional data)</a>
        </p>
      </div>
    </section>
  )
}

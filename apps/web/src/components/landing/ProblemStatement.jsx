const PROBLEMS = [
  {
    icon: (
      <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
    label: 'The IET Countdown',
    title: 'Missed IET = Bank Pays. Always.',
    body:
      'RBI\'s Item Expiry Time mandate (Jan 2026) gives banks a T+3 hour window to decide on inward cheques. Miss it — the cheque is deemed approved. Even if it\'s fraud. Urban Co-op Banks and RRBs are most exposed — they lack the infrastructure to process 500+ cheques in parallel inside this window.',
    accent: 'text-red-400',
    border: 'border-red-500/20',
    glow: 'bg-red-500/5',
  },
  {
    icon: (
      <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 4.875c0-.621.504-1.125 1.125-1.125h4.5c.621 0 1.125.504 1.125 1.125v4.5c0 .621-.504 1.125-1.125 1.125h-4.5A1.125 1.125 0 013.75 9.375v-4.5zM3.75 14.625c0-.621.504-1.125 1.125-1.125h4.5c.621 0 1.125.504 1.125 1.125v4.5c0 .621-.504 1.125-1.125 1.125h-4.5a1.125 1.125 0 01-1.125-1.125v-4.5zM13.5 4.875c0-.621.504-1.125 1.125-1.125h4.5c.621 0 1.125.504 1.125 1.125v4.5c0 .621-.504 1.125-1.125 1.125h-4.5A1.125 1.125 0 0113.5 9.375v-4.5zM13.5 14.625c0-.621.504-1.125 1.125-1.125h4.5c.621 0 1.125.504 1.125 1.125v4.5c0 .621-.504 1.125-1.125 1.125h-4.5a1.125 1.125 0 01-1.125-1.125v-4.5z" />
      </svg>
    ),
    label: 'The EJ Chaos',
    title: '5+ OEMs. Zero Standard. Every ATM Speaks a Different Language.',
    body:
      'Electronic Journal logs from NCR, Diebold, Hyosung, Nautilus, GRG — every OEM has a proprietary format. Banks manually normalise these for dispute resolution, fleet observability, and RBI reporting. It\'s slow, error-prone, and doesn\'t scale. ASTRA solves it permanently with an LLM that understands all formats.',
    accent: 'text-amber-400',
    border: 'border-amber-500/20',
    glow: 'bg-amber-500/5',
  },
]

export default function ProblemStatement() {
  return (
    <section id="platform" className="py-24 px-6">
      <div className="max-w-7xl mx-auto">
        {/* Section header */}
        <div className="text-center mb-16">
          <div className="inline-flex items-center gap-2 glass rounded-full px-4 py-1.5 mb-4">
            <span className="text-xs font-medium text-slate-400 uppercase tracking-wide">The Problem</span>
          </div>
          <h2 className="text-3xl sm:text-4xl font-bold text-white mb-4">
            Two Unsolved Problems.<br />
            <span className="text-gradient">One Unified Platform.</span>
          </h2>
          <p className="text-slate-400 max-w-xl mx-auto text-lg">
            Both problems hit the same buyer — the bank\'s IT and operations team.
            ASTRA solves them together, deployed once.
          </p>
        </div>

        {/* Problem cards */}
        <div className="grid md:grid-cols-2 gap-6">
          {PROBLEMS.map(({ icon, label, title, body, accent, border, glow }) => (
            <div
              key={label}
              className={`relative rounded-2xl border ${border} ${glow} p-8 overflow-hidden group hover:-translate-y-1 transition-transform duration-300`}
            >
              {/* Subtle inner glow on hover */}
              <div className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none rounded-2xl"
                   style={{ background: 'radial-gradient(ellipse at top left, rgba(255,255,255,0.03) 0%, transparent 70%)' }} />

              <div className={`inline-flex items-center justify-center w-10 h-10 rounded-xl bg-white/5 ${accent} mb-6`}>
                {icon}
              </div>

              <div className={`text-xs font-semibold uppercase tracking-widest ${accent} mb-2`}>{label}</div>
              <h3 className="text-xl font-bold text-white mb-4 leading-snug">{title}</h3>
              <p className="text-slate-400 leading-relaxed text-sm">{body}</p>
            </div>
          ))}
        </div>

        {/* Bridge line */}
        <div className="mt-12 text-center">
          <p className="text-slate-500 text-sm">
            18-month first-mover window before incumbents (Nelito, TCS BaNCS) catch up.
            <span className="text-slate-300"> The window is open now.</span>
          </p>
        </div>
      </div>
    </section>
  )
}

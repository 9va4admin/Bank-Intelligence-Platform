const PAIN_POINTS = [
  {
    icon: '⏱',
    title: 'The IET Clock Never Stops',
    body: 'RBI\'s Item Expiry Time (IET) mandate: every inward cheque must be decided — confirm or return — within T+3 hours. Miss it, and the cheque is deemed approved. Your bank pays. Regardless of fraud.',
    color: 'border-red-200 bg-red-50',
    badgeColor: 'bg-red-100 text-red-700',
    badge: 'CTS Risk',
  },
  {
    icon: '📋',
    title: '45 Days to Resolve One ATM Dispute',
    body: 'A customer disputes a failed ATM dispense. Your ops team manually collects EJ logs, cross-references cash tallies, requests CCTV, files with NPCI. Average resolution: 45 working days. Customer experience: broken.',
    color: 'border-orange-200 bg-orange-50',
    badgeColor: 'bg-orange-100 text-orange-700',
    badge: 'EJ Risk',
  },
  {
    icon: '🔀',
    title: '5+ OEM Formats, Zero Standard',
    body: 'NCR, Diebold, Wincor, Hyosung, AGS — each ATM OEM produces a different EJ format. There is no industry standard. Banks maintain 5 separate parsers, each breaking on every OEM firmware update.',
    color: 'border-amber-200 bg-amber-50',
    badgeColor: 'bg-amber-100 text-amber-700',
    badge: 'EJ Complexity',
  },
  {
    icon: '🏦',
    title: 'Incumbents Need 18–24 Months',
    body: 'Legacy CBS vendors (TCS BaNCS, Nelito) are built for batch processing. Retrofitting agentic AI on a 30-year architecture takes 18–24 months. ASTRA is purpose-built — config change, not a rebuild.',
    color: 'border-violet-200 bg-violet-50',
    badgeColor: 'bg-violet-100 text-violet-700',
    badge: 'Competitive Gap',
  },
]

export default function ProblemStatement() {
  return (
    <section id="platform" className="bg-cream-100 py-20 px-6">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-14">
          <span className="inline-block text-xs font-semibold text-teal-600 tracking-widest uppercase mb-3">The Problem</span>
          <h2 className="text-3xl sm:text-4xl font-bold text-slate-900 mb-4">
            Two Operations. Two Unsolved Problems.
            <span className="text-teal-500"> One Platform.</span>
          </h2>
          <p className="text-slate-500 max-w-2xl mx-auto text-sm leading-relaxed">
            India processes 609 million cheques annually worth ₹71.1 lakh crore. 2.5 lakh ATMs log every transaction in formats no system can read automatically. Both problems have the same root cause — a missing intelligence layer.
          </p>
        </div>

        <div className="grid sm:grid-cols-2 gap-5 mb-14">
          {PAIN_POINTS.map(({ icon, title, body, color, badge, badgeColor }) => (
            <div key={title} className={`rounded-2xl border p-7 ${color}`}>
              <div className="flex items-start gap-4">
                <span className="text-3xl flex-shrink-0">{icon}</span>
                <div>
                  <span className={`inline-block text-xs font-semibold px-2 py-0.5 rounded-full mb-2 ${badgeColor}`}>{badge}</span>
                  <h3 className="font-semibold text-slate-900 mb-2">{title}</h3>
                  <p className="text-sm text-slate-600 leading-relaxed">{body}</p>
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* AI taxonomy */}
        <div className="bg-forest-900 rounded-2xl p-8 text-white">
          <div className="text-center mb-8">
            <span className="text-xs font-semibold text-teal-400 tracking-widest uppercase">ASTRA's Approach</span>
            <h3 className="text-xl font-bold mt-2 text-white">Not Just AI. <span style={{ color: '#1D9E75' }}>Agentic AI.</span></h3>
            <p className="text-slate-400 text-sm mt-2 max-w-lg mx-auto">There is a meaningful difference between a model that answers and a system that acts. ASTRA uses the right tier for each task.</p>
          </div>
          <div className="grid sm:grid-cols-3 gap-4">
            {[
              {
                tier: 'AI',
                emoji: '🤖',
                verb: 'Predicts. Answers. Stops.',
                desc: 'OCR extraction, fraud scoring, confidence estimation — outputs a number or a label.',
                borderColor: 'border-slate-600',
                tagColor: 'text-slate-400',
              },
              {
                tier: 'AI Agents',
                emoji: '⚙️',
                verb: 'Reasons. Uses tools. Takes steps.',
                desc: 'Multi-step cheque processing: OCR → vault lookup → CBS check → fraud score → decision → NGCH filing.',
                borderColor: 'border-sky-400/50',
                tagColor: 'text-sky-400',
                highlight: true,
              },
              {
                tier: 'Agentic AI',
                emoji: '🎯',
                verb: 'Perceives. Decides. Acts. Terminates.',
                desc: 'IET watchdog: monitors countdown, detects risk at T-30s, auto-files emergency return, closes itself.',
                borderColor: 'border-teal-400/50',
                tagColor: 'text-teal-400',
              },
            ].map(({ tier, emoji, verb, desc, borderColor, tagColor, highlight }) => (
              <div key={tier} className={`rounded-xl border p-5 ${borderColor} ${highlight ? 'bg-sky-400/6' : 'bg-white/4'}`}>
                <div className="text-2xl mb-3">{emoji}</div>
                <div className={`text-xs font-bold tracking-wide uppercase mb-1 ${tagColor}`}>{tier}</div>
                <div className="text-sm font-semibold text-white mb-2 italic">"{verb}"</div>
                <p className="text-xs text-slate-400 leading-relaxed">{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}

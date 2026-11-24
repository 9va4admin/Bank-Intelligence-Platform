import { ACCENTS, DoubleBullet, Icon } from './ui'

// Landing page copy is exempt from the message registry by decision (see CLAUDE.md, message taxonomy).
// The chart and the outage figure come from ASTRA's own test on 70 real cheque and draft images, with the truth read by eye.
// A small sample. Stated as such on the page.
const STAGES = [
  { icon: 'cheque', accent: 'sky', name: 'Intake', ai: 'Image and data arrive. A deadline watchdog starts first.' },
  { icon: 'search', accent: 'teal', name: 'Read', ai: 'Handwriting, amount, MICR and payee read twice by two different models.' },
  { icon: 'shield', accent: 'violet', name: 'Check', ai: 'Signature, stop-payment, positive pay and fraud score, each with a reason.' },
  { icon: 'layers', accent: 'amber', name: 'Decide', ai: 'Rules and AI together. Anything uncertain goes to a person.' },
  { icon: 'bolt', accent: 'rose', name: 'File', ai: 'Filed inside the window. Exactly once.' },
]
const BOLTED = ['A separate tool that runs after the real work', 'Results that nobody can trace to a decision', 'When the model is down, the process stops, or guesses', 'Audit and explanation added later, if at all']
const BUILT = ['AI at every step of the flow, not beside it', 'Every score has a reason and an audit record', 'When a model is down, items go to a person. Nothing is decided blindly', 'The deadline is guarded by design, not by hope']
const BARS = [
  { name: 'Cheque number', wrong: 3, caught: 3 },
  { name: 'Sort code', wrong: 4, caught: 4 },
  { name: 'Amount (30 tested)', wrong: 5, caught: 4 },
]

function CatchChart() {
  const unit = 40
  return (
    <svg viewBox="0 0 470 170" className="w-full h-auto" role="img" aria-label="Wrong reads caught by the second reader: cheque number 3 of 3, sort code 4 of 4, amount 4 of 5">
      {BARS.map((b, i) => {
        const y = 14 + i * 50
        return (
          <g key={b.name}>
            <text x="0" y={y + 14} fontSize="11.5" fill="#334155" fontWeight="600">{b.name}</text>
            <rect x="130" y={y} width={b.wrong * unit} height="22" rx="5" fill="#e2e8f0" />
            <rect x="130" y={y} width={b.caught * unit} height="22" rx="5" fill={ACCENTS.teal} />
            <text x={136 + b.wrong * unit} y={y + 15} fontSize="12" fill="#0f172a" fontWeight="700">{b.caught} of {b.wrong} caught</text>
          </g>
        )
      })}
      <text x="130" y="166" fontSize="10" fill="#94a3b8">each bar is the number of wrong reads in the test</text>
    </svg>
  )
}

export default function AIByDesign() {
  return (
    <section id="ai-by-design" className="bg-cream-50 py-20 px-6">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-12">
          <span className="inline-block text-xs font-semibold text-teal-600 tracking-widest uppercase mb-3">AI by design</span>
          <h2 className="text-3xl sm:text-4xl font-bold text-slate-900 mb-4">
            Not retrofitted. <span className="text-teal-500">Designed in from the first line.</span>
          </h2>
          <p className="text-slate-500 max-w-2xl mx-auto text-sm leading-relaxed">
            The flow, the deadline guard, the human review and the audit trail were all designed around AI doing the work, and around what happens when it cannot.
          </p>
        </div>

        <div className="grid md:grid-cols-2 gap-5 mb-8">
          <div className="rounded-2xl bg-white border border-dashed border-slate-300 p-6">
            <div className="text-xs font-semibold tracking-widest uppercase text-slate-400 mb-4">AI bolted on</div>
            <ul className="space-y-3">{BOLTED.map((t) => <li key={t} className="flex gap-3 text-sm text-slate-500"><DoubleBullet accent="#94a3b8" />{t}</li>)}</ul>
          </div>
          <div className="rounded-2xl bg-white border p-6 shadow-sm" style={{ borderColor: `${ACCENTS.teal}77` }}>
            <div className="text-xs font-semibold tracking-widest uppercase text-teal-600 mb-4">AI built in</div>
            <ul className="space-y-3">{BUILT.map((t) => <li key={t} className="flex gap-3 text-sm text-slate-800"><DoubleBullet accent="teal" />{t}</li>)}</ul>
          </div>
        </div>

        <div className="rounded-2xl bg-white border border-slate-200 p-6 mb-8">
          <div className="text-xs font-semibold tracking-widest uppercase text-slate-400 mb-4">One cheque, start to finish</div>
          <div className="grid sm:grid-cols-5 gap-3">
            {STAGES.map(({ icon, accent, name, ai }, i) => (
              <div key={name} className="relative rounded-xl bg-cream-50 border border-slate-200 p-4" style={{ borderTop: `3px solid ${ACCENTS[accent]}` }}>
                <div className="flex items-center gap-2 mb-2">
                  <Icon name={icon} color={ACCENTS[accent]} size={20} />
                  <span className="text-sm font-semibold text-slate-900">{i + 1}. {name}</span>
                </div>
                <p className="text-xs text-slate-500 leading-relaxed">{ai}</p>
              </div>
            ))}
          </div>
          <div className="mt-3 grid gap-2">
            <div className="rounded-lg px-4 py-2 text-xs font-medium text-center" style={{ border: `2px dashed ${ACCENTS.rose}88`, color: ACCENTS.rose }}>Deadline watchdog: files an emergency decision before the window closes, and stands the pipeline down</div>
            <div className="rounded-lg px-4 py-2 text-xs font-medium text-center" style={{ border: `2px dashed ${ACCENTS.sky}88`, color: ACCENTS.sky }}>Audit record at every step: what was read, what was decided, why, and by whom</div>
          </div>
        </div>

        <div className="grid md:grid-cols-2 gap-5">
          <div className="rounded-2xl bg-white border border-slate-200 p-6">
            <div className="text-xs font-semibold tracking-widest uppercase text-slate-400 mb-1">What a second reader catches</div>
            <p className="text-xs text-slate-500 mb-3">Every key field is read by two different models. When they disagree, a person decides.</p>
            <CatchChart />
            <p className="text-[11px] text-slate-400 mt-1 leading-relaxed">
              ASTRA internal test on 70 real cheque and draft images. About one correct read in eight was also sent to a person. Small sample; the true values were read by eye. A bank&rsquo;s own labelled set is needed to prove final accuracy.
            </p>
          </div>
          <div className="rounded-2xl bg-white border border-slate-200 p-6">
            <div className="text-xs font-semibold tracking-widest uppercase text-slate-400 mb-1">When the AI is gone entirely</div>
            <p className="text-xs text-slate-500 mb-4">The same 70 images, run with the AI models completely unavailable.</p>
            <div className="grid grid-cols-3 gap-3 text-center mb-4">
              {[['70 of 70', 'sent to a person', 'teal'], ['0', 'failed', 'sky'], ['0', 'decided automatically', 'violet']].map(([v, l, a]) => (
                <div key={l} className="rounded-xl bg-cream-50 border border-slate-200 py-4">
                  <div className="text-xl font-bold" style={{ color: ACCENTS[a] }}>{v}</div>
                  <div className="text-[11px] text-slate-500 px-1 leading-snug">{l}</div>
                </div>
              ))}
            </div>
            <p className="text-sm text-slate-700 leading-relaxed">
              This is what &ldquo;designed in&rdquo; means. A failure of the AI makes the system more careful, not more reckless.
            </p>
          </div>
        </div>
      </div>
    </section>
  )
}

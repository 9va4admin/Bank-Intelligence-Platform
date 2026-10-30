import { msg } from '../../shared/messages'
const PAIN_POINTS = [
  {
    icon: '⏱',
    title: msg('UI_PROBLEMSTATEMENT_THE_IET_CLOCK_NEVER_STOPS'),
    body: msg('UI_PROBLEMSTATEMENT_RBI_S_ITEM_EXPIRY_TIME'),
    color: 'border-red-200 bg-red-50',
    badgeColor: 'bg-red-100 text-red-700',
    badge: msg('UI_PROBLEMSTATEMENT_CTS_RISK'),
  },
  {
    icon: '📋',
    title: msg('UI_PROBLEMSTATEMENT_45_DAYS_TO_RESOLVE_ONE'),
    body: msg('UI_PROBLEMSTATEMENT_A_CUSTOMER_DISPUTES_A_FAILED'),
    color: 'border-orange-200 bg-orange-50',
    badgeColor: 'bg-orange-100 text-orange-700',
    badge: msg('UI_PROBLEMSTATEMENT_EJ_RISK'),
  },
  {
    icon: '🔀',
    title: msg('UI_PROBLEMSTATEMENT_5_OEM_FORMATS_ZERO_STANDARD'),
    body: msg('UI_PROBLEMSTATEMENT_NCR_DIEBOLD_WINCOR_HYOSUNG_AGS'),
    color: 'border-amber-200 bg-amber-50',
    badgeColor: 'bg-amber-100 text-amber-700',
    badge: msg('UI_PROBLEMSTATEMENT_EJ_COMPLEXITY'),
  },
  {
    icon: '🏦',
    title: msg('UI_PROBLEMSTATEMENT_INCUMBENTS_NEED_18_24_MONTHS'),
    body: msg('UI_PROBLEMSTATEMENT_LEGACY_CBS_VENDORS_TCS_BANCS'),
    color: 'border-violet-200 bg-violet-50',
    badgeColor: 'bg-violet-100 text-violet-700',
    badge: msg('UI_PROBLEMSTATEMENT_COMPETITIVE_GAP'),
  },
]

export default function ProblemStatement() {
  return (
    <section id="platform" className="bg-cream-100 py-20 px-6">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-14">
          <span className="inline-block text-xs font-semibold text-teal-600 tracking-widest uppercase mb-3">{msg('UI_PROBLEMSTATEMENT_THE_PROBLEM')}</span>
          <h2 className="text-3xl sm:text-4xl font-bold text-slate-900 mb-4">
           {msg('UI_PROBLEMSTATEMENT_TWO_OPERATIONS_TWO_UNSOLVED_PROBLEMS')}
            <span className="text-teal-500"> {msg('UI_PROBLEMSTATEMENT_ONE_PLATFORM')}</span>
          </h2>
          <p className="text-slate-500 max-w-2xl mx-auto text-sm leading-relaxed">
           {msg('UI_PROBLEMSTATEMENT_INDIA_PROCESSES_609_MILLION_CHEQUES')}
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
            <span className="text-xs font-semibold text-teal-400 tracking-widest uppercase">{msg('UI_PROBLEMSTATEMENT_ASTRA_S_APPROACH')}</span>
            <h3 className="text-xl font-bold mt-2 text-white">{msg('UI_PROBLEMSTATEMENT_NOT_JUST_AI')} <span style={{ color: '#1D9E75' }}>{msg('UI_PROBLEMSTATEMENT_AGENTIC_AI')}</span></h3>
            <p className="text-slate-400 text-sm mt-2 max-w-lg mx-auto">{msg('UI_PROBLEMSTATEMENT_THERE_IS_A_MEANINGFUL_DIFFERENCE')}</p>
          </div>
          <div className="grid sm:grid-cols-3 gap-4">
            {[
              {
                tier: 'AI',
                emoji: '🤖',
                verb: 'Predicts. Answers. Stops.',
                desc: msg('UI_PROBLEMSTATEMENT_OCR_EXTRACTION_FRAUD_SCORING_CONFIDE'),
                borderColor: 'border-slate-600',
                tagColor: 'text-slate-400',
              },
              {
                tier: 'AI Agents',
                emoji: '⚙️',
                verb: 'Reasons. Uses tools. Takes steps.',
                desc: msg('UI_PROBLEMSTATEMENT_MULTI_STEP_CHEQUE_PROCESSING_OCR'),
                borderColor: 'border-sky-400/50',
                tagColor: 'text-sky-400',
                highlight: true,
              },
              {
                tier: 'Agentic AI',
                emoji: '🎯',
                verb: 'Perceives. Decides. Acts. Terminates.',
                desc: msg('UI_PROBLEMSTATEMENT_IET_WATCHDOG_MONITORS_COUNTDOWN_DETE'),
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

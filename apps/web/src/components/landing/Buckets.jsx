import { useState } from 'react'
import { ACCENTS, DoubleBullet, Icon, IconTile } from './ui'

// Landing page copy is exempt from the message registry by decision (see CLAUDE.md, message taxonomy).
// Status words are honest: only CTS is the first product; PRAMAAN is with design partners; the rest are planned.
const BUCKETS = [
  {
    id: 'scale', icon: 'server', accent: 'teal',
    name: 'Speed and scale',
    line: 'Take the load off your core banking system',
    today: ['Every channel reads the CBS directly: balance, status, holds, signatures', 'Peaks such as clearing windows and salary days land on one database', 'Reports and reconciliation run on production, often overnight'],
    achieve: ['Serve most reads from a live working copy beside the CBS', 'Absorb peaks across two active data centres', 'Run reports and reconciliation without touching the CBS', 'Add capability without changing the core'],
    by: 'ASTRA data hub', status: 'Platform',
  },
  {
    id: 'clearing', icon: 'cheque', accent: 'sky',
    name: 'Clearing and payments',
    line: 'Never miss the RBI window',
    today: ['A missed item-expiry window means deemed approval, whatever the fraud risk', 'Handwriting, signatures and stop-payments checked by hand, under time pressure', 'Outward and sub-member routing handled in separate tools'],
    achieve: ['One AI agent per cheque, the whole batch decided in parallel', 'A watchdog that files before the deadline', 'Uncertain items go to a reviewer, never to an automatic return', 'Inward, outward and sub-member banks on one flow'],
    by: 'CTS', status: 'First product',
  },
  {
    id: 'fraud', icon: 'search', accent: 'rose',
    name: 'Fraud and mule defence',
    line: 'Find it before the loss',
    today: ['Rules that look at one account at a time', 'Mule accounts found after the money has moved', 'Alerts that do not say why'],
    achieve: ['Rank suspect accounts using live events across accounts', 'Extend cheque scoring to NEFT, UPI and NACH', 'Every score carries a plain reason and an audit record', 'A person decides. Agents never freeze an account on their own'],
    by: 'Fraud and mule detection', status: 'Planned',
  },
  {
    id: 'compliance', icon: 'shield', accent: 'violet',
    name: 'Compliance and regulators',
    line: 'One integration, every regulator, every deadline',
    today: ['Many regulators, many clocks, run on spreadsheets and email', 'Late or rejected filings carry penalties', 'Audit evidence collected by hand'],
    achieve: ['One calendar with a clock per regulator', 'Filings pre-filled and pre-checked, rejections corrected', 'One-click maker-checker approval for the critical ones', 'Timestamped, tamper-evident proof of every filing'],
    by: 'PRAMAAN', status: 'Design partners',
  },
  {
    id: 'kyc', icon: 'idcard', accent: 'amber',
    name: 'KYC and onboarding',
    line: 'Less rework, faster accounts',
    today: ['Documents keyed and checked by hand', 'KYC expiry noticed late', 'Mismatches found at review, not at intake'],
    achieve: ['Read documents and check them against records', 'Flag mismatches and expiring KYC early', 'Hand the reviewer a pre-filled file', 'A person approves. Nothing is auto-approved'],
    by: 'KYC automation', status: 'Planned',
  },
  {
    id: 'growth', icon: 'gift', accent: 'teal',
    name: 'Growth and customer delight',
    line: 'The right offer, and a call before the complaint',
    today: ['Offers are generic', 'A failed payment or returned cheque becomes a complaint', 'Branch staff lack a clear view of the customer'],
    achieve: ['Match steady behaviour to the right product and time', 'Trigger a follow-up when a customer has a bad experience', 'Give relationship managers a short, reasoned list', 'Only with the customer’s consent'],
    by: 'Customer insights', status: 'Planned',
  },
  {
    id: 'ops', icon: 'link', accent: 'sky',
    name: 'Operations and reconciliation',
    line: 'Close the books without the chase',
    today: ['Reconciliation across cheques, ATM, NACH and UPI done by hand', 'Breaks found days later', 'Dispute evidence scattered across systems'],
    achieve: ['Match every instrument from one place', 'Surface breaks the same day, with the evidence attached', 'Pull ATM journal evidence for disputes', 'Free staff for exceptions only'],
    by: 'Reconciliation and ATM journal', status: 'Planned',
  },
]

const PRINCIPLES = [
  ['server', 'teal', 'On premises', 'Everything runs inside the bank. No customer data leaves.'],
  ['search', 'sky', 'Explained', 'Every automated score has a reason and an audit record.'],
  ['users', 'violet', 'Humans decide', 'Agents recommend. People or fixed rules decide anything that moves money.'],
  ['shield', 'amber', 'Consent first', 'Personal insights and offers respect what each customer agreed to.'],
]

export default function Buckets() {
  const [active, setActive] = useState(BUCKETS[0].id)
  const b = BUCKETS.find((x) => x.id === active)
  const c = ACCENTS[b.accent]

  return (
    <section id="platform" className="bg-cream-50 py-12 sm:py-14 px-6">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-8">
          <span className="inline-block text-xs font-semibold text-teal-600 tracking-widest uppercase mb-3">What ASTRA can do for a bank</span>
          <h2 className="text-3xl sm:text-4xl font-bold text-slate-900 mb-4">
            Pick a problem. <span className="text-teal-500">See what becomes possible.</span>
          </h2>
          <p className="text-slate-500 max-w-2xl mx-auto text-sm leading-relaxed">
            Your core banking system stays as it is. ASTRA sits beside it and takes on the work it was never built for.
          </p>
        </div>

        <div className="flex flex-wrap justify-center gap-2 mb-6" role="tablist" aria-label="Problem areas">
          {BUCKETS.map((x) => {
            const on = x.id === active
            const col = ACCENTS[x.accent]
            return (
              <button
                key={x.id}
                role="tab"
                aria-selected={on}
                onClick={() => setActive(x.id)}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium border transition-all bg-white"
                style={on ? { borderColor: col, color: '#0e1a14', boxShadow: `0 4px 14px ${col}33`, background: `${col}12` } : { borderColor: '#e2e8f0', color: '#475569' }}
              >
                <Icon name={x.icon} color={col} size={16} />
                {x.name}
              </button>
            )
          })}
        </div>

        <div role="tabpanel" className="bg-white rounded-2xl border overflow-hidden shadow-sm" style={{ borderColor: `${c}55` }}>
          <div className="h-1" style={{ background: `linear-gradient(90deg, ${c}, ${c}22)` }} />
          <div className="px-6 sm:px-8 py-6 border-b border-slate-100 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div className="flex items-center gap-4">
              <IconTile name={b.icon} accent={b.accent} size={48} />
              <div>
                <h3 className="text-xl font-bold text-slate-900">{b.name}</h3>
                <p className="text-sm" style={{ color: c }}>{b.line}</p>
              </div>
            </div>
            <div className="text-xs text-slate-500">
              Delivered by <strong className="text-slate-800">{b.by}</strong>
              <span className="ml-2 inline-block px-2.5 py-0.5 rounded-full font-semibold" style={{ background: `${c}1A`, color: '#334155' }}>{b.status}</span>
            </div>
          </div>
          <div className="grid md:grid-cols-2">
            <div className="p-6 sm:p-8 bg-cream-50 md:border-r border-dashed border-slate-300">
              <div className="text-xs font-semibold tracking-widest uppercase text-slate-400 mb-4">Today</div>
              <ul className="space-y-3.5">
                {b.today.map((t) => (
                  <li key={t} className="text-sm text-slate-600 leading-relaxed flex gap-3"><DoubleBullet accent="#94a3b8" />{t}</li>
                ))}
              </ul>
            </div>
            <div className="p-6 sm:p-8">
              <div className="text-xs font-semibold tracking-widest uppercase mb-4" style={{ color: c }}>With ASTRA</div>
              <ul className="space-y-3.5">
                {b.achieve.map((t) => (
                  <li key={t} className="text-sm text-slate-800 leading-relaxed flex gap-3"><DoubleBullet accent={b.accent} />{t}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>

        <div className="mt-6 grid sm:grid-cols-2 lg:grid-cols-4 gap-3 text-xs">
          {PRINCIPLES.map(([icon, accent, t, d]) => (
            <div key={t} className="rounded-xl bg-white border border-slate-200 p-4 flex gap-3">
              <IconTile name={icon} accent={accent} size={34} />
              <div>
                <div className="font-semibold text-slate-900 mb-0.5">{t}</div>
                <p className="text-slate-500 leading-relaxed">{d}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

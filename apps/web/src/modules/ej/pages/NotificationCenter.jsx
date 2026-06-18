import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Bell, Monitor, MessageSquare, Mail, Lock, CheckCircle2, AlertCircle, ChevronRight } from 'lucide-react'
import { BRE_RULES } from '../hooks/useBRERules'

const ROLES_ORDER = ['branch_manager','zonal_manager','regional_head','national_head','ops_reviewer','compliance_officer']
const ROLE_LABEL = {
  branch_manager:'Branch Manager', zonal_manager:'Zonal Manager', regional_head:'Regional Head',
  national_head:'National Head', ops_reviewer:'Ops Reviewer', compliance_officer:'Compliance Officer',
}

function buildMatrix() {
  const matrix = {}
  ROLES_ORDER.forEach(r => { matrix[r] = { onscreen:new Set(), whatsapp:new Set(), email:new Set(), digest:new Set() } })
  BRE_RULES.forEach(rule => {
    rule.notify_roles.forEach(r => {
      const ch = rule.channels[r]
      if (!ch || !matrix[r]) return
      if (ch.onscreen) matrix[r].onscreen.add(rule.severity)
      if (ch.whatsapp) matrix[r].whatsapp.add(rule.severity)
      if (ch.email)    matrix[r].email.add(rule.severity)
    })
  })
  matrix['branch_manager'].digest.add('W')
  matrix['zonal_manager'].digest.add('W')
  matrix['regional_head'].digest.add('W'); matrix['regional_head'].digest.add('M')
  matrix['national_head'].digest.add('W'); matrix['national_head'].digest.add('M')
  matrix['ops_reviewer'].digest.add('W')
  matrix['compliance_officer'].digest.add('M')
  return matrix
}

const MATRIX = buildMatrix()

const SEV_PILL = {
  CRITICAL: 'bg-red-500/20 text-red-300 border border-red-500/30',
  HIGH:     'bg-amber-500/20 text-amber-300 border border-amber-500/30',
  MEDIUM:   'bg-yellow-500/20 text-yellow-300 border border-yellow-500/30',
  LOW:      'bg-slate-500/20 text-slate-400 border border-slate-400/20',
}
const DIGEST_PILL = 'bg-violet-500/20 text-violet-300 border border-violet-500/30'

const DELIVERY_LOG = [
  { time:'10:47:03', rule:'Cash Not Dispensed',   atm:'ATM-MUM-004', channel:'WhatsApp', role:'ops_reviewer',   status:'Delivered' },
  { time:'10:47:03', rule:'Cash Not Dispensed',   atm:'ATM-MUM-004', channel:'WhatsApp', role:'zonal_manager',  status:'Delivered' },
  { time:'10:47:04', rule:'Cash Not Dispensed',   atm:'ATM-MUM-004', channel:'Email',    role:'regional_head',  status:'Delivered' },
  { time:'10:32:11', rule:'Cash Near Empty',       atm:'ATM-MUM-012', channel:'WhatsApp', role:'branch_manager', status:'Delivered' },
  { time:'10:32:12', rule:'Cash Near Empty',       atm:'ATM-MUM-012', channel:'Email',    role:'zonal_manager',  status:'Delivered' },
  { time:'10:15:55', rule:'Card Retention',        atm:'ATM-BLR-002', channel:'Email',    role:'ops_reviewer',   status:'Delivered' },
  { time:'09:58:20', rule:'High Txn Velocity',     atm:'ATM-DEL-007', channel:'Email',    role:'fraud_analyst',  status:'Delivered' },
  { time:'09:45:02', rule:'Comm Failure >15m',     atm:'ATM-PNQ-011', channel:'Email',    role:'branch_manager', status:'Failed', retry:true },
  { time:'09:45:18', rule:'Comm Failure >15m',     atm:'ATM-PNQ-011', channel:'Email',    role:'branch_manager', status:'Delivered', note:'Retry #1' },
  { time:'09:22:44', rule:'EJ Parse Failure',      atm:'ATM-CHN-003', channel:'OnScreen', role:'ml_engineer',    status:'Delivered' },
]

const SEV_ORDER = ['CRITICAL','HIGH','MEDIUM','LOW']

function MatrixTab() {
  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm min-w-[680px]">
          <thead>
            <tr className="border-b border-white/10">
              <th className="text-left text-xs text-slate-500 pb-3 pr-6 font-normal w-36">Role</th>
              {[
                { label:'On-Screen', icon:<Monitor size={14}/> },
                { label:'WhatsApp',  icon:<MessageSquare size={14}/> },
                { label:'Email',     icon:<Mail size={14}/> },
                { label:'Digest',    icon:<Bell size={14}/> },
              ].map(col => (
                <th key={col.label} className="text-center text-xs text-slate-500 pb-3 px-4 font-normal">
                  <div className="flex flex-col items-center gap-1">{col.icon}{col.label}</div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ROLES_ORDER.map(r => {
              const m = MATRIX[r]
              return (
                <tr key={r} className="border-b border-white/5 hover:bg-white/2 transition-colors">
                  <td className="py-3 pr-6 text-sm font-medium text-slate-200">{ROLE_LABEL[r]}</td>
                  {['onscreen','whatsapp','email'].map(ch => (
                    <td key={ch} className="py-3 px-4 text-center">
                      <div className="flex flex-wrap justify-center gap-1">
                        {SEV_ORDER.filter(s => m[ch].has(s)).map(s => (
                          <span key={s} className={`text-[10px] px-1.5 py-0.5 rounded font-bold ${SEV_PILL[s]}`}>{s[0]}</span>
                        ))}
                        {m[ch].size === 0 && <span className="text-slate-700 text-xs">—</span>}
                      </div>
                    </td>
                  ))}
                  <td className="py-3 px-4 text-center">
                    <div className="flex flex-wrap justify-center gap-1">
                      {[...m.digest].map(d => (
                        <span key={d} className={`text-[10px] px-1.5 py-0.5 rounded font-bold ${DIGEST_PILL}`}>{d === 'W' ? 'Weekly' : 'Monthly'}</span>
                      ))}
                      {m.digest.size === 0 && <span className="text-slate-700 text-xs">—</span>}
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Legend */}
      <div className="mt-5 flex flex-wrap gap-4 text-xs text-slate-500 border-t border-white/5 pt-4">
        {SEV_ORDER.map(s => (
          <span key={s} className="flex items-center gap-1">
            <span className={`px-1.5 py-0.5 rounded font-bold ${SEV_PILL[s]}`}>{s[0]}</span> {s}
          </span>
        ))}
        <span className="flex items-center gap-1"><Lock size={10}/> Mandatory — cannot be disabled by user preference</span>
        <span className="flex items-center gap-1"><span className={`px-1.5 py-0.5 rounded font-bold ${DIGEST_PILL} text-[10px]`}>W</span> Weekly digest</span>
        <span className="flex items-center gap-1"><span className={`px-1.5 py-0.5 rounded font-bold ${DIGEST_PILL} text-[10px]`}>M</span> Monthly report</span>
      </div>

      {/* Escalation chain */}
      <div className="mt-6">
        <div className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">
          CRITICAL Escalation Chain — example: Cash Not Dispensed
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {[
            { role:'Branch Manager',  channels:'OnScreen · WhatsApp · Email', t:'Immediate', esc:false },
            { role:'Zonal Manager',   channels:'OnScreen · WhatsApp · Email', t:'Immediate', esc:false },
            { role:'Ops Reviewer',    channels:'OnScreen · WhatsApp · Email', t:'Immediate', esc:false },
            { role:'National Head',   channels:'WhatsApp · Email',            t:'unACKed 10m', esc:true },
          ].map((step, i) => (
            <div key={i} className="flex items-center gap-2">
              {i > 0 && <ChevronRight size={14} className="text-slate-600 flex-shrink-0"/>}
              <div className={`px-3 py-2.5 rounded-xl border text-xs flex-shrink-0 ${
                step.esc ? 'border-amber-500/40 bg-amber-500/10' : 'border-white/10 bg-white/5'
              }`}>
                <div className="font-medium text-slate-200">{step.role}</div>
                <div className="text-slate-500 text-[10px] mt-0.5">{step.channels}</div>
                <div className={`text-[10px] mt-0.5 ${step.esc ? 'text-amber-400' : 'text-slate-600'}`}>
                  {step.esc ? '↑ ' : ''}{step.t}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function ChannelHealthTab() {
  const channels = [
    {
      name: 'On-Screen (Live)',
      icon: Monitor,
      color: 'text-cyan-400',
      status: 'LIVE',
      statusCls: 'text-emerald-400 bg-emerald-400/10 border-emerald-400/20',
      metrics: [
        { label:'Delivery Latency', val:'<100ms' },
        { label:'Active Sessions',  val:'3' },
        { label:'Alarms Shown Today', val:'47' },
        { label:'ACK Rate',         val:'91%' },
      ],
      note: 'Real-time updates. No delivery guarantee for offline users — email fallback activates automatically after 2 minutes undelivered.',
    },
    {
      name: 'WhatsApp Business API (Meta)',
      icon: MessageSquare,
      color: 'text-emerald-400',
      status: 'OPERATIONAL',
      statusCls: 'text-emerald-400 bg-emerald-400/10 border-emerald-400/20',
      metrics: [
        { label:'Templates Approved', val:'4' },
        { label:'Daily Rate Limit',   val:'1,000 msgs' },
        { label:'Used Today',         val:'23 msgs' },
        { label:'Delivery Rate',      val:'99.1%' },
      ],
      note: 'CRITICAL and mandatory HIGH only. Abuse prevention: max 3 msgs/ATM/hour per role. Templates pre-approved by Meta.',
    },
    {
      name: 'Email (Postal SMTP)',
      icon: Mail,
      color: 'text-violet-400',
      status: 'OPERATIONAL',
      statusCls: 'text-emerald-400 bg-emerald-400/10 border-emerald-400/20',
      metrics: [
        { label:'Queue Depth',    val:'0' },
        { label:'Sent Today',     val:'147' },
        { label:'Bounce Rate',    val:'0.2%' },
        { label:'Avg Delivery',   val:'4.2s' },
      ],
      note: 'Self-hosted Postal MTA — zero cloud relay. All email stays on-premises. Digests queued at 08:55 for 09:00 delivery.',
    },
  ]

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {channels.map(ch => {
          const Icon = ch.icon
          return (
            <div key={ch.name} className="bg-white/5 rounded-xl border border-white/5 p-5">
              <div className="flex items-center justify-between mb-3">
                <Icon size={22} className={ch.color}/>
                <span className={`text-xs px-2 py-0.5 rounded border font-medium ${ch.statusCls}`}>● {ch.status}</span>
              </div>
              <div className="text-sm font-semibold text-white mb-4">{ch.name}</div>
              <div className="space-y-2 mb-4">
                {ch.metrics.map(m => (
                  <div key={m.label} className="flex justify-between text-xs">
                    <span className="text-slate-400">{m.label}</span>
                    <span className="text-white font-medium">{m.val}</span>
                  </div>
                ))}
              </div>
              <p className="text-xs text-slate-500 leading-relaxed">{ch.note}</p>
            </div>
          )
        })}
      </div>
      <div className="bg-slate-800/30 border border-white/5 rounded-xl px-5 py-3 text-xs text-slate-500 flex items-start gap-2">
        <AlertCircle size={13} className="text-slate-600 mt-0.5 flex-shrink-0"/>
        <span>SMS is not in the ASTRA notification stack — WhatsApp Business API replaces SMS for all time-sensitive alerts. Banks with legacy SMS requirements can add a custom channel plugin via the notification-service dispatcher (Kafka consumer pattern).</span>
      </div>
    </div>
  )
}

function DeliveryLogTab() {
  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm min-w-[640px]">
          <thead>
            <tr className="text-left text-xs text-slate-500 border-b border-white/5">
              {['Time','Rule','ATM','Channel','Recipient Role','Status'].map(h => (
                <th key={h} className="pb-2 pr-4 font-normal">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {DELIVERY_LOG.map((entry, i) => (
              <tr key={i} className="border-b border-white/5 hover:bg-white/2 transition-colors">
                <td className="py-2 pr-4 font-mono text-xs text-slate-400">{entry.time}</td>
                <td className="py-2 pr-4 text-xs text-slate-200">{entry.rule}</td>
                <td className="py-2 pr-4 font-mono text-xs text-cyan-400">{entry.atm}</td>
                <td className="py-2 pr-4 text-xs text-slate-300">
                  <span className="flex items-center gap-1">
                    {entry.channel === 'WhatsApp' && <MessageSquare size={11} className="text-emerald-400"/>}
                    {entry.channel === 'Email'    && <Mail size={11} className="text-violet-400"/>}
                    {entry.channel === 'OnScreen' && <Monitor size={11} className="text-cyan-400"/>}
                    {entry.channel}
                  </span>
                </td>
                <td className="py-2 pr-4 text-xs text-slate-400 capitalize">{entry.role.replace(/_/g,' ')}</td>
                <td className="py-2 text-xs">
                  {entry.status === 'Delivered'
                    ? <span className="flex items-center gap-1 text-emerald-400">
                        <CheckCircle2 size={11}/> Delivered
                        {entry.note && <span className="text-slate-500 ml-1">({entry.note})</span>}
                      </span>
                    : <span className="flex items-center gap-1 text-red-400">
                        <AlertCircle size={11}/> Failed
                        {entry.retry && <span className="text-amber-400 ml-1">→ retry queued</span>}
                      </span>
                  }
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 text-xs text-slate-600">
        Showing last 10 delivery events · No PII in log · Recipients identified by role only · Full log in Immudb audit trail
      </div>
    </div>
  )
}

export default function NotificationCenter() {
  const [tab, setTab] = useState('matrix')

  return (
    <div className="min-h-screen bg-[#020817] text-white flex flex-col">
      <nav className="flex items-center justify-between px-6 py-3 border-b border-white/5 bg-black/30">
        <Link to="/" className="text-xs text-slate-400 hover:text-white">← ASTRA Platform</Link>
        <div className="flex items-center gap-1 text-xs flex-wrap justify-center">
          <Link to="/ej" className="px-3 py-1.5 rounded text-slate-400 hover:text-white">Command Center</Link>
          <Link to="/ej/incidents" className="px-3 py-1.5 rounded text-slate-400 hover:text-white">Incidents</Link>
          <Link to="/ej/portal" className="px-3 py-1.5 rounded text-slate-400 hover:text-white">Manager Portal</Link>
          <Link to="/ej/bre" className="px-3 py-1.5 rounded text-slate-400 hover:text-white">BRE Policy</Link>
          <span className="px-3 py-1.5 rounded bg-violet-600/20 text-violet-300 font-medium border border-violet-500/30">Notifications</span>
        </div>
        <Link to="/cts" className="text-xs text-slate-400 hover:text-white">CTS →</Link>
      </nav>

      <div className="max-w-7xl w-full mx-auto px-6 py-6 flex-1 space-y-6">
        <div>
          <h1 className="text-xl font-bold flex items-center gap-2">
            <Bell size={20} className="text-violet-400"/> Notification Center
          </h1>
          <p className="text-xs text-slate-400 mt-0.5">Role × channel matrix · Channel health · Delivery log</p>
        </div>

        <div className="flex gap-1 border-b border-white/5">
          {[['matrix','Notification Matrix'],['health','Channel Health'],['log','Delivery Log']].map(([id,label]) => (
            <button key={id} onClick={() => setTab(id)}
              className={`px-5 py-2.5 text-sm transition-colors border-b-2 -mb-px ${
                tab === id ? 'border-violet-500 text-violet-300' : 'border-transparent text-slate-400 hover:text-white'
              }`}>
              {label}
            </button>
          ))}
        </div>

        <div className="bg-white/5 rounded-xl border border-white/5 p-6">
          {tab === 'matrix' && <MatrixTab/>}
          {tab === 'health' && <ChannelHealthTab/>}
          {tab === 'log'    && <DeliveryLogTab/>}
        </div>
      </div>
    </div>
  )
}

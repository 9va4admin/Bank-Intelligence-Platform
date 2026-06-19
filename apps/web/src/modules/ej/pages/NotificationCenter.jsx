import { useState } from 'react'
import { Link } from 'react-router-dom'
import EJShell from '../layout/EJShell'
import { Bell, Monitor, MessageSquare, Mail, Lock, CheckCircle2, AlertCircle, Clock, Activity, ChevronRight } from 'lucide-react'
import { BRE_RULES } from '../hooks/useBRERules'

const ROLES_ORDER = ['branch_manager','zonal_manager','regional_head','national_head','ops_reviewer','compliance_officer']
const ROLE_LABEL = { branch_manager:'Branch Manager', zonal_manager:'Zonal Manager', regional_head:'Regional Head', national_head:'National Head', ops_reviewer:'Ops Reviewer', compliance_officer:'Compliance Officer', fraud_analyst:'Fraud Analyst' }

function buildMatrix() {
  const matrix = {}
  ROLES_ORDER.forEach(r => { matrix[r] = { onscreen:new Set(), whatsapp:new Set(), email:new Set(), digest:new Set() } })

  BRE_RULES.forEach(rule => {
    rule.notify_roles.forEach(r => {
      const ch = rule.channels[r]
      if (!ch) return
      if (ch.onscreen) matrix[r]?.onscreen.add(rule.severity)
      if (ch.whatsapp) matrix[r]?.whatsapp.add(rule.severity)
      if (ch.email) matrix[r]?.email.add(rule.severity)
    })
  })

  matrix['branch_manager']?.digest.add('WEEKLY')
  matrix['zonal_manager']?.digest.add('WEEKLY')
  matrix['regional_head']?.digest.add('WEEKLY')
  matrix['regional_head']?.digest.add('MONTHLY')
  matrix['national_head']?.digest.add('WEEKLY')
  matrix['national_head']?.digest.add('MONTHLY')
  matrix['ops_reviewer']?.digest.add('WEEKLY')
  matrix['compliance_officer']?.digest.add('MONTHLY')

  return matrix
}

const MATRIX = buildMatrix()

const SEV_PILL = { CRITICAL:'bg-red-500/20 text-red-300 border border-red-500/30', HIGH:'bg-amber-500/20 text-amber-300 border border-amber-500/30', MEDIUM:'bg-yellow-500/20 text-yellow-300 border border-yellow-500/30', LOW:'bg-slate-500/20 text-slate-300 border border-slate-400/20' }

const DELIVERY_LOG = [
  { time:'10:47:03', rule:'Cash Not Dispensed', atm:'ATM-MUM-004', channel:'WhatsApp', role:'ops_reviewer', status:'Delivered' },
  { time:'10:47:03', rule:'Cash Not Dispensed', atm:'ATM-MUM-004', channel:'WhatsApp', role:'zonal_manager', status:'Delivered' },
  { time:'10:47:04', rule:'Cash Not Dispensed', atm:'ATM-MUM-004', channel:'Email', role:'regional_head', status:'Delivered' },
  { time:'10:32:11', rule:'Cash Near Empty', atm:'ATM-MUM-012', channel:'WhatsApp', role:'branch_manager', status:'Delivered' },
  { time:'10:32:12', rule:'Cash Near Empty', atm:'ATM-MUM-012', channel:'Email', role:'zonal_manager', status:'Delivered' },
  { time:'10:15:55', rule:'Card Retention', atm:'ATM-BLR-002', channel:'Email', role:'ops_reviewer', status:'Delivered' },
  { time:'09:58:20', rule:'High Txn Velocity', atm:'ATM-DEL-007', channel:'Email', role:'fraud_analyst', status:'Delivered' },
  { time:'09:45:02', rule:'Comm Failure >15m', atm:'ATM-PNQ-011', channel:'Email', role:'branch_manager', status:'Failed', retry:true },
  { time:'09:45:18', rule:'Comm Failure >15m', atm:'ATM-PNQ-011', channel:'Email', role:'branch_manager', status:'Delivered', note:'Retry #1' },
  { time:'09:22:44', rule:'EJ Parse Failure', atm:'ATM-CHN-003', channel:'OnScreen', role:'ml_engineer', status:'Delivered' },
]

function MatrixTab() {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm min-w-[700px]">
        <thead>
          <tr className="border-b border-white/10">
            <th className="text-left text-xs text-slate-500 pb-3 pr-4 font-normal">Role</th>
            <th className="text-center text-xs text-slate-500 pb-3 px-3 font-normal">
              <div className="flex flex-col items-center gap-1"><Monitor size={14}/> On-Screen</div>
            </th>
            <th className="text-center text-xs text-slate-500 pb-3 px-3 font-normal">
              <div className="flex flex-col items-center gap-1"><MessageSquare size={14}/> WhatsApp</div>
            </th>
            <th className="text-center text-xs text-slate-500 pb-3 px-3 font-normal">
              <div className="flex flex-col items-center gap-1"><Mail size={14}/> Email</div>
            </th>
            <th className="text-center text-xs text-slate-500 pb-3 px-3 font-normal">
              <div className="flex flex-col items-center gap-1"><Bell size={14}/> Digest</div>
            </th>
          </tr>
        </thead>
        <tbody>
          {ROLES_ORDER.map(r => {
            const m = MATRIX[r]
            return (
              <tr key={r} className="border-b border-white/5">
                <td className="py-3 pr-4">
                  <div className="text-sm font-medium text-slate-200">{ROLE_LABEL[r]}</div>
                </td>
                {['onscreen','whatsapp','email'].map(ch => (
                  <td key={ch} className="py-3 px-3 text-center">
                    <div className="flex flex-wrap justify-center gap-1">
                      {['CRITICAL','HIGH','MEDIUM','LOW'].filter(s => m[ch].has(s)).map(s => (
                        <span key={s} className={`text-xs px-1.5 py-0.5 rounded font-medium ${SEV_PILL[s]}`}>{s[0]}</span>
                      ))}
                      {m[ch].size === 0 && <span className="text-slate-600 text-xs">—</span>}
                    </div>
                  </td>
                ))}
                <td className="py-3 px-3 text-center">
                  <div className="flex flex-wrap justify-center gap-1">
                    {[...m.digest].map(d => (
                      <span key={d} className="text-xs px-1.5 py-0.5 rounded bg-violet-500/20 text-violet-300 border border-violet-500/30">{d[0]}</span>
                    ))}
                    {m.digest.size === 0 && <span className="text-slate-600 text-xs">—</span>}
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>

      <div className="mt-4 flex flex-wrap gap-4 text-xs text-slate-500">
        <span className="flex items-center gap-1"><span className={`px-1.5 py-0.5 rounded ${SEV_PILL.CRITICAL}`}>C</span> CRITICAL</span>
        <span className="flex items-center gap-1"><span className={`px-1.5 py-0.5 rounded ${SEV_PILL.HIGH}`}>H</span> HIGH</span>
        <span className="flex items-center gap-1"><span className={`px-1.5 py-0.5 rounded ${SEV_PILL.MEDIUM}`}>M</span> MEDIUM</span>
        <span className="flex items-center gap-1"><span className={`px-1.5 py-0.5 rounded ${SEV_PILL.LOW}`}>L</span> LOW</span>
        <span className="flex items-center gap-1"><span className="px-1.5 py-0.5 rounded bg-violet-500/20 text-violet-300 border border-violet-500/30">W</span> Weekly Digest</span>
        <span className="flex items-center gap-1"><span className="px-1.5 py-0.5 rounded bg-violet-500/20 text-violet-300 border border-violet-500/30">M</span> Monthly Report</span>
        <span className="flex items-center gap-1"><Lock size={10}/> Mandatory (cannot be opted out)</span>
      </div>

      <div className="mt-6">
        <div className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">CRITICAL Rule Escalation Chain (example: Cash Not Dispensed)</div>
        <div className="flex items-center gap-2 flex-wrap">
          {[
            { role:'Branch Manager', channels:['OnScreen','WhatsApp','Email'], t:'0m' },
            { role:'Zonal Manager',  channels:['OnScreen','WhatsApp','Email'], t:'0m' },
            { role:'Ops Reviewer',   channels:['OnScreen','WhatsApp','Email'], t:'0m' },
            { role:'National Head',  channels:['WhatsApp','Email'],            t:'↑ if unACKed 10m', escalation:true },
          ].map((step, i) => (
            <div key={i} className="flex items-center gap-2">
              {i > 0 && <ChevronRight size={14} className="text-slate-600"/>}
              <div className={`px-3 py-2 rounded-xl border text-xs ${step.escalation ? 'border-amber-500/40 bg-amber-500/10' : 'border-white/10 bg-white/5'}`}>
                <div className="font-medium text-slate-200">{step.role}</div>
                <div className="text-slate-500">{step.channels.join(' · ')}</div>
                {step.escalation && <div className="text-amber-400 text-xs mt-0.5">{step.t}</div>}
                {!step.escalation && <div className="text-slate-600">{step.t}</div>}
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
      statusCls: 'text-emerald-400 bg-emerald-400/10',
      metrics: [
        { label:'Delivery Latency', val:'<100ms' },
        { label:'Active Sessions', val:'3' },
        { label:'Alarms Shown Today', val:'47' },
        { label:'ACK Rate', val:'91%' },
      ],
      note: 'Real-time updates via WebSocket. No delivery guarantee for offline users — email fallback activates automatically.',
    },
    {
      name: 'WhatsApp Business API (Meta)',
      icon: MessageSquare,
      color: 'text-emerald-400',
      status: 'OPERATIONAL',
      statusCls: 'text-emerald-400 bg-emerald-400/10',
      metrics: [
        { label:'Templates Approved', val:'4' },
        { label:'Daily Rate Limit', val:'1,000 msgs' },
        { label:'Used Today', val:'23 msgs' },
        { label:'Delivery Rate', val:'99.1%' },
      ],
      note: 'Only CRITICAL and mandatory HIGH alerts. Abuse prevention: max 3 WhatsApp msgs/ATM/hour per role.',
    },
    {
      name: 'Email (Postal SMTP)',
      icon: Mail,
      color: 'text-violet-400',
      status: 'OPERATIONAL',
      statusCls: 'text-emerald-400 bg-emerald-400/10',
      metrics: [
        { label:'Queue Depth', val:'0' },
        { label:'Sent Today', val:'147' },
        { label:'Bounce Rate', val:'0.2%' },
        { label:'Avg Delivery', val:'4.2s' },
      ],
      note: 'Self-hosted Postal MTA. All email stays on-premises — zero cloud relay. Weekly/monthly digests queued at 08:55 for 09:00 delivery.',
    },
  ]

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {channels.map(ch => {
          const Icon = ch.icon
          return (
            <div key={ch.name} className="bg-white/5 rounded-xl border border-white/5 p-5">
              <div className="flex items-center justify-between mb-3">
                <Icon size={20} className={ch.color}/>
                <span className={`text-xs px-2 py-0.5 rounded font-medium ${ch.statusCls}`}>● {ch.status}</span>
              </div>
              <div className="text-sm font-semibold text-white mb-3">{ch.name}</div>
              <div className="space-y-2 mb-3">
                {ch.metrics.map(m => (
                  <div key={m.label} className="flex justify-between text-xs">
                    <span className="text-slate-400">{m.label}</span>
                    <span className="text-white font-medium">{m.val}</span>
                  </div>
                ))}
              </div>
              <p className="text-xs text-slate-500">{ch.note}</p>
            </div>
          )
        })}
      </div>
      <div className="bg-slate-800/30 border border-white/5 rounded-xl px-5 py-3 text-xs text-slate-500 flex items-center gap-2">
        <AlertCircle size={13} className="text-slate-600"/>
        SMS is not in the ASTRA notification stack — WhatsApp Business API replaces SMS for all time-sensitive alerts. Banks with legacy SMS integrations can add a custom channel plugin via the notification-service dispatcher.
      </div>
    </div>
  )
}

function DeliveryLogTab() {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-slate-500 border-b border-white/5">
            <th className="pb-2 pr-4">Time</th>
            <th className="pb-2 pr-4">Rule</th>
            <th className="pb-2 pr-4">ATM</th>
            <th className="pb-2 pr-4">Channel</th>
            <th className="pb-2 pr-4">Recipient Role</th>
            <th className="pb-2">Status</th>
          </tr>
        </thead>
        <tbody>
          {DELIVERY_LOG.map((entry, i) => (
            <tr key={i} className="border-b border-white/5">
              <td className="py-2 pr-4 font-mono text-xs text-slate-400">{entry.time}</td>
              <td className="py-2 pr-4 text-xs text-slate-200">{entry.rule}</td>
              <td className="py-2 pr-4 font-mono text-xs text-cyan-400">{entry.atm}</td>
              <td className="py-2 pr-4 text-xs text-slate-300">
                <span className="flex items-center gap-1">
                  {entry.channel === 'WhatsApp' && <MessageSquare size={11} className="text-emerald-400"/>}
                  {entry.channel === 'Email' && <Mail size={11} className="text-violet-400"/>}
                  {entry.channel === 'OnScreen' && <Monitor size={11} className="text-cyan-400"/>}
                  {entry.channel}
                </span>
              </td>
              <td className="py-2 pr-4 text-xs text-slate-400 capitalize">{(entry.role||'').replace('_',' ')}</td>
              <td className="py-2 text-xs">
                {entry.status === 'Delivered'
                  ? <span className="flex items-center gap-1 text-emerald-400"><CheckCircle2 size={11}/> Delivered {entry.note && <span className="text-slate-500">({entry.note})</span>}</span>
                  : <span className="flex items-center gap-1 text-red-400"><AlertCircle size={11}/> Failed {entry.retry && <span className="text-amber-400">→ retry</span>}</span>
                }
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-3 text-xs text-slate-600">Showing last 10 delivery events · No PII in delivery log · Recipient identified by role only</div>
    </div>
  )
}

export default function NotificationCenter() {
  const [tab, setTab] = useState('matrix')

  return (
    <EJShell><div className="bg-[#020817] text-white flex flex-col">
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
          <h1 className="text-xl font-bold flex items-center gap-2"><Bell size={20} className="text-violet-400"/> Notification Center</h1>
          <p className="text-xs text-slate-400 mt-0.5">Role × channel matrix · Channel health · Delivery log</p>
        </div>

        <div className="flex gap-1 border-b border-white/5">
          {[['matrix','Notification Matrix'],['health','Channel Health'],['log','Delivery Log']].map(([id,label]) => (
            <button key={id} onClick={() => setTab(id)}
              className={`px-5 py-2.5 text-sm transition-colors border-b-2 -mb-px ${tab===id ? 'border-violet-500 text-violet-300' : 'border-transparent text-slate-400 hover:text-white'}`}>
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
    </div></EJShell>
  )
}

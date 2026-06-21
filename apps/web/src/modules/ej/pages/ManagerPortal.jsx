import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import EJShell from '../layout/EJShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import {
  Bell, Mail, MessageSquare, Calendar, ChevronRight,
  ShieldCheck, Users, MapPin, Building2, Globe, Eye,
  AlertTriangle, CheckCircle2, Clock, TrendingUp, Cpu,
  ToggleLeft, ToggleRight, Send, Shield, Monitor, Lock
} from 'lucide-react'
import WeeklyDigestModal from '../components/WeeklyDigestModal'
import { BRE_RULES } from '../hooks/useBRERules'

const ROLES = [
  {
    id: 'branch_manager',
    label: 'Branch Manager',
    icon: Building2,
    color: 'text-cyan-400',
    scope: 'Branch',
    scopeValue: 'Andheri West Branch, Mumbai',
    atms: 4,
    desc: 'Sees ATMs under own branch only. Gets daily alerts for cash, card & downtime.',
  },
  {
    id: 'zonal_manager',
    label: 'Zonal Manager',
    icon: MapPin,
    color: 'text-violet-400',
    scope: 'Zone',
    scopeValue: 'Mumbai Metro Zone (18 branches)',
    atms: 68,
    desc: 'Sees all ATMs across zone. Gets escalation alerts and weekly digest.',
  },
  {
    id: 'regional_head',
    label: 'Regional Head',
    icon: TrendingUp,
    color: 'text-amber-400',
    scope: 'Region',
    scopeValue: 'West Region (Mumbai, Pune, Goa)',
    atms: 106,
    desc: 'Fleet health, SLA compliance and dispute trends across region.',
  },
  {
    id: 'national_head',
    label: 'National Head',
    icon: Globe,
    color: 'text-emerald-400',
    scope: 'National',
    scopeValue: 'All India (247 ATMs)',
    atms: 247,
    desc: 'Full fleet visibility. Receives monthly executive digest and RBI compliance summary.',
  },
  {
    id: 'ops_reviewer',
    label: 'Ops Reviewer',
    icon: Eye,
    color: 'text-sky-400',
    scope: 'Functional',
    scopeValue: 'All Zones — Operational View',
    atms: 247,
    desc: 'Can view and resolve incidents across all zones. No financial data access.',
  },
  {
    id: 'compliance_officer',
    label: 'Compliance Officer',
    icon: ShieldCheck,
    color: 'text-rose-400',
    scope: 'Audit',
    scopeValue: 'All India — Read-Only Audit Trail',
    atms: 247,
    desc: 'Read-only view of incidents, decisions and EJ records for RBI audit.',
  },
]

const ATM_HEALTH = {
  branch_manager: [
    { id: 'ATM-MUM-011', status: 'HEALTHY', cash: 78, txn: 312, lastSync: '2m ago' },
    { id: 'ATM-MUM-012', status: 'DEGRADED', cash: 18, txn: 89, lastSync: '5m ago' },
    { id: 'ATM-MUM-013', status: 'HEALTHY', cash: 65, txn: 201, lastSync: '1m ago' },
    { id: 'ATM-MUM-014', status: 'OFFLINE', cash: 0, txn: 0, lastSync: '2h ago' },
  ],
  zonal_manager: [
    { id: 'ATM-MUM-004', status: 'CRITICAL', cash: 5, txn: 14, lastSync: '3m ago' },
    { id: 'ATM-MUM-012', status: 'DEGRADED', cash: 18, txn: 89, lastSync: '5m ago' },
    { id: 'ATM-MUM-014', status: 'OFFLINE', cash: 0, txn: 0, lastSync: '2h ago' },
    { id: 'ATM-MUM-001', status: 'HEALTHY', cash: 82, txn: 1203, lastSync: '1m ago' },
    { id: 'ATM-MUM-002', status: 'HEALTHY', cash: 91, txn: 874, lastSync: '2m ago' },
  ],
  regional_head: 'aggregate',
  national_head: 'aggregate',
  ops_reviewer: 'aggregate',
  compliance_officer: 'readonly',
}

const STATUS_STYLE = {
  CRITICAL: 'text-red-400 bg-red-400/10 border border-red-400/20',
  DEGRADED: 'text-amber-400 bg-amber-400/10 border border-amber-400/20',
  OFFLINE:  'text-slate-500 bg-slate-400/10 border border-slate-400/20',
  HEALTHY:  'text-emerald-400 bg-emerald-400/10 border border-emerald-400/20',
}

const INCIDENTS_BY_ROLE = {
  branch_manager: [
    { id: 'INC-2026-0042', atm: 'ATM-MUM-012', type: 'Cash Near Empty', sev: 'HIGH', status: 'OPEN', ago: '34m' },
    { id: 'INC-2026-0044', atm: 'ATM-MUM-014', type: 'Comm Failure', sev: 'MEDIUM', status: 'IN_PROGRESS', ago: '2h' },
  ],
  zonal_manager: [
    { id: 'INC-2026-0038', atm: 'ATM-MUM-004', type: 'Cash Not Dispensed', sev: 'CRITICAL', status: 'OPEN', ago: '8m' },
    { id: 'INC-2026-0042', atm: 'ATM-MUM-012', type: 'Cash Near Empty', sev: 'HIGH', status: 'OPEN', ago: '34m' },
    { id: 'INC-2026-0044', atm: 'ATM-MUM-014', type: 'Comm Failure', sev: 'MEDIUM', status: 'IN_PROGRESS', ago: '2h' },
    { id: 'INC-2026-0047', atm: 'ATM-MUM-009', type: 'Card Retention', sev: 'HIGH', status: 'ASSIGNED', ago: '1h' },
  ],
  regional_head: [
    { id: 'INC-2026-0038', atm: 'ATM-MUM-004', type: 'Cash Not Dispensed', sev: 'CRITICAL', status: 'OPEN', ago: '8m' },
    { id: 'INC-2026-0039', atm: 'ATM-PNQ-005', type: 'High Txn Velocity', sev: 'HIGH', status: 'OPEN', ago: '22m' },
    { id: 'INC-2026-0042', atm: 'ATM-MUM-012', type: 'Cash Near Empty', sev: 'HIGH', status: 'OPEN', ago: '34m' },
    { id: 'INC-2026-0043', atm: 'ATM-PNQ-011', type: 'Offline >1hr', sev: 'HIGH', status: 'ASSIGNED', ago: '55m' },
    { id: 'INC-2026-0044', atm: 'ATM-MUM-014', type: 'Comm Failure', sev: 'MEDIUM', status: 'IN_PROGRESS', ago: '2h' },
    { id: 'INC-2026-0047', atm: 'ATM-MUM-009', type: 'Card Retention', sev: 'HIGH', status: 'ASSIGNED', ago: '1h' },
  ],
  national_head: 'all',
  ops_reviewer: 'all',
  compliance_officer: 'readonly',
}

const SEV_STYLE = {
  CRITICAL: 'bg-red-500/20 text-red-300 border border-red-500/30',
  HIGH: 'bg-amber-500/20 text-amber-300 border border-amber-500/30',
  MEDIUM: 'bg-yellow-500/20 text-yellow-300 border border-yellow-500/30',
  LOW: 'bg-slate-500/20 text-slate-300 border border-slate-400/20',
}

const ALL_INCIDENTS = [
  { id: 'INC-2026-0038', atm: 'ATM-MUM-004', type: 'Cash Not Dispensed', sev: 'CRITICAL', status: 'OPEN', ago: '8m' },
  { id: 'INC-2026-0039', atm: 'ATM-PNQ-005', type: 'High Txn Velocity', sev: 'HIGH', status: 'OPEN', ago: '22m' },
  { id: 'INC-2026-0040', atm: 'ATM-DEL-003', type: 'Cash Near Empty', sev: 'HIGH', status: 'ASSIGNED', ago: '31m' },
  { id: 'INC-2026-0041', atm: 'ATM-BLR-002', type: 'Card Retention', sev: 'HIGH', status: 'IN_PROGRESS', ago: '38m' },
  { id: 'INC-2026-0042', atm: 'ATM-MUM-012', type: 'Cash Near Empty', sev: 'HIGH', status: 'OPEN', ago: '34m' },
  { id: 'INC-2026-0043', atm: 'ATM-PNQ-011', type: 'Offline >1hr', sev: 'HIGH', status: 'ASSIGNED', ago: '55m' },
  { id: 'INC-2026-0044', atm: 'ATM-MUM-014', type: 'Comm Failure', sev: 'MEDIUM', status: 'IN_PROGRESS', ago: '2h' },
  { id: 'INC-2026-0045', atm: 'ATM-CHN-001', type: 'Dispense Mismatch', sev: 'CRITICAL', status: 'OPEN', ago: '14m' },
  { id: 'INC-2026-0047', atm: 'ATM-MUM-009', type: 'Card Retention', sev: 'HIGH', status: 'ASSIGNED', ago: '1h' },
]

const DEFAULT_NOTIF = {
  email_critical: true,
  email_high: true,
  email_medium: false,
  whatsapp_critical: true,
  whatsapp_high: false,
  weekly_digest: true,
  monthly_digest: true,
}

export default function ManagerPortal() {
  const navigate = useNavigate()
  const [activeRole, setActiveRole] = useState('zonal_manager')
  const [notif, setNotif] = useState(DEFAULT_NOTIF)
  const [digestOpen, setDigestOpen] = useState(false)
  const [sentDemo, setSentDemo] = useState(false)
  const { isDark } = useTheme()

  const pg   = 'bg-slate-50 text-slate-900 dark:bg-[#020817] dark:text-white'
  const nav  = 'border-slate-200 bg-white dark:border-white/5 dark:bg-black/30'
  const nlnk = 'text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white'
  const card = 'bg-white border-slate-200 dark:bg-white/5 dark:border-white/5'
  const row  = 'bg-slate-50 border-slate-100 dark:bg-white/5 dark:border-white/5'
  const h2   = 'text-slate-700 dark:text-slate-300'
  const h1   = 'text-slate-900 dark:text-white'
  const sub  = 'text-slate-500 dark:text-slate-400'
  const mono = 'text-slate-800 dark:text-slate-200'
  const muted= 'text-slate-500 dark:text-slate-400'
  const ctx  = 'bg-slate-100 border-slate-200 dark:bg-white/5 dark:border-white/5'
  const sep  = 'bg-slate-300 dark:bg-white/10'
  const roleBtnActive = 'border-violet-400 bg-violet-50 dark:border-violet-500/60 dark:bg-violet-500/10'
  const roleBtnIdle   = 'border-slate-200 bg-white hover:border-slate-300 dark:border-white/5 dark:bg-white/2 dark:hover:border-white/20'
  const roleLbl       = 'text-slate-700 dark:text-slate-300'
  const ctx2 = 'bg-slate-100 dark:bg-white/5'
  const retBdr= 'border-slate-200 dark:border-white/5'

  const role = ROLES.find(r => r.id === activeRole)
  const RoleIcon = role.icon

  const atms = ATM_HEALTH[activeRole]
  const incidents = INCIDENTS_BY_ROLE[activeRole]

  const displayAtms = (atms === 'aggregate' || atms === 'readonly' || atms === 'all')
    ? null : atms
  const displayIncidents = (incidents === 'all')
    ? ALL_INCIDENTS
    : (incidents === 'readonly')
      ? ALL_INCIDENTS.filter(i => ['RESOLVED','CLOSED'].includes(i.status)).slice(0,4)
      : incidents

  const toggle = k => setNotif(p => ({ ...p, [k]: !p[k] }))

  // Compute mandatory channels for this role from BRE rules
  const mandatoryKeys = new Set()
  BRE_RULES.forEach(rule => {
    const ch = rule.channels?.[activeRole]
    if (!ch?.mandatory) return
    ch.mandatory.forEach(m => {
      if (m === 'onscreen') return // onscreen is always on, not in prefs
      if (m === 'email') {
        mandatoryKeys.add('email_critical')
        mandatoryKeys.add('email_high')
      }
      if (m === 'whatsapp') {
        mandatoryKeys.add('whatsapp_critical')
      }
    })
  })

  return (
    <EJShell><div className={`min-h-full flex flex-col ${pg}`}>
      {/* Top nav */}
      <nav className={`flex items-center justify-between px-6 py-3 border-b ${nav}`}>
        <Link to="/" className={`text-xs flex items-center gap-1 ${nlnk}`}>
          ← ASTRA Platform
        </Link>
        <div className="flex items-center gap-1 text-xs">
          <Link to="/ej" className={`px-3 py-1.5 rounded ${nlnk}`}>Command Center</Link>
          <Link to="/ej/incidents" className={`px-3 py-1.5 rounded ${nlnk}`}>Incidents</Link>
          <span className="px-3 py-1.5 rounded bg-violet-600/20 text-violet-500 font-medium border border-violet-500/30">Manager Portal</span>
          <Link to="/ej/bre" className={`px-3 py-1.5 rounded ${nlnk}`}>BRE Policy</Link>
          <Link to="/ej/notifications" className={`px-3 py-1.5 rounded ${nlnk}`}>Notifications</Link>
        </div>
        <span />
      </nav>

      <div className="flex-1 max-w-7xl w-full mx-auto px-6 py-6 space-y-6">
        <div>
          <h1 className={`text-xl font-bold flex items-center gap-2 ${h1}`}>
            <Users size={20} className="text-violet-500" /> Manager Portal
          </h1>
          <p className={`text-xs mt-1 ${sub}`}>Role-scoped ATM health view · Notification preferences · Digest scheduling</p>
        </div>

        {/* Role switcher */}
        <div>
          <div className={`text-xs ${muted} uppercase tracking-widest mb-3`}>Select Role (Demo)</div>
          <div className="grid grid-cols-3 gap-3 lg:grid-cols-6">
            {ROLES.map(r => {
              const Icon = r.icon
              return (
                <button
                  key={r.id}
                  onClick={() => setActiveRole(r.id)}
                  className={`flex flex-col items-center gap-2 p-3 rounded-xl border text-center transition-all ${
                    activeRole === r.id ? roleBtnActive : roleBtnIdle
                  }`}
                >
                  <Icon size={18} className={r.color} />
                  <span className={`text-xs leading-tight ${roleLbl}`}>{r.label}</span>
                </button>
              )
            })}
          </div>
        </div>

        {/* Role context bar */}
        <div className={`flex items-center gap-6 rounded-xl px-5 py-4 border ${ctx}`}>
          <div className="flex items-center gap-3">
            <div className={`p-2 rounded-lg ${ctx2}`}>
              <RoleIcon size={20} className={role.color} />
            </div>
            <div>
              <div className={`text-sm font-semibold ${h1}`}>{role.label}</div>
              <div className={`text-xs ${sub}`}>{role.desc}</div>
            </div>
          </div>
          <div className={`h-8 w-px ${sep}`} />
          <div>
            <div className={`text-xs ${muted}`}>Scope</div>
            <div className={`text-sm font-medium ${h1}`}>{role.scopeValue}</div>
          </div>
          <div className={`h-8 w-px ${sep}`} />
          <div>
            <div className={`text-xs ${muted}`}>ATMs Visible</div>
            <div className={`text-2xl font-bold ${h1}`}>{role.atms}</div>
          </div>
          {activeRole === 'compliance_officer' && (
            <>
              <div className="h-8 w-px bg-white/10" />
              <div className="flex items-center gap-2 text-xs text-rose-400 bg-rose-400/10 px-3 py-1.5 rounded-lg border border-rose-400/20">
                <ShieldCheck size={14} /> Read-Only · Audit Mode
              </div>
            </>
          )}
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* ATM Health (scoped) */}
          <div className="lg:col-span-2 space-y-4">
            <h2 className={`text-sm font-semibold flex items-center gap-2 ${h2}`}>
              <Cpu size={15} className="text-cyan-500" /> ATM Health — {role.scope} View
            </h2>

            {displayAtms ? (
              <div className="space-y-2">
                {displayAtms.map(a => (
                  <div key={a.id} className={`flex items-center gap-4 rounded-lg px-4 py-3 border ${row}`}>
                    <span className={`text-sm font-mono w-28 ${mono}`}>{a.id}</span>
                    <span className={`text-xs px-2 py-0.5 rounded font-medium ${STATUS_STYLE[a.status]}`}>{a.status}</span>
                    <div className="flex-1 flex items-center gap-1">
                      <div className="flex-1 bg-white/10 rounded-full h-1.5 overflow-hidden">
                        <div
                          className={`h-full rounded-full ${a.cash > 50 ? 'bg-emerald-500' : a.cash > 20 ? 'bg-amber-500' : 'bg-red-500'}`}
                          style={{ width: `${a.cash}%` }}
                        />
                      </div>
                      <span className="text-xs text-slate-400 w-10 text-right">{a.cash}%</span>
                    </div>
                    <span className="text-sm text-slate-300 w-20 text-right">{a.txn.toLocaleString()} txn</span>
                    <span className="text-xs text-slate-500 w-16 text-right">{a.lastSync}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className={`rounded-xl border px-6 py-8 text-center ${card}`}>
                {activeRole === 'compliance_officer' ? (
                  <div className="text-slate-400 text-sm">
                    <ShieldCheck size={24} className="text-rose-400 mx-auto mb-3" />
                    Audit view — ATM operational data not exposed.<br />
                    See Incident log below for audit-trail records.
                  </div>
                ) : (
                  <>
                    <Globe size={28} className="text-slate-600 mx-auto mb-3" />
                    <div className="text-slate-300 font-medium mb-1">Aggregate Fleet View</div>
                    <div className="text-xs text-slate-500 mb-4">
                      {role.atms} ATMs · Use Command Center for live tile grid
                    </div>
                    <div className="grid grid-cols-5 gap-3 text-center">
                      {[
                        { label: 'Healthy', val: Math.round(role.atms * 0.87), cls: 'text-emerald-400' },
                        { label: 'Degraded', val: Math.round(role.atms * 0.07), cls: 'text-amber-400' },
                        { label: 'Critical', val: Math.round(role.atms * 0.03), cls: 'text-red-400' },
                        { label: 'Offline', val: Math.round(role.atms * 0.02), cls: 'text-slate-500' },
                        { label: 'Uptime', val: '98.7%', cls: 'text-cyan-400' },
                      ].map(s => (
                        <div key={s.label}>
                          <div className={`text-xl font-bold ${s.cls}`}>{s.val}</div>
                          <div className="text-xs text-slate-500">{s.label}</div>
                        </div>
                      ))}
                    </div>
                    <button
                      onClick={() => navigate('/ej')}
                      className="mt-5 text-xs text-cyan-400 hover:text-cyan-300 flex items-center gap-1 mx-auto"
                    >
                      Open Command Center <ChevronRight size={14} />
                    </button>
                  </>
                )}
              </div>
            )}

            {/* Open incidents */}
            <h2 className={`text-sm font-semibold flex items-center gap-2 pt-2 ${h2}`}>
              <AlertTriangle size={15} className="text-amber-500" /> Open Incidents — {role.scope} Scope
            </h2>
            <div className="space-y-2">
              {displayIncidents && displayIncidents.length > 0 ? displayIncidents.map(inc => (
                <div key={inc.id} className={`flex items-center gap-3 rounded-lg px-4 py-2.5 border ${row}`}>
                  <span className={`text-xs px-2 py-0.5 rounded font-medium ${SEV_STYLE[inc.sev]}`}>{inc.sev}</span>
                  <span className="text-xs font-mono text-slate-400 w-32">{inc.id}</span>
                  <span className="text-xs font-mono text-cyan-400 w-24">{inc.atm}</span>
                  <span className="text-sm text-slate-200 flex-1">{inc.type}</span>
                  <span className="text-xs text-slate-500">{inc.ago}</span>
                  <span className={`text-xs px-2 py-0.5 rounded ${
                    inc.status === 'OPEN' ? 'bg-red-500/20 text-red-300' :
                    inc.status === 'ASSIGNED' ? 'bg-amber-500/20 text-amber-300' :
                    'bg-blue-500/20 text-blue-300'
                  }`}>{inc.status}</span>
                </div>
              )) : (
                <div className="text-center text-slate-500 text-sm py-6">No open incidents in your scope</div>
              )}
              {displayIncidents && (
                <Link to="/ej/incidents" className="text-xs text-violet-400 hover:text-violet-300 flex items-center gap-1 pt-1">
                  View all in Incident Management <ChevronRight size={13} />
                </Link>
              )}
            </div>
          </div>

          {/* Right panel: notifications + digest */}
          <div className="space-y-5">
            {/* Notification prefs */}
            <div className={`rounded-xl border p-5 ${card}`}>
              <h2 className={`text-sm font-semibold flex items-center gap-2 mb-4 ${h2}`}>
                <Bell size={15} className="text-violet-400" /> Notification Preferences
              </h2>
              <div className="space-y-3">
                {[
                  { key: 'email_critical', label: 'Email — CRITICAL alerts', icon: Mail },
                  { key: 'email_high', label: 'Email — HIGH alerts', icon: Mail },
                  { key: 'email_medium', label: 'Email — MEDIUM alerts', icon: Mail },
                  { key: 'whatsapp_critical', label: 'WhatsApp — CRITICAL', icon: MessageSquare },
                  { key: 'whatsapp_high', label: 'WhatsApp — HIGH', icon: MessageSquare },
                  { key: 'weekly_digest', label: 'Weekly Digest (Mon 9AM)', icon: Calendar },
                  { key: 'monthly_digest', label: 'Monthly Report (1st 9AM)', icon: Calendar },
                ].map(({ key, label, icon: Icon }) => {
                  const mandatory = mandatoryKeys.has(key)
                  return (
                    <button
                      key={key}
                      onClick={() => !mandatory && toggle(key)}
                      className={`w-full flex items-center justify-between gap-3 rounded-lg px-2 py-1.5 transition-colors ${
                        mandatory ? 'opacity-80 cursor-not-allowed' : 'hover:bg-white/5'
                      }`}
                      title={mandatory ? 'Mandatory — set by BRE policy. Contact Compliance Officer to change.' : undefined}
                    >
                      <div className="flex items-center gap-2">
                        <Icon size={13} className="text-slate-400" />
                        <span className="text-xs text-slate-300">{label}</span>
                        {mandatory && <Lock size={10} className="text-amber-400" title="Mandatory via BRE" />}
                      </div>
                      {mandatory
                        ? <ToggleRight size={20} className="text-amber-400" />
                        : notif[key]
                          ? <ToggleRight size={20} className="text-violet-400" />
                          : <ToggleLeft size={20} className="text-slate-600" />
                      }
                    </button>
                  )
                })}
              </div>
              <button className="mt-4 w-full text-xs bg-violet-600/30 hover:bg-violet-600/50 border border-violet-500/30 text-violet-300 rounded-lg py-2 transition-colors flex items-center justify-center gap-2">
                <CheckCircle2 size={13} /> Save Preferences
              </button>
            </div>

            {/* Digest preview */}
            <div className={`rounded-xl border p-5 ${card}`}>
              <h2 className={`text-sm font-semibold flex items-center gap-2 mb-1 ${h2}`}>
                <Calendar size={15} className="text-emerald-400" /> Scheduled Digests
              </h2>
              <p className="text-xs text-slate-500 mb-4">
                Auto-generated emails via Postal SMTP. Scoped to your access level.
              </p>
              <div className="space-y-2 mb-4">
                {[
                  { label: 'Weekly Digest', schedule: 'Every Monday · 09:00 IST', active: notif.weekly_digest },
                  { label: 'Monthly Report', schedule: '1st of month · 09:00 IST', active: notif.monthly_digest },
                ].map(d => (
                  <div key={d.label} className="flex items-center justify-between bg-white/5 rounded-lg px-3 py-2">
                    <div>
                      <div className="text-xs font-medium text-slate-200">{d.label}</div>
                      <div className="text-xs text-slate-500 flex items-center gap-1">
                        <Clock size={10} /> {d.schedule}
                      </div>
                    </div>
                    <span className={`text-xs px-2 py-0.5 rounded ${d.active ? 'bg-emerald-500/20 text-emerald-400' : 'bg-slate-700 text-slate-500'}`}>
                      {d.active ? 'Active' : 'Off'}
                    </span>
                  </div>
                ))}
              </div>
              <button
                onClick={() => setDigestOpen(true)}
                className="w-full text-xs bg-emerald-600/20 hover:bg-emerald-600/30 border border-emerald-500/30 text-emerald-300 rounded-lg py-2 transition-colors flex items-center justify-center gap-2"
              >
                <Eye size={13} /> Preview Weekly Digest
              </button>
              <button
                onClick={() => setSentDemo(true)}
                className="mt-2 w-full text-xs bg-white/5 hover:bg-white/10 border border-white/10 text-slate-300 rounded-lg py-2 transition-colors flex items-center justify-center gap-2"
              >
                <Send size={13} /> Send Test Email Now
              </button>
              {sentDemo && (
                <div className="mt-2 text-xs text-emerald-400 text-center flex items-center justify-center gap-1">
                  <CheckCircle2 size={12} /> Test email queued via Postal SMTP
                </div>
              )}
            </div>

            {/* BRE Rules Affecting You */}
            <div className={`rounded-xl border p-5 ${card}`}>
              <h2 className={`text-sm font-semibold flex items-center gap-2 mb-3 ${h2}`}>
                <Shield size={15} className="text-red-400" /> BRE Rules Affecting You
              </h2>
              {(() => {
                const myRules = BRE_RULES.filter(r => r.notify_roles.includes(activeRole)).slice(0, 5)
                return myRules.length === 0 ? (
                  <p className="text-xs text-slate-500">No BRE rules configured for this role.</p>
                ) : (
                  <div className="space-y-2">
                    {myRules.map(rule => {
                      const ch = rule.channels[activeRole] || {}
                      return (
                        <div key={rule.id} className="flex items-center justify-between bg-white/5 rounded-lg px-3 py-2">
                          <div>
                            <div className="text-xs font-medium text-slate-200">{rule.name}</div>
                            <div className="flex items-center gap-1.5 mt-0.5">
                              {ch.onscreen && <Monitor size={10} className="text-cyan-400" title="OnScreen" />}
                              {ch.whatsapp && <MessageSquare size={10} className="text-emerald-400" title="WhatsApp" />}
                              {ch.email && <Mail size={10} className="text-violet-400" title="Email" />}
                              {ch.mandatory?.length > 0 && <Lock size={9} className="text-amber-400" title="Has mandatory channels" />}
                            </div>
                          </div>
                          <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${
                            rule.severity === 'CRITICAL' ? 'text-red-400 bg-red-400/10' :
                            rule.severity === 'HIGH' ? 'text-amber-400 bg-amber-400/10' :
                            rule.severity === 'MEDIUM' ? 'text-yellow-400 bg-yellow-400/10' :
                            'text-slate-400 bg-slate-400/10'
                          }`}>{rule.severity}</span>
                        </div>
                      )
                    })}
                  </div>
                )
              })()}
              <Link to="/ej/bre" className="mt-3 text-xs text-violet-400 hover:text-violet-300 flex items-center gap-1">
                View all BRE rules <ChevronRight size={12} />
              </Link>
            </div>

            {/* Data retention info */}
            <div className={`rounded-xl border p-5 ${card}`}>
              <h2 className={`text-sm font-semibold flex items-center gap-2 mb-3 ${h2}`}>
                <Clock size={15} className="text-slate-400" /> Data Retention
              </h2>
              <div className="space-y-2 text-xs">
                {[
                  { tier: 'Hot (last 90 days)', color: 'bg-cyan-500', label: 'Full EJ · All incidents · Real-time' },
                  { tier: 'Warm (90d → 2yr)', color: 'bg-violet-500', label: 'Compressed EJ · Closed incidents' },
                  { tier: 'Cold / WORM (2→10yr)', color: 'bg-slate-600', label: 'Regulatory hold · RBI audit access' },
                ].map(t => (
                  <div key={t.tier} className="flex items-start gap-2">
                    <div className={`w-2 h-2 rounded-full mt-1 ${t.color} flex-shrink-0`} />
                    <div>
                      <div className="text-slate-300 font-medium">{t.tier}</div>
                      <div className="text-slate-500">{t.label}</div>
                    </div>
                  </div>
                ))}
              </div>
              <div className={`mt-3 pt-3 border-t ${retBdr} text-xs ${muted}`}>
                All data stored on-premises · No cloud transmission · YugabyteDB + MinIO WORM
              </div>
            </div>
          </div>
        </div>
      </div>

      <WeeklyDigestModal open={digestOpen} onClose={() => setDigestOpen(false)} role={role.label} />
    </div></EJShell>
  )
}

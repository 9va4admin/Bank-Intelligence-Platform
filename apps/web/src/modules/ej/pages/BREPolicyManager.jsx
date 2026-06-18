import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Shield, CheckCircle2, XCircle, Lock, Monitor, MessageSquare,
  Mail, ChevronRight, AlertTriangle, Clock, FileText, Users, Filter
} from 'lucide-react'
import { useBRERules } from '../hooks/useBRERules'

const ROLES = [
  { id:'compliance_officer', label:'Compliance Officer', color:'text-rose-400' },
  { id:'bank_it_admin',      label:'Bank IT Admin',      color:'text-amber-400' },
  { id:'national_head',      label:'National Head',      color:'text-emerald-400' },
  { id:'zonal_manager',      label:'Zonal Manager',      color:'text-violet-400' },
  { id:'ops_reviewer',       label:'Ops Reviewer',       color:'text-sky-400' },
  { id:'branch_manager',     label:'Branch Manager',     color:'text-cyan-400' },
]

const SEV_CLS = {
  CRITICAL: 'text-red-400 bg-red-400/10 border border-red-400/20',
  HIGH:     'text-amber-400 bg-amber-400/10 border border-amber-400/20',
  MEDIUM:   'text-yellow-400 bg-yellow-400/10 border border-yellow-400/20',
  LOW:      'text-slate-400 bg-slate-400/10 border border-slate-400/20',
}
const STATUS_CLS = {
  ACTIVE:  'text-emerald-400 bg-emerald-400/10',
  PENDING: 'text-amber-400 bg-amber-400/10 animate-pulse',
  DRAFT:   'text-slate-400 bg-slate-400/10',
}

const CATS = ['All','Transaction Integrity','Cash Management','Customer Impact','Fraud Signal','Availability','Security','Maintenance','Data Quality']

function RuleDetail({ rule, role, onApprove, onReject }) {
  if (!rule) return (
    <div className="flex-1 flex items-center justify-center">
      <div className="text-center text-slate-600">
        <Shield size={32} className="mx-auto mb-3 opacity-30" />
        <div className="text-sm">Select a rule to view details</div>
      </div>
    </div>
  )

  const canSeeRego = ['compliance_officer','bank_it_admin'].includes(role)
  const canApprove = role === 'bank_it_admin' && rule.pending_change
  const showChannels = !['branch_manager'].includes(role)

  return (
    <div className="flex-1 overflow-y-auto p-5 space-y-5">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2 mb-1 flex-wrap">
          <span className={`text-xs px-2 py-0.5 rounded border font-medium ${SEV_CLS[rule.severity]}`}>{rule.severity}</span>
          <span className="text-xs text-slate-500 bg-white/5 px-2 py-0.5 rounded">{rule.category}</span>
          <span className={`text-xs px-2 py-0.5 rounded font-medium ${STATUS_CLS[rule.status]}`}>{rule.status}</span>
          <span className="text-xs text-slate-600 font-mono">v{rule.version}</span>
        </div>
        <h2 className="text-lg font-bold text-white">{rule.name}</h2>
        <p className="text-sm text-slate-400 mt-1">{rule.description}</p>
      </div>

      {/* Pending change banner */}
      {rule.pending_change && (
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl p-4">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <div className="text-xs font-semibold text-amber-400 mb-1 flex items-center gap-1">
                <AlertTriangle size={12}/> PENDING APPROVAL
              </div>
              <div className="text-sm text-slate-300">{rule.pending_change.description}</div>
              <div className="text-xs text-slate-500 mt-1">
                Submitted by {rule.pending_change.submitted_by} · {new Date(rule.pending_change.submitted_at).toLocaleString('en-IN')}
              </div>
              <div className="text-xs text-slate-500">Awaiting: <span className="text-amber-400">{rule.pending_change.awaiting}</span></div>
            </div>
            {canApprove && (
              <div className="flex gap-2 flex-shrink-0">
                <button
                  onClick={() => onApprove(rule.id)}
                  className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-emerald-600/30 hover:bg-emerald-600/50 border border-emerald-500/30 text-emerald-300 text-xs font-medium transition-colors"
                >
                  <CheckCircle2 size={13}/> Approve
                </button>
                <button
                  onClick={() => onReject(rule.id)}
                  className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-red-600/20 hover:bg-red-600/30 border border-red-500/30 text-red-400 text-xs font-medium transition-colors"
                >
                  <XCircle size={13}/> Reject
                </button>
              </div>
            )}
            {role === 'compliance_officer' && (
              <span className="text-xs text-amber-400 flex-shrink-0">Awaiting bank_it_admin approval</span>
            )}
          </div>
        </div>
      )}

      {/* OPA Rego — compliance & admin only */}
      {canSeeRego && (
        <div>
          <div className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-2 flex items-center gap-2">
            <FileText size={13}/> OPA Rego Conditions
          </div>
          <pre className="bg-black/50 border border-white/10 rounded-lg p-4 text-xs font-mono text-emerald-300 overflow-x-auto leading-relaxed">
{`# package astra.ej.bre\n# rule: ${rule.id}\n\nallow if {\n${rule.rego_conditions.map(c => `    ${c}`).join('\n')}\n}`}
          </pre>
          <div className="text-xs text-slate-600 mt-1 flex items-center gap-1">
            <Lock size={10}/> Rego source visible to Compliance Officer and Bank IT Admin only
          </div>
        </div>
      )}

      {/* Notification routing */}
      {showChannels && (
        <div>
          <div className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-2 flex items-center gap-2">
            <Users size={13}/> Notification Routing
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-slate-500 border-b border-white/5">
                <th className="pb-2 pr-3">Role</th>
                <th className="pb-2 text-center w-16"><Monitor size={12} className="mx-auto"/></th>
                <th className="pb-2 text-center w-16"><MessageSquare size={12} className="mx-auto"/></th>
                <th className="pb-2 text-center w-16"><Mail size={12} className="mx-auto"/></th>
                <th className="pb-2 pl-2">Mandatory</th>
              </tr>
            </thead>
            <tbody>
              {rule.notify_roles.map(r => {
                const ch = rule.channels[r] || {}
                return (
                  <tr key={r} className="border-b border-white/5 text-slate-300">
                    <td className="py-2 pr-3 text-xs capitalize">{r.replace(/_/g,' ')}</td>
                    <td className="py-2 text-center text-xs">{ch.onscreen ? <span className="text-emerald-400">✓</span> : <span className="text-slate-600">–</span>}</td>
                    <td className="py-2 text-center text-xs">{ch.whatsapp ? <span className="text-emerald-400">✓</span> : <span className="text-slate-600">–</span>}</td>
                    <td className="py-2 text-center text-xs">{ch.email ? <span className="text-emerald-400">✓</span> : <span className="text-slate-600">–</span>}</td>
                    <td className="py-2 pl-2 text-xs">
                      {(ch.mandatory || []).map(m => (
                        <span key={m} className="inline-flex items-center gap-0.5 mr-1.5 text-amber-400 text-[10px]">
                          <Lock size={9}/>{m}
                        </span>
                      ))}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Branch manager: simplified view */}
      {role === 'branch_manager' && rule.channels['branch_manager'] && (
        <div>
          <div className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-2">You Will Receive</div>
          <div className="flex gap-3">
            {rule.channels['branch_manager'].onscreen && <span className="flex items-center gap-1 text-xs text-cyan-400 bg-cyan-400/10 px-2 py-1 rounded"><Monitor size={11}/> On-Screen</span>}
            {rule.channels['branch_manager'].whatsapp && <span className="flex items-center gap-1 text-xs text-emerald-400 bg-emerald-400/10 px-2 py-1 rounded"><MessageSquare size={11}/> WhatsApp</span>}
            {rule.channels['branch_manager'].email && <span className="flex items-center gap-1 text-xs text-violet-400 bg-violet-400/10 px-2 py-1 rounded"><Mail size={11}/> Email</span>}
          </div>
          {(rule.channels['branch_manager'].mandatory || []).length > 0 && (
            <div className="text-xs text-slate-500 mt-2 flex items-center gap-1"><Lock size={10}/> Mandatory channels cannot be disabled</div>
          )}
        </div>
      )}

      {/* Escalation */}
      <div>
        <div className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-2 flex items-center gap-2">
          <Clock size={13}/> Escalation Policy
        </div>
        {rule.escalation ? (
          <div className="bg-white/5 rounded-lg px-4 py-3 text-sm text-slate-300">
            If unACKed for <span className="text-amber-400 font-bold">{rule.escalation.unacked_minutes} min</span> → notify{' '}
            <span className="text-violet-400 font-medium capitalize">{rule.escalation.then_notify.replace(/_/g,' ')}</span> via{' '}
            {rule.escalation.then_channels.map(c => (
              <span key={c} className="text-cyan-400 mx-0.5">[{c}]</span>
            ))}
          </div>
        ) : (
          <div className="text-xs text-slate-600 bg-white/5 rounded-lg px-4 py-3">No escalation configured</div>
        )}
      </div>

      {/* Audit trail */}
      <div>
        <div className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-2">Audit Trail</div>
        <div className="grid grid-cols-2 gap-2 text-xs">
          {[
            { label:'Version', val:`v${rule.version}` },
            { label:'Last Changed', val:rule.last_changed },
            { label:'Edited By', val:rule.last_edited_by },
            { label:'Approved By', val:rule.last_approved_by || '—' },
          ].map(a => (
            <div key={a.label} className="bg-white/5 rounded-lg px-3 py-2">
              <div className="text-slate-500">{a.label}</div>
              <div className="text-slate-200 font-mono">{a.val}</div>
            </div>
          ))}
        </div>
        {!canSeeRego && (
          <div className="mt-2 text-xs text-slate-600 flex items-center gap-1">
            <Lock size={10}/> Full audit trail and Rego source visible to Compliance Officer only
          </div>
        )}
      </div>
    </div>
  )
}

export default function BREPolicyManager() {
  const { rules, selectedRule, setSelectedRule, approveChange, rejectChange } = useBRERules()
  const [activeRole, setActiveRole] = useState('compliance_officer')
  const [catFilter, setCatFilter] = useState('All')
  const [sevFilter, setSevFilter] = useState('All')

  const pending = rules.filter(r => r.pending_change)

  const visibleRules = rules.filter(r => {
    if (activeRole === 'branch_manager' && !r.notify_roles.includes('branch_manager')) return false
    if (catFilter !== 'All' && r.category !== catFilter) return false
    if (sevFilter !== 'All' && r.severity !== sevFilter) return false
    return true
  })

  const ACCESS_MSG = {
    compliance_officer: 'Full access — view Rego conditions, submit rule changes for approval',
    bank_it_admin: 'Approver access — approve or reject pending rule changes. Cannot author.',
    national_head: 'Executive view — rule summaries and notification routing. Rego hidden.',
    ops_reviewer: 'Operational view — see rules and which channels notify you. Rego hidden.',
    zonal_manager: 'Operational view — see rules and which channels notify you. Rego hidden.',
    branch_manager: 'Branch view — only rules that affect your ATMs and send you notifications.',
  }

  const ACCESS_CLS = {
    compliance_officer: 'bg-rose-500/10 border-rose-500/20 text-rose-300',
    bank_it_admin: 'bg-amber-500/10 border-amber-500/20 text-amber-300',
    national_head: 'bg-emerald-500/10 border-emerald-500/20 text-emerald-300',
    ops_reviewer: 'bg-sky-500/10 border-sky-500/20 text-sky-300',
    zonal_manager: 'bg-violet-500/10 border-violet-500/20 text-violet-300',
    branch_manager: 'bg-cyan-500/10 border-cyan-500/20 text-cyan-300',
  }

  return (
    <div className="min-h-screen bg-[#020817] text-white flex flex-col">
      <nav className="flex items-center justify-between px-6 py-3 border-b border-white/5 bg-black/30">
        <Link to="/" className="text-xs text-slate-400 hover:text-white">← ASTRA Platform</Link>
        <div className="flex items-center gap-1 text-xs flex-wrap justify-center">
          <Link to="/ej" className="px-3 py-1.5 rounded text-slate-400 hover:text-white">Command Center</Link>
          <Link to="/ej/incidents" className="px-3 py-1.5 rounded text-slate-400 hover:text-white">Incidents</Link>
          <Link to="/ej/portal" className="px-3 py-1.5 rounded text-slate-400 hover:text-white">Manager Portal</Link>
          <span className="px-3 py-1.5 rounded bg-violet-600/20 text-violet-300 font-medium border border-violet-500/30">BRE Policy</span>
          <Link to="/ej/notifications" className="px-3 py-1.5 rounded text-slate-400 hover:text-white">Notifications</Link>
        </div>
        <Link to="/cts" className="text-xs text-slate-400 hover:text-white">CTS →</Link>
      </nav>

      <div className="max-w-7xl w-full mx-auto px-6 py-4 flex-1 flex flex-col space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold flex items-center gap-2">
              <Shield size={20} className="text-violet-400"/> BRE Policy Manager
            </h1>
            <p className="text-xs text-slate-400 mt-0.5">Business Rule Engine — OPA Rego governance · Maker-checker workflow</p>
          </div>
          {activeRole === 'bank_it_admin' && pending.length > 0 && (
            <div className="flex items-center gap-2 bg-amber-500/10 border border-amber-500/30 px-3 py-2 rounded-lg text-xs text-amber-400 animate-pulse">
              <AlertTriangle size={13}/> {pending.length} rule{pending.length > 1 ? 's' : ''} awaiting approval
            </div>
          )}
        </div>

        {/* Role switcher */}
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs text-slate-500">Viewing as:</span>
          {ROLES.map(r => (
            <button key={r.id} onClick={() => { setActiveRole(r.id); setSelectedRule(null) }}
              className={`px-3 py-1 rounded-lg text-xs transition-colors border ${
                activeRole === r.id ? `bg-white/10 ${r.color} border-white/20` : 'text-slate-500 hover:text-slate-300 border-transparent'
              }`}>
              {r.label}
            </button>
          ))}
        </div>

        {/* Access level banner */}
        <div className={`flex items-center gap-2 px-4 py-2 rounded-lg border text-xs ${ACCESS_CLS[activeRole] || 'bg-white/5 border-white/5 text-slate-400'}`}>
          <Lock size={12}/> {ACCESS_MSG[activeRole]}
        </div>

        {/* Filters */}
        <div className="flex gap-3 items-center">
          <Filter size={13} className="text-slate-500"/>
          <select value={catFilter} onChange={e => setCatFilter(e.target.value)}
            className="bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-xs text-slate-300 outline-none">
            {CATS.map(c => <option key={c} value={c} className="bg-[#0d1117]">{c}</option>)}
          </select>
          <select value={sevFilter} onChange={e => setSevFilter(e.target.value)}
            className="bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-xs text-slate-300 outline-none">
            {['All','CRITICAL','HIGH','MEDIUM','LOW'].map(s => <option key={s} value={s} className="bg-[#0d1117]">{s}</option>)}
          </select>
          <span className="text-xs text-slate-500">{visibleRules.length} rules visible</span>
          {activeRole === 'branch_manager' && <span className="text-xs text-cyan-500">(filtered to your scope)</span>}
        </div>

        {/* Main 2-panel layout */}
        <div className="flex gap-4 flex-1 min-h-0" style={{height:'560px'}}>
          {/* Rule list */}
          <div className="w-72 flex-shrink-0 overflow-y-auto space-y-1.5">
            {visibleRules.map(r => (
              <button key={r.id} onClick={() => setSelectedRule(r)}
                className={`w-full text-left px-3 py-3 rounded-xl border transition-all ${
                  selectedRule?.id === r.id
                    ? 'border-violet-500/40 bg-violet-500/10'
                    : 'border-white/5 bg-white/3 hover:border-white/15 hover:bg-white/5'
                }`}>
                <div className="flex items-center justify-between mb-1.5">
                  <span className={`text-[10px] px-1.5 py-0.5 rounded border font-bold ${SEV_CLS[r.severity]}`}>{r.severity}</span>
                  <div className="flex items-center gap-1.5">
                    {r.pending_change && <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse"/>}
                    <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${STATUS_CLS[r.status]}`}>{r.status}</span>
                  </div>
                </div>
                <div className="text-sm font-medium text-slate-200 leading-tight">{r.name}</div>
                <div className="text-[10px] text-slate-500 mt-1 flex justify-between">
                  <span>{r.category}</span>
                  <span className="font-mono">v{r.version}</span>
                </div>
              </button>
            ))}
            {visibleRules.length === 0 && (
              <div className="text-center text-slate-600 text-xs py-8">No rules match filters</div>
            )}
          </div>

          {/* Detail panel */}
          <div className="flex-1 bg-white/5 rounded-xl border border-white/5 overflow-hidden flex flex-col">
            <RuleDetail
              rule={selectedRule}
              role={activeRole}
              onApprove={approveChange}
              onReject={rejectChange}
            />
          </div>
        </div>
      </div>
    </div>
  )
}

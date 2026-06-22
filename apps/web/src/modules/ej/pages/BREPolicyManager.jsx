import { useState } from 'react'
import EJShell from '../layout/EJShell'
import { Shield, CheckCircle2, XCircle, Lock, Monitor, MessageSquare, Mail, AlertTriangle, Clock, FileText, Users } from 'lucide-react'
import { useBRERules } from '../hooks/useBRERules'

const ROLES = [
  { id:'compliance_officer', label:'Compliance Officer', color:'text-rose-400' },
  { id:'bank_it_admin',      label:'Bank IT Admin',      color:'text-amber-400' },
  { id:'national_head',      label:'National Head',      color:'text-emerald-400' },
  { id:'zonal_manager',      label:'Zonal Manager',      color:'text-violet-400' },
  { id:'ops_reviewer',       label:'Ops Reviewer',       color:'text-sky-400' },
  { id:'branch_manager',     label:'Branch Manager',     color:'text-cyan-400' },
]

const SEV = { CRITICAL:'text-red-400 bg-red-400/10 border-red-400/20', HIGH:'text-amber-400 bg-amber-400/10 border-amber-400/20', MEDIUM:'text-yellow-400 bg-yellow-400/10 border-yellow-400/20', LOW:'text-slate-400 bg-slate-400/10 border-slate-400/20' }
const STATUS_CLS = { ACTIVE:'text-emerald-400 bg-emerald-400/10', PENDING:'text-amber-400 bg-amber-400/10 animate-pulse', DRAFT:'text-slate-400 bg-slate-400/10' }

function RuleDetail({ rule, role, onApprove, onReject }) {
  if (!rule) return (
    <div className="flex-1 flex items-center justify-center text-slate-600 text-sm">
      Select a rule to view details
    </div>
  )

  const canSeeRego = ['compliance_officer','bank_it_admin'].includes(role)
  const canApprove = role === 'bank_it_admin' && rule.pending_change
  const showChannelTable = ['compliance_officer','bank_it_admin','national_head','ops_reviewer','zonal_manager','regional_head'].includes(role)

  return (
    <div className="flex-1 overflow-y-auto p-5 space-y-5">
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className={`text-xs px-2 py-0.5 rounded border font-medium ${SEV[rule.severity]}`}>{rule.severity}</span>
            <span className="text-xs text-slate-500 bg-white/5 px-2 py-0.5 rounded">{rule.category}</span>
            <span className={`text-xs px-2 py-0.5 rounded font-medium ${STATUS_CLS[rule.status]}`}>{rule.status}</span>
            <span className="text-xs text-slate-600">v{rule.version}</span>
          </div>
          <h2 className="text-lg font-bold text-white">{rule.name}</h2>
          <p className="text-sm text-slate-400 mt-1">{rule.description}</p>
        </div>
      </div>

      {rule.pending_change && (
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl p-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="text-xs font-semibold text-amber-400 mb-1 flex items-center gap-1"><AlertTriangle size={12}/> PENDING APPROVAL</div>
              <div className="text-sm text-slate-300">{rule.pending_change.description}</div>
              <div className="text-xs text-slate-500 mt-1">Submitted by {rule.pending_change.submitted_by} · {new Date(rule.pending_change.submitted_at).toLocaleString('en-IN')}</div>
              <div className="text-xs text-slate-500">Awaiting: <span className="text-amber-400">{rule.pending_change.awaiting}</span></div>
            </div>
            {canApprove && (
              <div className="flex gap-2 flex-shrink-0">
                <button onClick={() => onApprove(rule.id)} className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-emerald-600/30 hover:bg-emerald-600/50 border border-emerald-500/30 text-emerald-300 text-xs font-medium transition-colors">
                  <CheckCircle2 size={13}/> Approve
                </button>
                <button onClick={() => onReject(rule.id)} className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-red-600/20 hover:bg-red-600/30 border border-red-500/30 text-red-400 text-xs font-medium transition-colors">
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

      {canSeeRego && (
        <div>
          <div className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-2 flex items-center gap-2"><FileText size={13}/> OPA Rego Conditions</div>
          <pre className="bg-black/40 border border-white/10 rounded-lg p-4 text-xs font-mono text-emerald-300 overflow-x-auto">
{`# package astra.ej.bre
# rule: ${rule.id}

allow if {
${rule.rego_conditions.map(c => `    ${c}`).join('\n')}
}`}
          </pre>
          <div className="text-xs text-slate-600 mt-1 flex items-center gap-1"><Lock size={10}/> Rego source visible to Compliance Officer and Bank IT Admin only</div>
        </div>
      )}

      {showChannelTable && (
        <div>
          <div className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-2 flex items-center gap-2"><Users size={13}/> Notification Routing</div>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-slate-500 border-b border-white/5">
                <th className="pb-2">Role</th>
                <th className="pb-2 text-center"><Monitor size={13} className="mx-auto"/></th>
                <th className="pb-2 text-center"><MessageSquare size={13} className="mx-auto"/></th>
                <th className="pb-2 text-center"><Mail size={13} className="mx-auto"/></th>
                <th className="pb-2">Mandatory</th>
              </tr>
            </thead>
            <tbody>
              {rule.notify_roles.map(r => {
                const ch = rule.channels[r] || {}
                return (
                  <tr key={r} className="border-b border-white/5 text-slate-300">
                    <td className="py-2 text-xs capitalize">{r.replace('_',' ')}</td>
                    <td className="py-2 text-center text-xs">{ch.onscreen ? <span className="text-emerald-400">✓</span> : <span className="text-slate-600">–</span>}</td>
                    <td className="py-2 text-center text-xs">{ch.whatsapp ? <span className="text-emerald-400">✓</span> : <span className="text-slate-600">–</span>}</td>
                    <td className="py-2 text-center text-xs">{ch.email ? <span className="text-emerald-400">✓</span> : <span className="text-slate-600">–</span>}</td>
                    <td className="py-2 text-xs">
                      {(ch.mandatory||[]).map(m => (
                        <span key={m} className="inline-flex items-center gap-0.5 mr-1 text-amber-400"><Lock size={9}/>{m}</span>
                      ))}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <div>
        <div className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-2 flex items-center gap-2"><Clock size={13}/> Escalation</div>
        {rule.escalation ? (
          <div className="bg-white/5 rounded-lg px-4 py-3 text-sm text-slate-300">
            If unACKed for <span className="text-amber-400 font-bold">{rule.escalation.unacked_minutes} minutes</span> → notify{' '}
            <span className="text-violet-400 font-medium capitalize">{rule.escalation.then_notify.replace('_',' ')}</span> via{' '}
            {rule.escalation.then_channels.map(c => (
              <span key={c} className="text-cyan-400 mx-0.5">[{c}]</span>
            ))}
          </div>
        ) : (
          <div className="text-xs text-slate-600 bg-white/5 rounded-lg px-4 py-3">No escalation configured for this rule</div>
        )}
      </div>

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
          <div className="mt-2 text-xs text-slate-600 flex items-center gap-1"><Lock size={10}/> Full audit trail and Rego source visible to Compliance Officer only</div>
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

  const th = {
    pg:      'bg-slate-50 text-slate-900 dark:bg-[#020817] dark:text-white',
    nav:     'border-slate-200 bg-white dark:border-white/5 dark:bg-black/30',
    nlnk:    'text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white',
    h1:      'text-slate-900 dark:text-white',
    sub:     'text-slate-500 dark:text-slate-400',
    roleBtn: 'text-slate-400 hover:text-slate-700 dark:text-slate-500 dark:hover:text-slate-300',
    ctx:     'bg-slate-100 border-slate-200 text-slate-600 dark:bg-white/5 dark:border-white/5 dark:text-slate-400',
    sel:     'bg-white border-slate-300 text-slate-700 dark:bg-white/5 dark:border-white/10 dark:text-slate-300',
    selOpt:  'bg-white dark:bg-[#020817]',
    ruleBtn: 'border-slate-200 bg-white hover:border-slate-300 dark:border-white/5 dark:bg-white/2 dark:hover:border-white/15',
    ruleName:'text-slate-800 dark:text-slate-200',
    ruleMeta:'text-slate-400 dark:text-slate-500',
    detail:  'bg-white border-slate-200 dark:bg-white/5 dark:border-white/5',
  }

  const visibleRules = rules.filter(r => {
    if (activeRole === 'branch_manager' && !r.notify_roles.includes('branch_manager')) return false
    if (catFilter !== 'All' && r.category !== catFilter) return false
    if (sevFilter !== 'All' && r.severity !== sevFilter) return false
    return true
  })

  const pending = rules.filter(r => r.pending_change)

  return (
    <EJShell><div className={`flex flex-col ${th.pg}`}>
      <div className="max-w-7xl w-full mx-auto px-6 py-4 space-y-4 flex-1 flex flex-col">
        <div className="flex items-center justify-between">
          <div>
            <h1 className={`text-xl font-bold flex items-center gap-2 ${th.h1}`}><Shield size={20} className="text-violet-400"/> BRE Policy Manager</h1>
            <p className={`text-xs ${th.sub} mt-0.5`}>Business Rule Engine — OPA Rego governance · Maker-checker workflow</p>
          </div>
          {activeRole === 'bank_it_admin' && pending.length > 0 && (
            <div className="flex items-center gap-2 bg-amber-500/10 border border-amber-500/30 px-3 py-2 rounded-lg text-xs text-amber-400 animate-pulse">
              <AlertTriangle size={13}/> {pending.length} rule{pending.length > 1 ? 's' : ''} pending your approval
            </div>
          )}
        </div>

        <div className="flex gap-2 flex-wrap">
          <span className="text-xs text-slate-500 self-center">Viewing as:</span>
          {ROLES.map(r => (
            <button key={r.id} onClick={() => setActiveRole(r.id)}
              className={`px-3 py-1 rounded-lg text-xs transition-colors ${activeRole === r.id ? `bg-white/10 ${r.color} border border-white/20` : th.roleBtn}`}>
              {r.label}
            </button>
          ))}
        </div>

        <div className={`flex items-center gap-2 px-4 py-2 rounded-lg border text-xs ${
          activeRole === 'compliance_officer' ? 'bg-rose-500/10 border-rose-500/20 text-rose-300' :
          activeRole === 'bank_it_admin' ? 'bg-amber-500/10 border-amber-500/20 text-amber-300' :
          th.ctx
        }`}>
          <Lock size={12}/>
          {activeRole === 'compliance_officer' && 'Full access — can view Rego conditions, submit rule changes for approval'}
          {activeRole === 'bank_it_admin' && 'Approver access — can approve or reject pending rule changes. Cannot author rules.'}
          {activeRole === 'national_head' && 'Executive view — rule summaries and notification routing. Rego conditions hidden.'}
          {activeRole === 'ops_reviewer' && 'Operational view — see rules and which channels notify you. Rego conditions hidden.'}
          {activeRole === 'zonal_manager' && 'Operational view — see rules and which channels notify you. Rego conditions hidden.'}
          {activeRole === 'branch_manager' && 'Branch view — only showing rules that affect your ATMs and send you notifications.'}
        </div>

        <div className="flex gap-3">
          <select value={catFilter} onChange={e => setCatFilter(e.target.value)}
            className={`border rounded-lg px-3 py-1.5 text-xs outline-none ${th.sel}`}>
            {['All','Transaction Integrity','Cash Management','Customer Impact','Fraud Signal','Availability','Security','Maintenance','Data Quality'].map(c => (
              <option key={c} value={c} className={th.selOpt}>{c}</option>
            ))}
          </select>
          <select value={sevFilter} onChange={e => setSevFilter(e.target.value)}
            className={`border rounded-lg px-3 py-1.5 text-xs outline-none ${th.sel}`}>
            {['All','CRITICAL','HIGH','MEDIUM','LOW'].map(s => (
              <option key={s} value={s} className={th.selOpt}>{s}</option>
            ))}
          </select>
          <span className={`text-xs ${th.sub} self-center`}>{visibleRules.length} rules</span>
        </div>

        <div className="flex gap-4 flex-1 min-h-0" style={{height:'560px'}}>
          <div className="w-80 flex-shrink-0 overflow-y-auto space-y-1.5">
            {visibleRules.map(r => (
              <button key={r.id} onClick={() => setSelectedRule(r)}
                className={`w-full text-left px-3 py-3 rounded-xl border transition-all ${
                  selectedRule?.id === r.id
                    ? 'border-violet-500/40 bg-violet-500/10'
                    : th.ruleBtn
                }`}>
                <div className="flex items-center justify-between mb-1">
                  <span className={`text-xs px-1.5 py-0.5 rounded border font-medium ${SEV[r.severity]}`}>{r.severity}</span>
                  <div className="flex items-center gap-1">
                    {r.pending_change && <span className="text-xs text-amber-400 animate-pulse">●</span>}
                    <span className={`text-xs px-1.5 py-0.5 rounded ${STATUS_CLS[r.status]}`}>{r.status}</span>
                  </div>
                </div>
                <div className={`text-sm font-medium ${th.ruleName}`}>{r.name}</div>
                <div className={`text-xs ${th.ruleMeta} mt-0.5 flex items-center justify-between`}>
                  <span>{r.category}</span>
                  <span>v{r.version}</span>
                </div>
              </button>
            ))}
          </div>

          <div className={`flex-1 rounded-xl border overflow-hidden flex flex-col ${th.detail}`}>
            <RuleDetail
              rule={selectedRule}
              role={activeRole}
              onApprove={(id) => { approveChange(id); setSelectedRule(prev => prev?.id === id ? {...prev, status:'ACTIVE', pending_change:null, version: prev.version+1} : prev) }}
              onReject={(id) => { rejectChange(id); setSelectedRule(prev => prev?.id === id ? {...prev, status: prev.version>0?'ACTIVE':'DRAFT', pending_change:null} : prev) }}
            />
          </div>
        </div>
      </div>
    </div></EJShell>
  )
}

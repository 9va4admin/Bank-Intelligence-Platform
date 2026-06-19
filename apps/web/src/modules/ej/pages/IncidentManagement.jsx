import { useState, useMemo } from 'react'
import { Link } from 'react-router-dom'
import EJShell from '../layout/EJShell'
import { useTheme } from '../../../shared/theme/ThemeContext'

const MOCK_INCIDENTS = [
  { id:'INC-2026-0041', atm_id:'ATM-MUM-004', city:'Mumbai',    branch:'Kurla',        severity:'CRITICAL', type:'Dispense-Balance Mismatch',  status:'IN_PROGRESS', opened:'2026-06-18T10:31:07Z', assigned_to:'Rahul Sharma',  sla_breach_at:'2026-06-18T11:01:07Z', notes:'Cassette 1 jam confirmed. Engineer dispatched.' },
  { id:'INC-2026-0042', atm_id:'ATM-CHE-002', city:'Chennai',   branch:'Anna Nagar',   severity:'CRITICAL', type:'Cash-Not-Dispensed Spike',   status:'OPEN',        opened:'2026-06-18T10:38:14Z', assigned_to:null,            sla_breach_at:'2026-06-18T11:08:14Z', notes:'' },
  { id:'INC-2026-0043', atm_id:'ATM-DEL-001', city:'Delhi',     branch:'Connaught Pl', severity:'HIGH',     type:'Excessive PIN Failures',     status:'ASSIGNED',    opened:'2026-06-18T10:41:52Z', assigned_to:'Priya Mehta',   sla_breach_at:'2026-06-18T12:41:52Z', notes:'Investigating card skimming possibility.' },
  { id:'INC-2026-0044', atm_id:'ATM-BLR-001', city:'Bangalore', branch:'Koramangala',  severity:'HIGH',     type:'Journal Sequence Gap',       status:'RESOLVED',    opened:'2026-06-18T09:12:00Z', assigned_to:'Kiran Rao',     sla_breach_at:'2026-06-18T11:12:00Z', notes:'EJ re-sync completed. Records recovered.' },
  { id:'INC-2026-0045', atm_id:'ATM-MUM-002', city:'Mumbai',    branch:'Bandra East',  severity:'HIGH',     type:'Transaction Velocity Spike', status:'IN_PROGRESS', opened:'2026-06-18T10:46:19Z', assigned_to:'Amit Desai',    sla_breach_at:'2026-06-18T12:46:19Z', notes:'Monitoring for fraud pattern.' },
  { id:'INC-2026-0046', atm_id:'ATM-PUN-001', city:'Pune',      branch:'FC Road',      severity:'MEDIUM',   type:'EJ Upload Timeout',          status:'OPEN',        opened:'2026-06-18T10:47:33Z', assigned_to:null,            sla_breach_at:'2026-06-18T18:47:33Z', notes:'' },
  { id:'INC-2026-0047', atm_id:'ATM-DEL-004', city:'Delhi',     branch:'Rohini',       severity:'MEDIUM',   type:'ATM Offline',                status:'ASSIGNED',    opened:'2026-06-18T07:03:00Z', assigned_to:'Vikram Singh',  sla_breach_at:'2026-06-18T15:03:00Z', notes:'Power outage reported. Technician en route.' },
  { id:'INC-2026-0048', atm_id:'ATM-BLR-003', city:'Bangalore', branch:'Indiranagar',  severity:'MEDIUM',   type:'Cassette Jam Pattern',       status:'RESOLVED',    opened:'2026-06-18T08:30:00Z', assigned_to:'Kiran Rao',     sla_breach_at:'2026-06-18T16:30:00Z', notes:'Cassette replaced. Back online.' },
  { id:'INC-2026-0049', atm_id:'ATM-CHE-001', city:'Chennai',   branch:'T Nagar',      severity:'LOW',      type:'Low Cash Warning',           status:'CLOSED',      opened:'2026-06-18T06:00:00Z', assigned_to:'Meena Iyer',    sla_breach_at:'2026-06-19T06:00:00Z', notes:'Cash replenished. Incident closed.' },
  { id:'INC-2026-0050', atm_id:'ATM-MUM-001', city:'Mumbai',    branch:'Andheri West', severity:'LOW',      type:'EJ Upload Delayed',          status:'CLOSED',      opened:'2026-06-17T22:15:00Z', assigned_to:'Rahul Sharma',  sla_breach_at:'2026-06-18T22:15:00Z', notes:'Network congestion resolved overnight.' },
  { id:'INC-2026-0039', atm_id:'ATM-DEL-002', city:'Delhi',     branch:'Karol Bagh',   severity:'HIGH',     type:'Off-Hours Large Dispense',   status:'CLOSED',      opened:'2026-06-18T02:17:00Z', assigned_to:'Priya Mehta',   sla_breach_at:'2026-06-18T04:17:00Z', notes:'Verified legitimate corporate withdrawal. Closed.' },
  { id:'INC-2026-0038', atm_id:'ATM-BLR-002', city:'Bangalore', branch:'Whitefield',   severity:'MEDIUM',   type:'EJ Upload Timeout',          status:'RESOLVED',    opened:'2026-06-17T18:00:00Z', assigned_to:'Kiran Rao',     sla_breach_at:'2026-06-18T02:00:00Z', notes:'Network restored after ISP maintenance.' },
]

const SEV_D = { CRITICAL: 'bg-red-900/60 text-red-300 border-red-700/50', HIGH: 'bg-amber-900/50 text-amber-300 border-amber-700/40', MEDIUM: 'bg-yellow-900/40 text-yellow-300 border-yellow-700/30', LOW: 'bg-slate-800 text-slate-400 border-slate-700' }
const SEV_L = { CRITICAL: 'bg-red-100 text-red-700 border-red-300', HIGH: 'bg-amber-100 text-amber-700 border-amber-300', MEDIUM: 'bg-yellow-100 text-yellow-700 border-yellow-300', LOW: 'bg-slate-100 text-slate-600 border-slate-300' }

const STATUS_D = { OPEN: 'bg-red-900/50 text-red-300', ASSIGNED: 'bg-blue-900/50 text-blue-300', IN_PROGRESS: 'bg-violet-900/50 text-violet-300', RESOLVED: 'bg-emerald-900/40 text-emerald-400', CLOSED: 'bg-slate-800 text-slate-500' }
const STATUS_L = { OPEN: 'bg-red-100 text-red-700', ASSIGNED: 'bg-blue-100 text-blue-700', IN_PROGRESS: 'bg-violet-100 text-violet-700', RESOLVED: 'bg-emerald-100 text-emerald-700', CLOSED: 'bg-slate-100 text-slate-500' }

const TIME_RANGES = ['2h','6h','24h','7d','30d']
const STATUS_OPTIONS = ['ALL','OPEN','ASSIGNED','IN_PROGRESS','RESOLVED','CLOSED']
const SEV_OPTIONS = ['ALL','CRITICAL','HIGH','MEDIUM','LOW']

function getSLA(inc) {
  if (['RESOLVED','CLOSED'].includes(inc.status)) return { label:'Met', cls:'text-emerald-500' }
  const diff = Math.round((new Date(inc.sla_breach_at) - Date.now()) / 60000)
  if (diff < 0)  return { label:`BREACHED ${Math.abs(diff)}m`, cls:'text-red-500 animate-pulse font-bold' }
  if (diff < 10) return { label:`${diff}m left`, cls:'text-red-500' }
  if (diff < 60) return { label:`${diff}m left`, cls:'text-amber-500' }
  return { label:`${Math.round(diff/60)}h left`, cls:'text-slate-400' }
}

function DetailPanel({ inc, onClose, onStatusChange, isDark }) {
  const [note, setNote] = useState(inc.notes)
  const sla = getSLA(inc)
  const nextStatus = { OPEN:'ASSIGNED', ASSIGNED:'IN_PROGRESS', IN_PROGRESS:'RESOLVED', RESOLVED:'CLOSED' }
  const SEV    = isDark ? SEV_D    : SEV_L
  const STATUS = isDark ? STATUS_D : STATUS_L

  const panel  = isDark ? 'bg-[#0a1628] border-slate-800' : 'bg-white border-slate-200'
  const hdr    = isDark ? 'border-slate-800' : 'border-slate-200'
  const id_cls = isDark ? 'text-cyan-400' : 'text-blue-600'
  const ttl    = isDark ? 'text-slate-100' : 'text-slate-900'
  const close  = isDark ? 'text-slate-500 hover:text-slate-300' : 'text-slate-400 hover:text-slate-700'
  const kCard  = isDark ? 'bg-slate-900/60 border-slate-800 text-slate-500' : 'bg-slate-50 border-slate-200 text-slate-400'
  const kVal   = isDark ? 'text-slate-200' : 'text-slate-800'
  const tlBdr  = isDark ? 'border-slate-700' : 'border-slate-300'
  const tlTxt  = isDark ? 'text-slate-300' : 'text-slate-700'
  const tlTs   = isDark ? 'text-slate-600' : 'text-slate-400'
  const lbl    = isDark ? 'text-slate-500' : 'text-slate-400'
  const ta     = isDark ? 'bg-slate-900/60 border-slate-700 text-slate-200 focus:border-cyan-700' : 'bg-slate-50 border-slate-300 text-slate-800 focus:border-blue-400'
  const ftr    = isDark ? 'border-slate-800' : 'border-slate-200'
  const btn    = isDark ? 'bg-cyan-800 hover:bg-cyan-700 text-cyan-100' : 'bg-blue-600 hover:bg-blue-700 text-white'
  const clsBtn = isDark ? 'text-slate-400 hover:text-slate-200 border-slate-700' : 'text-slate-500 hover:text-slate-700 border-slate-300'

  return (
    <div className={`fixed inset-y-0 right-0 w-96 border-l z-50 flex flex-col shadow-2xl ${panel}`}>
      <div className={`flex items-center justify-between px-4 py-3 border-b ${hdr}`}>
        <div>
          <div className={`text-xs font-mono ${id_cls}`}>{inc.id}</div>
          <div className={`text-sm font-semibold ${ttl} mt-0.5`}>{inc.type}</div>
        </div>
        <button onClick={onClose} className={`${close} text-xl`}>×</button>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
        <div className="grid grid-cols-2 gap-3 text-xs">
          {[['ATM ID', inc.atm_id],['Branch', inc.branch],['City', inc.city],['Assigned To', inc.assigned_to || '—']].map(([k,v]) => (
            <div key={k} className={`border rounded-lg p-2 ${kCard}`}>
              <div className="mb-0.5">{k}</div>
              <div className={`font-mono font-semibold ${kVal}`}>{v}</div>
            </div>
          ))}
        </div>

        <div className="flex gap-2">
          <span className={`text-[11px] px-2 py-0.5 rounded-full border ${SEV[inc.severity]}`}>{inc.severity}</span>
          <span className={`text-[11px] px-2 py-0.5 rounded-full ${STATUS[inc.status]}`}>{inc.status.replace('_',' ')}</span>
          <span className={`text-[11px] ml-auto ${sla.cls}`}>{sla.label}</span>
        </div>

        <div>
          <div className={`text-xs ${lbl} mb-1 uppercase tracking-wider`}>Timeline</div>
          <div className={`space-y-1.5 border-l ${tlBdr} pl-3`}>
            {[
              { ts: inc.opened, label: 'Incident opened', color: 'bg-red-500' },
              inc.assigned_to && { ts: inc.opened, label: `Assigned to ${inc.assigned_to}`, color: 'bg-blue-500' },
              inc.status === 'RESOLVED' && { ts: inc.sla_breach_at, label: 'Resolved before SLA', color: 'bg-emerald-500' },
              inc.status === 'CLOSED' && { ts: inc.sla_breach_at, label: 'Incident closed', color: 'bg-slate-500' },
            ].filter(Boolean).map((ev, i) => (
              <div key={i} className="flex items-start gap-2 text-xs">
                <div className={`w-2 h-2 rounded-full mt-0.5 -ml-4 shrink-0 ${ev.color}`} />
                <div>
                  <div className={tlTxt}>{ev.label}</div>
                  <div className={`${tlTs} font-mono`}>{new Date(ev.ts).toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit',hour12:false})} IST</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div>
          <div className={`text-xs ${lbl} mb-1 uppercase tracking-wider`}>Notes</div>
          <textarea
            value={note}
            onChange={e => setNote(e.target.value)}
            rows={4}
            className={`w-full border rounded-lg px-3 py-2 text-xs font-mono resize-none focus:outline-none ${ta}`}
            placeholder="Add investigation notes..."
          />
        </div>
      </div>

      {nextStatus[inc.status] && (
        <div className={`px-4 py-3 border-t ${ftr} flex gap-2`}>
          <button onClick={() => onStatusChange(inc.id, nextStatus[inc.status])}
            className={`flex-1 py-2 text-xs font-semibold rounded-lg transition-colors ${btn}`}>
            Mark as {nextStatus[inc.status].replace('_',' ')}
          </button>
          <button onClick={onClose} className={`px-4 py-2 text-xs border rounded-lg ${clsBtn}`}>Close</button>
        </div>
      )}
    </div>
  )
}

export default function IncidentManagement() {
  const [incidents, setIncidents]     = useState(MOCK_INCIDENTS)
  const [statusFilter, setStatusFilter] = useState('ALL')
  const [sevFilter, setSevFilter]     = useState('ALL')
  const [timeRange, setTimeRange]     = useState('24h')
  const [selected, setSelected]       = useState(null)
  const { isDark } = useTheme()

  const SEV    = isDark ? SEV_D    : SEV_L
  const STATUS = isDark ? STATUS_D : STATUS_L

  const th = {
    page:    isDark ? 'bg-[#020817] text-slate-100' : 'bg-slate-50 text-slate-900',
    nav:     isDark ? 'border-b border-slate-800' : 'border-b border-slate-200',
    navLink: isDark ? 'text-slate-500 hover:text-cyan-400' : 'text-slate-400 hover:text-blue-600',
    navAct:  isDark ? 'text-cyan-400 font-semibold border-b border-cyan-500 pb-px' : 'text-blue-600 font-semibold border-b border-blue-500 pb-px',
    h1:      isDark ? 'text-slate-100' : 'text-slate-900',
    sub:     isDark ? 'text-slate-500' : 'text-slate-500',
    createBtn: isDark ? 'bg-cyan-800 hover:bg-cyan-700 text-cyan-100' : 'bg-blue-600 hover:bg-blue-700 text-white',
    filterBar: isDark ? 'bg-slate-900/40 border-slate-800' : 'bg-white border-slate-200',
    filterLbl: isDark ? 'text-slate-500' : 'text-slate-400',
    filterBtn: (active) => active
      ? (isDark ? 'bg-cyan-800 text-cyan-100' : 'bg-blue-600 text-white')
      : (isDark ? 'text-slate-400 hover:text-slate-200' : 'text-slate-500 hover:text-slate-800'),
    sep:     isDark ? 'bg-slate-700' : 'bg-slate-300',
    select:  isDark ? 'bg-slate-800 border-slate-700 text-slate-200 focus:border-cyan-600' : 'bg-white border-slate-300 text-slate-700 focus:border-blue-400',
    count:   isDark ? 'text-slate-600' : 'text-slate-400',
    tbl:     isDark ? 'border-slate-800' : 'border-slate-200',
    thead:   isDark ? 'bg-slate-900/80 border-b border-slate-800 text-slate-500' : 'bg-slate-100 border-b border-slate-200 text-slate-400',
    tbody:   isDark ? 'divide-slate-800/60' : 'divide-slate-100',
    row:     isDark ? 'hover:bg-slate-800/40' : 'hover:bg-slate-50',
    idCls:   isDark ? 'text-cyan-400' : 'text-blue-600',
    atmId:   isDark ? 'text-slate-200' : 'text-slate-800',
    branch:  isDark ? 'text-slate-500' : 'text-slate-500',
    type:    isDark ? 'text-slate-300' : 'text-slate-700',
    asgn:    isDark ? 'text-slate-400' : 'text-slate-600',
    asgnNone:isDark ? 'text-slate-600' : 'text-slate-400',
    time:    isDark ? 'text-slate-500' : 'text-slate-400',
    detBtn:  isDark ? 'text-cyan-500 hover:text-cyan-300' : 'text-blue-500 hover:text-blue-700',
    overlay: isDark ? 'bg-black/40' : 'bg-black/20',
  }

  function changeStatus(id, newStatus) {
    setIncidents(prev => prev.map(i => i.id === id ? { ...i, status: newStatus } : i))
    setSelected(prev => prev?.id === id ? { ...prev, status: newStatus } : prev)
  }

  const filtered = useMemo(() => incidents.filter(i => {
    if (statusFilter !== 'ALL' && i.status !== statusFilter) return false
    if (sevFilter    !== 'ALL' && i.severity !== sevFilter)  return false
    return true
  }), [incidents, statusFilter, sevFilter])

  const counts = {
    open:     incidents.filter(i => i.status === 'OPEN').length,
    inProg:   incidents.filter(i => i.status === 'IN_PROGRESS').length,
    resolved: incidents.filter(i => ['RESOLVED','CLOSED'].includes(i.status)).length,
    breached: incidents.filter(i => !['RESOLVED','CLOSED'].includes(i.status) && new Date(i.sla_breach_at) < Date.now()).length,
  }

  const summaryCards = [
    { label:'Open',         value: counts.open,     color:'text-red-500',     bg: isDark ? 'border-red-800/40 bg-red-950/20' : 'border-red-200 bg-red-50' },
    { label:'In Progress',  value: counts.inProg,   color:'text-violet-500',  bg: isDark ? 'border-violet-800/40 bg-violet-950/20' : 'border-violet-200 bg-violet-50' },
    { label:'Resolved',     value: counts.resolved, color:'text-emerald-500', bg: isDark ? 'border-emerald-800/30 bg-emerald-950/10' : 'border-emerald-200 bg-emerald-50' },
    { label:'SLA Breached', value: counts.breached, color: counts.breached > 0 ? 'text-red-500 animate-pulse' : (isDark ? 'text-slate-500' : 'text-slate-400'), bg: counts.breached > 0 ? (isDark ? 'border-red-700/50 bg-red-950/30' : 'border-red-200 bg-red-50') : (isDark ? 'border-slate-800 bg-slate-900/30' : 'border-slate-200 bg-white') },
  ]

  return (
    <EJShell>
      <div className={`min-h-full ${th.page}`}>
        <div className={`${th.nav} px-6 py-2 flex items-center gap-6`}>
          <Link to="/ej" className={`text-xs ${th.navLink}`}>← EJ Dashboard</Link>
          <span className={`text-xs ${th.navAct}`}>Incident Management</span>
          <Link to="/ej/portal" className={`text-xs ${th.navLink}`}>Manager Portal</Link>
        </div>

        <div className="px-6 py-4 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h1 className={`text-lg font-bold ${th.h1}`}>Incident Management</h1>
              <p className={`text-xs ${th.sub} mt-0.5`}>Full lifecycle tracking · SLA monitoring · Escalation management</p>
            </div>
            <button className={`px-4 py-2 text-xs font-semibold rounded-lg transition-colors ${th.createBtn}`}>
              + Create Incident
            </button>
          </div>

          {/* Summary cards */}
          <div className="grid grid-cols-4 gap-3">
            {summaryCards.map(({ label, value, color, bg }) => (
              <div key={label} className={`border rounded-xl px-4 py-3 text-center ${bg}`}>
                <div className={`text-xs ${th.sub} uppercase tracking-wider mb-1`}>{label}</div>
                <div className={`text-3xl font-bold font-mono ${color}`}>{value}</div>
              </div>
            ))}
          </div>

          {/* Filters */}
          <div className={`flex items-center gap-3 border rounded-lg px-4 py-2 ${th.filterBar}`}>
            <span className={`text-xs uppercase tracking-wider ${th.filterLbl}`}>Filter:</span>
            <div className="flex gap-1">
              {TIME_RANGES.map(r => (
                <button key={r} onClick={() => setTimeRange(r)}
                  className={`text-xs px-2.5 py-1 rounded font-mono transition-colors ${th.filterBtn(timeRange === r)}`}>
                  {r}
                </button>
              ))}
            </div>
            <div className={`w-px h-4 ${th.sep}`} />
            <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}
              className={`border rounded px-2 py-1 text-xs focus:outline-none ${th.select}`}>
              {STATUS_OPTIONS.map(s => <option key={s}>{s}</option>)}
            </select>
            <select value={sevFilter} onChange={e => setSevFilter(e.target.value)}
              className={`border rounded px-2 py-1 text-xs focus:outline-none ${th.select}`}>
              {SEV_OPTIONS.map(s => <option key={s}>{s}</option>)}
            </select>
            <span className={`ml-auto text-xs ${th.count}`}>{filtered.length} incidents</span>
          </div>

          {/* Table */}
          <div className={`border rounded-xl overflow-hidden ${th.tbl}`}>
            <table className="w-full text-xs">
              <thead className={th.thead}>
                <tr>
                  {['Incident ID','ATM / Branch','Type','Severity','Status','Assigned To','Opened','SLA',''].map(h => (
                    <th key={h} className="px-3 py-2.5 text-left text-[10px] font-semibold uppercase tracking-wider whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className={`divide-y ${th.tbody}`}>
                {filtered.map(inc => {
                  const sla = getSLA(inc)
                  return (
                    <tr key={inc.id} onClick={() => setSelected(inc)}
                      className={`cursor-pointer transition-colors ${th.row}`}>
                      <td className={`px-3 py-2.5 font-mono whitespace-nowrap ${th.idCls}`}>{inc.id}</td>
                      <td className="px-3 py-2.5">
                        <div className={`font-mono ${th.atmId}`}>{inc.atm_id}</div>
                        <div className={th.branch}>{inc.branch}, {inc.city}</div>
                      </td>
                      <td className={`px-3 py-2.5 max-w-[160px] truncate ${th.type}`}>{inc.type}</td>
                      <td className="px-3 py-2.5">
                        <span className={`px-2 py-0.5 rounded-full border text-[10px] font-semibold ${SEV[inc.severity]}`}>{inc.severity}</span>
                      </td>
                      <td className="px-3 py-2.5">
                        <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${STATUS[inc.status]}`}>{inc.status.replace('_',' ')}</span>
                      </td>
                      <td className={`px-3 py-2.5 ${inc.assigned_to ? th.asgn : th.asgnNone}`}>{inc.assigned_to || '—unassigned—'}</td>
                      <td className={`px-3 py-2.5 font-mono whitespace-nowrap ${th.time}`}>
                        {new Date(inc.opened).toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit',hour12:false})} IST
                      </td>
                      <td className={`px-3 py-2.5 font-mono text-[11px] whitespace-nowrap ${sla.cls}`}>{sla.label}</td>
                      <td className="px-3 py-2.5">
                        <button className={`text-[10px] transition-colors ${th.detBtn}`}>Details →</button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>

        {selected && (
          <>
            <div className={`fixed inset-0 ${th.overlay} z-40`} onClick={() => setSelected(null)} />
            <DetailPanel inc={selected} onClose={() => setSelected(null)} onStatusChange={changeStatus} isDark={isDark} />
          </>
        )}
      </div>
    </EJShell>
  )
}

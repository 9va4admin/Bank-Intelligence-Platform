import { useState } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'

const MOCK_MICR_PREFIXES = [
  { id: 1, prefix: '400002',  bank: 'State Bank of India',          branch: 'Fort, Mumbai',           zone: 'MUMBAI', grid: 'CTS-MUMBAI', status: 'ACTIVE'   },
  { id: 2, prefix: '400004',  bank: 'HDFC Bank',                    branch: 'Nariman Point, Mumbai',  zone: 'MUMBAI', grid: 'CTS-MUMBAI', status: 'ACTIVE'   },
  { id: 3, prefix: '400229',  bank: 'ICICI Bank',                   branch: 'BKC, Mumbai',            zone: 'MUMBAI', grid: 'CTS-MUMBAI', status: 'ACTIVE'   },
  { id: 4, prefix: '110002',  bank: 'Punjab National Bank',         branch: 'Connaught Place, Delhi', zone: 'DELHI',  grid: 'CTS-DELHI',  status: 'ACTIVE'   },
  { id: 5, prefix: '110029',  bank: 'Axis Bank',                    branch: 'Nehru Place, Delhi',     zone: 'DELHI',  grid: 'CTS-DELHI',  status: 'ACTIVE'   },
  { id: 6, prefix: '560001',  bank: 'Canara Bank',                  branch: 'MG Road, Bengaluru',     zone: 'CHENNAI',grid: 'CTS-CHENNAI',status: 'ACTIVE'   },
  { id: 7, prefix: '380001',  bank: 'Bank of Baroda',               branch: 'CG Road, Ahmedabad',     zone: 'MUMBAI', grid: 'CTS-MUMBAI', status: 'ACTIVE'   },
  { id: 8, prefix: '999001',  bank: 'TEST BANK (UAT)',              branch: 'Test Branch',            zone: 'MUMBAI', grid: 'CTS-MUMBAI', status: 'INACTIVE' },
]

const ZONES = ['ALL', 'MUMBAI', 'DELHI', 'CHENNAI']

export default function CTSMICRPrefixes() {
  const { bankId, bankName, bankIfsc, bankType, isSB, isSMB } = useBankContext()
  const { isDark } = useTheme()
  const [search, setSearch] = useState('')
  const [zone, setZone] = useState('ALL')
  const [editing, setEditing] = useState(null)

  const th = {
    page:    isDark ? 'bg-transparent' : 'bg-slate-50',
    card:    isDark ? 'bg-white/3 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    row:     isDark ? 'border-white/5 hover:bg-white/3' : 'border-slate-100 hover:bg-slate-50',
    input:   isDark ? 'bg-white/5 border-white/10 text-white placeholder-slate-500 focus:border-cyan-500' : 'bg-white border-slate-300 text-slate-900 placeholder-slate-400 focus:border-cyan-500',
    badge:   isDark ? 'bg-white/5 text-slate-300' : 'bg-slate-100 text-slate-600',
  }

  const filtered = MOCK_MICR_PREFIXES.filter(m =>
    (zone === 'ALL' || m.zone === zone) &&
    (m.prefix.includes(search) || m.bank.toLowerCase().includes(search.toLowerCase()) || m.branch.toLowerCase().includes(search.toLowerCase()))
  )

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>MICR Prefix Table</h1>
            <p className={`text-xs mt-0.5 ${th.muted}`}>6-digit MICR codes used to route inward cheques to drawee banks</p>
          </div>
          <button className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${isDark ? 'bg-cyan-600 hover:bg-cyan-500 text-white' : 'bg-cyan-600 hover:bg-cyan-700 text-white'}`}>
            + Add Prefix
          </button>
        </div>

        {/* Filter bar */}
        <div className="flex gap-3 mb-4">
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search prefix, bank, or branch…"
            className={`flex-1 h-8 px-3 rounded-lg border text-xs outline-none transition-colors ${th.input}`}
          />
          <div className="flex gap-1.5">
            {ZONES.map(z => (
              <button
                key={z}
                onClick={() => setZone(z)}
                className={`px-3 h-8 rounded-lg text-xs font-medium transition-all border ${zone === z ? 'bg-cyan-600 text-white border-cyan-600' : `${th.card} ${th.muted} hover:${th.body}`}`}
              >
                {z}
              </button>
            ))}
          </div>
        </div>

        {/* Info callout */}
        <div className={`mb-4 rounded-lg border px-4 py-3 text-xs ${isDark ? 'bg-amber-900/20 border-amber-700/40 text-amber-300' : 'bg-amber-50 border-amber-200 text-amber-800'}`}>
          <span className="font-semibold">MICR Routing Note:</span> The first 6 digits of the MICR code identify the drawee bank and branch. Changes here affect real-time NGCH routing. Incorrect entries will cause cheque returns. Dual-approval required for any modification.
        </div>

        {/* Table */}
        <div className={`rounded-xl border overflow-hidden ${th.card}`}>
          <table className="w-full text-xs">
            <thead>
              <tr className={`border-b ${th.divider}`}>
                {['MICR Prefix', 'Drawee Bank', 'Branch', 'Zone', 'Grid', 'Status', ''].map(h => (
                  <th key={h} className={`px-4 py-3 text-left font-medium ${th.muted}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map(m => (
                <tr key={m.id} className={`border-b transition-colors ${th.row}`}>
                  <td className={`px-4 py-3 font-mono font-semibold tracking-widest ${th.heading}`}>{m.prefix}</td>
                  <td className={`px-4 py-3 ${th.body}`}>{m.bank}</td>
                  <td className={`px-4 py-3 ${th.muted}`}>{m.branch}</td>
                  <td className="px-4 py-3">
                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${th.badge}`}>{m.zone}</span>
                  </td>
                  <td className={`px-4 py-3 text-[11px] font-mono ${th.muted}`}>{m.grid}</td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${m.status === 'ACTIVE' ? (isDark ? 'bg-emerald-900/40 text-emerald-300' : 'bg-emerald-100 text-emerald-700') : (isDark ? 'bg-slate-700 text-slate-400' : 'bg-slate-100 text-slate-500')}`}>
                      {m.status}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => setEditing(m)}
                      className={`text-[11px] ${isDark ? 'text-cyan-400 hover:text-cyan-300' : 'text-cyan-600 hover:text-cyan-700'}`}
                    >
                      Edit
                    </button>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={7} className={`px-4 py-8 text-center text-xs ${th.muted}`}>No MICR prefixes match the current filter.</td>
                </tr>
              )}
            </tbody>
          </table>
          <div className={`px-4 py-2 border-t text-xs ${th.divider} ${th.muted}`}>
            {filtered.length} of {MOCK_MICR_PREFIXES.length} prefixes
          </div>
        </div>

        {/* Edit modal */}
        {editing && (
          <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.6)' }}>
            <div className={`w-full max-w-md rounded-2xl border p-6 shadow-2xl ${isDark ? 'bg-[#0e1428] border-white/10' : 'bg-white border-slate-200'}`}>
              <div className="flex items-center justify-between mb-4">
                <h3 className={`font-semibold ${th.heading}`}>Edit MICR Prefix — {editing.prefix}</h3>
                <button onClick={() => setEditing(null)} className={th.muted}>✕</button>
              </div>
              <div className="space-y-3">
                {[['Bank Name', editing.bank], ['Branch', editing.branch], ['Grid', editing.grid]].map(([label, val]) => (
                  <div key={label}>
                    <label className={`text-xs ${th.muted}`}>{label}</label>
                    <input defaultValue={val} className={`w-full mt-1 h-8 px-3 rounded-lg border text-xs outline-none transition-colors ${th.input}`} />
                  </div>
                ))}
              </div>
              <div className={`mt-4 p-3 rounded-lg text-xs ${isDark ? 'bg-amber-900/20 border border-amber-700/40 text-amber-300' : 'bg-amber-50 border border-amber-200 text-amber-800'}`}>
                ⚠ Changes require maker-checker approval before taking effect.
              </div>
              <div className="flex gap-2 mt-4">
                <button onClick={() => setEditing(null)} className={`flex-1 px-3 py-2 rounded-lg text-xs font-medium ${isDark ? 'bg-white/5 text-slate-300 hover:bg-white/10' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'}`}>Cancel</button>
                <button onClick={() => setEditing(null)} className="flex-1 px-3 py-2 rounded-lg text-xs font-medium bg-cyan-600 hover:bg-cyan-500 text-white">Submit for Approval</button>
              </div>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  )
}

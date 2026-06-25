import { useState } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'

const MOCK_SUB_MEMBERS = [
  {
    id: 'SMB001',
    name: 'Saraswat Co-operative Bank',
    ifsc_prefix: 'SRCB',
    sponsor_account: 'SVCB00000001',
    clearing_zones: ['MUMBAI'],
    status: 'ACTIVE',
    daily_limit: 5000,
    cheques_today: 312,
    risk_level: 'LOW',
    onboarded: '2026-01-15',
    contact: 'ops@saraswat.coop',
  },
  {
    id: 'SMB002',
    name: 'Cosmos Co-operative Bank',
    ifsc_prefix: 'COSB',
    sponsor_account: 'SVCB00000002',
    clearing_zones: ['MUMBAI', 'PUNE'],
    risk_level: 'LOW',
    status: 'ACTIVE',
    daily_limit: 3000,
    cheques_today: 187,
    onboarded: '2026-02-20',
    contact: 'clearing@cosmosbank.in',
  },
  {
    id: 'SMB003',
    name: 'Janata Sahakari Bank',
    ifsc_prefix: 'JSBP',
    sponsor_account: 'SVCB00000003',
    clearing_zones: ['PUNE'],
    status: 'SUSPENDED',
    daily_limit: 2000,
    cheques_today: 0,
    risk_level: 'HIGH',
    onboarded: '2026-03-05',
    contact: 'mgmt@janatasahakari.co.in',
  },
]

const RISK_COLORS_D = { LOW: 'bg-emerald-900/40 text-emerald-300 border-emerald-700/50', MEDIUM: 'bg-amber-900/40 text-amber-300 border-amber-700/50', HIGH: 'bg-red-900/40 text-red-300 border-red-700/50' }
const RISK_COLORS_L = { LOW: 'bg-emerald-100 text-emerald-700 border-emerald-300', MEDIUM: 'bg-amber-100 text-amber-700 border-amber-300', HIGH: 'bg-red-100 text-red-700 border-red-300' }

export default function CTSSubMemberBanks() {
  const { isDark } = useTheme()
  const [selected, setSelected] = useState(null)
  const [showAdd, setShowAdd] = useState(false)

  const th = {
    page:    isDark ? 'bg-transparent' : 'bg-slate-50',
    card:    isDark ? 'bg-white/3 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    row:     isDark ? 'border-white/5 hover:bg-white/3' : 'border-slate-100 hover:bg-slate-50',
    badge:   isDark ? 'bg-white/5 text-slate-300' : 'bg-slate-100 text-slate-600',
    input:   isDark ? 'bg-white/5 border-white/10 text-white placeholder-slate-500 focus:border-cyan-500' : 'bg-white border-slate-300 text-slate-900 placeholder-slate-400 focus:border-cyan-500',
    btn:     isDark ? 'bg-cyan-600 hover:bg-cyan-500 text-white' : 'bg-cyan-600 hover:bg-cyan-700 text-white',
  }
  const RISK = isDark ? RISK_COLORS_D : RISK_COLORS_L

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>Sub-Member Banks</h1>
            <p className={`text-xs mt-0.5 ${th.muted}`}>Banks sponsored by this institution for CTS clearing access</p>
          </div>
          <button
            onClick={() => setShowAdd(true)}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${th.btn}`}
          >
            <span>+ Onboard Sub-Member</span>
          </button>
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-4 gap-3 mb-5">
          {[
            { label: 'Total Sub-Members', value: MOCK_SUB_MEMBERS.length },
            { label: 'Active', value: MOCK_SUB_MEMBERS.filter(s => s.status === 'ACTIVE').length },
            { label: 'Cheques Today', value: MOCK_SUB_MEMBERS.reduce((a, s) => a + s.cheques_today, 0).toLocaleString() },
            { label: 'Suspended', value: MOCK_SUB_MEMBERS.filter(s => s.status === 'SUSPENDED').length },
          ].map(({ label, value }) => (
            <div key={label} className={`rounded-xl border px-4 py-3 ${th.card}`}>
              <div className={`text-[11px] ${th.muted}`}>{label}</div>
              <div className={`text-xl font-bold mt-0.5 ${th.heading}`}>{value}</div>
            </div>
          ))}
        </div>

        {/* Table */}
        <div className={`rounded-xl border overflow-hidden ${th.card}`}>
          <table className="w-full text-xs">
            <thead>
              <tr className={`border-b ${th.divider}`}>
                {['Bank Name', 'IFSC Prefix', 'Clearing Zones', 'Daily Limit', 'Today', 'Risk', 'Status', ''].map(h => (
                  <th key={h} className={`px-4 py-3 text-left font-medium ${th.muted}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {MOCK_SUB_MEMBERS.map(sm => (
                <tr key={sm.id} className={`border-b cursor-pointer transition-colors ${th.row}`} onClick={() => setSelected(sm)}>
                  <td className={`px-4 py-3 font-medium ${th.heading}`}>{sm.name}</td>
                  <td className={`px-4 py-3 font-mono ${th.body}`}>{sm.ifsc_prefix}</td>
                  <td className="px-4 py-3">
                    <div className="flex gap-1 flex-wrap">
                      {sm.clearing_zones.map(z => (
                        <span key={z} className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${th.badge}`}>{z}</span>
                      ))}
                    </div>
                  </td>
                  <td className={`px-4 py-3 ${th.body}`}>{sm.daily_limit.toLocaleString()} / day</td>
                  <td className={`px-4 py-3 ${th.body}`}>{sm.cheques_today}</td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded-full border text-[10px] font-semibold ${RISK[sm.risk_level]}`}>{sm.risk_level}</span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${sm.status === 'ACTIVE' ? (isDark ? 'bg-emerald-900/40 text-emerald-300' : 'bg-emerald-100 text-emerald-700') : (isDark ? 'bg-red-900/40 text-red-300' : 'bg-red-100 text-red-700')}`}>
                      {sm.status}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <button className={`text-[11px] ${isDark ? 'text-cyan-400 hover:text-cyan-300' : 'text-cyan-600 hover:text-cyan-700'}`}>View →</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Detail panel */}
        {selected && (
          <div className={`mt-5 rounded-xl border p-5 ${th.card}`}>
            <div className="flex items-center justify-between mb-4">
              <h2 className={`font-semibold ${th.heading}`}>{selected.name}</h2>
              <button onClick={() => setSelected(null)} className={`text-xs ${th.muted} hover:${th.body}`}>✕ Close</button>
            </div>
            <div className="grid grid-cols-3 gap-4 text-xs">
              {[
                ['Sub-Member ID', selected.id],
                ['IFSC Prefix', selected.ifsc_prefix],
                ['Sponsor Account', selected.sponsor_account],
                ['Onboarded', selected.onboarded],
                ['Contact', selected.contact],
                ['Risk Level', selected.risk_level],
              ].map(([label, val]) => (
                <div key={label}>
                  <div className={th.muted}>{label}</div>
                  <div className={`font-medium mt-0.5 ${th.heading}`}>{val}</div>
                </div>
              ))}
            </div>
            <div className={`mt-4 pt-4 border-t ${th.divider} flex gap-3`}>
              <button className={`px-3 py-1.5 rounded-lg text-xs font-medium ${selected.status === 'ACTIVE' ? (isDark ? 'bg-red-900/40 text-red-300 hover:bg-red-900/60' : 'bg-red-100 text-red-700 hover:bg-red-200') : th.btn}`}>
                {selected.status === 'ACTIVE' ? 'Suspend' : 'Reactivate'}
              </button>
              <button className={`px-3 py-1.5 rounded-lg text-xs font-medium ${isDark ? 'bg-white/5 text-slate-300 hover:bg-white/10' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'}`}>
                Edit Limits
              </button>
              <button className={`px-3 py-1.5 rounded-lg text-xs font-medium ${isDark ? 'bg-white/5 text-slate-300 hover:bg-white/10' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'}`}>
                View Risk Report
              </button>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  )
}

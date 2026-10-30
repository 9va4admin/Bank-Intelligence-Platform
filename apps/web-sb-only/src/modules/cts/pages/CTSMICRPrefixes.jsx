import { useState } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'
import { msg } from '../../../shared/messages'

const MOCK_MICR_PREFIXES = [
  { id: 1, prefix: '400002',  bank: 'State Bank of India',          branch: 'Fort, Mumbai', status: 'ACTIVE'   },
  { id: 2, prefix: '400004',  bank: 'HDFC Bank',                    branch: 'Nariman Point, Mumbai', status: 'ACTIVE'   },
  { id: 3, prefix: '400229',  bank: 'ICICI Bank',                   branch: 'BKC, Mumbai', status: 'ACTIVE'   },
  { id: 4, prefix: '110002',  bank: 'Punjab National Bank',         branch: 'Connaught Place, Delhi', status: 'ACTIVE'   },
  { id: 5, prefix: '110029',  bank: 'Axis Bank',                    branch: 'Nehru Place, Delhi', status: 'ACTIVE'   },
  { id: 6, prefix: '560001',  bank: 'Canara Bank',                  branch: 'MG Road, Bengaluru', status: 'ACTIVE'   },
  { id: 7, prefix: '380001',  bank: 'Bank of Baroda',               branch: 'CG Road, Ahmedabad', status: 'ACTIVE'   },
  { id: 8, prefix: '999001',  bank: 'TEST BANK (UAT)',              branch: 'Test Branch', status: 'INACTIVE' },
]

export default function CTSMICRPrefixes() {
  const { bankId, bankName, bankIfsc, bankType, isSB, isSMB } = useBankContext()
  const { isDark } = useTheme()
  const [search, setSearch] = useState('')
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
    (m.prefix.includes(search) || m.bank.toLowerCase().includes(search.toLowerCase()) || m.branch.toLowerCase().includes(search.toLowerCase()))
  )

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>{msg('UI_APPSHELL_MICR_PREFIX_TABLE')}</h1>
            <p className={`text-xs mt-0.5 ${th.muted}`}>{msg('UI_MICRPREFIXES_6_DIGIT_MICR_CODES_USED_2')}</p>
          </div>
          <button className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${isDark ? 'bg-cyan-600 hover:bg-cyan-500 text-white' : 'bg-cyan-600 hover:bg-cyan-700 text-white'}`}>
           {msg('UI_MICRPREFIXES_ADD_PREFIX_2')}
          </button>
        </div>

        {/* Filter bar */}
        <div className="flex gap-3 mb-4">
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder={msg('UI_MICRPREFIXES_SEARCH_PREFIX_BANK_OR_BRANCH_2')}
            className={`flex-1 h-8 px-3 rounded-lg border text-xs outline-none transition-colors ${th.input}`}
          />
        </div>

        {/* Info callout */}
        <div className={`mb-4 rounded-lg border px-4 py-3 text-xs ${isDark ? 'bg-amber-900/20 border-amber-700/40 text-amber-300' : 'bg-amber-50 border-amber-200 text-amber-800'}`}>
          <span className="font-semibold">{msg('UI_MICRPREFIXES_MICR_ROUTING_NOTE_2')}</span> {msg('UI_MICRPREFIXES_THE_FIRST_6_DIGITS_OF_2')}
        </div>

        {/* Table */}
        <div className={`rounded-xl border overflow-hidden ${th.card}`}>
          <table className="w-full text-xs">
            <thead>
              <tr className={`border-b ${th.divider}`}>
                {[msg('UI_MICRPREFIXES_MICR_PREFIX_2'), msg('UI_COMMON_DRAWEE_BANK_2'), msg('UI_COMMON_BRANCH'), msg('UI_COMMON_STATUS_2'), ''].map(h => (
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
                    <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${m.status === 'ACTIVE' ? (isDark ? 'bg-emerald-900/40 text-emerald-300' : 'bg-emerald-100 text-emerald-700') : (isDark ? 'bg-slate-700 text-slate-400' : 'bg-slate-100 text-slate-500')}`}>
                      {m.status}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => setEditing(m)}
                      className={`text-[11px] ${isDark ? 'text-cyan-400 hover:text-cyan-300' : 'text-cyan-600 hover:text-cyan-700'}`}
                    >
                     {msg('UI_COMMON_EDIT_2')}
                    </button>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={5} className={`px-4 py-8 text-center text-xs ${th.muted}`}>{msg('UI_MICRPREFIXES_NO_MICR_PREFIXES_MATCH_THE_2')}</td>
                </tr>
              )}
            </tbody>
          </table>
          <div className={`px-4 py-2 border-t text-xs ${th.divider} ${th.muted}`}>
            {msg('UI_MICRPREFIXES_OF_PREFIXES_2', { count: filtered.length, count2: MOCK_MICR_PREFIXES.length })}
          </div>
        </div>

        {/* Edit modal */}
        {editing && (
          <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.6)' }}>
            <div className={`w-full max-w-md rounded-2xl border p-6 shadow-2xl ${isDark ? 'bg-[#0e1428] border-white/10' : 'bg-white border-slate-200'}`}>
              <div className="flex items-center justify-between mb-4">
                <h3 className={`font-semibold ${th.heading}`}>{msg('UI_MICRPREFIXES_EDIT_MICR_PREFIX_2', { prefix: editing.prefix })}</h3>
                <button onClick={() => setEditing(null)} className={th.muted}>✕</button>
              </div>
              <div className="space-y-3">
                {[['Bank Name', editing.bank], ['Branch', editing.branch], ['Status', editing.status]].map(([label, val]) => (
                  <div key={label}>
                    <label className={`text-xs ${th.muted}`}>{label}</label>
                    <input defaultValue={val} className={`w-full mt-1 h-8 px-3 rounded-lg border text-xs outline-none transition-colors ${th.input}`} />
                  </div>
                ))}
              </div>
              <div className={`mt-4 p-3 rounded-lg text-xs ${isDark ? 'bg-amber-900/20 border border-amber-700/40 text-amber-300' : 'bg-amber-50 border border-amber-200 text-amber-800'}`}>
               {msg('UI_MICRPREFIXES_CHANGES_REQUIRE_MAKER_CHECKER_APPROV_2')}
              </div>
              <div className="flex gap-2 mt-4">
                <button onClick={() => setEditing(null)} className={`flex-1 px-3 py-2 rounded-lg text-xs font-medium ${isDark ? 'bg-white/5 text-slate-300 hover:bg-white/10' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'}`}>{msg('UI_COMMON_CANCEL_2')}</button>
                <button onClick={() => setEditing(null)} className="flex-1 px-3 py-2 rounded-lg text-xs font-medium bg-cyan-600 hover:bg-cyan-500 text-white">{msg('UI_COMMON_SUBMIT_FOR_APPROVAL')}</button>
              </div>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  )
}

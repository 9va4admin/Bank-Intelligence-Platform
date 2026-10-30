import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'
import { msg } from '../../../shared/messages'

function OnboardModal({ isDark, onClose, bankId }) {
  const th = {
    overlay: 'fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm',
    modal:   isDark ? 'bg-[#0f172a] border border-white/10 rounded-2xl w-full max-w-lg p-6 shadow-2xl' : 'bg-white border border-slate-200 rounded-2xl w-full max-w-lg p-6 shadow-2xl',
    heading: isDark ? 'text-white' : 'text-slate-900',
    label:   isDark ? 'text-slate-400' : 'text-slate-500',
    input:   isDark ? 'bg-white/5 border-white/10 text-white placeholder-slate-500 focus:border-cyan-500 focus:outline-none' : 'bg-white border-slate-300 text-slate-900 placeholder-slate-400 focus:border-cyan-500 focus:outline-none',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    btn:     isDark ? 'bg-cyan-600 hover:bg-cyan-500 text-white' : 'bg-cyan-600 hover:bg-cyan-700 text-white',
    cancel:  isDark ? 'bg-white/5 text-slate-300 hover:bg-white/10' : 'bg-slate-100 text-slate-700 hover:bg-slate-200',
  }

  const [form, setForm] = useState({
    name: '', ifsc_prefix: '', sponsor_account: '', contact: '',
    daily_limit: '', risk_level: 'LOW',
  })
  const [submitted, setSubmitted] = useState(false)
  const [submitError, setSubmitError] = useState(null)

  const registerMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch('/api/v1/cts/smb', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          bank_name: form.name,
          ifsc_prefix: form.ifsc_prefix,
          micr_prefix: form.ifsc_prefix,
          sponsor_account_number: form.sponsor_account,
          contact_email: form.contact,
          daily_presentment_limit: parseInt(form.daily_limit) || 1000,
          risk_level: form.risk_level,
          return_rate_threshold: 0.15,
          soft_hold_threshold: 0.25,
        }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: msg('UI_SUBMEMBERBANKS_REGISTRATION_FAILED_2') }))
        throw new Error(err.detail || msg('UI_SUBMEMBERBANKS_REGISTRATION_FAILED_2'))
      }
      return res.json()
    },
    onSuccess: () => {
      setSubmitted(true)
      setTimeout(onClose, 1500)
    },
    onError: (err) => {
      setSubmitError(err.message)
    },
  })

  const handleSubmit = (e) => {
    e.preventDefault()
    setSubmitError(null)
    registerMutation.mutate()
  }

  return (
    <div className={th.overlay} onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className={th.modal}>
        <div className="flex items-center justify-between mb-5">
          <div>
            <h2 className={`text-base font-semibold ${th.heading}`}>{msg('UI_SUBMEMBERBANKS_ONBOARD_SUB_MEMBER_BANK_2')}</h2>
            <p className={`text-xs mt-0.5 ${th.muted}`}>{msg('UI_SUBMEMBERBANKS_REGISTER_A_NEW_BANK_FOR_2')}</p>
          </div>
          <button onClick={onClose} className={`text-xs ${th.muted} hover:${th.heading} px-2`}>✕</button>
        </div>

        {submitted ? (
          <div className="py-8 text-center">
            <div className="text-2xl mb-2">✓</div>
            <p className={`text-sm font-medium ${th.heading}`}>{msg('UI_SUBMEMBERBANKS_ONBOARDING_REQUEST_SUBMITTED_2')}</p>
            <p className={`text-xs mt-1 ${th.muted}`}>{msg('UI_SUBMEMBERBANKS_COMPLIANCE_REVIEW_WILL_BE_INITIATED_2')}</p>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4 text-xs">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={`block mb-1 ${th.label}`}>{msg('UI_SUBMEMBERBANKS_BANK_NAME_3')}</label>
                <input required className={`w-full rounded-lg border px-3 py-2 text-xs ${th.input}`}
                  placeholder={msg('UI_SUBMEMBERBANKS_E_G_JANATA_CO_OPERATIVE_2')}
                  value={form.name} onChange={e => setForm(f => ({...f, name: e.target.value}))} />
              </div>
              <div>
                <label className={`block mb-1 ${th.label}`}>{msg('UI_SUBMEMBERBANKS_IFSC_PREFIX_3')}</label>
                <input required maxLength={4} className={`w-full rounded-lg border px-3 py-2 text-xs font-mono uppercase ${th.input}`}
                  placeholder={msg('UI_SUBMEMBERBANKS_E_G_JNCB_2')}
                  value={form.ifsc_prefix} onChange={e => setForm(f => ({...f, ifsc_prefix: e.target.value.toUpperCase()}))} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={`block mb-1 ${th.label}`}>{msg('UI_SUBMEMBERBANKS_SPONSOR_ACCOUNT_2')}</label>
                <input required className={`w-full rounded-lg border px-3 py-2 text-xs font-mono ${th.input}`}
                  placeholder="SVCB00000001"
                  value={form.sponsor_account} onChange={e => setForm(f => ({...f, sponsor_account: e.target.value}))} />
              </div>
              <div>
                <label className={`block mb-1 ${th.label}`}>{msg('UI_SUBMEMBERBANKS_DAILY_CHEQUE_LIMIT_2')}</label>
                <input required type="number" min={1} className={`w-full rounded-lg border px-3 py-2 text-xs ${th.input}`}
                  placeholder="5000"
                  value={form.daily_limit} onChange={e => setForm(f => ({...f, daily_limit: e.target.value}))} />
              </div>
            </div>
            <div>
              <label className={`block mb-1 ${th.label}`}>{msg('UI_SUBMEMBERBANKS_OPS_CONTACT_EMAIL_2')}</label>
              <input required type="email" className={`w-full rounded-lg border px-3 py-2 text-xs ${th.input}`}
                placeholder="ops@subbank.coop"
                value={form.contact} onChange={e => setForm(f => ({...f, contact: e.target.value}))} />
            </div>
            <div>
              <label className={`block mb-1 ${th.label}`}>{msg('UI_SUBMEMBERBANKS_INITIAL_RISK_ASSESSMENT_2')}</label>
              <div className="flex gap-2">
                {['LOW', 'MEDIUM', 'HIGH'].map(r => (
                  <button type="button" key={r} onClick={() => setForm(f => ({...f, risk_level: r}))}
                    className={`px-3 py-1 rounded-lg border text-[10px] font-semibold transition-all ${
                      form.risk_level === r
                        ? (r === 'LOW' ? 'bg-emerald-600 border-emerald-600 text-white' : r === 'MEDIUM' ? 'bg-amber-500 border-amber-500 text-white' : 'bg-red-600 border-red-600 text-white')
                        : (isDark ? 'bg-white/5 border-white/10 text-slate-400' : 'bg-slate-100 border-slate-300 text-slate-500')
                    }`}>{r}</button>
                ))}
              </div>
            </div>
            {submitError && (
              <div className="text-xs text-red-400 bg-red-900/20 border border-red-700/30 rounded-lg px-3 py-2">
                {submitError}
              </div>
            )}
            <div className={`pt-4 border-t ${th.divider} flex justify-end gap-2`}>
              <button type="button" onClick={onClose} className={`px-4 py-2 rounded-lg text-xs font-medium ${th.cancel}`}>{msg('UI_COMMON_CANCEL_2')}</button>
              <button type="submit" disabled={registerMutation.isPending}
                className={`px-4 py-2 rounded-lg text-xs font-medium disabled:opacity-40 ${th.btn}`}>
                {registerMutation.isPending ? msg('UI_OPERATIONSCONFIG_SUBMITTING') : msg('UI_SUBMEMBERBANKS_SUBMIT_FOR_COMPLIANCE_REVIEW_2')}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}

const MOCK_SUB_MEMBERS = [
  {
    id: 'SMB001',
    name: 'Vasavi Co-operative Bank',
    ifsc_prefix: 'VASB',
    sponsor_account: 'SVCB00000001',
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
  const { bankId, bankName, bankIfsc, isSB, isSMB } = useBankContext()
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

  if (isSMB) {
    return (
      <AppShell>
        <div className={`flex-1 flex items-center justify-center ${th.page}`}>
          <div className="text-center">
            <div className="text-4xl mb-4">🏦</div>
            <div className={`text-lg font-semibold mb-1 ${th.heading}`}>{msg('UI_COMMON_SB_ONLY_FEATURE_2')}</div>
            <div className={`text-sm ${th.muted}`}>{msg('UI_SUBMEMBERBANKS_SUB_MEMBER_ONBOARDING_IS_MANAGED_2')}</div>
          </div>
        </div>
      </AppShell>
    )
  }

  return (
    <AppShell>
      {showAdd && <OnboardModal isDark={isDark} onClose={() => setShowAdd(false)} />}
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>{msg('UI_APPSHELL_SUB_MEMBER_BANKS')}</h1>
            <p className={`text-xs mt-0.5 ${th.muted}`}>{msg('UI_SUBMEMBERBANKS_BANKS_SPONSORED_BY_THIS_INSTITUTION_2')}</p>
          </div>
          <button
            onClick={() => setShowAdd(true)}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${th.btn}`}
          >
            <span>{msg('UI_SUBMEMBERBANKS_ONBOARD_SUB_MEMBER_2')}</span>
          </button>
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-4 gap-3 mb-5">
          {[
            { label: msg('UI_SUBMEMBERBANKS_TOTAL_SUB_MEMBERS_2'), value: MOCK_SUB_MEMBERS.length },
            { label: msg('UI_COMMON_ACTIVE_2'), value: MOCK_SUB_MEMBERS.filter(s => s.status === 'ACTIVE').length },
            { label: msg('UI_SMBREGISTRY_CHEQUES_TODAY_2'), value: MOCK_SUB_MEMBERS.reduce((a, s) => a + s.cheques_today, 0).toLocaleString() },
            { label: msg('UI_SUBMEMBERBANKS_SUSPENDED_2'), value: MOCK_SUB_MEMBERS.filter(s => s.status === 'SUSPENDED').length },
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
                {[msg('UI_SMBREGISTRY_BANK_NAME'), msg('UI_SUBMEMBERBANKS_IFSC_PREFIX_2'), msg('UI_SUBMEMBERBANKS_DAILY_LIMIT_2'), msg('UI_SMBREGISTRY_TODAY_2'), msg('UI_SUBMEMBERBANKS_RISK_2'), msg('UI_COMMON_STATUS_2'), ''].map(h => (
                  <th key={h} className={`px-4 py-3 text-left font-medium ${th.muted}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {MOCK_SUB_MEMBERS.map(sm => (
                <tr key={sm.id} className={`border-b cursor-pointer transition-colors ${th.row}`} onClick={() => setSelected(sm)}>
                  <td className={`px-4 py-3 font-medium ${th.heading}`}>{sm.name}</td>
                  <td className={`px-4 py-3 font-mono ${th.body}`}>{sm.ifsc_prefix}</td>
                  <td className={`px-4 py-3 ${th.body}`}>{msg('UI_SUBMEMBERBANKS_DAY_2', { daily_limit: sm.daily_limit.toLocaleString() })}</td>
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
                    <button className={`text-[11px] ${isDark ? 'text-cyan-400 hover:text-cyan-300' : 'text-cyan-600 hover:text-cyan-700'}`}>{msg('UI_SUBMEMBERBANKS_VIEW_2')}</button>
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
              <button onClick={() => setSelected(null)} className={`text-xs ${th.muted} hover:${th.body}`}>{msg('UI_COMMON_CLOSE_2')}</button>
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
                {selected.status === 'ACTIVE' ? msg('UI_SMBREGISTRY_SUSPEND_2') : msg('UI_SMBREGISTRY_REACTIVATE_2')}
              </button>
              <button className={`px-3 py-1.5 rounded-lg text-xs font-medium ${isDark ? 'bg-white/5 text-slate-300 hover:bg-white/10' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'}`}>
               {msg('UI_SUBMEMBERBANKS_EDIT_LIMITS_2')}
              </button>
              <button className={`px-3 py-1.5 rounded-lg text-xs font-medium ${isDark ? 'bg-white/5 text-slate-300 hover:bg-white/10' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'}`}>
               {msg('UI_SUBMEMBERBANKS_VIEW_RISK_REPORT_2')}
              </button>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  )
}

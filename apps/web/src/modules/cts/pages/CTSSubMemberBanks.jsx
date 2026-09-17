import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'
import { BANK_CONFIG } from '../../../shared/config/bank.config'
import useSMBList from '../hooks/useSMBList'

function smbZone(state) {
  if (['KL', 'TN', 'KA', 'AP', 'TG'].includes(state)) return 'SOUTH'
  if (['MH', 'GA'].includes(state)) return 'WEST'
  if (['DL', 'UP', 'RJ', 'HR', 'PB'].includes(state)) return 'NORTH'
  return 'EAST'
}

const RISK_CYCLE = ['LOW', 'LOW', 'MEDIUM', 'LOW', 'LOW', 'MEDIUM', 'LOW', 'HIGH']
const ONBOARD_DATES = ['2026-01-15', '2026-01-22', '2026-02-01', '2026-02-10', '2026-02-20', '2026-03-05', '2026-03-15', '2026-04-01']

const BASE_MOCK_SUB_MEMBERS = [
  { id: 'SMB001', name: 'Vasavi Co-operative Bank',  ifsc_prefix: 'VASB', sponsor_account: 'SRCB00000001', clearing_zones: ['MUMBAI'], status: 'ACTIVE',    daily_limit: 5000, cheques_today: 312, risk_level: 'LOW',  onboarded: '2026-01-15', contact: 'ops@vasavi.coop' },
  { id: 'SMB002', name: 'Cosmos Co-operative Bank',  ifsc_prefix: 'COSB', sponsor_account: 'SRCB00000002', clearing_zones: ['MUMBAI', 'PUNE'], status: 'ACTIVE', daily_limit: 3000, cheques_today: 187, risk_level: 'LOW', onboarded: '2026-02-20', contact: 'clearing@cosmosbank.in' },
  { id: 'SMB003', name: 'Janata Sahakari Bank',      ifsc_prefix: 'JSBP', sponsor_account: 'SRCB00000003', clearing_zones: ['PUNE'], status: 'SUSPENDED', daily_limit: 2000, cheques_today: 0,   risk_level: 'HIGH', onboarded: '2026-03-05', contact: 'mgmt@janatasahakari.co.in' },
]

const MOCK_SUB_MEMBERS = (BANK_CONFIG.smbs ?? []).length > 0
  ? BANK_CONFIG.smbs.map((smb, i) => ({
      id: smb.id,
      name: smb.name,
      ifsc_prefix: smb.ifsc.substring(0, 4),
      sponsor_account: `${BANK_CONFIG.ifsc_prefix}${String(i + 1).padStart(8, '0')}`,
      clearing_zones: [smbZone(smb.state)],
      status: i === 13 ? 'SUSPENDED' : 'ACTIVE',
      daily_limit: (smb.daily_avg ?? 50) * 10,
      cheques_today: i === 13 ? 0 : Math.round((smb.daily_avg ?? 50) * 0.85),
      risk_level: RISK_CYCLE[i % RISK_CYCLE.length],
      onboarded: ONBOARD_DATES[i % ONBOARD_DATES.length],
      contact: `ops@${smb.shortName.toLowerCase().replace(/\s+/g, '').replace(/[^a-z0-9]/g, '')}.coop`,
    }))
  : BASE_MOCK_SUB_MEMBERS

const CLEARING_ZONES = (BANK_CONFIG.smbs ?? []).length > 0
  ? [...new Set(BANK_CONFIG.smbs.map(s => smbZone(s.state)))]
  : ['MUMBAI', 'PUNE', 'DELHI', 'CHENNAI', 'KOLKATA', 'AHMEDABAD', 'HYDERABAD']

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
    clearing_zones: [], daily_limit: '', risk_level: 'LOW',
  })
  const [submitted, setSubmitted] = useState(false)
  const [submitError, setSubmitError] = useState(null)

  const toggle_zone = (z) => setForm(f => ({
    ...f,
    clearing_zones: f.clearing_zones.includes(z)
      ? f.clearing_zones.filter(x => x !== z)
      : [...f.clearing_zones, z],
  }))

  const registerMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch('/v1/cts/smb', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          bank_name: form.name,
          ifsc_prefix: form.ifsc_prefix,
          micr_prefix: form.ifsc_prefix,
          sponsor_account_number: form.sponsor_account,
          contact_email: form.contact,
          clearing_zones: form.clearing_zones,
          daily_presentment_limit: parseInt(form.daily_limit) || 1000,
          risk_level: form.risk_level,
          return_rate_threshold: 0.15,
          soft_hold_threshold: 0.25,
        }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Registration failed' }))
        throw new Error(err.detail || 'Registration failed')
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
            <h2 className={`text-base font-semibold ${th.heading}`}>Onboard Sub-Member Bank</h2>
            <p className={`text-xs mt-0.5 ${th.muted}`}>Register a new bank for CTS clearing access via this institution</p>
          </div>
          <button onClick={onClose} className={`text-xs ${th.muted} hover:${th.heading} px-2`}>✕</button>
        </div>

        {submitted ? (
          <div className="py-8 text-center">
            <div className="text-2xl mb-2">✓</div>
            <p className={`text-sm font-medium ${th.heading}`}>Onboarding request submitted</p>
            <p className={`text-xs mt-1 ${th.muted}`}>Compliance review will be initiated within 24 hours.</p>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4 text-xs">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={`block mb-1 ${th.label}`}>Bank Name *</label>
                <input required className={`w-full rounded-lg border px-3 py-2 text-xs ${th.input}`}
                  placeholder="e.g. Janata Co-operative Bank"
                  value={form.name} onChange={e => setForm(f => ({...f, name: e.target.value}))} />
              </div>
              <div>
                <label className={`block mb-1 ${th.label}`}>IFSC Prefix *</label>
                <input required maxLength={4} className={`w-full rounded-lg border px-3 py-2 text-xs font-mono uppercase ${th.input}`}
                  placeholder="e.g. JNCB"
                  value={form.ifsc_prefix} onChange={e => setForm(f => ({...f, ifsc_prefix: e.target.value.toUpperCase()}))} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={`block mb-1 ${th.label}`}>Sponsor Account *</label>
                <input required className={`w-full rounded-lg border px-3 py-2 text-xs font-mono ${th.input}`}
                  placeholder="SVCB00000001"
                  value={form.sponsor_account} onChange={e => setForm(f => ({...f, sponsor_account: e.target.value}))} />
              </div>
              <div>
                <label className={`block mb-1 ${th.label}`}>Daily Cheque Limit *</label>
                <input required type="number" min={1} className={`w-full rounded-lg border px-3 py-2 text-xs ${th.input}`}
                  placeholder="5000"
                  value={form.daily_limit} onChange={e => setForm(f => ({...f, daily_limit: e.target.value}))} />
              </div>
            </div>
            <div>
              <label className={`block mb-1 ${th.label}`}>Ops Contact Email *</label>
              <input required type="email" className={`w-full rounded-lg border px-3 py-2 text-xs ${th.input}`}
                placeholder="ops@subbank.coop"
                value={form.contact} onChange={e => setForm(f => ({...f, contact: e.target.value}))} />
            </div>
            <div>
              <label className={`block mb-2 ${th.label}`}>Clearing Zones *</label>
              <div className="flex flex-wrap gap-2">
                {CLEARING_ZONES.map(z => {
                  const active = form.clearing_zones.includes(z)
                  return (
                    <button type="button" key={z} onClick={() => toggle_zone(z)}
                      className={`px-2.5 py-1 rounded-full border text-[10px] font-medium transition-all ${
                        active
                          ? (isDark ? 'bg-cyan-600 border-cyan-500 text-white' : 'bg-cyan-600 border-cyan-600 text-white')
                          : (isDark ? 'bg-white/5 border-white/10 text-slate-400 hover:border-white/20' : 'bg-slate-100 border-slate-300 text-slate-500 hover:border-slate-400')
                      }`}>{z}</button>
                  )
                })}
              </div>
            </div>
            <div>
              <label className={`block mb-1 ${th.label}`}>Initial Risk Assessment</label>
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
              <button type="button" onClick={onClose} className={`px-4 py-2 rounded-lg text-xs font-medium ${th.cancel}`}>Cancel</button>
              <button type="submit" disabled={form.clearing_zones.length === 0 || registerMutation.isPending}
                className={`px-4 py-2 rounded-lg text-xs font-medium disabled:opacity-40 ${th.btn}`}>
                {registerMutation.isPending ? 'Submitting…' : 'Submit for Compliance Review'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}

const RISK_COLORS_D = { LOW: 'bg-emerald-900/40 text-emerald-300 border-emerald-700/50', MEDIUM: 'bg-amber-900/40 text-amber-300 border-amber-700/50', HIGH: 'bg-red-900/40 text-red-300 border-red-700/50' }
const RISK_COLORS_L = { LOW: 'bg-emerald-100 text-emerald-700 border-emerald-300', MEDIUM: 'bg-amber-100 text-amber-700 border-amber-300', HIGH: 'bg-red-100 text-red-700 border-red-300' }

export default function CTSSubMemberBanks() {
  const { isDark } = useTheme()
  const { bankId, bankName, bankIfsc, isSB, isSMB, isDemo } = useBankContext()
  const [selected, setSelected] = useState(null)
  const [showAdd, setShowAdd] = useState(false)

  const { subMembers: liveSmbs } = useSMBList({ pollEnabled: !isDemo && isSB })
  const smbs = isDemo || !liveSmbs ? MOCK_SUB_MEMBERS : liveSmbs

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
            <div className={`text-lg font-semibold mb-1 ${th.heading}`}>SB-Only Feature</div>
            <div className={`text-sm ${th.muted}`}>Sub-member onboarding is managed by the Sponsor Bank. This page is not available for SMB users.</div>
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
            { label: 'Total Sub-Members', value: smbs.length },
            { label: 'Active', value: smbs.filter(s => s.status === 'ACTIVE').length },
            { label: 'Cheques Today', value: smbs.reduce((a, s) => a + (s.cheques_today ?? 0), 0).toLocaleString() },
            { label: 'Suspended', value: smbs.filter(s => s.status === 'SUSPENDED').length },
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
              {smbs.map(sm => (
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

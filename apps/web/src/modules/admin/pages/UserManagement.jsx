/**
 * User Management — Admin console for bank IT admin.
 *
 * Features:
 * - User list with role / zone / TOTP status
 * - Create / edit user modal
 * - TOTP setup flow: QR-code-style URI display + 6-digit confirm
 * - Force logout / deactivate actions
 */
import { useState } from 'react'
import { useTheme } from '../../../shared/theme/ThemeContext'
import AppShell from '../../../shared/layout/AppShell'

// ─── Mock data ────────────────────────────────────────────────────────────────

const MOCK_USERS = [
  { user_id: 'usr-001', email: 'ops1@bank.com',    display_name: 'Priya Mehta',      role: 'ops_reviewer',   clearing_zone: 'MUMBAI', is_active: true,  totp_enabled: true,  last_login: '2026-06-25T09:14:00Z' },
  { user_id: 'usr-002', email: 'fraud1@bank.com',  display_name: 'Rahul Singh',      role: 'fraud_analyst',  clearing_zone: 'DELHI',  is_active: true,  totp_enabled: false, last_login: '2026-06-25T08:52:00Z' },
  { user_id: 'usr-003', email: 'mgr1@bank.com',    display_name: 'Sunita Iyer',      role: 'ops_manager',    clearing_zone: null,     is_active: true,  totp_enabled: true,  last_login: '2026-06-24T17:30:00Z' },
  { user_id: 'usr-004', email: 'admin1@bank.com',  display_name: 'Vikram Kapoor',    role: 'bank_it_admin',  clearing_zone: null,     is_active: true,  totp_enabled: true,  last_login: '2026-06-25T07:00:00Z' },
  { user_id: 'usr-005', email: 'compliance@bank.com', display_name: 'Meena Nair',   role: 'compliance_officer', clearing_zone: null, is_active: false, totp_enabled: false, last_login: '2026-06-20T11:00:00Z' },
  { user_id: 'usr-006', email: 'rbi@examiner.in',  display_name: 'RBI Examiner A',  role: 'rbi_examiner',   clearing_zone: null,     is_active: true,  totp_enabled: true,  last_login: '2026-06-18T14:00:00Z' },
  { user_id: 'usr-007', email: 'ml@bank.com',      display_name: 'Asha Reddy',      role: 'ml_engineer',    clearing_zone: null,     is_active: true,  totp_enabled: false, last_login: '2026-06-25T10:05:00Z' },
]

const VALID_ROLES = ['ops_reviewer', 'fraud_analyst', 'ops_manager', 'bank_it_admin', 'compliance_officer', 'rbi_examiner', 'ml_engineer']
const VALID_ZONES = ['MUMBAI', 'DELHI', 'CHENNAI', 'KOLKATA', 'AHMEDABAD', 'HYDERABAD']

const ROLE_LABELS = {
  ops_reviewer:       'Ops Reviewer',
  fraud_analyst:      'Fraud Analyst',
  ops_manager:        'Ops Manager',
  bank_it_admin:      'IT Admin',
  compliance_officer: 'Compliance',
  rbi_examiner:       'RBI Examiner',
  ml_engineer:        'ML Engineer',
}

const ROLE_COLORS_D = {
  ops_reviewer:       'bg-blue-900/50 text-blue-300 border-blue-700/30',
  fraud_analyst:      'bg-orange-900/50 text-orange-300 border-orange-700/30',
  ops_manager:        'bg-violet-900/50 text-violet-300 border-violet-700/30',
  bank_it_admin:      'bg-emerald-900/50 text-emerald-300 border-emerald-700/30',
  compliance_officer: 'bg-amber-900/50 text-amber-300 border-amber-700/30',
  rbi_examiner:       'bg-red-900/50 text-red-300 border-red-700/30',
  ml_engineer:        'bg-cyan-900/50 text-cyan-300 border-cyan-700/30',
}
const ROLE_COLORS_L = {
  ops_reviewer:       'bg-blue-100 text-blue-700 border-blue-300',
  fraud_analyst:      'bg-orange-100 text-orange-700 border-orange-300',
  ops_manager:        'bg-violet-100 text-violet-700 border-violet-300',
  bank_it_admin:      'bg-emerald-100 text-emerald-700 border-emerald-300',
  compliance_officer: 'bg-amber-100 text-amber-700 border-amber-300',
  rbi_examiner:       'bg-red-100 text-red-700 border-red-300',
  ml_engineer:        'bg-cyan-100 text-cyan-700 border-cyan-300',
}

function fmt(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
}

// ─── Modal sub-components ────────────────────────────────────────────────────

function Modal({ title, onClose, isDark, children }) {
  const th = {
    overlay: 'fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm',
    box:     isDark ? 'bg-navy-900 border border-white/10 rounded-2xl shadow-2xl w-full max-w-lg mx-4' : 'bg-white border border-slate-200 rounded-2xl shadow-2xl w-full max-w-lg mx-4',
    header:  isDark ? 'flex items-center justify-between px-6 py-4 border-b border-white/8' : 'flex items-center justify-between px-6 py-4 border-b border-slate-200',
    title:   isDark ? 'text-sm font-semibold text-white' : 'text-sm font-semibold text-slate-900',
    close:   isDark ? 'text-slate-400 hover:text-white text-lg leading-none' : 'text-slate-400 hover:text-slate-700 text-lg leading-none',
  }
  return (
    <div className={th.overlay} onClick={e => e.target === e.currentTarget && onClose()}>
      <div className={th.box}>
        <div className={th.header}>
          <span className={th.title}>{title}</span>
          <button onClick={onClose} className={th.close}>✕</button>
        </div>
        {children}
      </div>
    </div>
  )
}

function Field({ label, isDark, children }) {
  const muted = isDark ? 'text-slate-400' : 'text-slate-500'
  return (
    <div>
      <label className={`block text-[11px] uppercase tracking-wide ${muted} mb-1`}>{label}</label>
      {children}
    </div>
  )
}

function inputCls(isDark) {
  return isDark
    ? 'w-full text-sm bg-navy-950 border border-white/10 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-blue-500'
    : 'w-full text-sm bg-white border border-slate-300 rounded-lg px-3 py-2 text-slate-800 focus:outline-none focus:border-blue-500'
}

function CreateEditModal({ user, isDark, onClose, onSave }) {
  const [form, setForm] = useState(user ? {
    display_name: user.display_name,
    email: user.email,
    role: user.role,
    clearing_zone: user.clearing_zone || '',
    is_active: user.is_active,
  } : { display_name: '', email: '', role: 'ops_reviewer', clearing_zone: '', is_active: true })

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))
  const body = isDark ? 'text-slate-300' : 'text-slate-700'
  const btnPri = 'px-4 py-1.5 rounded-lg text-[12px] font-medium bg-blue-600 hover:bg-blue-500 text-white transition-colors'
  const btnSec = isDark ? 'px-4 py-1.5 rounded-lg text-[12px] border border-white/10 text-slate-300 hover:text-white transition-colors' : 'px-4 py-1.5 rounded-lg text-[12px] border border-slate-200 text-slate-600 hover:text-slate-900 transition-colors'

  return (
    <Modal title={user ? 'Edit User' : 'Create User'} onClose={onClose} isDark={isDark}>
      <div className="px-6 py-5 space-y-4">
        <Field label="Display Name" isDark={isDark}>
          <input className={inputCls(isDark)} value={form.display_name} onChange={e => set('display_name', e.target.value)} />
        </Field>
        <Field label="Email" isDark={isDark}>
          <input className={inputCls(isDark)} type="email" value={form.email} onChange={e => set('email', e.target.value)} disabled={!!user} />
          {user && <p className={`text-[10px] mt-1 ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>Email cannot be changed after creation.</p>}
        </Field>
        <Field label="Role" isDark={isDark}>
          <select className={inputCls(isDark)} value={form.role} onChange={e => set('role', e.target.value)}>
            {VALID_ROLES.map(r => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
          </select>
        </Field>
        {(form.role === 'ops_reviewer') && (
          <Field label="Clearing Zone" isDark={isDark}>
            <select className={inputCls(isDark)} value={form.clearing_zone} onChange={e => set('clearing_zone', e.target.value)}>
              <option value="">— none —</option>
              {VALID_ZONES.map(z => <option key={z} value={z}>{z}</option>)}
            </select>
          </Field>
        )}
        {user && (
          <Field label="Status" isDark={isDark}>
            <label className={`flex items-center gap-2 text-sm ${body} cursor-pointer`}>
              <input type="checkbox" checked={form.is_active} onChange={e => set('is_active', e.target.checked)} className="w-4 h-4 rounded" />
              Active
            </label>
          </Field>
        )}
      </div>
      <div className={`flex justify-end gap-2 px-6 py-4 border-t ${isDark ? 'border-white/8' : 'border-slate-200'}`}>
        <button onClick={onClose} className={btnSec}>Cancel</button>
        <button onClick={() => onSave(form)} className={btnPri}>{user ? 'Save Changes' : 'Create User'}</button>
      </div>
    </Modal>
  )
}

function TOTPSetupModal({ user, isDark, onClose }) {
  const [step, setStep] = useState('setup') // setup | confirm | done
  const [code, setCode] = useState('')
  const [verified, setVerified] = useState(null)

  // Demo base32 key — production value comes from POST /v1/admin/users/{id}/totp/setup
  const demoBase32 = 'JBSWY3DPEHPK3PXP'
  const otpauthUri = `otpauth://totp/ASTRA:${user.email}?secret=${demoBase32}&issuer=ASTRA`

  const btnPri = 'px-4 py-1.5 rounded-lg text-[12px] font-medium bg-blue-600 hover:bg-blue-500 text-white transition-colors'
  const btnSec = isDark ? 'px-4 py-1.5 rounded-lg text-[12px] border border-white/10 text-slate-300 hover:text-white transition-colors' : 'px-4 py-1.5 rounded-lg text-[12px] border border-slate-200 text-slate-600 hover:text-slate-900 transition-colors'
  const muted = isDark ? 'text-slate-400' : 'text-slate-500'
  const body = isDark ? 'text-slate-200' : 'text-slate-800'
  const codeBg = isDark ? 'bg-navy-950 border border-white/10 text-emerald-400' : 'bg-slate-100 border border-slate-200 text-emerald-700'

  return (
    <Modal title="Set Up TOTP Authenticator" onClose={onClose} isDark={isDark}>
      <div className="px-6 py-5">

        {step === 'setup' && (
          <div className="space-y-4">
            <p className={`text-[12px] ${muted}`}>
              Scan this URI in Google Authenticator, Authy, or any TOTP app. In production, this is a QR code.
            </p>
            <div className={`rounded-xl p-4 font-mono text-[11px] break-all ${codeBg}`}>
              {otpauthUri}
            </div>
            <div className="space-y-1">
              <p className={`text-[10px] ${muted}`}>Manual entry — Secret key (Base32):</p>
              <div className={`rounded-lg px-3 py-2 font-mono text-sm tracking-widest ${isDark ? 'bg-white/5 text-white' : 'bg-slate-100 text-slate-900'}`}>
                {demoBase32}
              </div>
            </div>
            <p className={`text-[11px] ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>
              ⚠ Store this backup code securely. It cannot be shown again.
            </p>
            <div className="flex justify-end gap-2 pt-2">
              <button onClick={onClose} className={btnSec}>Cancel</button>
              <button onClick={() => setStep('confirm')} className={btnPri}>I've scanned it →</button>
            </div>
          </div>
        )}

        {step === 'confirm' && (
          <div className="space-y-4">
            <p className={`text-[12px] ${muted}`}>
              Enter the 6-digit code from your authenticator app to confirm setup.
            </p>
            <input
              className={`${inputCls(isDark)} text-center tracking-[0.5em] font-mono text-xl`}
              maxLength={6}
              value={code}
              onChange={e => { setCode(e.target.value.replace(/\D/g, '')); setVerified(null) }}
              placeholder="000000"
            />
            {verified === false && (
              <p className="text-[11px] text-red-400">Incorrect code. Try again — codes expire every 30 seconds.</p>
            )}
            <div className="flex justify-end gap-2 pt-2">
              <button onClick={() => setStep('setup')} className={btnSec}>← Back</button>
              <button
                onClick={() => {
                  // Demo: accept 123456 or any 6-digit code as "valid" for UI flow
                  if (code.length === 6) { setVerified(true); setStep('done') }
                  else setVerified(false)
                }}
                className={btnPri}
                disabled={code.length !== 6}
              >Verify & Activate</button>
            </div>
          </div>
        )}

        {step === 'done' && (
          <div className="space-y-4 text-center py-4">
            <div className="text-4xl">✅</div>
            <p className={`text-sm font-medium ${body}`}>TOTP Activated</p>
            <p className={`text-[12px] ${muted}`}>
              {user.display_name} will now be prompted for a TOTP code on every login.
            </p>
            <button onClick={onClose} className={btnPri + ' mx-auto block mt-4'}>Done</button>
          </div>
        )}
      </div>
    </Modal>
  )
}

function ConfirmModal({ title, message, confirmLabel, danger, isDark, onClose, onConfirm }) {
  const btnDanger = 'px-4 py-1.5 rounded-lg text-[12px] font-medium bg-red-600 hover:bg-red-500 text-white transition-colors'
  const btnPri = 'px-4 py-1.5 rounded-lg text-[12px] font-medium bg-blue-600 hover:bg-blue-500 text-white transition-colors'
  const btnSec = isDark ? 'px-4 py-1.5 rounded-lg text-[12px] border border-white/10 text-slate-300 hover:text-white transition-colors' : 'px-4 py-1.5 rounded-lg text-[12px] border border-slate-200 text-slate-600 hover:text-slate-900 transition-colors'
  const body = isDark ? 'text-slate-300' : 'text-slate-600'

  return (
    <Modal title={title} onClose={onClose} isDark={isDark}>
      <div className="px-6 py-5">
        <p className={`text-[13px] ${body}`}>{message}</p>
      </div>
      <div className={`flex justify-end gap-2 px-6 py-4 border-t ${isDark ? 'border-white/8' : 'border-slate-200'}`}>
        <button onClick={onClose} className={btnSec}>Cancel</button>
        <button onClick={onConfirm} className={danger ? btnDanger : btnPri}>{confirmLabel}</button>
      </div>
    </Modal>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function UserManagement() {
  const { isDark } = useTheme()
  const [users, setUsers] = useState(MOCK_USERS)
  const [search, setSearch] = useState('')
  const [roleFilter, setRoleFilter] = useState('all')
  const [modal, setModal] = useState(null) // null | {type, user?}

  const th = {
    page:    isDark ? 'bg-navy-950' : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    row:     isDark ? 'border-white/4 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
    input:   isDark ? 'bg-navy-900 border-white/10 text-slate-300 placeholder-slate-500' : 'bg-white border-slate-200 text-slate-700 placeholder-slate-400',
  }

  const ROLE_COLORS = isDark ? ROLE_COLORS_D : ROLE_COLORS_L

  const filtered = users.filter(u => {
    const q = search.toLowerCase()
    const matchSearch = !q || u.display_name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q)
    const matchRole = roleFilter === 'all' || u.role === roleFilter
    return matchSearch && matchRole
  })

  const closeModal = () => setModal(null)

  const handleSave = (form) => {
    if (modal.user) {
      setUsers(us => us.map(u => u.user_id === modal.user.user_id ? { ...u, ...form } : u))
    } else {
      const newUser = {
        user_id: `usr-${String(users.length + 1).padStart(3, '0')}`,
        ...form,
        is_active: true,
        totp_enabled: false,
        last_login: null,
      }
      setUsers(us => [...us, newUser])
    }
    closeModal()
  }

  const handleDeactivate = (user) => {
    setUsers(us => us.map(u => u.user_id === user.user_id ? { ...u, is_active: false } : u))
    closeModal()
  }

  const handleResetTOTP = (user) => {
    setUsers(us => us.map(u => u.user_id === user.user_id ? { ...u, totp_enabled: false } : u))
    closeModal()
  }

  const counts = {
    total: users.length,
    active: users.filter(u => u.is_active).length,
    totp: users.filter(u => u.totp_enabled).length,
  }

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page}`}>
        {/* Header */}
        <div className={`sticky top-0 z-10 ${isDark ? 'bg-navy-950/95' : 'bg-slate-50/95'} backdrop-blur border-b ${th.divider} px-6 py-3`}>
          <div className="flex items-center justify-between">
            <div>
              <h1 className={`text-base font-semibold ${th.heading}`}>User Management</h1>
              <p className={`text-[11px] ${th.muted}`}>
                {counts.active} active · {counts.totp} with TOTP · {counts.total} total
              </p>
            </div>
            <button
              onClick={() => setModal({ type: 'create' })}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium bg-blue-600 hover:bg-blue-500 text-white transition-colors"
            >
              + New User
            </button>
          </div>
        </div>

        <div className="px-6 py-5 max-w-7xl space-y-5">

          {/* Summary cards */}
          <div className="grid grid-cols-3 gap-3">
            {[
              { label: 'Total Users',   value: counts.total,  color: th.heading,       sub: 'all roles'             },
              { label: 'Active',        value: counts.active, color: 'text-emerald-400', sub: 'can log in'           },
              { label: 'TOTP Enabled',  value: counts.totp,   color: 'text-blue-400',   sub: `${Math.round(counts.totp / counts.total * 100)}% coverage` },
            ].map(k => (
              <div key={k.label} className={`border rounded-xl p-4 ${th.card}`}>
                <div className={`text-[10px] uppercase tracking-wide ${th.muted} mb-1`}>{k.label}</div>
                <div className={`text-2xl font-bold font-mono ${k.color}`}>{k.value}</div>
                <div className={`text-[10px] mt-0.5 ${th.muted}`}>{k.sub}</div>
              </div>
            ))}
          </div>

          {/* Filter bar */}
          <div className="flex gap-3 items-center">
            <input
              type="text"
              placeholder="Search name or email…"
              value={search}
              onChange={e => setSearch(e.target.value)}
              className={`text-[12px] border rounded-lg px-3 py-1.5 flex-1 max-w-xs focus:outline-none ${th.input}`}
            />
            <select
              value={roleFilter}
              onChange={e => setRoleFilter(e.target.value)}
              className={`text-[12px] border rounded-lg px-3 py-1.5 focus:outline-none ${th.input}`}
            >
              <option value="all">All Roles</option>
              {VALID_ROLES.map(r => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
            </select>
            <span className={`text-[11px] ${th.muted}`}>{filtered.length} results</span>
          </div>

          {/* User table */}
          <div className={`border rounded-xl overflow-hidden ${th.card}`}>
            <div className="overflow-x-auto">
              <table className="w-full text-[12px]">
                <thead>
                  <tr className={`border-b ${th.divider}`}>
                    {['User', 'Role', 'Zone', 'TOTP', 'Status', 'Last Login', ''].map(h => (
                      <th key={h} className={`px-4 py-2.5 text-left text-[10px] uppercase tracking-wide ${th.muted}`}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filtered.map(u => (
                    <tr key={u.user_id} className={`border-b ${th.row} transition-colors`}>
                      <td className="px-4 py-3">
                        <div className={`font-medium ${th.body}`}>{u.display_name}</div>
                        <div className={`text-[10px] ${th.muted}`}>{u.email}</div>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full border ${ROLE_COLORS[u.role]}`}>
                          {ROLE_LABELS[u.role]}
                        </span>
                      </td>
                      <td className={`px-4 py-3 ${th.muted} font-mono text-[11px]`}>
                        {u.clearing_zone || '—'}
                      </td>
                      <td className="px-4 py-3">
                        {u.totp_enabled
                          ? <span className="text-[10px] text-emerald-400 font-medium">● Enabled</span>
                          : <span className={`text-[10px] ${th.muted}`}>○ Off</span>
                        }
                      </td>
                      <td className="px-4 py-3">
                        <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full border ${
                          u.is_active
                            ? (isDark ? 'bg-emerald-900/30 text-emerald-300 border-emerald-700/30' : 'bg-emerald-100 text-emerald-700 border-emerald-300')
                            : (isDark ? 'bg-slate-800 text-slate-500 border-white/5' : 'bg-slate-100 text-slate-400 border-slate-200')
                        }`}>
                          {u.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                      <td className={`px-4 py-3 text-[11px] ${th.muted} font-mono`}>
                        {fmt(u.last_login)}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex gap-2 justify-end">
                          <button
                            onClick={() => setModal({ type: 'edit', user: u })}
                            className={`text-[10px] px-2.5 py-1 rounded border transition-colors ${isDark ? 'border-white/10 text-slate-400 hover:text-white' : 'border-slate-200 text-slate-500 hover:text-slate-800'}`}
                          >Edit</button>
                          {!u.totp_enabled && u.is_active && (
                            <button
                              onClick={() => setModal({ type: 'totp_setup', user: u })}
                              className="text-[10px] px-2.5 py-1 rounded border border-blue-700/40 text-blue-400 hover:text-blue-300 transition-colors"
                            >Setup TOTP</button>
                          )}
                          {u.totp_enabled && (
                            <button
                              onClick={() => setModal({ type: 'totp_reset', user: u })}
                              className={`text-[10px] px-2.5 py-1 rounded border transition-colors ${isDark ? 'border-amber-700/40 text-amber-400 hover:text-amber-300' : 'border-amber-300 text-amber-600 hover:text-amber-700'}`}
                            >Reset TOTP</button>
                          )}
                          {u.is_active && (
                            <button
                              onClick={() => setModal({ type: 'deactivate', user: u })}
                              className={`text-[10px] px-2.5 py-1 rounded border transition-colors ${isDark ? 'border-red-700/40 text-red-400 hover:text-red-300' : 'border-red-300 text-red-600 hover:text-red-700'}`}
                            >Deactivate</button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                  {filtered.length === 0 && (
                    <tr>
                      <td colSpan={7} className={`px-4 py-10 text-center text-[12px] ${th.muted}`}>No users match the current filter.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* TOTP info panel */}
          <div className={`border rounded-xl p-4 ${th.card}`}>
            <div className={`text-[11px] font-semibold uppercase tracking-wide ${th.muted} mb-3`}>TOTP (RFC 6238) — How It Works</div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-[11px]">
              {[
                { step: '1', title: 'Setup', desc: 'IT Admin generates a shared secret for the user. User scans QR code (otpauth:// URI) in their authenticator app.' },
                { step: '2', title: 'Confirm', desc: 'User enters first 6-digit code to confirm. This activates TOTP. The secret is stored in Vault — never in the database.' },
                { step: '3', title: 'Login', desc: 'After SAML authentication, user is prompted for TOTP. Code is valid for ±30 seconds (1 window tolerance). 000000 codes are rejected.' },
              ].map(s => (
                <div key={s.step} className={`rounded-lg p-3 ${isDark ? 'bg-white/3' : 'bg-slate-50'}`}>
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className={`text-[10px] font-bold w-5 h-5 rounded-full flex items-center justify-center ${isDark ? 'bg-blue-900/60 text-blue-300' : 'bg-blue-100 text-blue-700'}`}>{s.step}</span>
                    <span className={`font-semibold ${th.body}`}>{s.title}</span>
                  </div>
                  <p className={th.muted}>{s.desc}</p>
                </div>
              ))}
            </div>
          </div>

        </div>
      </div>

      {/* Modals */}
      {(modal?.type === 'create' || modal?.type === 'edit') && (
        <CreateEditModal user={modal.user || null} isDark={isDark} onClose={closeModal} onSave={handleSave} />
      )}
      {modal?.type === 'totp_setup' && (
        <TOTPSetupModal user={modal.user} isDark={isDark} onClose={closeModal} />
      )}
      {modal?.type === 'totp_reset' && (
        <ConfirmModal
          title="Reset TOTP"
          message={`This will disable TOTP for ${modal.user.display_name}. They will be able to log in without a second factor until TOTP is set up again. Proceed?`}
          confirmLabel="Reset TOTP"
          danger
          isDark={isDark}
          onClose={closeModal}
          onConfirm={() => handleResetTOTP(modal.user)}
        />
      )}
      {modal?.type === 'deactivate' && (
        <ConfirmModal
          title="Deactivate User"
          message={`${modal.user.display_name} (${modal.user.email}) will no longer be able to log in. This action is reversible via Edit.`}
          confirmLabel="Deactivate"
          danger
          isDark={isDark}
          onClose={closeModal}
          onConfirm={() => handleDeactivate(modal.user)}
        />
      )}
    </AppShell>
  )
}

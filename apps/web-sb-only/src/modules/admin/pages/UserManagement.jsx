/**
 * User Management — Admin console for bank IT admin.
 * Supports SB (Sponsor Bank) and SMB (Sub-Member Bank) users on separate tabs.
 * Permission levels: ADMIN | EDIT | READ_ONLY within each tenant.
 * bank_type is immutable after creation — shown as read-only in edit mode.
 */
import { useState } from 'react'
import { useTheme } from '../../../shared/theme/ThemeContext'
import AppShell from '../../../shared/layout/AppShell'

// ─── Constants ────────────────────────────────────────────────────────────────

const SB_ROLES = ['ops_reviewer', 'fraud_analyst', 'ops_manager', 'bank_it_admin', 'compliance_officer', 'rbi_examiner', 'ml_engineer', 'smb_it_admin']
const SMB_ROLES = ['smb_admin', 'smb_editor', 'smb_viewer']
const VALID_ZONES = ['MUMBAI', 'DELHI', 'CHENNAI', 'KOLKATA', 'AHMEDABAD', 'HYDERABAD']
const PERMISSION_LEVELS = ['ADMIN', 'EDIT', 'READ_ONLY']

const ROLE_LABELS = {
  ops_reviewer:       'Ops Reviewer',
  fraud_analyst:      'Fraud Analyst',
  ops_manager:        'Ops Manager',
  bank_it_admin:      'IT Admin',
  compliance_officer: 'Compliance',
  rbi_examiner:       'RBI Examiner',
  ml_engineer:        'ML Engineer',
  smb_it_admin:       'SMB IT Admin',
  smb_admin:          'SMB Admin',
  smb_editor:         'SMB Editor',
  smb_viewer:         'SMB Viewer',
}

const PERM_LABELS = { ADMIN: 'Admin', EDIT: 'Edit', READ_ONLY: 'Read Only' }

const PERM_COLORS_D = {
  ADMIN:     'bg-violet-900/50 text-violet-300 border-violet-700/30',
  EDIT:      'bg-blue-900/50 text-blue-300 border-blue-700/30',
  READ_ONLY: 'bg-slate-800 text-slate-400 border-white/10',
}
const PERM_COLORS_L = {
  ADMIN:     'bg-violet-100 text-violet-700 border-violet-300',
  EDIT:      'bg-blue-100 text-blue-700 border-blue-300',
  READ_ONLY: 'bg-slate-100 text-slate-500 border-slate-200',
}

const ROLE_COLORS_D = {
  ops_reviewer:       'bg-blue-900/50 text-blue-300 border-blue-700/30',
  fraud_analyst:      'bg-orange-900/50 text-orange-300 border-orange-700/30',
  ops_manager:        'bg-violet-900/50 text-violet-300 border-violet-700/30',
  bank_it_admin:      'bg-emerald-900/50 text-emerald-300 border-emerald-700/30',
  compliance_officer: 'bg-amber-900/50 text-amber-300 border-amber-700/30',
  rbi_examiner:       'bg-red-900/50 text-red-300 border-red-700/30',
  ml_engineer:        'bg-cyan-900/50 text-cyan-300 border-cyan-700/30',
  smb_it_admin:       'bg-teal-900/50 text-teal-300 border-teal-700/30',
  smb_admin:          'bg-emerald-900/50 text-emerald-300 border-emerald-700/30',
  smb_editor:         'bg-blue-900/50 text-blue-300 border-blue-700/30',
  smb_viewer:         'bg-slate-800 text-slate-400 border-white/10',
}
const ROLE_COLORS_L = {
  ops_reviewer:       'bg-blue-100 text-blue-700 border-blue-300',
  fraud_analyst:      'bg-orange-100 text-orange-700 border-orange-300',
  ops_manager:        'bg-violet-100 text-violet-700 border-violet-300',
  bank_it_admin:      'bg-emerald-100 text-emerald-700 border-emerald-300',
  compliance_officer: 'bg-amber-100 text-amber-700 border-amber-300',
  rbi_examiner:       'bg-red-100 text-red-700 border-red-300',
  ml_engineer:        'bg-cyan-100 text-cyan-700 border-cyan-300',
  smb_it_admin:       'bg-teal-100 text-teal-700 border-teal-300',
  smb_admin:          'bg-emerald-100 text-emerald-700 border-emerald-300',
  smb_editor:         'bg-blue-100 text-blue-700 border-blue-300',
  smb_viewer:         'bg-slate-100 text-slate-500 border-slate-200',
}

// ─── Mock data ────────────────────────────────────────────────────────────────

const MOCK_USERS = [
  { user_id: 'usr-001', email: 'ops1@hdfc.com',        display_name: 'Priya Mehta',       bank_type: 'SB',  role: 'ops_reviewer',       permission_level: 'EDIT',      clearing_zone: 'MUMBAI', is_active: true,  totp_enabled: true,  last_login: '2026-06-25T09:14:00Z' },
  { user_id: 'usr-002', email: 'fraud1@hdfc.com',      display_name: 'Rahul Singh',        bank_type: 'SB',  role: 'fraud_analyst',      permission_level: 'EDIT',      clearing_zone: 'DELHI',  is_active: true,  totp_enabled: false, last_login: '2026-06-25T08:52:00Z' },
  { user_id: 'usr-003', email: 'mgr1@hdfc.com',        display_name: 'Sunita Iyer',        bank_type: 'SB',  role: 'ops_manager',        permission_level: 'EDIT',      clearing_zone: null,     is_active: true,  totp_enabled: true,  last_login: '2026-06-24T17:30:00Z' },
  { user_id: 'usr-004', email: 'admin1@hdfc.com',      display_name: 'Vikram Kapoor',      bank_type: 'SB',  role: 'bank_it_admin',      permission_level: 'ADMIN',     clearing_zone: null,     is_active: true,  totp_enabled: true,  last_login: '2026-06-25T07:00:00Z' },
  { user_id: 'usr-005', email: 'compliance@hdfc.com',  display_name: 'Meena Nair',         bank_type: 'SB',  role: 'compliance_officer', permission_level: 'READ_ONLY', clearing_zone: null,     is_active: false, totp_enabled: false, last_login: '2026-06-20T11:00:00Z' },
  { user_id: 'usr-006', email: 'admin@saraswat.coop',  display_name: 'Ravi Kulkarni',      bank_type: 'SMB', role: 'smb_admin',          permission_level: 'ADMIN',     clearing_zone: null,     is_active: true,  totp_enabled: true,  last_login: '2026-06-25T10:05:00Z' },
  { user_id: 'usr-007', email: 'ops@saraswat.coop',    display_name: 'Anita Desai',        bank_type: 'SMB', role: 'smb_editor',         permission_level: 'EDIT',      clearing_zone: null,     is_active: true,  totp_enabled: false, last_login: '2026-06-24T15:30:00Z' },
  { user_id: 'usr-008', email: 'view@cosmos.coop',     display_name: 'Suresh Patil',       bank_type: 'SMB', role: 'smb_viewer',         permission_level: 'READ_ONLY', clearing_zone: null,     is_active: true,  totp_enabled: false, last_login: '2026-06-23T09:00:00Z' },
]

function fmt(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
}

// ─── Shared UI helpers ────────────────────────────────────────────────────────

function Modal({ title, onClose, isDark, children }) {
  const th = {
    overlay: 'fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm',
    box:     isDark ? 'bg-navy-900 border border-white/10 rounded-xl shadow-2xl w-full max-w-lg mx-4' : 'bg-white border border-slate-200 rounded-xl shadow-2xl w-full max-w-lg mx-4',
    header:  isDark ? 'flex items-center justify-between px-6 py-4 border-b border-white/10' : 'flex items-center justify-between px-6 py-4 border-b border-slate-200',
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

function Field({ label, isDark, children, hint }) {
  const muted = isDark ? 'text-slate-400' : 'text-slate-500'
  return (
    <div>
      <label className={`block text-[11px] uppercase tracking-wide ${muted} mb-1`}>{label}</label>
      {children}
      {hint && <p className={`text-[10px] mt-1 ${muted}`}>{hint}</p>}
    </div>
  )
}

function inputCls(isDark) {
  return isDark
    ? 'w-full text-sm bg-navy-950 border border-white/10 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-blue-500'
    : 'w-full text-sm bg-white border border-slate-300 rounded-lg px-3 py-2 text-slate-800 focus:outline-none focus:border-blue-500'
}

// ─── Create / Edit Modal ──────────────────────────────────────────────────────

function CreateEditModal({ user, isDark, onClose, onSave, defaultBankType }) {
  const isEdit = !!user
  const [form, setForm] = useState(user ? {
    display_name:     user.display_name,
    email:            user.email,
    role:             user.role,
    bank_type:        user.bank_type,
    permission_level: user.permission_level,
    clearing_zone:    user.clearing_zone || '',
    is_active:        user.is_active,
  } : {
    display_name: '', email: '',
    bank_type:        defaultBankType || 'SB',
    role:             defaultBankType === 'SMB' ? 'smb_editor' : 'ops_reviewer',
    permission_level: 'EDIT',
    clearing_zone: '', is_active: true,
  })

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const handleBankTypeChange = (bt) => {
    set('bank_type', bt)
    set('role', bt === 'SMB' ? 'smb_editor' : 'ops_reviewer')
  }

  const rolesForType = form.bank_type === 'SMB' ? SMB_ROLES : SB_ROLES
  const showZone = form.role === 'ops_reviewer'

  const body = isDark ? 'text-slate-300' : 'text-slate-700'
  const muted = isDark ? 'text-slate-400' : 'text-slate-500'
  const btnPri = 'px-4 py-1.5 rounded-lg text-[12px] font-medium bg-gold-400 hover:bg-gold-500 text-navy-950 transition-colors'
  const btnSec = isDark
    ? 'px-4 py-1.5 rounded-lg text-[12px] border border-white/10 text-slate-300 hover:text-white transition-colors'
    : 'px-4 py-1.5 rounded-lg text-[12px] border border-slate-200 text-slate-600 hover:text-slate-900 transition-colors'

  return (
    <Modal title={isEdit ? 'Edit User' : 'Create User'} onClose={onClose} isDark={isDark}>
      <div className="px-6 py-5 space-y-4">

        {/* Bank Type — immutable after creation */}
        <Field label="Bank Type" isDark={isDark} hint={isEdit ? 'Bank type cannot be changed after user creation.' : 'SB = Sponsor Bank staff · SMB = Sub-Member Bank staff'}>
          {isEdit ? (
            <div className={`flex items-center gap-2 text-sm font-medium ${body}`}>
              <span className={`px-2.5 py-1 rounded-full text-[11px] font-semibold border ${
                form.bank_type === 'SB'
                  ? (isDark ? 'bg-indigo-900/50 text-indigo-300 border-indigo-700/30' : 'bg-indigo-100 text-indigo-700 border-indigo-300')
                  : (isDark ? 'bg-teal-900/50 text-teal-300 border-teal-700/30' : 'bg-teal-100 text-teal-700 border-teal-300')
              }`}>{form.bank_type}</span>
              <span className={`text-[10px] ${muted}`}>(immutable)</span>
            </div>
          ) : (
            <div className="flex gap-2">
              {['SB', 'SMB'].map(bt => (
                <button
                  key={bt}
                  onClick={() => handleBankTypeChange(bt)}
                  className={`flex-1 py-2 rounded-lg text-[12px] font-semibold border transition-all ${
                    form.bank_type === bt
                      ? 'bg-blue-600 border-blue-500 text-white'
                      : (isDark ? 'bg-navy-950 border-white/10 text-slate-400 hover:border-white/20' : 'bg-white border-slate-200 text-slate-500 hover:border-slate-300')
                  }`}
                >{bt === 'SB' ? 'SB — Sponsor Bank' : 'SMB — Sub-Member'}</button>
              ))}
            </div>
          )}
        </Field>

        <Field label="Display Name" isDark={isDark}>
          <input className={inputCls(isDark)} value={form.display_name} onChange={e => set('display_name', e.target.value)} />
        </Field>

        <Field label="Email" isDark={isDark} hint={isEdit ? 'Email cannot be changed after creation.' : undefined}>
          <input className={inputCls(isDark)} type="email" value={form.email} onChange={e => set('email', e.target.value)} disabled={isEdit} />
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Role" isDark={isDark}>
            <select className={inputCls(isDark)} value={form.role} onChange={e => set('role', e.target.value)}>
              {rolesForType.map(r => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
            </select>
          </Field>
          <Field label="Permission Level" isDark={isDark} hint="ADMIN includes all EDIT rights">
            <select className={inputCls(isDark)} value={form.permission_level} onChange={e => set('permission_level', e.target.value)}>
              {PERMISSION_LEVELS.map(p => <option key={p} value={p}>{PERM_LABELS[p]}</option>)}
            </select>
          </Field>
        </div>

        {showZone && (
          <Field label="Clearing Zone" isDark={isDark} hint="Required for ops_reviewer role">
            <select className={inputCls(isDark)} value={form.clearing_zone} onChange={e => set('clearing_zone', e.target.value)}>
              <option value="">— select zone —</option>
              {VALID_ZONES.map(z => <option key={z} value={z}>{z}</option>)}
            </select>
          </Field>
        )}

        {isEdit && (
          <Field label="Status" isDark={isDark}>
            <label className={`flex items-center gap-2 text-sm ${body} cursor-pointer`}>
              <input type="checkbox" checked={form.is_active} onChange={e => set('is_active', e.target.checked)} className="w-4 h-4 rounded" />
              Active
            </label>
          </Field>
        )}
      </div>

      <div className={`flex justify-end gap-2 px-6 py-4 border-t ${isDark ? 'border-white/10' : 'border-slate-200'}`}>
        <button onClick={onClose} className={btnSec}>Cancel</button>
        <button onClick={() => onSave(form)} className={btnPri}>{isEdit ? 'Save Changes' : 'Create User'}</button>
      </div>
    </Modal>
  )
}

// ─── TOTP modals (unchanged logic) ───────────────────────────────────────────

function TOTPSetupModal({ user, isDark, onClose }) {
  const [step, setStep] = useState('setup')
  const [code, setCode] = useState('')
  const [verified, setVerified] = useState(null)

  const demoBase32 = 'JBSWY3DPEHPK3PXP'
  const otpauthUri = `otpauth://totp/ASTRA:${user.email}?secret=${demoBase32}&issuer=ASTRA`

  const btnPri = 'px-4 py-1.5 rounded-lg text-[12px] font-medium bg-gold-400 hover:bg-gold-500 text-navy-950 transition-colors'
  const btnSec = isDark ? 'px-4 py-1.5 rounded-lg text-[12px] border border-white/10 text-slate-300 hover:text-white transition-colors' : 'px-4 py-1.5 rounded-lg text-[12px] border border-slate-200 text-slate-600 hover:text-slate-900 transition-colors'
  const muted = isDark ? 'text-slate-400' : 'text-slate-500'
  const body = isDark ? 'text-slate-200' : 'text-slate-800'
  const codeBg = isDark ? 'bg-navy-950 border border-white/10 text-emerald-400' : 'bg-slate-100 border border-slate-200 text-emerald-700'

  return (
    <Modal title="Set Up TOTP Authenticator" onClose={onClose} isDark={isDark}>
      <div className="px-6 py-5">
        {step === 'setup' && (
          <div className="space-y-4">
            <p className={`text-[12px] ${muted}`}>Scan this URI in Google Authenticator, Authy, or any TOTP app.</p>
            <div className={`rounded-xl p-4 font-mono text-[11px] break-all ${codeBg}`}>{otpauthUri}</div>
            <div className="space-y-1">
              <p className={`text-[10px] ${muted}`}>Manual entry — Secret key (Base32):</p>
              <div className={`rounded-lg px-3 py-2 font-mono text-sm tracking-widest ${isDark ? 'bg-white/5 text-white' : 'bg-slate-100 text-slate-900'}`}>{demoBase32}</div>
            </div>
            <p className={`text-[11px] ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>⚠ Store this backup code securely. It cannot be shown again.</p>
            <div className="flex justify-end gap-2 pt-2">
              <button onClick={onClose} className={btnSec}>Cancel</button>
              <button onClick={() => setStep('confirm')} className={btnPri}>I've scanned it →</button>
            </div>
          </div>
        )}
        {step === 'confirm' && (
          <div className="space-y-4">
            <p className={`text-[12px] ${muted}`}>Enter the 6-digit code from your authenticator app to confirm setup.</p>
            <input
              className={`${inputCls(isDark)} text-center tracking-[0.5em] font-mono text-xl`}
              maxLength={6} value={code}
              onChange={e => { setCode(e.target.value.replace(/\D/g, '')); setVerified(null) }}
              placeholder="000000"
            />
            {verified === false && <p className="text-[11px] text-red-400">Incorrect code. Try again.</p>}
            <div className="flex justify-end gap-2 pt-2">
              <button onClick={() => setStep('setup')} className={btnSec}>← Back</button>
              <button onClick={() => { if (code.length === 6) { setVerified(true); setStep('done') } else setVerified(false) }} className={btnPri} disabled={code.length !== 6}>Verify & Activate</button>
            </div>
          </div>
        )}
        {step === 'done' && (
          <div className="space-y-4 text-center py-4">
            <div className="text-4xl">✅</div>
            <p className={`text-sm font-medium ${body}`}>TOTP Activated</p>
            <p className={`text-[12px] ${muted}`}>{user.display_name} will now be prompted for a TOTP code on every login.</p>
            <button onClick={onClose} className={btnPri + ' mx-auto block mt-4'}>Done</button>
          </div>
        )}
      </div>
    </Modal>
  )
}

function ConfirmModal({ title, message, confirmLabel, danger, isDark, onClose, onConfirm }) {
  const btnDanger = 'px-4 py-1.5 rounded-lg text-[12px] font-medium bg-red-600 hover:bg-red-500 text-white transition-colors'
  const btnPri = 'px-4 py-1.5 rounded-lg text-[12px] font-medium bg-gold-400 hover:bg-gold-500 text-navy-950 transition-colors'
  const btnSec = isDark ? 'px-4 py-1.5 rounded-lg text-[12px] border border-white/10 text-slate-300 hover:text-white transition-colors' : 'px-4 py-1.5 rounded-lg text-[12px] border border-slate-200 text-slate-600 hover:text-slate-900 transition-colors'
  const body = isDark ? 'text-slate-300' : 'text-slate-600'
  return (
    <Modal title={title} onClose={onClose} isDark={isDark}>
      <div className="px-6 py-5"><p className={`text-[13px] ${body}`}>{message}</p></div>
      <div className={`flex justify-end gap-2 px-6 py-4 border-t ${isDark ? 'border-white/10' : 'border-slate-200'}`}>
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
  const [bankTypeTab, setBankTypeTab] = useState('SB')   // 'SB' | 'SMB'
  const [search, setSearch] = useState('')
  const [modal, setModal] = useState(null)

  const th = {
    page:    isDark ? 'bg-navy-950' : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    row:     isDark ? 'border-white/4 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
    input:   isDark ? 'bg-navy-900 border-white/10 text-slate-300 placeholder:text-slate-500' : 'bg-white border-slate-200 text-slate-700 placeholder:text-slate-400',
  }

  const ROLE_COLORS = isDark ? ROLE_COLORS_D : ROLE_COLORS_L
  const PERM_COLORS = isDark ? PERM_COLORS_D : PERM_COLORS_L

  const tabUsers = users.filter(u => u.bank_type === bankTypeTab)
  const filtered = tabUsers.filter(u => {
    const q = search.toLowerCase()
    return !q || u.display_name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q)
  })

  const closeModal = () => setModal(null)

  const handleSave = (form) => {
    if (modal.user) {
      setUsers(us => us.map(u => u.user_id === modal.user.user_id ? { ...u, ...form } : u))
    } else {
      const newUser = {
        user_id: `usr-${String(users.length + 1).padStart(3, '0')}`,
        ...form, is_active: true, totp_enabled: false, last_login: null,
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

  const sbCount  = users.filter(u => u.bank_type === 'SB').length
  const smbCount = users.filter(u => u.bank_type === 'SMB').length
  const activeCount = tabUsers.filter(u => u.is_active).length
  const totpCount   = tabUsers.filter(u => u.totp_enabled).length

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page}`}>

        {/* Header */}
        <div className={`sticky top-0 z-10 ${isDark ? 'bg-navy-950/95' : 'bg-slate-50/95'} backdrop-blur border-b ${th.divider} px-6 py-3`}>
          <div className="flex items-center justify-between">
            <div>
              <h1 className={`text-base font-semibold ${th.heading}`}>User Management</h1>
              <p className={`text-[11px] ${th.muted}`}>{activeCount} active · {totpCount} with TOTP · {tabUsers.length} in this tab</p>
            </div>
            <button
              onClick={() => setModal({ type: 'create' })}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium bg-gold-400 hover:bg-gold-500 text-navy-950 transition-colors"
            >+ New User</button>
          </div>
        </div>

        <div className="px-6 py-5 max-w-7xl space-y-5">

          {/* SB / SMB tab selector */}
          <div className={`inline-flex rounded-xl border p-1 gap-1 ${th.card}`}>
            {[
              { key: 'SB',  label: 'Sponsor Bank (SB)',       count: sbCount  },
              { key: 'SMB', label: 'Sub-Member Banks (SMB)',   count: smbCount },
            ].map(tab => (
              <button
                key={tab.key}
                onClick={() => { setBankTypeTab(tab.key); setSearch('') }}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg text-[12px] font-medium transition-all ${
                  bankTypeTab === tab.key
                    ? 'bg-gold-400 text-navy-950'
                    : (isDark ? 'text-slate-400 hover:text-slate-200' : 'text-slate-500 hover:text-slate-700')
                }`}
              >
                {tab.label}
                <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-semibold ${
                  bankTypeTab === tab.key
                    ? 'bg-navy-950/20 text-navy-950'
                    : (isDark ? 'bg-white/8 text-slate-400' : 'bg-slate-200 text-slate-500')
                }`}>{tab.count}</span>
              </button>
            ))}
          </div>

          {/* SMB context note */}
          {bankTypeTab === 'SMB' && (
            <div className={`rounded-xl border px-4 py-3 text-[11px] ${isDark ? 'bg-teal-900/20 border-teal-700/30 text-teal-300' : 'bg-teal-50 border-teal-200 text-teal-700'}`}>
              <strong>SMB Users</strong> — These accounts belong to Sub-Member Banks that route clearing through this sponsor. Each SMB user can only see their own bank's data. Roles: smb_admin · smb_editor · smb_viewer.
            </div>
          )}

          {/* Search + inline stats */}
          <div className="flex gap-3 items-center">
            <input
              type="text" placeholder="Search name or email…"
              value={search} onChange={e => setSearch(e.target.value)}
              className={`text-[12px] border rounded-lg px-3 py-1.5 flex-1 max-w-xs focus:outline-none focus:border-gold-400/40 transition-colors ${th.input}`}
            />
            <span className={`text-[11px] ${th.muted}`}>{filtered.length} shown</span>
            <div className={`h-4 w-px ${th.divider}`} />
            <span className={`text-[11px] ${th.muted}`}>
              <span className={th.heading}>{activeCount}</span> active
              <span className="mx-1.5 opacity-40">·</span>
              <span className={th.heading}>{totpCount}</span> with TOTP
              {tabUsers.length > 0 && <span className="opacity-60"> ({Math.round(totpCount / tabUsers.length * 100)}%)</span>}
            </span>
          </div>

          {/* User table */}
          <div className={`border rounded-xl overflow-hidden ${th.card}`}>
            <div className="overflow-x-auto">
              <table className="w-full text-[12px]">
                <thead>
                  <tr className={`border-b ${th.divider}`}>
                    {['User', 'Role', 'Permission', bankTypeTab === 'SB' ? 'Zone' : 'Bank', 'TOTP', 'Status', 'Last Login', 'Actions'].map(h => (
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
                        <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full border ${ROLE_COLORS[u.role] || ''}`}>
                          {ROLE_LABELS[u.role] || u.role}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full border ${PERM_COLORS[u.permission_level] || ''}`}>
                          {PERM_LABELS[u.permission_level] || u.permission_level}
                        </span>
                      </td>
                      <td className={`px-4 py-3 ${th.muted} font-mono text-[11px]`}>
                        {bankTypeTab === 'SB' ? (u.clearing_zone || '—') : u.email.split('@')[1]}
                      </td>
                      <td className="px-4 py-3">
                        {u.totp_enabled
                          ? <span className="text-[10px] text-emerald-400 font-medium">● On</span>
                          : <span className={`text-[10px] ${th.muted}`}>○ Off</span>}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full border ${
                          u.is_active
                            ? (isDark ? 'bg-emerald-900/30 text-emerald-300 border-emerald-700/30' : 'bg-emerald-100 text-emerald-700 border-emerald-300')
                            : (isDark ? 'bg-slate-800 text-slate-500 border-white/5' : 'bg-slate-100 text-slate-400 border-slate-200')
                        }`}>{u.is_active ? 'Active' : 'Inactive'}</span>
                      </td>
                      <td className={`px-4 py-3 text-[11px] ${th.muted} font-mono`}>{fmt(u.last_login)}</td>
                      <td className="px-4 py-3">
                        <div className="flex gap-2 justify-end">
                          <button onClick={() => setModal({ type: 'edit', user: u })} className={`text-[10px] px-2.5 py-1 rounded border transition-colors ${isDark ? 'border-white/10 text-slate-400 hover:text-white' : 'border-slate-200 text-slate-500 hover:text-slate-800'}`}>Edit</button>
                          {!u.totp_enabled && u.is_active && (
                            <button onClick={() => setModal({ type: 'totp_setup', user: u })} className="text-[10px] px-2.5 py-1 rounded border border-blue-700/40 text-blue-400 hover:text-blue-300 transition-colors">Setup TOTP</button>
                          )}
                          {u.totp_enabled && (
                            <button onClick={() => setModal({ type: 'totp_reset', user: u })} className={`text-[10px] px-2.5 py-1 rounded border transition-colors ${isDark ? 'border-amber-700/40 text-amber-400 hover:text-amber-300' : 'border-amber-300 text-amber-600 hover:text-amber-700'}`}>Reset TOTP</button>
                          )}
                          {u.is_active && (
                            <button onClick={() => setModal({ type: 'deactivate', user: u })} className={`text-[10px] px-2.5 py-1 rounded border transition-colors ${isDark ? 'border-red-700/40 text-red-400 hover:text-red-300' : 'border-red-300 text-red-600 hover:text-red-700'}`}>Deactivate</button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                  {filtered.length === 0 && (
                    <tr>
                      <td colSpan={8} className={`px-4 py-12 text-center ${th.muted}`}>
                        <div className="text-2xl mb-2 opacity-30">👤</div>
                        <div className={`text-[12px] font-medium ${th.body} mb-1`}>
                          {search ? `No users match "${search}"` : `No ${bankTypeTab} users yet`}
                        </div>
                        <div className={`text-[11px] ${th.muted}`}>
                          {search ? 'Try a different name or email.' : 'Create the first user with the button above.'}
                        </div>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

        </div>
      </div>

      {/* Modals */}
      {(modal?.type === 'create' || modal?.type === 'edit') && (
        <CreateEditModal
          user={modal.user || null}
          isDark={isDark}
          onClose={closeModal}
          onSave={handleSave}
          defaultBankType={bankTypeTab}
        />
      )}
      {modal?.type === 'totp_setup' && <TOTPSetupModal user={modal.user} isDark={isDark} onClose={closeModal} />}
      {modal?.type === 'totp_reset' && (
        <ConfirmModal title="Reset TOTP" message={`This will disable TOTP for ${modal.user.display_name}. They will be able to log in without a second factor until TOTP is set up again. Proceed?`} confirmLabel="Reset TOTP" danger isDark={isDark} onClose={closeModal} onConfirm={() => handleResetTOTP(modal.user)} />
      )}
      {modal?.type === 'deactivate' && (
        <ConfirmModal title="Deactivate User" message={`${modal.user.display_name} (${modal.user.email}) will no longer be able to log in. This action is reversible via Edit.`} confirmLabel="Deactivate" danger isDark={isDark} onClose={closeModal} onConfirm={() => handleDeactivate(modal.user)} />
      )}
    </AppShell>
  )
}

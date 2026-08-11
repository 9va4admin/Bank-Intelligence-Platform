import { useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'
import { BANK_CONFIG } from '../../../shared/config/bank.config'
import { FEDERAL_BANK_BRANCHES } from '../../../shared/config/federalBankBranches'

const API = import.meta.env.VITE_API_BASE || ''
// DEMO mode: no backend, use client-side mock data.
// POC/PROD: Vite proxy forwards /v1/* to the real backend — always use real API.
const USE_MOCK = BANK_CONFIG.deployment_mode === 'DEMO'

// ── Mock branch data (keyed by bank_id) ──────────────────────────────────

const MOCK_BRANCHES_DB = {
  'karnataka-bank': [
    { branch_name: 'Mangalore Main',         branch_ifsc: 'KARB0000001', address: '1st Cross, Kodialbail',     city: 'Mangalore',  district: 'Dakshina Kannada', state: 'Karnataka',   pin_code: '575003', phone: '08242440150', is_active: true,  scanner_input_mode: 'SDK_PUSH'    },
    { branch_name: 'Bengaluru MG Road',      branch_ifsc: 'KARB0000002', address: '41 MG Road',                city: 'Bengaluru',  district: 'Bengaluru Urban',  state: 'Karnataka',   pin_code: '560001', phone: '08022212000', is_active: true,  scanner_input_mode: 'FOLDER_DROP' },
    { branch_name: 'Hubli Main',             branch_ifsc: 'KARB0000003', address: 'Lamington Road',            city: 'Hubli',      district: 'Dharwad',          state: 'Karnataka',   pin_code: '580020', phone: '08362357000', is_active: true,  scanner_input_mode: 'UI_UPLOAD'   },
    { branch_name: 'Mysuru Sayyaji Rao Rd',  branch_ifsc: 'KARB0000004', address: 'Sayyaji Rao Road',          city: 'Mysuru',     district: 'Mysuru',           state: 'Karnataka',   pin_code: '570001', phone: '08212420000', is_active: true,  scanner_input_mode: 'UI_UPLOAD'   },
    { branch_name: 'Udupi Town',             branch_ifsc: 'KARB0000005', address: 'Car Street, Udupi',         city: 'Udupi',      district: 'Udupi',            state: 'Karnataka',   pin_code: '576101', phone: '08202529000', is_active: true,  scanner_input_mode: 'SDK_PUSH'    },
    { branch_name: 'Kochi Fort Branch',      branch_ifsc: 'KARB0000006', address: 'Fort Kochi, Ernakulam',     city: 'Kochi',      district: 'Ernakulam',        state: 'Kerala',      pin_code: '682001', phone: '04842226000', is_active: true,  scanner_input_mode: 'UI_UPLOAD'   },
    { branch_name: 'Chennai Anna Salai',     branch_ifsc: 'KARB0000007', address: '56 Anna Salai',             city: 'Chennai',    district: 'Chennai',          state: 'Tamil Nadu',  pin_code: '600002', phone: '04428562000', is_active: true,  scanner_input_mode: 'UI_UPLOAD'   },
    { branch_name: 'Mumbai Fort',            branch_ifsc: 'KARB0000008', address: '12 Horniman Circle',        city: 'Mumbai',     district: 'Mumbai',           state: 'Maharashtra', pin_code: '400001', phone: '02222654000', is_active: false, scanner_input_mode: 'UI_UPLOAD'   },
    { branch_name: 'Bengaluru Jayanagar',    branch_ifsc: 'KARB0000009', address: '4th Block, 11th Main',      city: 'Bengaluru',  district: 'Bengaluru Urban',  state: 'Karnataka',   pin_code: '560041', phone: '08026572000', is_active: true,  scanner_input_mode: 'FOLDER_DROP' },
    { branch_name: 'Manipal Campus',         branch_ifsc: 'KARB0000010', address: 'MIT Campus Road',           city: 'Manipal',    district: 'Udupi',            state: 'Karnataka',   pin_code: '576104', phone: '08202577000', is_active: true,  scanner_input_mode: 'UI_UPLOAD'   },
    { branch_name: 'Hyderabad Banjara Hills',branch_ifsc: 'KARB0000011', address: 'Road No 2, Banjara Hills',  city: 'Hyderabad',  district: 'Hyderabad',        state: 'Telangana',   pin_code: '500034', phone: '04023554000', is_active: true,  scanner_input_mode: 'SDK_PUSH'    },
    { branch_name: 'Delhi Connaught Place',  branch_ifsc: 'KARB0000012', address: 'Block A, Connaught Place',  city: 'New Delhi',  district: 'New Delhi',        state: 'Delhi',       pin_code: '110001', phone: '01123415000', is_active: true,  scanner_input_mode: 'UI_UPLOAD'   },
  ],
  'saraswat-coop': [
    { branch_name: 'Saraswat Head Office',   branch_ifsc: 'SRCB0000001', address: 'Erandwane, Karve Road',     city: 'Pune',       district: 'Pune',             state: 'Maharashtra', pin_code: '411004', phone: '02025435000', is_active: true,  scanner_input_mode: 'SDK_PUSH'    },
    { branch_name: 'Mumbai Fort Main',       branch_ifsc: 'SRCB0000002', address: 'DN Road, Fort',             city: 'Mumbai',     district: 'Mumbai',           state: 'Maharashtra', pin_code: '400001', phone: '02222660000', is_active: true,  scanner_input_mode: 'FOLDER_DROP' },
    { branch_name: 'Thane West',             branch_ifsc: 'SRCB0000003', address: 'Gokhale Road, Naupada',     city: 'Thane',      district: 'Thane',            state: 'Maharashtra', pin_code: '400602', phone: '02225414000', is_active: true,  scanner_input_mode: 'UI_UPLOAD'   },
    { branch_name: 'Pune Shivajinagar',      branch_ifsc: 'SRCB0000004', address: 'FC Road, Shivajinagar',     city: 'Pune',       district: 'Pune',             state: 'Maharashtra', pin_code: '411005', phone: '02025536000', is_active: true,  scanner_input_mode: 'UI_UPLOAD'   },
    { branch_name: 'Nashik Main',            branch_ifsc: 'SRCB0000005', address: 'Mahatma Gandhi Road',       city: 'Nashik',     district: 'Nashik',           state: 'Maharashtra', pin_code: '422001', phone: '02532318000', is_active: true,  scanner_input_mode: 'UI_UPLOAD'   },
    { branch_name: 'Aurangabad Nirala Bazar',branch_ifsc: 'SRCB0000006', address: 'Nirala Bazar',              city: 'Aurangabad', district: 'Aurangabad',       state: 'Maharashtra', pin_code: '431001', phone: '02402335000', is_active: true,  scanner_input_mode: 'SDK_PUSH'    },
    { branch_name: 'Navi Mumbai Vashi',      branch_ifsc: 'SRCB0000007', address: 'Sector 17, Vashi',          city: 'Navi Mumbai',district: 'Thane',            state: 'Maharashtra', pin_code: '400703', phone: '02227892000', is_active: true,  scanner_input_mode: 'UI_UPLOAD'   },
    { branch_name: 'Goa Panaji',             branch_ifsc: 'SRCB0000008', address: 'Dr Atmaram Borkar Road',    city: 'Panaji',     district: 'North Goa',        state: 'Goa',         pin_code: '403001', phone: '08322425000', is_active: true,  scanner_input_mode: 'UI_UPLOAD'   },
    { branch_name: 'Bengaluru Malleswaram',  branch_ifsc: 'SRCB0000009', address: '8th Cross, Malleswaram',    city: 'Bengaluru',  district: 'Bengaluru Urban',  state: 'Karnataka',   pin_code: '560003', phone: '08023565000', is_active: true,  scanner_input_mode: 'FOLDER_DROP' },
    { branch_name: 'Kolhapur Shahupuri',     branch_ifsc: 'SRCB0000010', address: 'Shahupuri 2nd Lane',        city: 'Kolhapur',   district: 'Kolhapur',         state: 'Maharashtra', pin_code: '416001', phone: '02312543000', is_active: true,  scanner_input_mode: 'UI_UPLOAD'   },
    { branch_name: 'Mumbai Dadar',           branch_ifsc: 'SRCB0000011', address: 'LJ Cross Road, Dadar West', city: 'Mumbai',     district: 'Mumbai',           state: 'Maharashtra', pin_code: '400028', phone: '02224441000', is_active: false, scanner_input_mode: 'UI_UPLOAD'   },
    { branch_name: 'Pune Kothrud',           branch_ifsc: 'SRCB0000012', address: 'Paud Road, Kothrud',        city: 'Pune',       district: 'Pune',             state: 'Maharashtra', pin_code: '411038', phone: '02025462000', is_active: true,  scanner_input_mode: 'UI_UPLOAD'   },
  ],
}

const SCANNER_MODES = ['SDK_PUSH', 'SDK_PUSH', 'FOLDER_DROP', 'UI_UPLOAD']
MOCK_BRANCHES_DB['federal-bank'] = FEDERAL_BANK_BRANCHES.map((b, i) => ({
  branch_name:        b.name,
  branch_ifsc:        b.ifsc,
  address:            '',
  city:               b.city,
  district:           b.district,
  state:              b.state,
  pin_code:           b.pin,
  phone_number:       b.phone,
  is_active:          true,
  scanner_input_mode: SCANNER_MODES[i % SCANNER_MODES.length],
}))

// Pick the mock set for the currently configured bank; fall back to an empty list.
const ACTIVE_MOCK_BRANCHES = MOCK_BRANCHES_DB[BANK_CONFIG.bank_id] ?? []

// ── Client-side CSV parser (used in mock mode for the import preview) ────

function parseCsvText(text) {
  const lines = text.split(/\r?\n/).filter(l => l.trim())
  if (lines.length < 2) throw new Error('CSV must have a header row and at least one data row.')

  const errors = []
  let validCount = 0
  // Skip header row (index 0), data rows start at index 1
  for (let i = 1; i < lines.length; i++) {
    const raw = lines[i]
    // Handle quoted fields — split on commas not inside quotes
    const cols = raw.match(/(".*?"|[^,]+|(?<=,)(?=,)|(?<=,)$|^(?=,))/g)
      ?.map(c => c.trim().replace(/^"|"$/g, '')) ?? raw.split(',').map(c => c.trim())
    const rowNum = i + 1

    if (cols.length < 8) {
      errors.push({ row: rowNum, error: `Expected 8 columns, found ${cols.length}` })
      continue
    }
    const [branchName, , , , , pinCode, ifsc] = cols
    if (!branchName?.trim()) {
      errors.push({ row: rowNum, error: 'Branch Name is empty' })
      continue
    }
    if (!ifsc || ifsc.trim().length !== 11) {
      errors.push({ row: rowNum, error: `IFSC "${ifsc?.trim()}" must be exactly 11 characters` })
      continue
    }
    if (!/^\d{6}$/.test(pinCode?.trim())) {
      errors.push({ row: rowNum, error: `PIN Code "${pinCode?.trim()}" must be 6 digits` })
      continue
    }
    validCount++
  }
  return { valid_count: validCount, error_count: errors.length, errors }
}

async function readFileAsText(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader()
    r.onload = e => resolve(e.target.result)
    r.onerror = () => reject(new Error('Could not read file'))
    r.readAsText(file)
  })
}

// ── API calls ──────────────────────────────────────────────────────────────

function getCsrf() { return sessionStorage.getItem('astra-csrf') || '' }

async function apiFetch(path, opts = {}) {
  const res = await fetch(`${API}${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': getCsrf(), ...opts.headers },
    ...opts,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

function fetchBranches({ state, city, q, isActive, limit = 50 }) {
  if (USE_MOCK) {
    let results = [...ACTIVE_MOCK_BRANCHES]
    if (q) results = results.filter(b =>
      b.branch_name.toLowerCase().includes(q.toLowerCase()) ||
      b.branch_ifsc.toLowerCase().includes(q.toLowerCase()))
    if (state) results = results.filter(b => b.state.toLowerCase().includes(state.toLowerCase()))
    if (city)  results = results.filter(b => b.city.toLowerCase().includes(city.toLowerCase()))
    if (isActive !== null) results = results.filter(b => b.is_active === (isActive === true || isActive === 'true'))
    const total = results.length
    return Promise.resolve({ branches: results.slice(0, limit), total })
  }
  const params = new URLSearchParams()
  if (state) params.set('state', state)
  if (city)  params.set('city', city)
  if (q)     params.set('q', q)
  if (isActive !== null) params.set('is_active', isActive)
  params.set('limit', limit)
  return apiFetch(`/v1/branches?${params}`)
}

function createBranch(payload) {
  if (USE_MOCK) {
    ACTIVE_MOCK_BRANCHES.push({ ...payload, is_active: true })
    return Promise.resolve({ branch_ifsc: payload.branch_ifsc })
  }
  return apiFetch('/v1/branches', { method: 'POST', body: JSON.stringify(payload) })
}

function updateBranch(ifsc, payload) {
  if (USE_MOCK) {
    const idx = ACTIVE_MOCK_BRANCHES.findIndex(b => b.branch_ifsc === ifsc)
    if (idx >= 0) ACTIVE_MOCK_BRANCHES[idx] = { ...ACTIVE_MOCK_BRANCHES[idx], ...payload }
    return Promise.resolve({ branch_ifsc: ifsc })
  }
  return apiFetch(`/v1/branches/${ifsc}`, { method: 'PUT', body: JSON.stringify(payload) })
}

function deleteBranch(ifsc) {
  if (USE_MOCK) {
    const idx = ACTIVE_MOCK_BRANCHES.findIndex(b => b.branch_ifsc === ifsc)
    if (idx >= 0) ACTIVE_MOCK_BRANCHES[idx].is_active = false
    return Promise.resolve({})
  }
  return apiFetch(`/v1/branches/${ifsc}`, { method: 'DELETE' })
}

async function previewImport(file) {
  if (USE_MOCK) {
    const text = await readFileAsText(file)
    return parseCsvText(text)
  }
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch(`${API}/v1/branches/bulk-import/preview`, {
    method: 'POST', credentials: 'include',
    headers: { 'X-CSRF-Token': getCsrf() },
    body: fd,
  })
  if (!res.ok) { const b = await res.json().catch(() => ({})); throw new Error(b.detail || `HTTP ${res.status}`) }
  return res.json()
}

async function confirmImport(file) {
  if (USE_MOCK) {
    const text = await readFileAsText(file)
    const { valid_count, error_count } = parseCsvText(text)
    return { imported_count: valid_count, skipped_count: 0, error_count }
  }
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch(`${API}/v1/branches/bulk-import`, {
    method: 'POST', credentials: 'include',
    headers: { 'X-CSRF-Token': getCsrf() },
    body: fd,
  })
  if (!res.ok) { const b = await res.json().catch(() => ({})); throw new Error(b.detail || `HTTP ${res.status}`) }
  return res.json()
}

// ── Sub-components ────────────────────────────────────────────────────────

function Badge({ children, variant = 'neutral', isDark }) {
  const cls = {
    green: isDark ? 'bg-emerald-900/50 text-emerald-300 border-emerald-700/40' : 'bg-emerald-50 text-emerald-700 border-emerald-200',
    red:   isDark ? 'bg-red-900/50 text-red-300 border-red-700/40' : 'bg-red-50 text-red-700 border-red-200',
    neutral: isDark ? 'bg-white/8 text-slate-300 border-white/10' : 'bg-slate-100 text-slate-600 border-slate-200',
  }
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${cls[variant]}`}>
      {children}
    </span>
  )
}

function Modal({ title, onClose, isDark, children }) {
  const th = {
    overlay: 'fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm',
    box: isDark ? 'bg-navy-900 border border-white/12 rounded-xl shadow-2xl w-full max-w-2xl mx-4' : 'bg-white border border-slate-200 rounded-xl shadow-2xl w-full max-w-2xl mx-4',
    header: isDark ? 'flex items-center justify-between px-6 py-4 border-b border-white/10' : 'flex items-center justify-between px-6 py-4 border-b border-slate-200',
    title: isDark ? 'text-white font-semibold text-base' : 'text-slate-900 font-semibold text-base',
    close: isDark ? 'text-slate-400 hover:text-white transition-colors' : 'text-slate-400 hover:text-slate-700 transition-colors',
    body: 'px-6 py-5 space-y-4',
  }
  return (
    <div className={th.overlay} onClick={onClose}>
      <div className={th.box} onClick={e => e.stopPropagation()}>
        <div className={th.header}>
          <span className={th.title}>{title}</span>
          <button className={th.close} onClick={onClose}>✕</button>
        </div>
        <div className={th.body}>{children}</div>
      </div>
    </div>
  )
}

function Field({ label, isDark, children }) {
  const lbl = isDark ? 'block text-xs font-medium text-slate-400 mb-1' : 'block text-xs font-medium text-slate-500 mb-1'
  return (
    <div>
      <label className={lbl}>{label}</label>
      {children}
    </div>
  )
}

function Input({ isDark, ...props }) {
  const cls = isDark
    ? 'w-full bg-white/6 border border-white/12 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-violet-500'
    : 'w-full bg-white border border-slate-300 rounded-lg px-3 py-2 text-sm text-slate-900 placeholder-slate-400 focus:outline-none focus:border-violet-500'
  return <input className={cls} {...props} />
}

function Select({ isDark, children, ...props }) {
  const cls = isDark
    ? 'w-full bg-white/6 border border-white/12 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-violet-500'
    : 'w-full bg-white border border-slate-300 rounded-lg px-3 py-2 text-sm text-slate-900 focus:outline-none focus:border-violet-500'
  return <select className={cls} {...props}>{children}</select>
}

const SCANNER_MODE_LABELS = {
  UI_UPLOAD:   { short: 'UI', label: 'UI Upload',   desc: 'Operator uploads cheque images via web UI' },
  FOLDER_DROP: { short: 'FDR', label: 'Folder Drop', desc: 'Scanner writes to folder; ASTRA watcher picks up' },
  SDK_PUSH:    { short: 'SDK', label: 'SDK Push',    desc: 'Scanner SDK calls POST /v1/cts/outward/scan/submit' },
}

function BranchFormModal({ branch, isDark, onClose, onSave }) {
  const isEdit = !!branch
  const [form, setForm] = useState({
    branch_name:          branch?.branch_name ?? '',
    branch_ifsc:          branch?.branch_ifsc ?? '',
    city:                 branch?.city ?? '',
    district:             branch?.district ?? '',
    state:                branch?.state ?? '',
    address:              branch?.address ?? '',
    pin_code:             branch?.pin_code ?? '',
    phone_number:         branch?.phone_number ?? '',
    scanner_input_mode:   branch?.scanner_input_mode ?? 'UI_UPLOAD',
  })
  const [err, setErr] = useState('')

  function handleChange(k, v) {
    setForm(f => ({ ...f, [k]: v }))
    setErr('')
  }

  function handleSubmit() {
    if (!form.branch_name.trim()) return setErr('Branch name is required.')
    if (!isEdit) {
      if (!form.branch_ifsc.trim()) return setErr('IFSC code is required.')
      if (form.branch_ifsc.length !== 11) return setErr('IFSC must be exactly 11 characters.')
      if (!/^[A-Za-z0-9]+$/.test(form.branch_ifsc)) return setErr('IFSC must be alphanumeric.')
    }
    const basePayload = {
      branch_name:   form.branch_name,
      city:          form.city,
      district:      form.district,
      state:         form.state,
      address:       form.address,
      pin_code:      form.pin_code,
      phone_number:  form.phone_number,
      scanner_input_mode: form.scanner_input_mode,
    }
    const payload = isEdit ? basePayload : { ...basePayload, branch_ifsc: form.branch_ifsc.toUpperCase() }
    onSave(payload)
  }

  const btnCls = 'px-4 py-2 rounded-lg text-sm font-medium transition-colors'
  const infoCls = isDark ? 'text-xs text-slate-400 bg-white/4 border border-white/10 rounded-lg px-3 py-2' : 'text-xs text-slate-500 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2'

  return (
    <Modal title={isEdit ? 'Edit Branch' : 'Add Branch'} onClose={onClose} isDark={isDark}>
      <div className="grid grid-cols-2 gap-4">
        <Field label="Branch Name *" isDark={isDark}>
          <Input isDark={isDark} value={form.branch_name} onChange={e => handleChange('branch_name', e.target.value)} placeholder="Koramangala Branch" />
        </Field>
        <Field label={isEdit ? 'IFSC Code (read-only)' : 'IFSC Code *'} isDark={isDark}>
          <Input isDark={isDark} value={form.branch_ifsc} onChange={e => handleChange('branch_ifsc', e.target.value)} placeholder="KARB0000123" maxLength={11} disabled={isEdit} />
        </Field>
        <Field label="City" isDark={isDark}>
          <Input isDark={isDark} value={form.city} onChange={e => handleChange('city', e.target.value)} placeholder="Bengaluru" />
        </Field>
        <Field label="District" isDark={isDark}>
          <Input isDark={isDark} value={form.district} onChange={e => handleChange('district', e.target.value)} placeholder="Bengaluru Urban" />
        </Field>
        <Field label="State" isDark={isDark}>
          <Input isDark={isDark} value={form.state} onChange={e => handleChange('state', e.target.value)} placeholder="Karnataka" />
        </Field>
        <Field label="PIN Code" isDark={isDark}>
          <Input isDark={isDark} value={form.pin_code} onChange={e => handleChange('pin_code', e.target.value)} placeholder="560034" maxLength={6} />
        </Field>
        <Field label="Phone Number" isDark={isDark}>
          <Input isDark={isDark} value={form.phone_number} onChange={e => handleChange('phone_number', e.target.value)} placeholder="08025534567" />
        </Field>
        <Field label="Address" isDark={isDark}>
          <Input isDark={isDark} value={form.address} onChange={e => handleChange('address', e.target.value)} placeholder="80 Feet Road, Koramangala" />
        </Field>
      </div>

      {/* Scanner configuration — full width below the grid */}
      <div className={`mt-1 p-4 rounded-xl border ${isDark ? 'border-white/8 bg-white/3' : 'border-slate-200 bg-slate-50'}`}>
        <p className={`text-xs font-semibold uppercase tracking-wide mb-3 ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>Scanner Configuration</p>
        <Field label="Scanner Input Mode" isDark={isDark}>
          <Select isDark={isDark} value={form.scanner_input_mode} onChange={e => handleChange('scanner_input_mode', e.target.value)}>
            {Object.entries(SCANNER_MODE_LABELS).map(([k, v]) => (
              <option key={k} value={k}>{v.label}</option>
            ))}
          </Select>
        </Field>
        <p className={`mt-1.5 ${infoCls}`}>{SCANNER_MODE_LABELS[form.scanner_input_mode]?.desc}</p>

        {form.scanner_input_mode === 'FOLDER_DROP' && (
          <p className={`mt-3 ${infoCls}`}>
            Folder path and OEM settings are configured in <strong>Scanner Config</strong> (Admin → Scanner Config). Set the drop folder path there after saving this branch.
          </p>
        )}

        {form.scanner_input_mode === 'SDK_PUSH' && (
          <p className={`mt-3 ${infoCls}`}>
            SDK endpoint: <span className="font-mono">POST /v1/cts/outward/scan/submit</span> — scanner SDK calls this directly. No folder configuration required.
          </p>
        )}
      </div>

      {err && <p className="text-red-400 text-xs mt-2">{err}</p>}
      <div className="flex justify-end gap-3 pt-2">
        <button className={`${btnCls} ${isDark ? 'text-slate-300 hover:text-white' : 'text-slate-600 hover:text-slate-900'}`} onClick={onClose}>Cancel</button>
        <button className={`${btnCls} bg-violet-600 text-white hover:bg-violet-500`} onClick={handleSubmit}>{isEdit ? 'Save Changes' : 'Create Branch'}</button>
      </div>
    </Modal>
  )
}

function ImportModal({ isDark, onClose, qc }) {
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState(null)
  const [step, setStep] = useState('pick') // pick → preview → done
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const fileRef = useRef()

  async function handlePreview() {
    if (!file) return
    setLoading(true)
    setErr('')
    try {
      const data = await previewImport(file)
      setPreview(data)
      setStep('preview')
    } catch (e) {
      setErr(e.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleConfirm() {
    setLoading(true)
    setErr('')
    try {
      const data = await confirmImport(file)
      setResult(data)
      setStep('done')
      qc.invalidateQueries({ queryKey: ['branches'] })
    } catch (e) {
      setErr(e.message)
    } finally {
      setLoading(false)
    }
  }

  const cardCls = isDark ? 'bg-white/5 border border-white/10 rounded-lg p-4' : 'bg-slate-50 border border-slate-200 rounded-lg p-4'
  const bodyText = isDark ? 'text-slate-300 text-sm' : 'text-slate-700 text-sm'
  const mutedText = isDark ? 'text-slate-400 text-xs' : 'text-slate-500 text-xs'
  const btnCls = 'px-4 py-2 rounded-lg text-sm font-medium transition-colors'

  return (
    <Modal title="Import Branch Directory (CSV)" onClose={onClose} isDark={isDark}>
      {step === 'pick' && (
        <div className="space-y-4">
          <div className={cardCls}>
            <p className={bodyText}>Upload your branch directory CSV with the following columns:</p>
            <p className={`${mutedText} mt-2 font-mono`}>Branch Name, Complete Address, City, District, State, PIN Code, IFSC Code, Phone Number</p>
          </div>

          {/* Drop zone */}
          <div
            className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors ${
              isDark ? 'border-white/20 hover:border-violet-500/60' : 'border-slate-300 hover:border-violet-400'
            }`}
            onClick={() => fileRef.current?.click()}
            onDragOver={e => e.preventDefault()}
            onDrop={e => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) setFile(f) }}
          >
            <input ref={fileRef} type="file" accept=".csv,text/csv" className="hidden" onChange={e => setFile(e.target.files[0])} />
            {file
              ? <p className={`${bodyText} font-medium`}>📄 {file.name} ({(file.size / 1024).toFixed(1)} KB)</p>
              : <p className={mutedText}>Drag & drop CSV or click to browse</p>
            }
          </div>

          {err && <p className="text-red-400 text-xs">{err}</p>}
          <div className="flex justify-end gap-3">
            <button className={`${btnCls} ${isDark ? 'text-slate-300 hover:text-white' : 'text-slate-600 hover:text-slate-900'}`} onClick={onClose}>Cancel</button>
            <button className={`${btnCls} bg-violet-600 text-white hover:bg-violet-500 disabled:opacity-40`} onClick={handlePreview} disabled={!file || loading}>
              {loading ? 'Validating…' : 'Validate CSV'}
            </button>
          </div>
        </div>
      )}

      {step === 'preview' && preview && (
        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-3">
            {[
              { label: 'Valid rows', value: preview.valid_count, color: 'text-emerald-400' },
              { label: 'Errors', value: preview.error_count, color: 'text-red-400' },
              { label: 'Total', value: preview.valid_count + preview.error_count, color: isDark ? 'text-white' : 'text-slate-900' },
            ].map(s => (
              <div key={s.label} className={cardCls}>
                <p className={`text-2xl font-bold ${s.color}`}>{s.value}</p>
                <p className={mutedText}>{s.label}</p>
              </div>
            ))}
          </div>

          {preview.errors.length > 0 && (
            <div className={`${cardCls} max-h-40 overflow-y-auto`}>
              <p className="text-red-400 text-xs font-semibold mb-2">Row errors (will be skipped):</p>
              {preview.errors.map((e, i) => (
                <p key={i} className="text-xs text-red-300 font-mono">Row {e.row}: {e.error}</p>
              ))}
            </div>
          )}

          {err && <p className="text-red-400 text-xs">{err}</p>}
          <div className="flex justify-end gap-3">
            <button className={`${btnCls} ${isDark ? 'text-slate-300 hover:text-white' : 'text-slate-600'}`} onClick={() => setStep('pick')}>Back</button>
            <button
              className={`${btnCls} bg-emerald-600 text-white hover:bg-emerald-500 disabled:opacity-40`}
              onClick={handleConfirm}
              disabled={preview.valid_count === 0 || loading}
            >
              {loading ? 'Importing…' : `Import ${preview.valid_count} branches`}
            </button>
          </div>
        </div>
      )}

      {step === 'done' && result && (
        <div className="space-y-4 text-center">
          <p className="text-4xl">✅</p>
          <p className={isDark ? 'text-white font-semibold' : 'text-slate-900 font-semibold'}>Import complete</p>
          <div className="grid grid-cols-3 gap-3">
            {[
              { label: 'Imported', value: result.imported_count, color: 'text-emerald-400' },
              { label: 'Updated', value: result.skipped_count, color: 'text-violet-400' },
              { label: 'Errors', value: result.error_count, color: 'text-red-400' },
            ].map(s => (
              <div key={s.label} className={cardCls}>
                <p className={`text-2xl font-bold ${s.color}`}>{s.value}</p>
                <p className={mutedText}>{s.label}</p>
              </div>
            ))}
          </div>
          <button className={`${btnCls} bg-violet-600 text-white hover:bg-violet-500`} onClick={onClose}>Done</button>
        </div>
      )}
    </Modal>
  )
}

function DeleteConfirmModal({ branch, isDark, onClose, onConfirm }) {
  const bodyText = isDark ? 'text-slate-300 text-sm' : 'text-slate-700 text-sm'
  const btnCls = 'px-4 py-2 rounded-lg text-sm font-medium transition-colors'
  return (
    <Modal title="Deactivate Branch" onClose={onClose} isDark={isDark}>
      <p className={bodyText}>
        Are you sure you want to deactivate <strong>{branch.branch_ifsc}</strong> — {branch.branch_name}?
      </p>
      <p className={`text-xs mt-1 ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>
        The branch will be marked inactive (soft-delete). Existing scan records are preserved.
      </p>
      <div className="flex justify-end gap-3 pt-2">
        <button className={`${btnCls} ${isDark ? 'text-slate-300 hover:text-white' : 'text-slate-600'}`} onClick={onClose}>Cancel</button>
        <button className={`${btnCls} bg-red-600 text-white hover:bg-red-500`} onClick={onConfirm}>Deactivate</button>
      </div>
    </Modal>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────

export default function CTSBranchMaster() {
  const { isDark } = useTheme()
  const { bankId } = useBankContext()
  const qc = useQueryClient()

  const [filters, setFilters] = useState({ q: '', state: '', city: '', isActive: null })
  const [modal, setModal] = useState(null) // null | 'create' | 'edit' | 'delete' | 'import'
  const [selected, setSelected] = useState(null)
  const [toast, setToast] = useState(null)

  const th = {
    page:    isDark ? 'bg-navy-950'  : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'   : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    row:     isDark ? 'border-white/4 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
    input:   isDark ? 'bg-white/6 border-white/12 text-white placeholder-slate-500 focus:border-violet-500' : 'bg-white border-slate-300 text-slate-900 placeholder-slate-400 focus:border-violet-500',
    th:      isDark ? 'text-slate-400 text-xs font-medium uppercase tracking-wide' : 'text-slate-500 text-xs font-medium uppercase tracking-wide',
    td:      isDark ? 'text-slate-300 text-sm' : 'text-slate-700 text-sm',
  }

  const { data, isLoading, isError } = useQuery({
    queryKey: ['branches', bankId, filters],
    queryFn: () => fetchBranches({ ...filters }),
    staleTime: 30_000,
  })

  const createMut = useMutation({
    mutationFn: createBranch,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['branches'] }); setModal(null); showToast('Branch created.', 'green') },
    onError: e => showToast(e.message, 'red'),
  })

  const updateMut = useMutation({
    mutationFn: ({ ifsc, payload }) => updateBranch(ifsc, payload),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['branches'] }); setModal(null); showToast('Branch updated.', 'green') },
    onError: e => showToast(e.message, 'red'),
  })

  const deleteMut = useMutation({
    mutationFn: ifsc => deleteBranch(ifsc),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['branches'] }); setModal(null); showToast('Branch deactivated.', 'green') },
    onError: e => showToast(e.message, 'red'),
  })

  function showToast(msg, variant = 'green') {
    setToast({ msg, variant })
    setTimeout(() => setToast(null), 3500)
  }

  const branches = data?.branches ?? []
  const total = data?.total ?? 0

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5 min-h-0`}>

        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>Branch Master</h1>
            <p className={`text-sm mt-0.5 ${th.muted}`}>
              {total} branch{total !== 1 ? 'es' : ''} registered
            </p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => setModal('import')}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition-colors ${isDark ? 'border-white/15 text-slate-300 hover:bg-white/6' : 'border-slate-300 text-slate-700 hover:bg-slate-50'}`}
            >
              Import CSV
            </button>
            <button
              onClick={() => { setSelected(null); setModal('create') }}
              className="px-3 py-1.5 rounded-lg text-sm font-medium bg-violet-600 text-white hover:bg-violet-500 transition-colors"
            >
              + Add Branch
            </button>
          </div>
        </div>

        {/* Filters */}
        <div className={`border rounded-xl p-4 mb-4 ${th.card}`}>
          <div className="grid grid-cols-4 gap-3">
            {[
              { key: 'q', ph: 'Search name or IFSC…' },
              { key: 'state', ph: 'Filter by state…' },
              { key: 'city', ph: 'Filter by city…' },
            ].map(({ key, ph }) => (
              <input
                key={key}
                className={`rounded-lg border px-3 py-2 text-sm focus:outline-none ${th.input}`}
                placeholder={ph}
                value={filters[key]}
                onChange={e => setFilters(f => ({ ...f, [key]: e.target.value }))}
              />
            ))}
            <select
              className={`rounded-lg border px-3 py-2 text-sm focus:outline-none ${th.input}`}
              value={filters.isActive === null ? '' : String(filters.isActive)}
              onChange={e => setFilters(f => ({ ...f, isActive: e.target.value === '' ? null : e.target.value === 'true' }))}
            >
              <option value="">All statuses</option>
              <option value="true">Active only</option>
              <option value="false">Inactive only</option>
            </select>
          </div>
        </div>

        {/* Table */}
        <div className={`border rounded-xl overflow-hidden ${th.card}`}>
          <table className="w-full">
            <thead>
              <tr className={`border-b ${th.divider}`}>
                {['IFSC', 'Branch Name', 'City', 'State', 'District', 'Phone', 'PU', 'Scanner', 'Status', ''].map(h => (
                  <th key={h} className={`text-left px-4 py-3 ${th.th}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {isLoading && (
                <tr><td colSpan={10} className={`text-center py-12 ${th.muted}`}>Loading…</td></tr>
              )}
              {isError && (
                <tr><td colSpan={10} className="text-center py-12 text-red-400 text-sm">Failed to load branches.</td></tr>
              )}
              {!isLoading && branches.length === 0 && (
                <tr>
                  <td colSpan={10} className={`text-center py-12 ${th.muted} text-sm`}>
                    No branches found. Use <strong>Import CSV</strong> to load your branch directory.
                  </td>
                </tr>
              )}
              {branches.map(b => (
                <tr key={b.branch_ifsc} className={`border-b ${th.row} transition-colors`}>
                  <td className={`px-4 py-3 font-mono text-xs ${th.body}`}>{b.branch_ifsc}</td>
                  <td className={`px-4 py-3 ${th.body} max-w-48 truncate`}>{b.branch_name}</td>
                  <td className={`px-4 py-3 ${th.muted} text-sm`}>{b.city ?? '—'}</td>
                  <td className={`px-4 py-3 ${th.muted} text-sm`}>{b.state ?? '—'}</td>
                  <td className={`px-4 py-3 ${th.muted} text-sm`}>{b.district ?? '—'}</td>
                  <td className={`px-4 py-3 ${th.muted} text-sm`}>{b.phone_number ?? '—'}</td>
                  <td className={`px-4 py-3 text-sm`}>
                    {b.pu_id
                      ? <span className="font-mono text-xs text-violet-400">{b.pu_id}</span>
                      : <span className={`text-xs ${th.muted} italic`}>unassigned</span>
                    }
                  </td>
                  <td className="px-4 py-3">
                    <span
                      title={SCANNER_MODE_LABELS[b.scanner_input_mode]?.desc ?? b.scanner_input_mode}
                      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-mono font-medium border ${
                        b.scanner_input_mode === 'SDK_PUSH'    ? (isDark ? 'bg-blue-900/40 text-blue-300 border-blue-700/40'    : 'bg-blue-50 text-blue-700 border-blue-200') :
                        b.scanner_input_mode === 'FOLDER_DROP' ? (isDark ? 'bg-amber-900/40 text-amber-300 border-amber-700/40' : 'bg-amber-50 text-amber-700 border-amber-200') :
                                                                 (isDark ? 'bg-white/8 text-slate-300 border-white/10'           : 'bg-slate-100 text-slate-600 border-slate-200')
                      }`}
                    >
                      {SCANNER_MODE_LABELS[b.scanner_input_mode]?.short ?? b.scanner_input_mode}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <Badge isDark={isDark} variant={b.is_active ? 'green' : 'red'}>
                      {b.is_active ? 'Active' : 'Inactive'}
                    </Badge>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-2">
                      <button
                        className={`text-xs px-2 py-1 rounded transition-colors ${isDark ? 'text-slate-400 hover:text-white hover:bg-white/8' : 'text-slate-500 hover:text-slate-900 hover:bg-slate-100'}`}
                        onClick={() => { setSelected(b); setModal('edit') }}
                      >
                        Edit
                      </button>
                      {b.is_active && (
                        <button
                          className={`text-xs px-2 py-1 rounded transition-colors text-red-400 hover:text-red-300 ${isDark ? 'hover:bg-red-900/30' : 'hover:bg-red-50'}`}
                          onClick={() => { setSelected(b); setModal('delete') }}
                        >
                          Deactivate
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

      </div>

      {/* Modals */}
      {modal === 'create' && (
        <BranchFormModal
          isDark={isDark}
          branch={null}
          onClose={() => setModal(null)}
          onSave={payload => createMut.mutate(payload)}
        />
      )}
      {modal === 'edit' && selected && (
        <BranchFormModal
          isDark={isDark}
          branch={selected}
          onClose={() => setModal(null)}
          onSave={payload => updateMut.mutate({ ifsc: selected.branch_ifsc, payload })}
        />
      )}
      {modal === 'delete' && selected && (
        <DeleteConfirmModal
          isDark={isDark}
          branch={selected}
          onClose={() => setModal(null)}
          onConfirm={() => deleteMut.mutate(selected.branch_ifsc)}
        />
      )}
      {modal === 'import' && (
        <ImportModal isDark={isDark} onClose={() => setModal(null)} qc={qc} />
      )}

      {/* Toast */}
      {toast && (
        <div className={`fixed bottom-6 right-6 z-50 px-4 py-3 rounded-xl text-sm font-medium shadow-lg transition-all ${
          toast.variant === 'green' ? 'bg-emerald-600 text-white' : 'bg-red-600 text-white'
        }`}>
          {toast.msg}
        </div>
      )}
    </AppShell>
  )
}

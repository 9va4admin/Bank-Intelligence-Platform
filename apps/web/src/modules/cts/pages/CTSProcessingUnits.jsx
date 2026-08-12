/**
 * Processing Unit Master — CRUD
 *
 * A Processing Unit (PU) is the clearing-zone level grouping for CTS.
 * Each PU maps to one NGCH grid zone, runs its own Temporal task queue,
 * and has its own Kafka inward topic.
 *
 * Constraint: exactly one PU per clearing zone per bank.
 *
 * Routes: /cts/admin/processing-units
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'
import { BANK_CONFIG } from '../../../shared/config/bank.config'
import { FEDERAL_BANK_BRANCHES } from '../../../shared/config/federalBankBranches'

const API = import.meta.env.VITE_API_BASE || ''
// DEMO mode: use client-side mock. POC/PROD: Vite proxy forwards /v1/* to backend.
const USE_MOCK = BANK_CONFIG.deployment_mode === 'DEMO'

// NGCH geographic zones (Federal Bank, large private banks)
// + MICR city zones (co-operative banks, regional banks)
const VALID_ZONES = ['SOUTH', 'WEST', 'NORTH', 'EAST', 'MUMBAI', 'DELHI', 'CHENNAI', 'KOLKATA', 'HYDERABAD', 'AHMEDABAD', 'BENGALURU']

// ── Mock data ────────────────────────────────────────────────────────────────

const MOCK_PU_DB = {
  'karnataka-bank': [
    { pu_id: 'MUMBAI-PU-01',    bank_id: 'karnataka-bank', pu_name: 'Mumbai Processing Unit',    clearing_zone: 'MUMBAI',    ngch_participant_code: 'MUMBAI-KARB-001',    temporal_task_queue: 'cts-processing-karnataka-bank-MUMBAI-PU-01',    kafka_inward_topic: 'cts.inward.karnataka-bank.MUMBAI-PU-01',    max_agent_swarm_size: 200, is_active: true,  created_at: '2026-07-01T09:00:00Z', created_by: 'admin' },
    { pu_id: 'CHENNAI-PU-01',   bank_id: 'karnataka-bank', pu_name: 'Chennai Processing Unit',   clearing_zone: 'CHENNAI',   ngch_participant_code: 'CHENNAI-KARB-001',   temporal_task_queue: 'cts-processing-karnataka-bank-CHENNAI-PU-01',   kafka_inward_topic: 'cts.inward.karnataka-bank.CHENNAI-PU-01',   max_agent_swarm_size: 150, is_active: true,  created_at: '2026-07-01T09:05:00Z', created_by: 'admin' },
    { pu_id: 'DELHI-PU-01',     bank_id: 'karnataka-bank', pu_name: 'Delhi Processing Unit',     clearing_zone: 'DELHI',     ngch_participant_code: 'DELHI-KARB-001',     temporal_task_queue: 'cts-processing-karnataka-bank-DELHI-PU-01',     kafka_inward_topic: 'cts.inward.karnataka-bank.DELHI-PU-01',     max_agent_swarm_size: 100, is_active: true,  created_at: '2026-07-01T09:10:00Z', created_by: 'admin' },
    { pu_id: 'HYDERABAD-PU-01', bank_id: 'karnataka-bank', pu_name: 'Hyderabad Processing Unit', clearing_zone: 'HYDERABAD', ngch_participant_code: 'HYDERABAD-KARB-001', temporal_task_queue: 'cts-processing-karnataka-bank-HYDERABAD-PU-01', kafka_inward_topic: 'cts.inward.karnataka-bank.HYDERABAD-PU-01', max_agent_swarm_size: 100, is_active: false, created_at: '2026-07-01T09:15:00Z', created_by: 'admin' },
  ],
  'saraswat-coop': [
    { pu_id: 'MUMBAI-PU-01',  bank_id: 'saraswat-coop', pu_name: 'Mumbai PU',  clearing_zone: 'MUMBAI', ngch_participant_code: 'MUMBAI-SRCB-001',  temporal_task_queue: 'cts-processing-saraswat-coop-MUMBAI-PU-01',  kafka_inward_topic: 'cts.inward.saraswat-coop.MUMBAI-PU-01',  max_agent_swarm_size: 500, is_active: true, created_at: '2026-07-01T09:00:00Z', created_by: 'admin' },
    { pu_id: 'PUNE-PU-01',   bank_id: 'saraswat-coop', pu_name: 'Pune PU',   clearing_zone: 'MUMBAI', ngch_participant_code: 'MUMBAI-SRCB-002',  temporal_task_queue: 'cts-processing-saraswat-coop-PUNE-PU-01',   kafka_inward_topic: 'cts.inward.saraswat-coop.PUNE-PU-01',   max_agent_swarm_size: 200, is_active: true, created_at: '2026-07-01T09:05:00Z', created_by: 'admin' },
  ],
  'federal-bank': [
    { pu_id: 'SOUTH-MAIN', bank_id: 'federal-bank', pu_name: 'South Zone PU — Chennai NGCH', clearing_zone: 'SOUTH', ngch_participant_code: 'SOUTH-FDRL-001', temporal_task_queue: 'cts-processing-federal-bank-SOUTH-MAIN', kafka_inward_topic: 'cts.inward.federal-bank.SOUTH-MAIN', max_agent_swarm_size: 500, is_active: true,  created_at: '2026-08-01T06:00:00Z', created_by: 'admin' },
    { pu_id: 'WEST-MAIN',  bank_id: 'federal-bank', pu_name: 'West Zone PU — Mumbai NGCH',  clearing_zone: 'WEST',  ngch_participant_code: 'WEST-FDRL-001',  temporal_task_queue: 'cts-processing-federal-bank-WEST-MAIN',  kafka_inward_topic: 'cts.inward.federal-bank.WEST-MAIN',  max_agent_swarm_size: 300, is_active: true,  created_at: '2026-08-01T06:00:00Z', created_by: 'admin' },
    { pu_id: 'NORTH-MAIN', bank_id: 'federal-bank', pu_name: 'North Zone PU — Delhi NGCH',  clearing_zone: 'NORTH', ngch_participant_code: 'NORTH-FDRL-001', temporal_task_queue: 'cts-processing-federal-bank-NORTH-MAIN', kafka_inward_topic: 'cts.inward.federal-bank.NORTH-MAIN', max_agent_swarm_size: 200, is_active: true,  created_at: '2026-08-01T06:00:00Z', created_by: 'admin' },
    { pu_id: 'EAST-MAIN',  bank_id: 'federal-bank', pu_name: 'East Zone PU — Kolkata NGCH', clearing_zone: 'EAST',  ngch_participant_code: 'EAST-FDRL-001',  temporal_task_queue: 'cts-processing-federal-bank-EAST-MAIN',  kafka_inward_topic: 'cts.inward.federal-bank.EAST-MAIN',  max_agent_swarm_size: 100, is_active: true,  created_at: '2026-08-01T06:00:00Z', created_by: 'admin' },
  ],
}

const ACTIVE_MOCK = MOCK_PU_DB[BANK_CONFIG.bank_id] ?? []

// Demo branch data — map state → PU for Federal Bank; other banks get static counts
const STATE_TO_PU_DEMO = {
  'Kerala': 'SOUTH-MAIN', 'Tamil Nadu': 'SOUTH-MAIN', 'Karnataka': 'SOUTH-MAIN',
  'Andhra Pradesh': 'SOUTH-MAIN', 'Telangana': 'SOUTH-MAIN',
  'Maharashtra': 'WEST-MAIN', 'Goa': 'WEST-MAIN',
  'Delhi': 'NORTH-MAIN', 'West Bengal': 'EAST-MAIN',
}
const DEMO_BRANCHES_BY_PU = (() => {
  const grouped = {}
  if (BANK_CONFIG.bank_id === 'federal-bank') {
    for (const b of FEDERAL_BANK_BRANCHES) {
      const pu = STATE_TO_PU_DEMO[b.state] ?? 'SOUTH-MAIN'
      if (!grouped[pu]) grouped[pu] = []
      grouped[pu].push({ branch_ifsc: b.ifsc, branch_name: b.name, city: b.city, is_active: true, is_scanning_enabled: true })
    }
  }
  return grouped
})()

let _mockStore = ACTIVE_MOCK.map(p => ({ ...p }))

function getMockPUs() { return [..._mockStore] }

function createMockPU(data, bankId) {
  const usedZones = _mockStore.map(p => p.clearing_zone)
  if (usedZones.includes(data.clearing_zone)) {
    throw new Error(`A Processing Unit already exists for zone ${data.clearing_zone}`)
  }
  if (_mockStore.find(p => p.pu_id === data.pu_id)) {
    throw new Error(`Processing Unit ${data.pu_id} already exists`)
  }
  const pu = {
    ...data,
    bank_id: bankId,
    temporal_task_queue: `cts-processing-${bankId}-${data.pu_id}`,
    kafka_inward_topic:  `cts.inward.${bankId}.${data.pu_id}`,
    max_agent_swarm_size: data.max_agent_swarm_size ?? 200,
    is_active: true,
    created_at: new Date().toISOString(),
    created_by: 'admin',
  }
  _mockStore.push(pu)
  return pu
}

function updateMockPU(puId, data) {
  const idx = _mockStore.findIndex(p => p.pu_id === puId)
  if (idx === -1) throw new Error(`PU ${puId} not found`)
  _mockStore[idx] = { ..._mockStore[idx], ...data, updated_at: new Date().toISOString() }
  return _mockStore[idx]
}

function deactivateMockPU(puId) {
  return updateMockPU(puId, { is_active: false })
}

// ── API helpers ──────────────────────────────────────────────────────────────

async function apiFetch(path, opts = {}) {
  const resp = await fetch(`${API}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}))
    throw new Error(err.detail || `HTTP ${resp.status}`)
  }
  return resp.json()
}

// ── Shared UI primitives ─────────────────────────────────────────────────────

function Badge({ active, isDark }) {
  return active
    ? <span className="inline-flex items-center text-[10px] px-1.5 py-0.5 rounded border bg-emerald-500/15 text-emerald-400 border-emerald-500/30">Active</span>
    : <span className={`inline-flex items-center text-[10px] px-1.5 py-0.5 rounded border ${isDark ? 'bg-white/5 text-slate-500 border-white/10' : 'bg-slate-100 text-slate-400 border-slate-200'}`}>Inactive</span>
}

function ZonePill({ zone }) {
  const COLORS = {
    SOUTH:     'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
    WEST:      'bg-blue-500/15 text-blue-400 border-blue-500/30',
    NORTH:     'bg-violet-500/15 text-violet-400 border-violet-500/30',
    EAST:      'bg-teal-500/15 text-teal-400 border-teal-500/30',
    MUMBAI:    'bg-blue-500/15 text-blue-400 border-blue-500/30',
    DELHI:     'bg-violet-500/15 text-violet-400 border-violet-500/30',
    CHENNAI:   'bg-amber-500/15 text-amber-400 border-amber-500/30',
    KOLKATA:   'bg-teal-500/15 text-teal-400 border-teal-500/30',
    HYDERABAD: 'bg-rose-500/15 text-rose-400 border-rose-500/30',
    AHMEDABAD: 'bg-indigo-500/15 text-indigo-400 border-indigo-500/30',
    BENGALURU: 'bg-orange-500/15 text-orange-400 border-orange-500/30',
  }
  return (
    <span className={`inline-flex items-center text-[10px] px-2 py-0.5 rounded border font-medium ${COLORS[zone] ?? 'bg-slate-500/15 text-slate-400 border-slate-500/30'}`}>
      {zone}
    </span>
  )
}

// ── PU form modal ────────────────────────────────────────────────────────────

function PUFormModal({ mode, initial, existingZones, onSave, onClose, isDark }) {
  const isEdit = mode === 'edit'
  const empty = { pu_id: '', pu_name: '', clearing_zone: '', ngch_participant_code: '', max_agent_swarm_size: 200 }
  const [form, setForm] = useState(isEdit ? { ...initial } : empty)
  const [error, setError] = useState('')

  const th = {
    overlay:  'fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm',
    modal:    isDark ? 'bg-navy-900 border border-white/10 text-white' : 'bg-white border border-slate-200 text-slate-900',
    label:    isDark ? 'text-slate-400 text-xs mb-1' : 'text-slate-500 text-xs mb-1',
    input:    isDark
      ? 'w-full bg-white/5 border border-white/10 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500/60'
      : 'w-full bg-white border border-slate-200 text-slate-900 text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-blue-400',
    select:   isDark
      ? 'w-full bg-white/5 border border-white/10 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500/60'
      : 'w-full bg-white border border-slate-200 text-slate-900 text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-blue-400',
    hint:     isDark ? 'text-slate-600 text-[10px] mt-0.5' : 'text-slate-400 text-[10px] mt-0.5',
  }

  const availableZones = isEdit
    ? VALID_ZONES
    : VALID_ZONES.filter(z => !existingZones.includes(z) || z === form.clearing_zone)

  function set(k, v) { setForm(f => ({ ...f, [k]: v })) }

  function handleSubmit(e) {
    e.preventDefault()
    setError('')
    if (!form.pu_name.trim()) return setError('PU Name is required.')
    if (!isEdit) {
      if (!form.pu_id.trim()) return setError('PU ID is required.')
      if (!form.clearing_zone) return setError('Clearing Zone is required.')
      if (!form.ngch_participant_code.trim()) return setError('NGCH Participant Code is required.')
    }
    if (form.max_agent_swarm_size < 1) return setError('Max swarm size must be ≥ 1.')
    onSave(form)
  }

  return (
    <div className={th.overlay} onClick={onClose}>
      <div
        className={`w-full max-w-md rounded-2xl shadow-2xl p-6 ${th.modal}`}
        onClick={e => e.stopPropagation()}
      >
        <h3 className="text-sm font-semibold mb-5">{isEdit ? 'Edit Processing Unit' : 'Add Processing Unit'}</h3>

        <form onSubmit={handleSubmit} className="space-y-4">
          {!isEdit && (
            <div>
              <div className={th.label}>PU ID *</div>
              <input
                className={th.input}
                placeholder="MUMBAI-PU-01"
                value={form.pu_id}
                onChange={e => set('pu_id', e.target.value.toUpperCase())}
                required
              />
              <div className={th.hint}>Immutable after creation. E.g. MUMBAI-PU-01</div>
            </div>
          )}

          <div>
            <div className={th.label}>PU Name *</div>
            <input
              className={th.input}
              placeholder="Mumbai Processing Unit"
              value={form.pu_name}
              onChange={e => set('pu_name', e.target.value)}
              required
            />
          </div>

          {!isEdit && (
            <>
              <div>
                <div className={th.label}>Clearing Zone *</div>
                <select
                  className={th.select}
                  value={form.clearing_zone}
                  onChange={e => set('clearing_zone', e.target.value)}
                  required
                >
                  <option value="">Select zone…</option>
                  {availableZones.map(z => (
                    <option key={z} value={z}>{z}</option>
                  ))}
                </select>
                <div className={th.hint}>One PU per zone per bank — immutable after creation.</div>
              </div>

              <div>
                <div className={th.label}>NGCH Participant Code *</div>
                <input
                  className={th.input}
                  placeholder="MUMBAI-KARB-001"
                  value={form.ngch_participant_code}
                  onChange={e => set('ngch_participant_code', e.target.value.toUpperCase())}
                  required
                />
                <div className={th.hint}>Immutable after creation. Issued by NPCI / NGCH grid.</div>
              </div>
            </>
          )}

          <div>
            <div className={th.label}>Max Agent Swarm Size</div>
            <input
              type="number"
              min={1}
              max={1000}
              className={th.input}
              value={form.max_agent_swarm_size}
              onChange={e => set('max_agent_swarm_size', parseInt(e.target.value) || 1)}
            />
            <div className={th.hint}>Max parallel agents for this PU during a clearing session (1–1000).</div>
          </div>

          {isEdit && (
            <div className="flex items-center gap-3">
              <label className={`text-xs ${isDark ? 'text-slate-300' : 'text-slate-700'}`}>Active</label>
              <button
                type="button"
                onClick={() => set('is_active', !form.is_active)}
                className={`relative w-10 h-5 rounded-full transition-colors ${form.is_active ? 'bg-emerald-500' : (isDark ? 'bg-white/10' : 'bg-slate-200')}`}
              >
                <span className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${form.is_active ? 'left-5' : 'left-0.5'}`} />
              </button>
            </div>
          )}

          {error && <p className="text-red-400 text-xs">{error}</p>}

          <div className="flex gap-2 pt-1">
            <button
              type="submit"
              className="flex-1 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded-lg py-2 transition-colors"
            >
              {isEdit ? 'Save Changes' : 'Create PU'}
            </button>
            <button
              type="button"
              onClick={onClose}
              className={`px-4 text-sm rounded-lg py-2 transition-colors border ${isDark ? 'border-white/10 text-slate-400 hover:text-white' : 'border-slate-200 text-slate-500 hover:text-slate-800'}`}
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Branches panel (shown inline, expandable per PU row) ─────────────────────

function BranchesPanel({ puId, bankId, isDark, isDemo }) {
  const { data, isLoading } = useQuery({
    queryKey: ['pu-branches', puId],
    queryFn: () => apiFetch(`/v1/processing-units/${puId}/branches?bank_id=${bankId}`),
    enabled: !isDemo,
  })

  const demoBranches = DEMO_BRANCHES_BY_PU[puId] ?? []
  const branches = isDemo ? demoBranches.slice(0, 8) : (data?.branches ?? [])
  const totalCount = isDemo ? demoBranches.length : (data?.total ?? branches.length)

  const th = {
    row:   isDark ? 'border-white/4 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
    muted: isDark ? 'text-slate-400' : 'text-slate-500',
  }

  if (isLoading) return <div className={`px-6 py-3 text-xs ${th.muted}`}>Loading branches…</div>

  if (branches.length === 0) {
    return (
      <div className={`px-6 py-3 text-xs ${th.muted}`}>
        {isDemo ? 'No branches mapped to this PU.' : 'No branches mapped to this PU yet.'}
      </div>
    )
  }

  return (
    <div className="px-6 pb-3">
      <table className="w-full text-xs">
        <thead>
          <tr>
            {['IFSC', 'Branch Name', 'City', 'Scanning', 'Status'].map(h => (
              <th key={h} className={`text-left py-1 pr-4 font-medium uppercase tracking-wide text-[10px] ${th.muted}`}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {branches.map(b => (
            <tr key={b.branch_ifsc} className={`border-t ${th.row}`}>
              <td className={`py-1.5 pr-4 font-mono ${th.muted}`}>{b.branch_ifsc}</td>
              <td className={`py-1.5 pr-4 ${isDark ? 'text-slate-300' : 'text-slate-700'}`}>{b.branch_name}</td>
              <td className={`py-1.5 pr-4 ${th.muted}`}>{b.city || '—'}</td>
              <td className={`py-1.5 pr-4 ${th.muted}`}>{b.is_scanning_enabled ? 'Yes' : 'No'}</td>
              <td className="py-1.5"><Badge active={b.is_active} isDark={isDark} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── PU table row ──────────────────────────────────────────────────────────────

function PURow({ pu, isDark, isDemo, onEdit, onDeactivate, bankId }) {
  const [expanded, setExpanded] = useState(false)

  const th = {
    row:     isDark ? 'border-white/4 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
    expRow:  isDark ? 'border-white/4 bg-white/2'       : 'border-slate-100 bg-slate-50',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    mono:    isDark ? 'text-xs font-mono text-slate-300' : 'text-xs font-mono text-slate-600',
    body:    isDark ? 'text-slate-200' : 'text-slate-700',
    btnGhost: isDark
      ? 'text-xs px-2 py-0.5 border border-white/10 rounded text-slate-400 hover:text-white hover:border-white/20 transition-colors'
      : 'text-xs px-2 py-0.5 border border-slate-200 rounded text-slate-500 hover:text-slate-800 hover:border-slate-300 transition-colors',
  }

  return (
    <>
      <tr className={`border-b transition-colors ${th.row}`}>
        <td className={`py-2.5 px-3 ${th.mono}`}>{pu.pu_id}</td>
        <td className="py-2.5 px-3"><ZonePill zone={pu.clearing_zone} /></td>
        <td className={`py-2.5 px-3 text-sm ${th.body}`}>{pu.pu_name}</td>
        <td className={`py-2.5 px-3 ${th.mono} text-[10px]`}>{pu.ngch_participant_code}</td>
        <td className={`py-2.5 px-3 tabular-nums text-sm ${th.muted}`}>{pu.max_agent_swarm_size}</td>
        <td className="py-2.5 px-3"><Badge active={pu.is_active} isDark={isDark} /></td>
        <td className="py-2.5 px-3">
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => setExpanded(v => !v)}
              className={th.btnGhost}
            >
              {expanded ? '▲ Branches' : `▼ Branches${(DEMO_BRANCHES_BY_PU[pu.pu_id]?.length ?? 0) > 0 ? ` (${DEMO_BRANCHES_BY_PU[pu.pu_id].length})` : ''}`}
            </button>
            <button onClick={() => onEdit(pu)} className={th.btnGhost}>Edit</button>
            {pu.is_active && (
              <button
                onClick={() => onDeactivate(pu.pu_id)}
                className="text-xs px-2 py-0.5 border border-red-500/30 rounded text-red-400 hover:border-red-400/60 hover:text-red-300 transition-colors"
              >
                Deactivate
              </button>
            )}
          </div>
        </td>
      </tr>
      {expanded && (
        <tr className={`border-b ${th.expRow}`}>
          <td colSpan={7}>
            <BranchesPanel puId={pu.pu_id} bankId={bankId} isDark={isDark} isDemo={isDemo} />
          </td>
        </tr>
      )}
    </>
  )
}

// ── Page component ───────────────────────────────────────────────────────────

export default function CTSProcessingUnits() {
  const { isDark } = useTheme()
  const { bankId, isDemo } = useBankContext()
  const qc = useQueryClient()

  const [showForm, setShowForm] = useState(false)
  const [editTarget, setEditTarget] = useState(null)
  const [feedback, setFeedback] = useState(null)

  const th = {
    page:    isDark ? 'bg-navy-950' : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'  : 'text-slate-900',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    thCell:  isDark
      ? 'text-slate-500 bg-navy-900/80 text-[10px] font-medium uppercase tracking-wider'
      : 'text-slate-400 bg-slate-50 text-[10px] font-medium uppercase tracking-wider',
  }

  // ── Queries ────────────────────────────────────────────────────────────────

  const { data, isLoading, isError } = useQuery({
    queryKey: ['processing-units', bankId],
    queryFn:  () => apiFetch(`/v1/processing-units?bank_id=${bankId}`),
    enabled:  !isDemo,
    retry: false,
    refetchInterval: isDemo ? false : 60_000,
  })

  const puList = isDemo ? getMockPUs() : (data?.processing_units ?? [])
  const usedZones = puList.map(p => p.clearing_zone)

  // ── Mutations ──────────────────────────────────────────────────────────────

  const createMut = useMutation({
    mutationFn: (body) => USE_MOCK
      ? Promise.resolve(createMockPU(body, bankId))
      : apiFetch('/v1/processing-units', { method: 'POST', body }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['processing-units', bankId] }); setShowForm(false); flash('PU created.', 'ok') },
    onError:   (e) => flash(e.message, 'err'),
  })

  const updateMut = useMutation({
    mutationFn: ({ puId, body }) => USE_MOCK
      ? Promise.resolve(updateMockPU(puId, body))
      : apiFetch(`/v1/processing-units/${puId}`, { method: 'PUT', body }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['processing-units', bankId] }); setEditTarget(null); flash('PU updated.', 'ok') },
    onError:   (e) => flash(e.message, 'err'),
  })

  const deactivateMut = useMutation({
    mutationFn: (puId) => USE_MOCK
      ? Promise.resolve(deactivateMockPU(puId))
      : apiFetch(`/v1/processing-units/${puId}`, { method: 'DELETE' }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['processing-units', bankId] }); flash('PU deactivated.', 'ok') },
    onError:   (e) => flash(e.message, 'err'),
  })

  function flash(msg, kind) {
    setFeedback({ msg, kind })
    setTimeout(() => setFeedback(null), 3500)
  }

  function handleSaveCreate(form) {
    createMut.mutate({
      pu_id:                form.pu_id,
      pu_name:              form.pu_name,
      clearing_zone:        form.clearing_zone,
      ngch_participant_code: form.ngch_participant_code,
      max_agent_swarm_size: form.max_agent_swarm_size,
    })
  }

  function handleSaveEdit(form) {
    updateMut.mutate({
      puId: editTarget.pu_id,
      body: {
        pu_name:              form.pu_name,
        max_agent_swarm_size: form.max_agent_swarm_size,
        is_active:            form.is_active,
      },
    })
  }

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>Processing Unit Master</h1>
            <p className={`text-xs mt-0.5 ${th.muted}`}>
              One PU per clearing zone per bank · each PU has its own Temporal queue and Kafka inward topic
            </p>
          </div>
          <button
            onClick={() => setShowForm(true)}
            className="bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium px-4 py-1.5 rounded-lg transition-colors"
          >
            + Add PU
          </button>
        </div>

        {/* Feedback toast */}
        {feedback && (
          <div className={`mb-4 text-xs px-4 py-2 rounded-lg border ${
            feedback.kind === 'ok'
              ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
              : 'bg-red-500/10 border-red-500/30 text-red-400'
          }`}>
            {feedback.msg}
          </div>
        )}

        {/* Info callout — used zones */}
        {puList.length > 0 && (
          <div className={`mb-4 text-xs px-4 py-2.5 rounded-lg border flex items-center gap-3 flex-wrap ${isDark ? 'bg-white/3 border-white/8 text-slate-400' : 'bg-slate-100 border-slate-200 text-slate-500'}`}>
            <span className="shrink-0 font-medium">Zones in use:</span>
            {usedZones.map(z => <ZonePill key={z} zone={z} />)}
            {VALID_ZONES.filter(z => !usedZones.includes(z)).length > 0 && (
              <span className={isDark ? 'text-slate-600' : 'text-slate-400'}>
                Available: {VALID_ZONES.filter(z => !usedZones.includes(z)).join(', ')}
              </span>
            )}
          </div>
        )}

        {/* Table */}
        <div className={`rounded-lg border overflow-hidden ${th.card}`}>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse">
              <thead>
                <tr>
                  {['PU ID', 'Zone', 'Name', 'NGCH Code', 'Max Swarm', 'Status', 'Actions'].map(h => (
                    <th key={h} className={`px-3 py-2.5 text-left border-b ${th.divider} ${th.thCell}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {isLoading && (
                  <tr>
                    <td colSpan={7} className={`px-3 py-8 text-center text-xs ${th.muted}`}>Loading…</td>
                  </tr>
                )}
                {isError && !isDemo && (
                  <tr>
                    <td colSpan={7} className="px-3 py-8 text-center text-xs text-red-400">
                      Failed to load. No backend running in POC mode.
                    </td>
                  </tr>
                )}
                {!isLoading && puList.length === 0 && (
                  <tr>
                    <td colSpan={7} className={`px-3 py-10 text-center text-xs ${th.muted}`}>
                      No Processing Units configured yet. Click <strong>+ Add PU</strong> to create the first one.
                    </td>
                  </tr>
                )}
                {puList.map(pu => (
                  <PURow
                    key={pu.pu_id}
                    pu={pu}
                    isDark={isDark}
                    isDemo={isDemo}
                    bankId={bankId}
                    onEdit={setEditTarget}
                    onDeactivate={(puId) => deactivateMut.mutate(puId)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Tech detail card */}
        {puList.length > 0 && (
          <div className={`mt-4 rounded-lg border p-4 ${th.card}`}>
            <p className={`text-[10px] font-medium uppercase tracking-wider mb-3 ${th.muted}`}>Computed Infrastructure Keys (read-only)</p>
            <div className="space-y-2">
              {puList.filter(p => p.is_active).map(pu => (
                <div key={pu.pu_id} className="flex flex-wrap gap-x-6 gap-y-1 text-[10px]">
                  <span className={`font-medium ${isDark ? 'text-slate-300' : 'text-slate-600'}`}>{pu.pu_id}</span>
                  <span className={isDark ? 'text-slate-500' : 'text-slate-400'}>
                    Queue: <code className={isDark ? 'text-slate-300' : 'text-slate-600'}>{pu.temporal_task_queue}</code>
                  </span>
                  <span className={isDark ? 'text-slate-500' : 'text-slate-400'}>
                    Topic: <code className={isDark ? 'text-slate-300' : 'text-slate-600'}>{pu.kafka_inward_topic}</code>
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Create modal */}
      {showForm && (
        <PUFormModal
          mode="create"
          existingZones={usedZones}
          onSave={handleSaveCreate}
          onClose={() => setShowForm(false)}
          isDark={isDark}
        />
      )}

      {/* Edit modal */}
      {editTarget && (
        <PUFormModal
          mode="edit"
          initial={editTarget}
          existingZones={usedZones}
          onSave={handleSaveEdit}
          onClose={() => setEditTarget(null)}
          isDark={isDark}
        />
      )}
    </AppShell>
  )
}

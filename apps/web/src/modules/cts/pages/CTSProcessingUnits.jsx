/**
 * Processing Unit Master — CRUD
 *
 * A Processing Unit (PU) is a group of branches handled together: it runs its own Temporal task queue and has its
 * own Kafka inward topic. A bank has one or more PUs and every branch belongs to one of them. There are no zones.
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
import { msg as uiMsg } from '../../../shared/messages'

const API = import.meta.env.VITE_API_BASE || ''
// DEMO mode: use client-side mock. POC/PROD: Vite proxy forwards /v1/* to backend.
const USE_MOCK = BANK_CONFIG.deployment_mode === 'DEMO' && import.meta.env.VITE_BRANCH_MASTER_LIVE !== 'true'


// ── Mock data ────────────────────────────────────────────────────────────────

const MOCK_PU_DB = {
  'karnataka-bank': [
    { pu_id: 'MUMBAI-PU-01',    bank_id: 'karnataka-bank', pu_name: 'Mumbai Processing Unit',    ngch_participant_code: 'MUMBAI-KARB-001',    temporal_task_queue: 'cts-processing-karnataka-bank-MUMBAI-PU-01',    kafka_inward_topic: 'cts.inward.karnataka-bank.MUMBAI-PU-01',    max_agent_swarm_size: 200, is_active: true,  created_at: '2026-07-01T09:00:00Z', created_by: 'admin' },
    { pu_id: 'CHENNAI-PU-01',   bank_id: 'karnataka-bank', pu_name: 'Chennai Processing Unit',   ngch_participant_code: 'CHENNAI-KARB-001',   temporal_task_queue: 'cts-processing-karnataka-bank-CHENNAI-PU-01',   kafka_inward_topic: 'cts.inward.karnataka-bank.CHENNAI-PU-01',   max_agent_swarm_size: 150, is_active: true,  created_at: '2026-07-01T09:05:00Z', created_by: 'admin' },
    { pu_id: 'DELHI-PU-01',     bank_id: 'karnataka-bank', pu_name: 'Delhi Processing Unit',     ngch_participant_code: 'DELHI-KARB-001',     temporal_task_queue: 'cts-processing-karnataka-bank-DELHI-PU-01',     kafka_inward_topic: 'cts.inward.karnataka-bank.DELHI-PU-01',     max_agent_swarm_size: 100, is_active: true,  created_at: '2026-07-01T09:10:00Z', created_by: 'admin' },
    { pu_id: 'HYDERABAD-PU-01', bank_id: 'karnataka-bank', pu_name: 'Hyderabad Processing Unit', ngch_participant_code: 'HYDERABAD-KARB-001', temporal_task_queue: 'cts-processing-karnataka-bank-HYDERABAD-PU-01', kafka_inward_topic: 'cts.inward.karnataka-bank.HYDERABAD-PU-01', max_agent_swarm_size: 100, is_active: false, created_at: '2026-07-01T09:15:00Z', created_by: 'admin' },
  ],
  'saraswat-coop': [
    { pu_id: 'MUMBAI-PU-01',  bank_id: 'saraswat-coop', pu_name: 'Mumbai PU', ngch_participant_code: 'MUMBAI-SRCB-001',  temporal_task_queue: 'cts-processing-saraswat-coop-MUMBAI-PU-01',  kafka_inward_topic: 'cts.inward.saraswat-coop.MUMBAI-PU-01',  max_agent_swarm_size: 500, is_active: true, created_at: '2026-07-01T09:00:00Z', created_by: 'admin' },
    { pu_id: 'PUNE-PU-01',   bank_id: 'saraswat-coop', pu_name: 'Pune PU', ngch_participant_code: 'MUMBAI-SRCB-002',  temporal_task_queue: 'cts-processing-saraswat-coop-PUNE-PU-01',   kafka_inward_topic: 'cts.inward.saraswat-coop.PUNE-PU-01',   max_agent_swarm_size: 200, is_active: true, created_at: '2026-07-01T09:05:00Z', created_by: 'admin' },
  ],
  'federal-bank': [
    { pu_id: 'SOUTH-MAIN', bank_id: 'federal-bank', pu_name: 'South PU', ngch_participant_code: 'SOUTH-FDRL-001', temporal_task_queue: 'cts-processing-federal-bank-SOUTH-MAIN', kafka_inward_topic: 'cts.inward.federal-bank.SOUTH-MAIN', max_agent_swarm_size: 500, is_active: true,  created_at: '2026-08-01T06:00:00Z', created_by: 'admin' },
    { pu_id: 'WEST-MAIN',  bank_id: 'federal-bank', pu_name: 'West PU',  ngch_participant_code: 'WEST-FDRL-001',  temporal_task_queue: 'cts-processing-federal-bank-WEST-MAIN',  kafka_inward_topic: 'cts.inward.federal-bank.WEST-MAIN',  max_agent_swarm_size: 300, is_active: true,  created_at: '2026-08-01T06:00:00Z', created_by: 'admin' },
    { pu_id: 'NORTH-MAIN', bank_id: 'federal-bank', pu_name: 'North PU', ngch_participant_code: 'NORTH-FDRL-001', temporal_task_queue: 'cts-processing-federal-bank-NORTH-MAIN', kafka_inward_topic: 'cts.inward.federal-bank.NORTH-MAIN', max_agent_swarm_size: 200, is_active: true,  created_at: '2026-08-01T06:00:00Z', created_by: 'admin' },
    { pu_id: 'EAST-MAIN',  bank_id: 'federal-bank', pu_name: 'East PU',  ngch_participant_code: 'EAST-FDRL-001',  temporal_task_queue: 'cts-processing-federal-bank-EAST-MAIN',  kafka_inward_topic: 'cts.inward.federal-bank.EAST-MAIN',  max_agent_swarm_size: 100, is_active: true,  created_at: '2026-08-01T06:00:00Z', created_by: 'admin' },
  ],
  'union-bank': [
    { pu_id: 'UBIN-PU-WEST',  bank_id: 'union-bank', pu_name: 'Union Bank Western PU',  ngch_participant_code: 'WEST-UBIN-001',  temporal_task_queue: 'cts-processing-union-bank-west',  kafka_inward_topic: 'cts.inward.union-bank.west',  max_agent_swarm_size: 300, is_active: true, created_at: '2026-08-01T06:00:00Z', created_by: 'admin' },
    { pu_id: 'UBIN-PU-SOUTH', bank_id: 'union-bank', pu_name: 'Union Bank Southern PU', ngch_participant_code: 'SOUTH-UBIN-001', temporal_task_queue: 'cts-processing-union-bank-south', kafka_inward_topic: 'cts.inward.union-bank.south', max_agent_swarm_size: 300, is_active: true, created_at: '2026-08-01T06:00:00Z', created_by: 'admin' },
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
  if (_mockStore.find(p => p.pu_id === data.pu_id)) {
    throw new Error(uiMsg('UI_PROCESSINGUNITS_PROCESSING_UNIT_ALREADY_EXISTS', { pu_id: data.pu_id }))
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
  if (idx === -1) throw new Error(uiMsg('UI_PROCESSINGUNITS_PU_NOT_FOUND', { puId }))
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
    ? <span className="inline-flex items-center text-[10px] px-1.5 py-0.5 rounded border bg-emerald-500/15 text-emerald-400 border-emerald-500/30">{uiMsg('UI_COMMON_ACTIVE')}</span>
    : <span className={`inline-flex items-center text-[10px] px-1.5 py-0.5 rounded border ${isDark ? 'bg-white/5 text-slate-500 border-white/10' : 'bg-slate-100 text-slate-400 border-slate-200'}`}>{uiMsg('UI_PROCESSINGUNITS_INACTIVE')}</span>
}

// ── PU form modal ────────────────────────────────────────────────────────────

function PUFormModal({ mode, initial, onSave, onClose, isDark }) {
  const isEdit = mode === 'edit'
  const empty = { pu_id: '', pu_name: '', ngch_participant_code: '', max_agent_swarm_size: 200 }
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

  function set(k, v) { setForm(f => ({ ...f, [k]: v })) }

  function handleSubmit(e) {
    e.preventDefault()
    setError('')
    if (!form.pu_name.trim()) return setError(uiMsg('UI_PROCESSINGUNITS_PU_NAME_IS_REQUIRED'))
    if (!isEdit) {
      if (!form.pu_id.trim()) return setError(uiMsg('UI_PROCESSINGUNITS_PU_ID_IS_REQUIRED'))
    }
    if (form.max_agent_swarm_size < 1) return setError(uiMsg('UI_PROCESSINGUNITS_MAX_SWARM_SIZE_MUST_BE'))
    onSave(form)
  }

  return (
    <div className={th.overlay} onClick={onClose}>
      <div
        className={`w-full max-w-md rounded-2xl shadow-2xl p-6 ${th.modal}`}
        onClick={e => e.stopPropagation()}
      >
        <h3 className="text-sm font-semibold mb-5">{isEdit ? uiMsg('UI_PROCESSINGUNITS_EDIT_PROCESSING_UNIT') : uiMsg('UI_PROCESSINGUNITS_ADD_PROCESSING_UNIT')}</h3>

        <form onSubmit={handleSubmit} className="space-y-4">
          {!isEdit && (
            <div>
              <div className={th.label}>{uiMsg('UI_PROCESSINGUNITS_PU_ID')}</div>
              <input
                className={th.input}
                placeholder={uiMsg('UI_PROCESSINGUNITS_MUMBAI_PU_01')}
                value={form.pu_id}
                onChange={e => set('pu_id', e.target.value.toUpperCase())}
                required
              />
              <div className={th.hint}>{uiMsg('UI_PROCESSINGUNITS_IMMUTABLE_AFTER_CREATION_E_G')}</div>
            </div>
          )}

          <div>
            <div className={th.label}>{uiMsg('UI_PROCESSINGUNITS_PU_NAME')}</div>
            <input
              className={th.input}
              placeholder={uiMsg('UI_BRANCHMASTER_MUMBAI_PROCESSING_UNIT')}
              value={form.pu_name}
              onChange={e => set('pu_name', e.target.value)}
              required
            />
          </div>

          {!isEdit && (
            <>
              <div>
                <div className={th.label}>{uiMsg('UI_PROCESSINGUNITS_NGCH_PARTICIPANT_CODE_OPTIONAL')}</div>
                <input
                  className={th.input}
                  placeholder={uiMsg('UI_PROCESSINGUNITS_ONLY_IF_THIS_PU_FILES')}
                  value={form.ngch_participant_code}
                  onChange={e => set('ngch_participant_code', e.target.value.toUpperCase())}
                />
                <div className={th.hint}>{uiMsg('UI_PROCESSINGUNITS_IMMUTABLE_AFTER_CREATION_LEAVE_EMPTY')}</div>
              </div>
            </>
          )}

          <div>
            <div className={th.label}>{uiMsg('UI_PROCESSINGUNITS_MAX_AGENT_SWARM_SIZE')}</div>
            <input
              type="number"
              min={1}
              max={1000}
              className={th.input}
              value={form.max_agent_swarm_size}
              onChange={e => set('max_agent_swarm_size', parseInt(e.target.value) || 1)}
            />
            <div className={th.hint}>{uiMsg('UI_PROCESSINGUNITS_MAX_PARALLEL_AGENTS_FOR_THIS')}</div>
          </div>

          {isEdit && (
            <div className="flex items-center gap-3">
              <label className={`text-xs ${isDark ? 'text-slate-300' : 'text-slate-700'}`}>{uiMsg('UI_COMMON_ACTIVE')}</label>
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
              {isEdit ? uiMsg('UI_COMMON_SAVE_CHANGES') : uiMsg('UI_PROCESSINGUNITS_CREATE_PU')}
            </button>
            <button
              type="button"
              onClick={onClose}
              className={`px-4 text-sm rounded-lg py-2 transition-colors border ${isDark ? 'border-white/10 text-slate-400 hover:text-white' : 'border-slate-200 text-slate-500 hover:text-slate-800'}`}
            >
             {uiMsg('UI_COMMON_CANCEL')}
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

  if (isLoading) return <div className={`px-6 py-3 text-xs ${th.muted}`}>{uiMsg('UI_PROCESSINGUNITS_LOADING_BRANCHES')}</div>

  if (branches.length === 0) {
    return (
      <div className={`px-6 py-3 text-xs ${th.muted}`}>
        {isDemo ? uiMsg('UI_PROCESSINGUNITS_NO_BRANCHES_MAPPED_TO_THIS') : uiMsg('UI_PROCESSINGUNITS_NO_BRANCHES_MAPPED_TO_THIS_2')}
      </div>
    )
  }

  return (
    <div className="px-6 pb-3">
      <table className="w-full text-xs">
        <thead>
          <tr>
            {[uiMsg('UI_COMMON_IFSC'), uiMsg('UI_BRANCHMASTER_BRANCH_NAME_2'), uiMsg('UI_BRANCHMASTER_CITY'), uiMsg('UI_PROCESSINGUNITS_SCANNING'), uiMsg('UI_COMMON_STATUS')].map(h => (
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
              <td className={`py-1.5 pr-4 ${th.muted}`}>{b.is_scanning_enabled ? uiMsg('UI_COMMON_YES') : uiMsg('UI_COMMON_NO')}</td>
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
        <td className={`py-2.5 px-3 text-sm ${th.body}`}>{pu.pu_name}</td>
        <td className={`py-2.5 px-3 ${th.mono} text-[10px]`}>{pu.ngch_participant_code || '—'}</td>
        <td className={`py-2.5 px-3 tabular-nums text-sm ${th.muted}`}>{pu.max_agent_swarm_size}</td>
        <td className="py-2.5 px-3"><Badge active={pu.is_active} isDark={isDark} /></td>
        <td className="py-2.5 px-3">
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => setExpanded(v => !v)}
              className={th.btnGhost}
            >
              {expanded ? uiMsg('UI_PROCESSINGUNITS_BRANCHES') : uiMsg('UI_PROCESSINGUNITS_BRANCHES_2', { value: (DEMO_BRANCHES_BY_PU[pu.pu_id]?.length ?? 0) > 0 ? ` (${DEMO_BRANCHES_BY_PU[pu.pu_id].length})` : '' })}
            </button>
            <button onClick={() => onEdit(pu)} className={th.btnGhost}>{uiMsg('UI_COMMON_EDIT')}</button>
            {pu.is_active && (
              <button
                onClick={() => onDeactivate(pu.pu_id)}
                className="text-xs px-2 py-0.5 border border-red-500/30 rounded text-red-400 hover:border-red-400/60 hover:text-red-300 transition-colors"
              >
               {uiMsg('UI_COMMON_DEACTIVATE')}
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
  const { bankId, isDemo: isDemoBuild } = useBankContext()
  // VITE_BRANCH_MASTER_LIVE=true: show and edit the real processing-unit table even in a DEMO build (same switch as Branch Master).
  const isDemo = isDemoBuild && import.meta.env.VITE_BRANCH_MASTER_LIVE !== 'true'
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

  // ── Mutations ──────────────────────────────────────────────────────────────

  const createMut = useMutation({
    mutationFn: (body) => USE_MOCK
      ? Promise.resolve(createMockPU(body, bankId))
      : apiFetch('/v1/processing-units', { method: 'POST', body }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['processing-units', bankId] }); setShowForm(false); flash(uiMsg('UI_PROCESSINGUNITS_PU_CREATED'), 'ok') },
    onError:   (e) => flash(e.message, 'err'),
  })

  const updateMut = useMutation({
    mutationFn: ({ puId, body }) => USE_MOCK
      ? Promise.resolve(updateMockPU(puId, body))
      : apiFetch(`/v1/processing-units/${puId}`, { method: 'PUT', body }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['processing-units', bankId] }); setEditTarget(null); flash(uiMsg('UI_PROCESSINGUNITS_PU_UPDATED'), 'ok') },
    onError:   (e) => flash(e.message, 'err'),
  })

  const deactivateMut = useMutation({
    mutationFn: (puId) => USE_MOCK
      ? Promise.resolve(deactivateMockPU(puId))
      : apiFetch(`/v1/processing-units/${puId}`, { method: 'DELETE' }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['processing-units', bankId] }); flash(uiMsg('UI_PROCESSINGUNITS_PU_DEACTIVATED'), 'ok') },
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
            <h1 className={`text-lg font-semibold ${th.heading}`}>{uiMsg('UI_PROCESSINGUNITS_PROCESSING_UNIT_MASTER')}</h1>
            <p className={`text-xs mt-0.5 ${th.muted}`}>
             {uiMsg('UI_PROCESSINGUNITS_A_GROUP_OF_BRANCHES_HANDLED')}
            </p>
          </div>
          <button
            onClick={() => setShowForm(true)}
            className="bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium px-4 py-1.5 rounded-lg transition-colors"
          >
           {uiMsg('UI_PROCESSINGUNITS_ADD_PU')}
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

        {/* Table */}
        <div className={`rounded-lg border overflow-hidden ${th.card}`}>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse">
              <thead>
                <tr>
                  {[uiMsg('UI_PROCESSINGUNITS_PU_ID_2'), uiMsg('UI_CHEQUEIMAGEVIEWER_NAME'), uiMsg('UI_PROCESSINGUNITS_NGCH_CODE'), uiMsg('UI_PROCESSINGUNITS_MAX_SWARM'), uiMsg('UI_COMMON_STATUS'), uiMsg('UI_COMMON_ACTIONS')].map(h => (
                    <th key={h} className={`px-3 py-2.5 text-left border-b ${th.divider} ${th.thCell}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {isLoading && (
                  <tr>
                    <td colSpan={7} className={`px-3 py-8 text-center text-xs ${th.muted}`}>{uiMsg('CTS_WF_BUCKETCFG_LOADING')}</td>
                  </tr>
                )}
                {isError && !isDemo && (
                  <tr>
                    <td colSpan={7} className="px-3 py-8 text-center text-xs text-red-400">
                     {uiMsg('UI_PROCESSINGUNITS_FAILED_TO_LOAD_NO_BACKEND')}
                    </td>
                  </tr>
                )}
                {!isLoading && puList.length === 0 && (
                  <tr>
                    <td colSpan={7} className={`px-3 py-10 text-center text-xs ${th.muted}`}>
                     {uiMsg('UI_PROCESSINGUNITS_NO_PROCESSING_UNITS_CONFIGURED_YET')} <strong>{uiMsg('UI_PROCESSINGUNITS_ADD_PU')}</strong> {uiMsg('UI_PROCESSINGUNITS_TO_CREATE_THE_FIRST_ONE')}
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
            <p className={`text-[10px] font-medium uppercase tracking-wider mb-3 ${th.muted}`}>{uiMsg('UI_PROCESSINGUNITS_COMPUTED_INFRASTRUCTURE_KEYS_READ_ON')}</p>
            <div className="space-y-2">
              {puList.filter(p => p.is_active).map(pu => (
                <div key={pu.pu_id} className="flex flex-wrap gap-x-6 gap-y-1 text-[10px]">
                  <span className={`font-medium ${isDark ? 'text-slate-300' : 'text-slate-600'}`}>{pu.pu_id}</span>
                  <span className={isDark ? 'text-slate-500' : 'text-slate-400'}>
                   {uiMsg('UI_PROCESSINGUNITS_QUEUE')} <code className={isDark ? 'text-slate-300' : 'text-slate-600'}>{pu.temporal_task_queue}</code>
                  </span>
                  <span className={isDark ? 'text-slate-500' : 'text-slate-400'}>
                   {uiMsg('UI_PROCESSINGUNITS_TOPIC')} <code className={isDark ? 'text-slate-300' : 'text-slate-600'}>{pu.kafka_inward_topic}</code>
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
          onSave={handleSaveEdit}
          onClose={() => setEditTarget(null)}
          isDark={isDark}
        />
      )}
    </AppShell>
  )
}

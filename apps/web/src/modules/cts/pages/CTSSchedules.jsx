import { useState } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'

// ── Mock schedule data ──────────────────────────────────────────────────────
// In production these come from GET /v1/cts/schedules

// CTS-only schedules — EJ schedules are managed separately in the EJ module
const MOCK_SCHEDULES = [
  {
    schedule_id: 'cts-vaultsync-schedule-bank001',
    label: 'PPS & Stop Cheque Vault Sync',
    description: 'Pulls Positive Pay and Stop Cheque records from CBS into the CTS Redis vaults.',
    workflow: 'VaultSyncWorkflow',
    module: 'CTS',
    cron: '0 7 * * *',
    cron_human: 'Daily at 07:00 AM',
    task_queue: 'cts-processing-bank001',
    status: 'RUNNING',         // RUNNING | PAUSED
    last_run_at: '2026-06-25T07:00:14Z',
    last_run_status: 'SUCCESS',
    last_run_duration_s: 43,
    next_run_at: '2026-06-26T07:00:00Z',
    created_at: '2026-06-01T00:00:00Z',
    triggered_by_default: 'SCHEDULED',
    editable_fields: ['cron'],
  },
]

// ── Common cron presets ─────────────────────────────────────────────────────

const CRON_PRESETS = [
  { label: 'Every 15 minutes',  value: '*/15 * * * *' },
  { label: 'Every 30 minutes',  value: '*/30 * * * *' },
  { label: 'Every hour',        value: '0 * * * *'    },
  { label: 'Every 2 hours',     value: '0 */2 * * *'  },
  { label: 'Every 6 hours',     value: '0 */6 * * *'  },
  { label: 'Daily at 04:00 AM', value: '0 4 * * *'    },
  { label: 'Daily at 06:00 AM', value: '0 6 * * *'    },
  { label: 'Daily at 07:00 AM', value: '0 7 * * *'    },
  { label: 'Daily at 08:00 AM', value: '0 8 * * *'    },
  { label: 'Daily at midnight', value: '0 0 * * *'    },
  { label: 'Custom…',           value: '__custom__'   },
]

// ── Helpers ─────────────────────────────────────────────────────────────────

function fmtDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })
}

function StatusDot({ status }) {
  if (status === 'RUNNING') return <span className="inline-block w-2 h-2 rounded-full bg-emerald-400 animate-pulse mr-1.5" />
  if (status === 'PAUSED')  return <span className="inline-block w-2 h-2 rounded-full bg-amber-400 mr-1.5" />
  return <span className="inline-block w-2 h-2 rounded-full bg-slate-500 mr-1.5" />
}

function RunStatusPill({ s, isDark }) {
  const MAP_D = { SUCCESS: 'bg-emerald-900/40 text-emerald-300', FAILED: 'bg-red-900/40 text-red-300', PARTIAL: 'bg-amber-900/40 text-amber-300' }
  const MAP_L = { SUCCESS: 'bg-emerald-50 text-emerald-700', FAILED: 'bg-red-50 text-red-700', PARTIAL: 'bg-amber-50 text-amber-700' }
  const cls = (isDark ? MAP_D : MAP_L)[s] ?? (isDark ? 'bg-slate-800 text-slate-400' : 'bg-slate-100 text-slate-500')
  return <span className={`inline-flex px-2 py-0.5 rounded-full text-[10px] font-semibold ${cls}`}>{s}</span>
}

function ModuleBadge({ module, isDark }) {
  const CTS_D = 'bg-violet-900/40 text-violet-300'
  const CTS_L = 'bg-violet-50 text-violet-700'
  const EJ_D  = 'bg-blue-900/40 text-blue-300'
  const EJ_L  = 'bg-blue-50 text-blue-700'
  const cls = module === 'CTS' ? (isDark ? CTS_D : CTS_L) : (isDark ? EJ_D : EJ_L)
  return <span className={`inline-flex px-1.5 py-0.5 rounded text-[10px] font-bold tracking-wide ${cls}`}>{module}</span>
}

// ── Edit Schedule Modal ──────────────────────────────────────────────────────

function EditScheduleModal({ schedule, isDark, onClose, onSave }) {
  const [cron, setCron] = useState(schedule.cron)
  const [preset, setPreset] = useState(
    CRON_PRESETS.find(p => p.value === schedule.cron) ? schedule.cron : '__custom__'
  )
  const [saving, setSaving] = useState(false)

  const th = {
    overlay: 'fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm',
    modal:   isDark ? 'bg-navy-900 border border-white/10 rounded-2xl shadow-2xl w-full max-w-lg mx-4' : 'bg-white border border-slate-200 rounded-2xl shadow-2xl w-full max-w-lg mx-4',
    head:    isDark ? 'border-b border-white/8' : 'border-b border-slate-100',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    label:   isDark ? 'text-slate-300 text-xs font-medium' : 'text-slate-600 text-xs font-medium',
    input:   isDark ? 'bg-white/8 border-white/10 text-white' : 'bg-white border-slate-200 text-slate-800',
    select:  isDark ? 'bg-white/8 border-white/10 text-white' : 'bg-white border-slate-200 text-slate-800',
    info:    isDark ? 'bg-white/4 border-white/8 text-slate-300' : 'bg-slate-50 border-slate-200 text-slate-600',
  }

  const handlePresetChange = (v) => {
    setPreset(v)
    if (v !== '__custom__') setCron(v)
  }

  const handleSave = async () => {
    setSaving(true)
    await new Promise(r => setTimeout(r, 800))
    onSave({ ...schedule, cron })
    setSaving(false)
    onClose()
  }

  return (
    <div className={th.overlay} onClick={onClose}>
      <div className={th.modal} onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className={`flex items-start justify-between px-6 py-4 ${th.head}`}>
          <div>
            <div className={`text-sm font-semibold ${th.heading}`}>Edit Schedule</div>
            <div className={`text-xs mt-0.5 ${th.muted}`}>{schedule.label}</div>
          </div>
          <button onClick={onClose} className={`p-1 rounded-lg ${isDark ? 'hover:bg-white/10 text-slate-400' : 'hover:bg-slate-100 text-slate-500'}`}>
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" className="w-4 h-4">
              <path strokeLinecap="round" d="M4 4l8 8M12 4l-8 8" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5 space-y-4">
          {/* Read-only info */}
          <div className={`rounded-xl border px-4 py-3 text-xs space-y-1.5 ${th.info}`}>
            <div className="flex justify-between"><span className={th.muted}>Workflow</span><span className="font-mono">{schedule.workflow}</span></div>
            <div className="flex justify-between"><span className={th.muted}>Task Queue</span><span className="font-mono text-[11px]">{schedule.task_queue}</span></div>
            <div className="flex justify-between"><span className={th.muted}>Schedule ID</span><span className="font-mono text-[10px] truncate ml-4">{schedule.schedule_id}</span></div>
          </div>

          {/* Cron preset */}
          <div>
            <label className={`block mb-1.5 ${th.label}`}>Frequency</label>
            <select
              value={preset}
              onChange={e => handlePresetChange(e.target.value)}
              className={`w-full h-9 px-3 rounded-lg border text-xs outline-none ${th.select}`}
            >
              {CRON_PRESETS.map(p => (
                <option key={p.value} value={p.value}>{p.label}</option>
              ))}
            </select>
          </div>

          {/* Cron expression */}
          <div>
            <label className={`block mb-1.5 ${th.label}`}>Cron Expression</label>
            <input
              value={cron}
              onChange={e => { setCron(e.target.value); setPreset('__custom__') }}
              placeholder="e.g. 0 7 * * *"
              className={`w-full h-9 px-3 rounded-lg border text-xs font-mono outline-none ${th.input}`}
            />
            <p className={`text-[11px] mt-1 ${th.muted}`}>
              Standard UNIX cron — minute hour day month weekday. Changes take effect on next scheduled run.
            </p>
          </div>

          {/* Warning */}
          <div className={`rounded-xl border px-4 py-3 text-xs ${isDark ? 'bg-amber-900/20 border-amber-700/30 text-amber-300' : 'bg-amber-50 border-amber-200 text-amber-700'}`}>
            ⚠ This updates the Temporal Schedule directly. The new cron takes effect for all future runs. The current run (if any) is not affected.
          </div>
        </div>

        {/* Footer */}
        <div className={`flex items-center justify-end gap-3 px-6 py-4 border-t ${th.head}`}>
          <button onClick={onClose} className={`px-4 py-2 rounded-lg text-xs ${isDark ? 'text-slate-400 hover:text-white hover:bg-white/8' : 'text-slate-500 hover:text-slate-800 hover:bg-slate-100'}`}>
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving || !cron.trim()}
            className={`px-4 py-2 rounded-lg text-xs font-medium transition-all ${
              saving || !cron.trim()
                ? 'opacity-50 cursor-not-allowed bg-slate-700 text-slate-400'
                : (isDark ? 'bg-violet-600 hover:bg-violet-500 text-white' : 'bg-violet-600 hover:bg-violet-700 text-white')
            }`}
          >
            {saving ? 'Saving…' : 'Save Schedule'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function CTSSchedules() {
  const { bankId, bankName, bankIfsc, bankType, isSB, isSMB } = useBankContext()
  const { isDark } = useTheme()
  const [schedules, setSchedules] = useState(MOCK_SCHEDULES)
  const [editing, setEditing] = useState(null)
  const [togglingId, setTogglingId] = useState(null)

  const th = {
    page:    isDark ? '' : 'bg-slate-50',
    card:    isDark ? 'bg-white/4 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    row:     isDark ? 'border-white/5 hover:bg-white/3' : 'border-slate-100 hover:bg-slate-50',
    input:   isDark ? 'bg-white/8 border-white/10 text-white placeholder-slate-500' : 'bg-white border-slate-200 text-slate-800 placeholder-slate-400',
  }

  const handleToggle = async (s) => {
    setTogglingId(s.schedule_id)
    await new Promise(r => setTimeout(r, 600))
    setSchedules(prev => prev.map(x =>
      x.schedule_id === s.schedule_id
        ? { ...x, status: x.status === 'RUNNING' ? 'PAUSED' : 'RUNNING' }
        : x
    ))
    setTogglingId(null)
  }

  const handleSave = (updated) => {
    setSchedules(prev => prev.map(s => s.schedule_id === updated.schedule_id ? updated : s))
  }

  const displayed = schedules
  const running = schedules.filter(s => s.status === 'RUNNING').length
  const paused  = schedules.filter(s => s.status === 'PAUSED').length

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>

        {/* Header */}
        <div className="flex items-start justify-between mb-5">
          <div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>Temporal Schedules</h1>
            <p className={`text-xs mt-0.5 ${th.muted}`}>
              Automated workflow schedules — view, pause, and edit cron expressions
            </p>
          </div>
          <div className="flex items-center gap-2">
            <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs ${th.card}`}>
              <StatusDot status="RUNNING" />
              <span className={th.body}>{running} running</span>
            </div>
            {paused > 0 && (
              <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs ${th.card}`}>
                <StatusDot status="PAUSED" />
                <span className={th.body}>{paused} paused</span>
              </div>
            )}
          </div>
        </div>

        {/* Schedule cards */}
        <div className="space-y-3">
          {displayed.map(s => (
            <div key={s.schedule_id} className={`rounded-xl border ${th.card}`}>
              {/* Card header */}
              <div className={`flex items-start justify-between px-5 py-4 border-b ${th.divider}`}>
                <div className="flex items-start gap-3 min-w-0">
                  <div className="mt-0.5">
                    <StatusDot status={s.status} />
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={`text-sm font-semibold ${th.heading}`}>{s.label}</span>
                      <ModuleBadge module={s.module} isDark={isDark} />
                    </div>
                    <p className={`text-[11px] mt-0.5 ${th.muted}`}>{s.description}</p>
                  </div>
                </div>
                <div className="flex items-center gap-2 ml-4 shrink-0">
                  {/* Pause / Resume */}
                  <button
                    onClick={() => handleToggle(s)}
                    disabled={togglingId === s.schedule_id}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all border ${
                      togglingId === s.schedule_id
                        ? 'opacity-50 cursor-not-allowed ' + (isDark ? 'border-white/10 text-slate-500' : 'border-slate-200 text-slate-400')
                        : s.status === 'RUNNING'
                          ? (isDark ? 'border-amber-700/40 text-amber-300 hover:bg-amber-900/20' : 'border-amber-200 text-amber-700 hover:bg-amber-50')
                          : (isDark ? 'border-emerald-700/40 text-emerald-300 hover:bg-emerald-900/20' : 'border-emerald-200 text-emerald-700 hover:bg-emerald-50')
                    }`}
                  >
                    {togglingId === s.schedule_id ? '…' : s.status === 'RUNNING' ? 'Pause' : 'Resume'}
                  </button>
                  {/* Edit */}
                  <button
                    onClick={() => setEditing(s)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all border ${
                      isDark
                        ? 'border-white/10 text-slate-300 hover:bg-white/8 hover:text-white'
                        : 'border-slate-200 text-slate-600 hover:bg-slate-100 hover:text-slate-800'
                    }`}
                  >
                    Edit
                  </button>
                </div>
              </div>

              {/* Card body */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-0 divide-x divide-y md:divide-y-0" style={{ borderColor: isDark ? 'rgba(255,255,255,0.06)' : '#e2e8f0' }}>
                {[
                  { label: 'Cron', value: s.cron, sub: s.cron_human, mono: true },
                  { label: 'Last Run', value: fmtDate(s.last_run_at), sub: <RunStatusPill s={s.last_run_status} isDark={isDark} /> },
                  { label: 'Next Run', value: fmtDate(s.next_run_at), sub: s.status === 'PAUSED' ? 'Paused — will not run' : null },
                  { label: 'Workflow', value: s.workflow, sub: <span className="font-mono text-[10px]">{s.task_queue.replace('bank001', '{bank_id}')}</span>, mono: true },
                ].map(({ label, value, sub, mono }) => (
                  <div key={label} className="px-5 py-3">
                    <div className={`text-[10px] uppercase tracking-widest font-semibold mb-1 ${th.muted}`}>{label}</div>
                    <div className={`text-[12px] font-medium ${th.heading} ${mono ? 'font-mono' : ''}`}>{value}</div>
                    {sub && <div className={`text-[11px] mt-0.5 ${th.muted}`}>{sub}</div>}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* How it works callout */}
        <div className={`mt-6 rounded-xl border px-5 py-4 ${isDark ? 'bg-white/2 border-white/6' : 'bg-slate-50 border-slate-200'}`}>
          <div className={`text-xs font-semibold mb-2 ${th.heading}`}>How Temporal Schedules work in ASTRA</div>
          <div className={`text-[11px] space-y-1 ${th.muted}`}>
            <p>• Each schedule is a <strong className={th.body}>Temporal Schedule</strong> (not a cron job) — durable, audited, and exactly-once. If the worker is down when the cron fires, Temporal catches up automatically on restart.</p>
            <p>• Editing a cron here calls <strong className={th.body}>PATCH /v1/cts/schedules/{'{id}'}</strong> which calls <code className="font-mono">temporal_client.get_schedule_handle(id).update(new_spec)</code> — the existing schedule is updated in-place, never deleted and recreated.</p>
            <p>• Pausing stops future runs without deleting the schedule. Any currently running workflow is not affected.</p>
            <p>• Each workflow run logs a <strong className={th.body}>triggered_by: SCHEDULED</strong> audit event to Immudb — visible in the Decisions Log and the Sync History tab on the PPS & Stop Cheque page.</p>
          </div>
        </div>

      </div>

      {/* Edit modal */}
      {editing && (
        <EditScheduleModal
          schedule={editing}
          isDark={isDark}
          onClose={() => setEditing(null)}
          onSave={handleSave}
        />
      )}
    </AppShell>
  )
}

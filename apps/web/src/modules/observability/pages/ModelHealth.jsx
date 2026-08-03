/**
 * ASTRA Model Health — AI model drift indicators for ops_manager + ml_engineer.
 *
 * Shows 7-day rolling drift for each deployed model:
 *   got-ocr2  → OCR confidence mean
 *   qwen2-vl  → Fraud score mean
 *
 * Alert statuses: SAFE (< 2% drift), WARN (2–5%), CRITICAL (> 5%), UNKNOWN (no baseline).
 */
import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'
import AppShell from '../../../shared/layout/AppShell'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

function useModelHealth(bankId) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/v1/ops/model-health`, { credentials: 'include' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setData(await res.json())
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [bankId])

  useEffect(() => { load() }, [load])

  return { data, loading, error, reload: load }
}

const STATUS_D = {
  SAFE:     'bg-emerald-900/20 text-emerald-300 border-emerald-700/30',
  WARN:     'bg-amber-900/20  text-amber-300  border-amber-700/30',
  CRITICAL: 'bg-red-900/20   text-red-300    border-red-700/30',
  UNKNOWN:  'bg-slate-800     text-slate-400  border-white/8',
}
const STATUS_L = {
  SAFE:     'bg-emerald-50 text-emerald-700 border-emerald-200',
  WARN:     'bg-amber-50   text-amber-700   border-amber-200',
  CRITICAL: 'bg-red-50     text-red-700     border-red-200',
  UNKNOWN:  'bg-slate-50   text-slate-500   border-slate-200',
}

function StatusBadge({ status, isDark }) {
  const cls = (isDark ? STATUS_D : STATUS_L)[status] ?? STATUS_D.UNKNOWN
  return (
    <span className={`text-[11px] font-semibold px-2.5 py-0.5 rounded-full border ${cls}`}>
      {status}
    </span>
  )
}

function DriftBar({ drift, isDark }) {
  const abs = Math.abs(drift)
  const capped = Math.min(abs, 10)
  const pct = capped / 10 * 100
  const color = abs >= 5 ? 'bg-red-400' : abs >= 2 ? 'bg-amber-400' : 'bg-emerald-400'
  const bg = isDark ? 'bg-white/8' : 'bg-slate-100'
  return (
    <div className={`h-1.5 rounded-full overflow-hidden w-full ${bg}`}>
      <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
    </div>
  )
}

export default function ModelHealth() {
  const { isDark } = useTheme()
  const { bankId } = useBankContext()
  const { data, loading, error, reload } = useModelHealth(bankId)

  const th = {
    page:    isDark ? 'bg-navy-950'                 : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8'  : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'                  : 'text-slate-900',
    body:    isDark ? 'text-slate-300'              : 'text-slate-700',
    muted:   isDark ? 'text-slate-400'              : 'text-slate-500',
    row:     isDark ? 'border-white/5 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
    col:     isDark ? 'text-slate-300'              : 'text-slate-700',
  }

  const models = data?.models ?? []
  const degraded = data?.degraded ?? true

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div>
            <div className="flex items-center gap-2 mb-0.5">
              <Link to="/ops/dashboard" className={`text-xs ${th.muted} hover:underline`}>
                Ops Dashboard
              </Link>
              <span className={`text-xs ${th.muted}`}>/</span>
              <span className={`text-xs ${th.muted}`}>Model Health</span>
            </div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>AI Model Health</h1>
            <p className={`text-xs mt-0.5 ${th.muted}`}>7-day rolling drift — WARN at 2%, CRITICAL at 5%</p>
          </div>
          <button
            onClick={reload}
            disabled={loading}
            className={`text-xs px-3 py-1.5 rounded-lg border font-medium transition-opacity disabled:opacity-50
              ${isDark ? 'border-white/12 text-slate-300 hover:bg-white/5' : 'border-slate-200 text-slate-700 hover:bg-slate-50'}`}
          >
            {loading ? 'Loading…' : 'Refresh'}
          </button>
        </div>

        {error && (
          <div className={`text-sm px-4 py-3 rounded-xl mb-4 border
            ${isDark ? 'bg-red-900/10 border-red-700/30 text-red-400' : 'bg-red-50 border-red-200 text-red-700'}`}>
            {error}
          </div>
        )}

        {degraded && (
          <div className={`text-sm px-4 py-3 rounded-xl mb-4 border
            ${isDark ? 'bg-amber-900/10 border-amber-700/30 text-amber-400' : 'bg-amber-50 border-amber-200 text-amber-700'}`}>
            Inference log DB unavailable — model metrics not computable.
          </div>
        )}

        <div className={`rounded-xl border overflow-hidden ${th.card}`}>
          {/* Table header */}
          <div className={`grid grid-cols-5 gap-4 px-5 py-3 border-b ${th.muted} text-[11px] uppercase tracking-widest font-semibold ${isDark ? 'border-white/8' : 'border-slate-100'}`}>
            <span className="col-span-1">Model</span>
            <span className="col-span-1">Metric</span>
            <span className="text-right">Current (1d)</span>
            <span className="text-right">Baseline (7d)</span>
            <span className="text-right">Status</span>
          </div>

          {models.length === 0 && !loading && (
            <div className={`px-5 py-8 text-center text-sm ${th.muted}`}>
              No model data available.
            </div>
          )}

          {models.map((m, i) => (
            <div
              key={m.model_name}
              className={`grid grid-cols-5 gap-4 px-5 py-4 border-b last:border-0 ${th.row} ${isDark ? 'border-white/5' : 'border-slate-50'}`}
            >
              <div className="col-span-1">
                <p className={`text-sm font-mono font-medium ${th.heading}`}>{m.model_name}</p>
              </div>
              <div className="col-span-1">
                <p className={`text-xs ${th.muted}`}>{m.metric}</p>
              </div>
              <div className="text-right">
                <p className={`text-sm font-semibold tabular-nums ${th.col}`}>
                  {m.degraded ? '—' : m.current_value.toFixed(4)}
                </p>
              </div>
              <div className="text-right">
                <p className={`text-sm tabular-nums ${th.muted}`}>
                  {m.degraded ? '—' : m.baseline_7d.toFixed(4)}
                </p>
                {!m.degraded && (
                  <div className="mt-1">
                    <DriftBar drift={m.drift_pct} isDark={isDark} />
                    <p className={`text-[10px] mt-0.5 tabular-nums ${th.muted}`}>
                      {m.drift_pct >= 0 ? '+' : ''}{m.drift_pct.toFixed(2)}%
                    </p>
                  </div>
                )}
              </div>
              <div className="text-right flex items-start justify-end">
                <StatusBadge status={m.alert_status} isDark={isDark} />
              </div>
            </div>
          ))}
        </div>

        <p className={`text-xs mt-4 ${th.muted}`}>
          Drift = (current_1d_avg − baseline_7d_avg) / baseline_7d_avg × 100.
          Alert engine triggers WhatsApp + email when CRITICAL.
        </p>
      </div>
    </AppShell>
  )
}

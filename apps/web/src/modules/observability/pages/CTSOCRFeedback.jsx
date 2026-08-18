/**
 * OCR Feedback & Model Retraining Dashboard
 *
 * Shows the bank admin (ops_manager / ml_engineer) the full picture of the
 * automated OCR feedback loop:
 *   1. Corpus accumulation progress — how many samples collected vs retrain threshold
 *   2. Failure mode breakdown — what root causes are driving the corpus (last 30 days)
 *   3. Retraining run history — each auto-triggered run with before/after accuracy
 *
 * Access: ops_manager, bank_it_admin, ml_engineer
 * Route : /ops/ocr-feedback
 */
import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'
import AppShell from '../../../shared/layout/AppShell'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

// ── Data hook ─────────────────────────────────────────────────────────────────

function useOCRFeedback(bankId) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/v1/ops/ocr-feedback`, { credentials: 'include' })
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

// ── Failure mode labels + colours ─────────────────────────────────────────────

const MODE_META = {
  OCR_CHAR_ERROR:   { label: 'OCR Character Error',    color: 'bg-red-400'    },
  XLIT_GAP:         { label: 'Transliteration Gap',    color: 'bg-amber-400'  },
  LEXICON_GAP:      { label: 'Lexicon Gap',            color: 'bg-violet-400' },
  THRESHOLD_ISSUE:  { label: 'Threshold Too Tight',    color: 'bg-sky-400'    },
  INDETERMINATE:    { label: 'Indeterminate',          color: 'bg-slate-400'  },
  CLEAN:            { label: 'Clean (no action)',      color: 'bg-emerald-400' },
}

// ── Status badge for retrain runs ─────────────────────────────────────────────

const RUN_STATUS_D = {
  PROMOTED: 'bg-emerald-900/30 text-emerald-300 border-emerald-700/40',
  REJECTED: 'bg-amber-900/30  text-amber-300  border-amber-700/40',
  FAILED:   'bg-red-900/30    text-red-300    border-red-700/40',
  RUNNING:  'bg-sky-900/30    text-sky-300    border-sky-700/40',
}
const RUN_STATUS_L = {
  PROMOTED: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  REJECTED: 'bg-amber-50   text-amber-700   border-amber-200',
  FAILED:   'bg-red-50     text-red-700     border-red-200',
  RUNNING:  'bg-sky-50     text-sky-700     border-sky-200',
}

function RunBadge({ status, isDark }) {
  const map = isDark ? RUN_STATUS_D : RUN_STATUS_L
  const cls = map[status] ?? (isDark ? 'bg-slate-800 text-slate-400 border-white/8' : 'bg-slate-50 text-slate-500 border-slate-200')
  return (
    <span className={`text-[11px] font-semibold px-2.5 py-0.5 rounded-full border ${cls}`}>
      {status}
    </span>
  )
}

// ── Corpus progress bar ───────────────────────────────────────────────────────

function CorpusBar({ entry, isDark }) {
  const th = {
    card:    isDark ? 'bg-navy-900 border-white/8'  : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'                  : 'text-slate-900',
    muted:   isDark ? 'text-slate-400'              : 'text-slate-500',
    track:   isDark ? 'bg-white/8'                  : 'bg-slate-100',
  }

  if (entry.degraded) {
    return (
      <div className={`rounded-xl border p-5 ${th.card}`}>
        <p className={`text-sm font-medium mb-1 capitalize ${th.heading}`}>{entry.corpus_type} Corpus</p>
        <p className={`text-xs ${th.muted}`}>Data unavailable — Redis unreachable</p>
      </div>
    )
  }

  const pct = entry.progress_pct
  const barColor = pct >= 90 ? 'bg-amber-400' : pct >= 50 ? 'bg-sky-400' : 'bg-emerald-400'

  return (
    <div className={`rounded-xl border p-5 ${th.card}`}>
      <div className="flex items-center justify-between mb-3">
        <p className={`text-sm font-semibold capitalize ${th.heading}`}>
          {entry.corpus_type === 'payee' ? 'Payee Name' : 'MICR Line'} Corpus
        </p>
        <span className={`text-xs font-mono tabular-nums ${th.muted}`}>
          {entry.count} / {entry.threshold} samples
        </span>
      </div>

      <div className={`h-2.5 rounded-full overflow-hidden ${th.track}`}>
        <div
          className={`h-full rounded-full transition-all duration-500 ${barColor}`}
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
      </div>

      <div className="flex items-center justify-between mt-2">
        <p className={`text-xs ${th.muted}`}>
          {pct >= 100
            ? 'Threshold reached — retraining triggered'
            : `${entry.threshold - entry.count} more to trigger next retrain`}
        </p>
        <p className={`text-xs font-semibold tabular-nums ${pct >= 90 ? 'text-amber-400' : th.muted}`}>
          {pct.toFixed(1)}%
        </p>
      </div>
    </div>
  )
}

// ── Failure mode chart ────────────────────────────────────────────────────────

function FailureModeChart({ modes, isDark }) {
  const th = {
    card:    isDark ? 'bg-navy-900 border-white/8'  : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'                  : 'text-slate-900',
    muted:   isDark ? 'text-slate-400'              : 'text-slate-500',
    track:   isDark ? 'bg-white/8'                  : 'bg-slate-100',
    row:     isDark ? 'border-white/5'              : 'border-slate-100',
  }

  return (
    <div className={`rounded-xl border p-5 ${th.card}`}>
      <p className={`text-sm font-semibold mb-4 ${th.heading}`}>Failure Mode Distribution (last 30 days)</p>

      {modes.length === 0 ? (
        <p className={`text-xs ${th.muted}`}>
          No failure events recorded yet — corpus accumulation table not yet populated, or no mismatches in the last 30 days.
        </p>
      ) : (
        <div className="space-y-3">
          {modes.map(fm => {
            const meta = MODE_META[fm.mode] ?? { label: fm.mode, color: 'bg-slate-400' }
            return (
              <div key={fm.mode}>
                <div className="flex items-center justify-between mb-1">
                  <span className={`text-xs font-medium ${th.heading}`}>{meta.label}</span>
                  <span className={`text-xs tabular-nums ${th.muted}`}>{fm.count} ({fm.pct}%)</span>
                </div>
                <div className={`h-1.5 rounded-full overflow-hidden ${th.track}`}>
                  <div
                    className={`h-full rounded-full ${meta.color}`}
                    style={{ width: `${fm.pct}%` }}
                  />
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── Retrain history table ─────────────────────────────────────────────────────

function RetrainHistory({ runs, isDark }) {
  const th = {
    card:    isDark ? 'bg-navy-900 border-white/8'          : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'                          : 'text-slate-900',
    muted:   isDark ? 'text-slate-400'                      : 'text-slate-500',
    col:     isDark ? 'text-slate-300'                      : 'text-slate-700',
    hdr:     isDark ? 'border-white/8 text-slate-400'       : 'border-slate-100 text-slate-500',
    row:     isDark ? 'border-white/5 hover:bg-white/2'     : 'border-slate-100 hover:bg-slate-50',
  }

  const fmt = (iso) => {
    if (!iso) return '—'
    try {
      return new Date(iso).toLocaleString('en-IN', {
        day: '2-digit', month: 'short', year: 'numeric',
        hour: '2-digit', minute: '2-digit', hour12: false,
      })
    } catch { return iso }
  }

  const fmtAcc = (v) => v != null ? `${(v * 100).toFixed(2)}%` : '—'
  const fmtImp = (v) => {
    if (v == null) return '—'
    const sign = v >= 0 ? '+' : ''
    return <span className={v >= 0 ? 'text-emerald-400' : 'text-red-400'}>{sign}{v.toFixed(2)}%</span>
  }

  return (
    <div className={`rounded-xl border overflow-hidden ${th.card}`}>
      <div className={`px-5 py-3 border-b ${th.hdr} text-[11px] uppercase tracking-widest font-semibold flex items-center justify-between`}>
        <span>Retraining Run History</span>
        <span className={`text-[10px] normal-case tracking-normal ${th.muted}`}>Last 10 runs</span>
      </div>

      {runs.length === 0 ? (
        <div className={`px-5 py-8 text-center text-sm ${th.muted}`}>
          No retraining runs yet. The automated pipeline triggers when the corpus threshold is reached.
        </div>
      ) : (
        <>
          <div className={`grid grid-cols-7 gap-3 px-5 py-2.5 border-b ${th.hdr} text-[10px] uppercase tracking-widest font-semibold`}
               style={{ gridTemplateColumns: '1fr 0.6fr 1.4fr 1.4fr 0.8fr 0.8fr 0.7fr' }}>
            <span>Run ID</span>
            <span>Corpus</span>
            <span>Triggered</span>
            <span>Completed</span>
            <span className="text-right">Before</span>
            <span className="text-right">After</span>
            <span className="text-right">Status</span>
          </div>
          {runs.map(run => (
            <div
              key={run.run_id}
              className={`grid gap-3 px-5 py-3.5 border-b last:border-0 ${th.row} text-sm`}
              style={{ gridTemplateColumns: '1fr 0.6fr 1.4fr 1.4fr 0.8fr 0.8fr 0.7fr' }}
            >
              <span className={`font-mono text-xs truncate ${th.muted}`}>{run.run_id.slice(-12)}</span>
              <span className={`text-xs capitalize ${th.col}`}>{run.corpus_type}</span>
              <span className={`text-xs tabular-nums ${th.muted}`}>{fmt(run.triggered_at)}</span>
              <span className={`text-xs tabular-nums ${th.muted}`}>{fmt(run.completed_at)}</span>
              <span className={`text-xs text-right tabular-nums ${th.col}`}>{fmtAcc(run.accuracy_before)}</span>
              <span className={`text-xs text-right tabular-nums ${th.col}`}>
                {run.accuracy_after != null
                  ? <span className="flex flex-col items-end gap-0.5">
                      <span>{fmtAcc(run.accuracy_after)}</span>
                      <span className="text-[10px]">{fmtImp(run.improvement_pct)}</span>
                    </span>
                  : '—'}
              </span>
              <div className="flex justify-end items-start">
                <RunBadge status={run.status} isDark={isDark} />
              </div>
            </div>
          ))}
        </>
      )}
    </div>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function CTSOCRFeedback() {
  const { isDark } = useTheme()
  const { bankId } = useBankContext()
  const { data, loading, error, reload } = useOCRFeedback(bankId)

  const th = {
    page:    isDark ? 'bg-navy-950'                : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'                 : 'text-slate-900',
    muted:   isDark ? 'text-slate-400'             : 'text-slate-500',
  }

  const corpus        = data?.corpus        ?? []
  const failureModes  = data?.failure_modes ?? []
  const retrainHistory = data?.retrain_history ?? []
  const degraded      = data?.degraded ?? false

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
              <span className={`text-xs ${th.muted}`}>OCR Feedback</span>
            </div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>OCR Feedback & Retraining</h1>
            <p className={`text-xs mt-0.5 ${th.muted}`}>
              Automated corpus accumulation · Zero human triggers · Auto-promotes on improvement ≥ 2%
            </p>
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
            Partial data — one or more data sources degraded. Redis or YugabyteDB may be unreachable.
          </div>
        )}

        {/* How this loop works — compact explainer */}
        <div className={`rounded-xl border p-4 mb-5 ${th.card}`}>
          <p className={`text-xs font-semibold uppercase tracking-widest mb-2 ${th.muted}`}>How the loop works</p>
          <div className="flex items-start gap-4 flex-wrap">
            {[
              { step: '1', text: 'Every cheque decision emits a feedback signal (payee match score + failure mode)' },
              { step: '2', text: 'FeedbackAccumulatorWorkflow collects OCR_CHAR_ERROR cases into the training corpus' },
              { step: '3', text: 'When corpus hits threshold (default 500), ModelRetrainWorkflow auto-triggers MLflow' },
              { step: '4', text: 'Shadow evaluation runs — new model promoted only if accuracy improves by ≥ 2%' },
            ].map(({ step, text }) => (
              <div key={step} className="flex items-start gap-2 min-w-[200px] flex-1">
                <span className={`text-xs font-bold mt-0.5 shrink-0 w-5 h-5 rounded-full flex items-center justify-center
                  ${isDark ? 'bg-white/8 text-slate-300' : 'bg-slate-100 text-slate-600'}`}>
                  {step}
                </span>
                <p className={`text-xs leading-relaxed ${th.muted}`}>{text}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Corpus progress */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-5">
          {corpus.map(entry => (
            <CorpusBar key={entry.corpus_type} entry={entry} isDark={isDark} />
          ))}
          {corpus.length === 0 && !loading && (
            <p className={`text-sm col-span-2 ${th.muted}`}>No corpus data available.</p>
          )}
        </div>

        {/* Failure mode breakdown */}
        <div className="mb-5">
          <FailureModeChart modes={failureModes} isDark={isDark} />
        </div>

        {/* Retraining history */}
        <div className="overflow-x-auto">
          <RetrainHistory runs={retrainHistory} isDark={isDark} />
        </div>

        <p className={`text-xs mt-4 ${th.muted}`}>
          Corpus counts from Redis · Failure modes and run history from YugabyteDB (cts.ocr_corpus_events, cts.model_retrain_runs).
          Retrain history appears once ModelRetrainWorkflow has completed at least one run.
        </p>
      </div>
    </AppShell>
  )
}

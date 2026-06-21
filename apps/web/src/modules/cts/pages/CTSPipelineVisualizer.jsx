import { useState, useEffect, useRef, useCallback } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'

// ─── Mock data ────────────────────────────────────────────────────────────────

const MOCK_QUEUE = [
  {
    id: 'CHQ-MUM-001847',
    fraud_score: 0.81,
    sig_match_score: 0.61,
    ocr_confidence: 0.94,
    reason: 'SIGNATURE_LOW_CONFIDENCE',
    amount_range: '₹[5L-10L]',
    account_suffix: '****7823',
    bank: 'Saraswat Co-op',
    stageResults: {
      0: { ms: 3,   ok: true,  detail: 'CTS 2010 validated' },
      1: { ms: 11,  ok: true,  detail: 'MICR: 001847 · IFSC: SRCB0000021' },
      2: { ms: 49,  ok: true,  detail: 'OCR conf 0.94 · Payee: R***' },
      3: { ms: 92,  ok: true,  detail: 'No alteration detected' },
      4: { ms: 138, ok: false, detail: 'Match score 0.61 < threshold 0.85' },
      5: { ms: 181, ok: false, detail: 'Fraud score 0.81 · SHAP: sig_mismatch=0.44' },
      6: { ms: 184, ok: false, detail: 'HELD — awaiting reviewer' },
    },
  },
  {
    id: 'CHQ-MUM-001901',
    fraud_score: 0.77,
    sig_match_score: 0.88,
    ocr_confidence: 0.91,
    reason: 'HIGH_VALUE_DUAL_APPROVAL',
    amount_range: '₹[>1Cr]',
    account_suffix: '****3341',
    bank: 'Saraswat Co-op',
    stageResults: {
      0: { ms: 2,   ok: true,  detail: 'CTS 2010 validated' },
      1: { ms: 9,   ok: true,  detail: 'MICR: 001901 · IFSC: SRCB0000021' },
      2: { ms: 53,  ok: true,  detail: 'OCR conf 0.91 · Payee: K***' },
      3: { ms: 88,  ok: true,  detail: 'No alteration detected' },
      4: { ms: 124, ok: true,  detail: 'Match score 0.88 ✓' },
      5: { ms: 165, ok: false, detail: 'Fraud score 0.77 · SHAP: high_value=0.51' },
      6: { ms: 168, ok: false, detail: 'HELD — dual approval required >₹1Cr' },
    },
  },
  {
    id: 'CHQ-MUM-001733',
    fraud_score: 0.74,
    sig_match_score: 0.79,
    ocr_confidence: 0.88,
    reason: 'OCR_FIELD_MISMATCH',
    amount_range: '₹[1L-5L]',
    account_suffix: '****5512',
    bank: 'Saraswat Co-op',
    stageResults: {
      0: { ms: 4,   ok: true,  detail: 'CTS 2010 validated' },
      1: { ms: 13,  ok: true,  detail: 'MICR: 001733 · IFSC: SRCB0000021' },
      2: { ms: 58,  ok: false, detail: 'Amount figures/words mismatch' },
      3: { ms: 91,  ok: true,  detail: 'Minor ink variation detected' },
      4: { ms: 127, ok: true,  detail: 'Match score 0.79 ✓' },
      5: { ms: 168, ok: false, detail: 'Fraud score 0.74 · SHAP: ocr_mismatch=0.38' },
      6: { ms: 171, ok: false, detail: 'HELD — OCR field mismatch' },
    },
  },
]

const MOCK_EXCEPTIONS = [
  {
    id: 'CHQ-MUM-001654',
    reason: 'VAULT_MISS',
    fraud_score: null,
    sig_match_score: null,
    ocr_confidence: 0.96,
    amount_range: '₹[5L-10L]',
    account_suffix: '****9904',
    bank: 'Saraswat Co-op',
    stageResults: {
      0: { ms: 3,   ok: true,  detail: 'CTS 2010 validated' },
      1: { ms: 10,  ok: true,  detail: 'MICR: 001654 · IFSC: SRCB0000021' },
      2: { ms: 47,  ok: true,  detail: 'OCR conf 0.96 · Payee: V***' },
      3: { ms: 79,  ok: true,  detail: 'No alteration detected' },
      4: { ms: 84,  ok: false, detail: 'VAULT MISS — no signature specimen on file' },
    },
  },
  {
    id: 'CHQ-MUM-001712',
    reason: 'CBS_TIMEOUT',
    fraud_score: null,
    sig_match_score: 0.91,
    ocr_confidence: 0.93,
    amount_range: '₹[1L-5L]',
    account_suffix: '****2278',
    bank: 'Saraswat Co-op',
    stageResults: {
      0: { ms: 2,   ok: true,  detail: 'CTS 2010 validated' },
      1: { ms: 8,   ok: true,  detail: 'MICR: 001712 · IFSC: SRCB0000021' },
      2: { ms: 44,  ok: true,  detail: 'OCR conf 0.93 · Payee: A***' },
      3: { ms: 76,  ok: true,  detail: 'No alteration detected' },
      4: { ms: 112, ok: true,  detail: 'Match score 0.91 ✓' },
      5: { ms: 122, ok: false, detail: 'CBS TIMEOUT after 10s — balance unavailable' },
    },
  },
]

// ─── Stage config ──────────────────────────────────────────────────────────────

const STAGES = [
  { id: 0, label: 'Ingest',   icon: '📥', shortLabel: 'Ingest',  avgMs: 3   },
  { id: 1, label: 'MICR',    icon: '🔢', shortLabel: 'MICR',    avgMs: 10  },
  { id: 2, label: 'OCR',     icon: '📄', shortLabel: 'OCR',     avgMs: 52  },
  { id: 3, label: 'Vision',  icon: '🔍', shortLabel: 'Vision',  avgMs: 88  },
  { id: 4, label: 'Sig',     icon: '✍️',  shortLabel: 'Sig',     avgMs: 130 },
  { id: 5, label: 'Fraud',   icon: '🛡️',  shortLabel: 'Fraud',   avgMs: 170 },
  { id: 6, label: 'Decision',icon: '⚖️',  shortLabel: 'Decide',  avgMs: 175 },
  { id: 7, label: 'NGCH',    icon: '📤', shortLabel: 'NGCH',    avgMs: 195 },
]

// ─── Particle factory ──────────────────────────────────────────────────────────

let _pid = 1000
function makeParticle() {
  const id = `CHQ-MUM-0${++_pid}`
  const r = Math.random()
  const outcome = r < 0.72 ? 'STP_CONFIRM' : r < 0.88 ? 'STP_RETURN' : 'HUMAN_REVIEW'
  return {
    id,
    stage: 0,
    stageProgress: 0,
    outcome,
    fraud_score: +(Math.random() * 0.5 + (outcome === 'STP_CONFIRM' ? 0.1 : 0.5)).toFixed(2),
    ocr_confidence: +(Math.random() * 0.1 + 0.88).toFixed(2),
    sig_match_score: +(Math.random() * 0.2 + (outcome === 'STP_CONFIRM' ? 0.78 : 0.6)).toFixed(2),
    amount_range: ['₹[<1L]', '₹[1L-5L]', '₹[5L-10L]', '₹[10L-1Cr]'][Math.floor(Math.random() * 4)],
    account_suffix: `****${String(Math.floor(Math.random() * 9000) + 1000)}`,
    bank: 'Saraswat Co-op',
    reason: outcome === 'HUMAN_REVIEW'
      ? ['SIGNATURE_LOW_CONFIDENCE', 'HIGH_VALUE_DUAL_APPROVAL', 'FRAUD_SCORE_HIGH'][Math.floor(Math.random() * 3)]
      : null,
    speed: 0.008 + Math.random() * 0.006,
    stageResults: {},
    finalized: false,
    exitProgress: 0,
  }
}

const initStats = () => STAGES.map(s => ({
  throughput: Math.floor(Math.random() * 40 + 60),
  avgMs: s.avgMs + Math.floor(Math.random() * 10 - 5),
  errRate: +(Math.random() * 2).toFixed(1),
}))

// ─── Child panel ──────────────────────────────────────────────────────────────

function ChildPanel({ item, onClose, isException }) {
  const stageCount = Object.keys(item.stageResults).length
  const allStages = STAGES.map((s, i) => {
    const r = item.stageResults[i]
    let status = 'pending'
    if (r) status = r.ok ? 'done' : (i === stageCount - 1 && isException ? 'error' : 'warn')
    return { ...s, result: r, status }
  })

  const heldStage = allStages.find(s => s.status === 'warn' || s.status === 'error')

  const statusIcon  = { done: '✓', warn: '⚠', error: '✗', pending: '·' }
  const statusBorder = {
    done:    'border-emerald-500/40 bg-emerald-500/8',
    warn:    'border-amber-500/40 bg-amber-500/8',
    error:   'border-red-500/40 bg-red-500/8',
    pending: 'border-white/6 bg-white/2',
  }
  const statusText = {
    done: 'text-emerald-400', warn: 'text-amber-400', error: 'text-red-400', pending: 'text-slate-600',
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: 'rgba(2,8,23,0.92)', backdropFilter: 'blur(12px)' }}
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-5xl mx-4 rounded-2xl border border-white/10 overflow-hidden"
        style={{
          background: 'linear-gradient(145deg, #0b1340 0%, #060d2e 100%)',
          boxShadow: '0 0 80px rgba(251,191,36,0.08), 0 40px 80px rgba(0,0,0,0.8)',
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/8">
          <div className="flex items-center gap-3 flex-wrap">
            <div className={`w-2 h-2 rounded-full animate-pulse ${isException ? 'bg-red-400' : 'bg-amber-400'}`} />
            <span className="text-white font-mono text-sm font-semibold">{item.id}</span>
            <span className="text-[11px] px-2 py-0.5 rounded-full border font-medium bg-amber-400/10 text-amber-400 border-amber-400/30">
              {item.account_suffix} · {item.amount_range}
            </span>
            {item.reason && (
              <span className={`text-[11px] px-2 py-0.5 rounded-full border font-medium ${isException ? 'bg-red-400/10 text-red-400 border-red-400/30' : 'bg-amber-400/10 text-amber-400 border-amber-400/30'}`}>
                {item.reason}
              </span>
            )}
          </div>
          <button
            onClick={onClose}
            className="w-7 h-7 flex items-center justify-center rounded-lg text-slate-400 hover:text-white hover:bg-white/10 transition-colors text-lg leading-none shrink-0"
          >×</button>
        </div>

        {/* Swimlane */}
        <div className="p-6 overflow-x-auto">
          <div className="flex items-start gap-0 min-w-max">
            {allStages.map((s, i) => (
              <div key={i} className="flex items-center">
                {/* Stage card */}
                <div
                  className={`w-[108px] rounded-xl border p-3 flex flex-col gap-2 ${statusBorder[s.status]}`}
                  style={{
                    boxShadow: s.status === 'done'
                      ? '0 0 12px rgba(52,211,153,0.08)'
                      : s.status === 'error'
                      ? '0 0 14px rgba(248,113,113,0.12)'
                      : s.status === 'warn'
                      ? '0 0 14px rgba(251,191,36,0.12)'
                      : 'none',
                  }}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm">{STAGES[i].icon}</span>
                    <span className={`text-lg font-bold leading-none ${statusText[s.status]}`}>{statusIcon[s.status]}</span>
                  </div>
                  <div>
                    <div className="text-[11px] font-semibold text-white/80">{s.label}</div>
                    <div className={`text-[10px] mt-0.5 ${s.result ? 'text-slate-400' : 'text-slate-700'}`}>
                      {s.result ? `${s.result.ms}ms` : '—'}
                    </div>
                  </div>
                  <div className="text-[10px] text-slate-400 leading-tight border-t border-white/5 pt-2 min-h-[30px]">
                    {s.result ? s.result.detail : 'not reached'}
                  </div>
                </div>
                {/* Arrow connector */}
                {i < allStages.length - 1 && (
                  <div className="flex items-center justify-center px-1">
                    <span className="text-slate-700 text-base font-bold">›</span>
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Score row */}
          <div className="mt-5 flex gap-3">
            {[
              { label: 'OCR Confidence',  val: item.ocr_confidence,  fmt: v => `${(v*100).toFixed(0)}%`, good: v => v > 0.90 },
              { label: 'Signature Match', val: item.sig_match_score, fmt: v => v == null ? 'N/A' : `${(v*100).toFixed(0)}%`, good: v => v != null && v > 0.85 },
              { label: 'Fraud Score',     val: item.fraud_score,     fmt: v => v == null ? 'N/A' : `${(v*100).toFixed(0)}%`, good: v => v != null && v < 0.72 },
              { label: 'Amount Range',    val: item.amount_range,    fmt: v => v, good: () => true, isStr: true },
            ].map(({ label, val, fmt, good, isStr }) => (
              <div key={label} className="flex-1 bg-white/3 rounded-xl border border-white/6 px-4 py-3">
                <div className="text-[10px] text-slate-500 mb-1">{label}</div>
                <div className={`text-xl font-bold font-mono ${isStr ? 'text-amber-400' : val == null ? 'text-slate-600' : good(val) ? 'text-emerald-400' : 'text-red-400'}`}>
                  {fmt(val)}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Action bar */}
        {heldStage && (
          <div className="px-6 py-4 border-t border-white/8 flex items-center gap-3 flex-wrap">
            <div className="flex-1 text-[11px] text-slate-500 min-w-0">
              {isException ? 'Exception review' : 'Human review decision required'}&nbsp;
              <span className="text-amber-400 font-mono">{item.id}</span>
            </div>
            <select className="text-[11px] bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-slate-300 focus:outline-none focus:border-amber-400/50 cursor-pointer">
              <option>Select return reason…</option>
              <option>Funds Insufficient</option>
              <option>Signature Mismatch</option>
              <option>Amount Alteration</option>
              <option>Refer to Drawer</option>
              <option>Payment Stopped</option>
            </select>
            <button
              onClick={onClose}
              className="px-4 py-1.5 text-[11px] font-semibold rounded-lg bg-red-500/20 border border-red-500/40 text-red-400 hover:bg-red-500/30 transition-colors"
            >✕ Return</button>
            <button
              onClick={onClose}
              className="px-4 py-1.5 text-[11px] font-semibold rounded-lg bg-emerald-500/20 border border-emerald-500/40 text-emerald-400 hover:bg-emerald-500/30 transition-colors"
            >✓ Confirm</button>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── IET Timer strip ──────────────────────────────────────────────────────────

function IETTimerStrip({ confirmCount, returnCount, reviewCount }) {
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setElapsed(e => e + 1), 1000)
    return () => clearInterval(t)
  }, [])
  const ietSecs = 180 * 60
  const pct = Math.min((elapsed / ietSecs) * 100, 100)
  const remaining = ietSecs - elapsed
  const mm = String(Math.floor(Math.abs(remaining) / 60)).padStart(2, '0')
  const ss = String(Math.abs(remaining) % 60).padStart(2, '0')
  const barColor = pct < 50 ? '#10b981' : pct < 80 ? '#f59e0b' : '#ef4444'

  return (
    <div className="flex items-center gap-5 bg-white/2 border border-white/6 rounded-xl px-5 py-3 shrink-0">
      <div className="flex items-center gap-3 shrink-0">
        <div>
          <div className="text-[10px] text-slate-500 uppercase tracking-widest mb-0.5">IET Window</div>
          <div
            className="font-mono text-2xl font-bold text-amber-400"
            style={{ letterSpacing: '-0.02em', textShadow: '0 0 20px rgba(251,191,36,0.4)' }}
          >{mm}:{ss}</div>
        </div>
        <div className="w-28 h-1.5 rounded-full bg-white/5 overflow-hidden">
          <div className="h-full rounded-full" style={{ width: `${pct}%`, background: barColor, transition: 'width 1s linear, background 1s' }} />
        </div>
      </div>

      <div className="w-px h-8 bg-white/8 shrink-0" />

      {[
        { label: 'STP Confirmed', val: confirmCount + 847, color: 'text-emerald-400' },
        { label: 'STP Returned',  val: returnCount  + 124, color: 'text-red-400' },
        { label: 'Human Review',  val: reviewCount,         color: 'text-amber-400' },
      ].map(({ label, val, color }) => (
        <div key={label} className="flex flex-col items-center shrink-0">
          <div className="text-[10px] text-slate-500 uppercase tracking-wide mb-0.5 whitespace-nowrap">{label}</div>
          <div className={`font-mono text-xl font-bold ${color}`}>{val}</div>
        </div>
      ))}

      <div className="ml-auto flex items-center gap-2 shrink-0">
        <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
        <span className="text-[11px] text-emerald-400 font-medium whitespace-nowrap">IET Watchdog ACTIVE</span>
      </div>
    </div>
  )
}

// ─── Stage node ───────────────────────────────────────────────────────────────

function StageNode({ stage, leftPct, isPulsing }) {
  return (
    <div
      className="absolute flex flex-col items-center z-10"
      style={{ left: `${leftPct}%`, top: '50%', transform: 'translate(-50%, -50%)' }}
    >
      <div
        className="w-10 h-10 rounded-full border-2 flex items-center justify-center text-base relative"
        style={{
          borderColor: isPulsing ? 'rgba(251,191,36,0.95)' : 'rgba(251,191,36,0.22)',
          background: isPulsing ? 'rgba(251,191,36,0.18)' : 'rgba(251,191,36,0.04)',
          boxShadow: isPulsing
            ? '0 0 18px rgba(251,191,36,0.7), 0 0 36px rgba(251,191,36,0.3), inset 0 0 10px rgba(251,191,36,0.1)'
            : '0 0 8px rgba(251,191,36,0.06)',
          transition: 'all 0.25s ease',
        }}
      >
        <span>{stage.icon}</span>
      </div>
      <div
        className="text-[9px] font-semibold tracking-wider uppercase whitespace-nowrap mt-1"
        style={{ color: isPulsing ? 'rgba(251,191,36,0.8)' : 'rgba(148,163,184,0.6)', transition: 'color 0.25s' }}
      >
        {stage.shortLabel}
      </div>
    </div>
  )
}

// ─── Moving particle dot ──────────────────────────────────────────────────────

function ParticleDot({ particle }) {
  const progress = (particle.stage + particle.stageProgress) / 7
  const leftPct = 5 + progress * 90
  const colorMap = {
    STP_CONFIRM:  { dot: '#10b981', glow: '#10b981' },
    STP_RETURN:   { dot: '#ef4444', glow: '#ef4444' },
    HUMAN_REVIEW: { dot: '#f59e0b', glow: '#f59e0b' },
  }
  const { dot, glow } = colorMap[particle.outcome] || colorMap.STP_CONFIRM
  return (
    <div
      className="absolute z-20 w-3 h-3 rounded-full pointer-events-none"
      style={{
        left: `${leftPct}%`,
        top: '50%',
        transform: 'translate(-50%, -50%)',
        background: dot,
        boxShadow: `0 0 6px ${glow}, 0 0 14px ${glow}70`,
        transition: 'left 0.05s linear',
      }}
    />
  )
}

// ─── Stats strip ──────────────────────────────────────────────────────────────

function StatsStrip({ stats, stageActive }) {
  return (
    <div className="flex gap-1.5 mt-3 shrink-0">
      {STAGES.map((s, i) => {
        const st = stats[i]
        const active = !!stageActive[i]
        return (
          <div
            key={i}
            className="flex-1 rounded-xl border px-2 py-2 flex flex-col gap-1"
            style={{
              borderColor: active ? 'rgba(251,191,36,0.35)' : 'rgba(255,255,255,0.06)',
              background: active ? 'rgba(251,191,36,0.06)' : 'rgba(255,255,255,0.02)',
              transition: 'all 0.3s ease',
              boxShadow: active ? '0 0 12px rgba(251,191,36,0.06)' : 'none',
            }}
          >
            <div className="text-[9px] font-semibold uppercase tracking-wide truncate" style={{ color: active ? 'rgba(251,191,36,0.7)' : 'rgba(148,163,184,0.5)' }}>
              {s.shortLabel}
            </div>
            <div className="text-[11px] font-mono font-bold text-amber-400">{st.avgMs}ms</div>
            <div className="flex items-center">
              <div className="text-[9px] text-slate-600">{st.throughput}/m</div>
              <div className={`text-[9px] ml-auto font-mono ${st.errRate < 1 ? 'text-emerald-600' : 'text-red-400'}`}>{st.errRate}%</div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ─── Exit pools ───────────────────────────────────────────────────────────────

function ConfirmPool({ count }) {
  const display = Math.min(count, 16)
  return (
    <div
      className="w-44 shrink-0 rounded-2xl border border-emerald-500/20 flex flex-col p-4 relative overflow-hidden"
      style={{ background: 'linear-gradient(145deg, rgba(16,185,129,0.07) 0%, rgba(16,185,129,0.02) 100%)', boxShadow: '0 0 40px rgba(16,185,129,0.04)' }}
    >
      <div className="absolute inset-x-0 bottom-0 h-px" style={{ background: 'linear-gradient(90deg, transparent, rgba(16,185,129,0.5), transparent)' }} />
      <div className="flex items-center gap-1.5 mb-2">
        <div className="w-2 h-2 rounded-full bg-emerald-400" style={{ boxShadow: '0 0 6px #10b981' }} />
        <span className="text-[10px] font-semibold text-emerald-400 uppercase tracking-wider">STP Confirm</span>
      </div>
      <div className="font-mono text-3xl font-bold text-emerald-400 mb-0.5" style={{ textShadow: '0 0 20px rgba(16,185,129,0.4)' }}>
        {count + 847}
      </div>
      <div className="text-[10px] text-emerald-700">confirmed this session</div>
      <div className="mt-auto pt-3 flex flex-wrap gap-1">
        {Array.from({ length: display }, (_, i) => (
          <div key={i} className="w-2 h-2 rounded-full" style={{ background: '#10b981', opacity: 0.5 + (i / display) * 0.5, boxShadow: '0 0 4px rgba(16,185,129,0.6)' }} />
        ))}
      </div>
    </div>
  )
}

function ReturnPool({ count }) {
  const display = Math.min(count, 16)
  return (
    <div
      className="w-44 shrink-0 rounded-2xl border border-red-500/20 flex flex-col p-4 relative overflow-hidden"
      style={{ background: 'linear-gradient(145deg, rgba(239,68,68,0.07) 0%, rgba(239,68,68,0.02) 100%)', boxShadow: '0 0 40px rgba(239,68,68,0.04)' }}
    >
      <div className="absolute inset-x-0 bottom-0 h-px" style={{ background: 'linear-gradient(90deg, transparent, rgba(239,68,68,0.5), transparent)' }} />
      <div className="flex items-center gap-1.5 mb-2">
        <div className="w-2 h-2 rounded-full bg-red-400 animate-pulse" style={{ boxShadow: '0 0 6px #ef4444' }} />
        <span className="text-[10px] font-semibold text-red-400 uppercase tracking-wider">STP Return</span>
      </div>
      <div className="font-mono text-3xl font-bold text-red-400 mb-0.5" style={{ textShadow: '0 0 20px rgba(239,68,68,0.4)' }}>
        {count + 124}
      </div>
      <div className="text-[10px] text-red-700">returned this session</div>
      <div className="mt-auto pt-3 flex flex-wrap gap-1">
        {Array.from({ length: display }, (_, i) => (
          <div key={i} className="w-2 h-2 rounded-full" style={{ background: '#ef4444', opacity: 0.5 + (i / display) * 0.5, boxShadow: '0 0 4px rgba(239,68,68,0.6)' }} />
        ))}
      </div>
    </div>
  )
}

function ReviewDock({ items, onSelect }) {
  return (
    <div
      className="flex-1 rounded-2xl border border-amber-500/20 flex flex-col p-4 relative overflow-hidden min-w-0"
      style={{ background: 'linear-gradient(145deg, rgba(245,158,11,0.06) 0%, rgba(245,158,11,0.02) 100%)', boxShadow: '0 0 40px rgba(245,158,11,0.04)' }}
    >
      <div className="absolute inset-x-0 bottom-0 h-px" style={{ background: 'linear-gradient(90deg, transparent, rgba(245,158,11,0.5), transparent)' }} />
      <div className="flex items-center gap-2 mb-3 shrink-0">
        <div className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" style={{ boxShadow: '0 0 8px #f59e0b' }} />
        <span className="text-[10px] font-semibold text-amber-400 uppercase tracking-wider">Human Review Dock</span>
        <span className="ml-auto bg-amber-400/15 border border-amber-400/25 text-amber-400 text-[10px] font-bold rounded-full px-2 py-0.5 shrink-0">
          {items.length}
        </span>
      </div>
      <div className="flex gap-2 overflow-x-auto pb-1" style={{ scrollbarWidth: 'none', msOverflowStyle: 'none' }}>
        {items.slice(0, 12).map((item) => (
          <button
            key={item.id}
            onClick={() => onSelect(item)}
            className="shrink-0 rounded-xl border border-amber-400/20 bg-amber-400/5 hover:bg-amber-400/12 hover:border-amber-400/40 transition-all px-3 py-2.5 text-left group"
            style={{ minWidth: 126 }}
          >
            <div className="text-[10px] font-mono font-semibold text-amber-300 group-hover:text-amber-200 truncate" style={{ maxWidth: 108 }}>{item.id}</div>
            <div className="text-[9px] text-slate-500 mt-0.5">{item.account_suffix}</div>
            <div className="flex items-center gap-1 mt-1.5">
              <span className="text-[9px] font-medium text-amber-400">{item.amount_range}</span>
              {item.fraud_score != null && (
                <span className="ml-auto text-[9px] font-mono text-red-400">{(item.fraud_score * 100).toFixed(0)}%</span>
              )}
            </div>
            <div className="text-[8px] text-slate-600 mt-1 truncate" style={{ maxWidth: 108 }}>{item.reason}</div>
          </button>
        ))}
        {items.length === 0 && (
          <div className="flex items-center justify-center w-full text-[11px] text-slate-700 py-4">Queue empty</div>
        )}
      </div>
    </div>
  )
}

// ─── Main page component ──────────────────────────────────────────────────────

export default function CTSPipelineVisualizer() {
  const [running, setRunning] = useState(true)
  const [particles, setParticles] = useState([])
  const [stats] = useState(initStats)
  const [stageActive, setStageActive] = useState({})
  const [confirmPool, setConfirmPool] = useState([])
  const [returnPool, setReturnPool] = useState([])
  const [reviewDock, setReviewDock] = useState(MOCK_QUEUE)
  const [exceptions] = useState(MOCK_EXCEPTIONS)
  const [selectedItem, setSelectedItem] = useState(null)
  const [isException, setIsException] = useState(false)

  const runningRef = useRef(running)
  runningRef.current = running
  const frameRef = useRef(null)
  const spawnRef = useRef(null)

  usePageHeader({
    subtitle: 'Live · 500 agents · <600ms wall clock',
    actions: (
      <button
        onClick={() => setRunning(r => !r)}
        className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-[11px] font-semibold transition-all border ${
          running
            ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/25'
            : 'bg-amber-500/15 border-amber-500/30 text-amber-400 hover:bg-amber-500/25'
        }`}
      >
        <span className={`w-1.5 h-1.5 rounded-full ${running ? 'bg-emerald-400 animate-pulse' : 'bg-amber-400'}`} />
        {running ? 'Running' : 'Paused'}
      </button>
    ),
  })

  // Animation tick
  useEffect(() => {
    const tick = () => {
      if (runningRef.current) {
        setParticles(prev => {
          const next = []
          const newActive = {}
          const toConfirm = []
          const toReturn = []
          const toReview = []

          for (const p of prev) {
            if (p.finalized) {
              const np = { ...p, exitProgress: p.exitProgress + 0.05 }
              if (np.exitProgress < 1) next.push(np)
              continue
            }
            const np = { ...p, stageProgress: p.stageProgress + p.speed }
            if (np.stageProgress >= 1) {
              const stageMs = STAGES[np.stage].avgMs + Math.floor(Math.random() * 20 - 10)
              np.stageResults = { ...np.stageResults, [np.stage]: { ms: stageMs, ok: true } }
              newActive[np.stage] = Date.now()
              if (np.stage < 7) {
                np.stage = np.stage + 1
                np.stageProgress = 0
              } else {
                np.finalized = true
                np.exitProgress = 0
                if (np.outcome === 'STP_CONFIRM') toConfirm.push(np)
                else if (np.outcome === 'STP_RETURN') toReturn.push(np)
                else toReview.push({
                  id: np.id,
                  fraud_score: np.fraud_score,
                  sig_match_score: np.sig_match_score,
                  ocr_confidence: np.ocr_confidence,
                  reason: np.reason,
                  amount_range: np.amount_range,
                  account_suffix: np.account_suffix,
                  bank: np.bank,
                  stageResults: np.stageResults,
                })
              }
            }
            next.push(np)
          }

          if (Object.keys(newActive).length) {
            setStageActive(sa => ({ ...sa, ...newActive }))
          }
          if (toConfirm.length) setConfirmPool(c => [...c, ...toConfirm].slice(-300))
          if (toReturn.length)  setReturnPool(r => [...r, ...toReturn].slice(-300))
          if (toReview.length)  setReviewDock(d => [...d, ...toReview].slice(-20))
          return next
        })
      }
      frameRef.current = requestAnimationFrame(tick)
    }
    frameRef.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frameRef.current)
  }, [])

  // Spawn interval
  useEffect(() => {
    spawnRef.current = setInterval(() => {
      if (!runningRef.current) return
      setParticles(prev => {
        if (prev.filter(p => !p.finalized).length >= 18) return prev
        return [...prev, makeParticle()]
      })
    }, 1400)
    return () => clearInterval(spawnRef.current)
  }, [])

  // Pulse cleanup
  useEffect(() => {
    const t = setInterval(() => {
      const now = Date.now()
      setStageActive(sa => {
        const u = {}
        for (const [k, v] of Object.entries(sa)) {
          if (now - v < 700) u[k] = v
        }
        return u
      })
    }, 200)
    return () => clearInterval(t)
  }, [])

  const openItem = useCallback((item, exc) => {
    setSelectedItem(item)
    setIsException(!!exc)
  }, [])

  const activeParticles = particles.filter(p => !p.finalized)

  return (
    <AppShell>
      <div
        className="flex flex-col h-full overflow-hidden select-none"
        style={{ background: 'linear-gradient(180deg, #020817 0%, #030c24 50%, #020817 100%)', minHeight: 0 }}
      >
        {/* Top accent line */}
        <div
          className="absolute top-0 left-0 right-0 h-px pointer-events-none"
          style={{ background: 'linear-gradient(90deg, transparent 0%, rgba(251,191,36,0.35) 30%, rgba(251,191,36,0.7) 50%, rgba(251,191,36,0.35) 70%, transparent 100%)' }}
        />

        <div className="flex-1 flex flex-col min-h-0 px-6 py-4 gap-4">

          {/* IET strip */}
          <IETTimerStrip
            confirmCount={confirmPool.length}
            returnCount={returnPool.length}
            reviewCount={reviewDock.length}
          />

          {/* Circuit board track */}
          <div className="flex-1 flex flex-col min-h-0" style={{ minHeight: 200 }}>
            {/* Track wrapper */}
            <div
              className="relative w-full rounded-2xl border border-amber-400/10 overflow-visible"
              style={{
                height: 130,
                background: 'radial-gradient(ellipse at 50% 50%, rgba(251,191,36,0.04) 0%, transparent 70%)',
                boxShadow: 'inset 0 0 60px rgba(251,191,36,0.03), 0 0 0 1px rgba(251,191,36,0.06)',
              }}
            >
              {/* Subtle grid */}
              {[12.5, 25, 37.5, 50, 62.5, 75, 87.5].map(p => (
                <div key={p} className="absolute top-0 bottom-0 w-px pointer-events-none" style={{ left: `${p}%`, background: 'rgba(255,255,255,0.015)' }} />
              ))}

              {/* Track glow line */}
              <div
                className="absolute pointer-events-none"
                style={{
                  top: '50%',
                  left: '5%',
                  right: '5%',
                  height: '2px',
                  transform: 'translateY(-50%)',
                  background: 'linear-gradient(90deg, rgba(251,191,36,0.05) 0%, rgba(251,191,36,0.55) 15%, rgba(251,191,36,0.85) 50%, rgba(251,191,36,0.55) 85%, rgba(251,191,36,0.05) 100%)',
                  boxShadow: '0 0 10px rgba(251,191,36,0.45), 0 0 22px rgba(251,191,36,0.2)',
                }}
              />

              {/* Stage nodes */}
              {STAGES.map((s, i) => {
                const leftPct = 5 + (i / 7) * 90
                return <StageNode key={i} stage={s} leftPct={leftPct} isPulsing={!!stageActive[i]} />
              })}

              {/* Particles */}
              {activeParticles.map(p => (
                <ParticleDot key={p.id} particle={p} />
              ))}

              {/* Exception indicators */}
              {exceptions.map((exc) => {
                const stuckStage = Object.keys(exc.stageResults).length - 1
                const leftPct = 5 + (stuckStage / 7) * 90 + 2.5
                return (
                  <button
                    key={exc.id}
                    onClick={() => openItem(exc, true)}
                    title={`${exc.id}: ${exc.reason}`}
                    className="absolute z-30 group flex flex-col items-center"
                    style={{ left: `${leftPct}%`, top: '14%', transform: 'translateX(-50%)' }}
                  >
                    <div
                      className="w-3 h-3 rounded-full border border-red-400/80 bg-red-500"
                      style={{
                        boxShadow: '0 0 8px #ef4444, 0 0 16px rgba(239,68,68,0.5)',
                        animation: 'pulse 0.8s infinite',
                      }}
                    />
                    <div
                      className="opacity-0 group-hover:opacity-100 transition-opacity absolute pointer-events-none"
                      style={{ top: '100%', marginTop: 4, left: '50%', transform: 'translateX(-50%)' }}
                    >
                      <div className="bg-red-950/95 border border-red-500/40 rounded-lg px-2.5 py-1.5 text-[10px] text-red-300 whitespace-nowrap shadow-lg">
                        <div className="font-mono font-semibold">{exc.id}</div>
                        <div className="text-red-500">{exc.reason}</div>
                      </div>
                    </div>
                  </button>
                )
              })}

              {/* Exception label top-right */}
              {exceptions.length > 0 && (
                <div className="absolute top-2.5 right-4 flex items-center gap-1.5 pointer-events-none">
                  <div className="w-1.5 h-1.5 rounded-full bg-red-400 animate-pulse" />
                  <span className="text-[10px] text-red-400 font-medium">{exceptions.length} Exception{exceptions.length > 1 ? 's' : ''}</span>
                </div>
              )}
            </div>

            {/* Stats */}
            <StatsStrip stats={stats} stageActive={stageActive} />
          </div>

          {/* Exit pools */}
          <div className="flex gap-3 shrink-0" style={{ height: 150 }}>
            <ConfirmPool count={confirmPool.length} />
            <ReviewDock items={reviewDock} onSelect={item => openItem(item, false)} />
            <ReturnPool count={returnPool.length} />
          </div>
        </div>
      </div>

      {/* Child panel */}
      {selectedItem && (
        <ChildPanel
          item={selectedItem}
          isException={isException}
          onClose={() => setSelectedItem(null)}
        />
      )}
    </AppShell>
  )
}

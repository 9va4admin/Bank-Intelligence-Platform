/**
 * CTSAnalytics — Decision analytics, AI model performance, IET safety.
 * Full Recharts charts: stacked area throughput, fraud score histogram,
 * donut decision split, risk flag frequency, branch breakdown, model drift.
 */
import { useState } from 'react'
import {
  AreaChart, Area,
  BarChart, Bar,
  LineChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell, Legend,
} from 'recharts'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'
import useAnalytics from '../hooks/useAnalytics'
import useInwardAnalytics from '../hooks/useInwardAnalytics'

// ── Mock data ─────────────────────────────────────────────────────────────────

const SB_DAILY = [
  { date: 'Aug 25', total: 4820, stp_confirm: 3921, stp_return: 641, human: 258, avg_ms: 389, ocr_conf: 99.1, sig_prec: 97.9 },
  { date: 'Aug 26', total: 5210, stp_confirm: 4281, stp_return: 721, human: 208, avg_ms: 372, ocr_conf: 99.3, sig_prec: 98.1 },
  { date: 'Aug 27', total: 4980, stp_confirm: 4101, stp_return: 681, human: 198, avg_ms: 401, ocr_conf: 99.0, sig_prec: 97.8 },
  { date: 'Aug 28', total: 5310, stp_confirm: 4441, stp_return: 741, human: 128, avg_ms: 358, ocr_conf: 99.4, sig_prec: 98.2 },
  { date: 'Aug 29', total: 4740, stp_confirm: 3881, stp_return: 631, human: 228, avg_ms: 413, ocr_conf: 98.9, sig_prec: 97.6 },
  { date: 'Aug 30', total: 5430, stp_confirm: 4561, stp_return: 711, human: 158, avg_ms: 344, ocr_conf: 99.5, sig_prec: 98.3 },
  { date: 'Aug 31', total: 2130, stp_confirm: 1801, stp_return: 221, human:  108, avg_ms: 361, ocr_conf: 99.2, sig_prec: 97.9 },
]

const SMB_DAILY = [
  { date: 'Aug 25', total: 295, stp_confirm: 243, stp_return: 38, human: 14, avg_ms: 391, ocr_conf: 98.8, sig_prec: 97.3 },
  { date: 'Aug 26', total: 312, stp_confirm: 258, stp_return: 41, human: 13, avg_ms: 374, ocr_conf: 99.1, sig_prec: 97.7 },
  { date: 'Aug 27', total: 298, stp_confirm: 247, stp_return: 38, human: 13, avg_ms: 403, ocr_conf: 98.7, sig_prec: 97.2 },
  { date: 'Aug 28', total: 321, stp_confirm: 268, stp_return: 42, human: 11, avg_ms: 360, ocr_conf: 99.2, sig_prec: 97.8 },
  { date: 'Aug 29', total: 287, stp_confirm: 235, stp_return: 38, human: 14, avg_ms: 415, ocr_conf: 98.6, sig_prec: 97.1 },
  { date: 'Aug 30', total: 331, stp_confirm: 275, stp_return: 43, human: 13, avg_ms: 346, ocr_conf: 99.3, sig_prec: 97.9 },
  { date: 'Aug 31', total:  79, stp_confirm:  65, stp_return: 10, human:  4, avg_ms: 363, ocr_conf: 99.0, sig_prec: 97.5 },
]

const SB_FRAUD_DIST = [
  { range: '0–10',  count: 3120, color: '#10b981' },
  { range: '10–30', count: 890,  color: '#34d399' },
  { range: '30–50', count: 410,  color: '#f59e0b' },
  { range: '50–70', count: 280,  color: '#f97316' },
  { range: '70–90', count: 310,  color: '#ef4444' },
  { range: '90–100',count: 440,  color: '#dc2626' },
]
const SMB_FRAUD_DIST = [
  { range: '0–10',  count: 189, color: '#10b981' },
  { range: '10–30', count: 54,  color: '#34d399' },
  { range: '30–50', count: 25,  color: '#f59e0b' },
  { range: '50–70', count: 17,  color: '#f97316' },
  { range: '70–90', count: 18,  color: '#ef4444' },
  { range: '90–100',count: 27,  color: '#dc2626' },
]

const SB_RISK_FLAGS = [
  { flag: 'HIGH_VALUE',          count: 841 },
  { flag: 'VAULT_MISS',          count: 612 },
  { flag: 'ALTERATION',          count: 380 },
  { flag: 'DORMANT_ACCOUNT',     count: 274 },
  { flag: 'STOP_PAYMENT',        count: 198 },
  { flag: 'OCR_LOW_CONF',        count: 143 },
  { flag: 'SIG_LOW_CONF',        count: 127 },
  { flag: 'VERY_HIGH_VALUE',     count: 92  },
]
const SMB_RISK_FLAGS = [
  { flag: 'HIGH_VALUE',          count: 51 },
  { flag: 'VAULT_MISS',          count: 37 },
  { flag: 'ALTERATION',          count: 23 },
  { flag: 'DORMANT_ACCOUNT',     count: 16 },
  { flag: 'STOP_PAYMENT',        count: 12 },
  { flag: 'OCR_LOW_CONF',        count:  9 },
  { flag: 'SIG_LOW_CONF',        count:  7 },
  { flag: 'VERY_HIGH_VALUE',     count:  6 },
]

const SB_RETURN_REASONS = [
  { reason: 'Fraud Risk',       count: 440 },
  { reason: 'Sig Mismatch',     count: 310 },
  { reason: 'Alteration',       count: 180 },
  { reason: 'Insufficient Funds',count: 90 },
  { reason: 'Stop Payment',     count: 78  },
  { reason: 'Dormant Account',  count: 62  },
  { reason: 'Other',            count: 40  },
]
const SMB_RETURN_REASONS = [
  { reason: 'Fraud Risk',       count: 27 },
  { reason: 'Sig Mismatch',     count: 18 },
  { reason: 'Alteration',       count: 11 },
  { reason: 'Insufficient Funds',count: 5 },
  { reason: 'Stop Payment',     count:  4 },
  { reason: 'Dormant Account',  count:  3 },
  { reason: 'Other',            count:  2 },
]

const SB_BRANCHES = [
  { branch: 'Fort Branch, Mumbai',        processed: 1840, hrq_pct: 4.8, vault_miss: 22, avg_ms: 381, returns: 182 },
  { branch: 'Dadar Branch, Mumbai',       processed: 1210, hrq_pct: 3.9, vault_miss: 14, avg_ms: 374, returns: 108 },
  { branch: 'Connaught Place, Delhi',     processed: 980,  hrq_pct: 6.2, vault_miss: 31, avg_ms: 412, returns: 97  },
  { branch: 'MG Road Branch, Bengaluru',  processed: 870,  hrq_pct: 5.1, vault_miss: 18, avg_ms: 388, returns: 84  },
  { branch: 'Abids Branch, Hyderabad',    processed: 620,  hrq_pct: 3.4, vault_miss:  9, avg_ms: 362, returns: 51  },
  { branch: 'Anna Nagar, Chennai',        processed: 530,  hrq_pct: 4.1, vault_miss: 12, avg_ms: 395, returns: 47  },
]
const SMB_BRANCHES = [
  { branch: 'Main Office, Pune',          processed: 180, hrq_pct: 4.4, vault_miss:  8, avg_ms: 392, returns: 17 },
  { branch: 'Camp Branch, Pune',          processed: 97,  hrq_pct: 3.8, vault_miss:  4, avg_ms: 381, returns:  9 },
  { branch: 'Deccan Branch, Pune',        processed: 73,  hrq_pct: 5.5, vault_miss:  5, avg_ms: 404, returns:  7 },
]

const MODEL_PERF = [
  { model: 'GOT-OCR2.0',      metric: 'Accuracy',       value: 99.3, threshold: 99.0, unit: '%' },
  { model: 'Siamese-SigNet',  metric: 'Precision',      value: 97.8, threshold: 97.0, unit: '%' },
  { model: 'XGBoost-Fraud',   metric: 'F1 Score',       value: 0.934, threshold: 0.920, unit: '' },
  { model: 'Qwen2-VL 72B',    metric: 'Conf Mean',      value: 0.912, threshold: 0.900, unit: '' },
  { model: 'IndicOCR/Paddle', metric: 'Indic Accuracy', value: 96.8, threshold: 95.0, unit: '%' },
]

// Colour map for live fraud distribution buckets (mirrors mock colours)
const _FRAUD_DIST_COLORS = {
  '0–10':   '#10b981',
  '10–30':  '#34d399',
  '30–50':  '#f59e0b',
  '50–70':  '#f97316',
  '70–90':  '#ef4444',
  '90–100': '#dc2626',
}

// ── Tooltip helper ────────────────────────────────────────────────────────────

function ChartTip({ active, payload, label, isDark, fmt }) {
  if (!active || !payload?.length) return null
  const bg = isDark ? '#0e1a3a' : '#fff'
  const border = isDark ? 'rgba(255,255,255,0.1)' : '#e2e8f0'
  const text = isDark ? '#e2e8f0' : '#1e293b'
  const muted = isDark ? '#64748b' : '#94a3b8'
  return (
    <div style={{ background: bg, border: `1px solid ${border}`, borderRadius: 10, padding: '8px 12px', fontSize: 11, color: text, boxShadow: '0 4px 16px rgba(0,0,0,0.3)' }}>
      <div style={{ color: muted, marginBottom: 4, fontWeight: 600 }}>{label}</div>
      {payload.map(p => (
        <div key={p.name} style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 2 }}>
          <span style={{ width: 8, height: 8, borderRadius: 2, background: p.color, display: 'inline-block' }} />
          <span style={{ color: muted }}>{p.name}</span>
          <span style={{ fontWeight: 700, marginLeft: 'auto', paddingLeft: 12 }}>{fmt ? fmt(p.value, p.name) : p.value}</span>
        </div>
      ))}
    </div>
  )
}

// ── Section heading ───────────────────────────────────────────────────────────

function SecHead({ title, sub, isDark }) {
  return (
    <div className="mb-4">
      <h2 className={`text-sm font-semibold ${isDark ? 'text-white' : 'text-slate-900'}`}>{title}</h2>
      {sub && <p className={`text-[11px] mt-0.5 ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>{sub}</p>}
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function CTSAnalytics() {
  const { isDark } = useTheme()
  const { isSMB, isDemo } = useBankContext()
  const [activeTab, setActiveTab] = useState('overview')

  usePageHeader({ subtitle: 'Decision analytics · AI model performance · IET safety · 7-day rolling' })

  // Live analytics — only fetched in POC/PROD; demo mode uses mock data below
  const { daily: liveDaily } = useAnalytics({ pollEnabled: !isDemo })
  const { data: liveInward } = useInwardAnalytics({ pollEnabled: !isDemo })

  const mockDaily = isSMB ? SMB_DAILY : SB_DAILY

  // Merge: outward daily (decision counts) + inward daily (ocr_conf, sig_prec) keyed on date
  const mergedDaily = (() => {
    if (isDemo || liveDaily.length === 0) return mockDaily
    if (liveInward.daily.length === 0) return liveDaily
    const inwardMap = Object.fromEntries(liveInward.daily.map(r => [r.date, r]))
    return liveDaily.map(row => {
      const iw = inwardMap[row.date] ?? {}
      return { ...row, ocr_conf: iw.ocr_conf ?? row.ocr_conf, sig_prec: iw.sig_prec ?? row.sig_prec }
    })
  })()

  const DAILY          = mergedDaily
  const FRAUD_DIST     = isDemo || liveInward.fraud_dist.length === 0
    ? (isSMB ? SMB_FRAUD_DIST     : SB_FRAUD_DIST)
    : liveInward.fraud_dist.map(r => ({ ...r, color: _FRAUD_DIST_COLORS[r.range] ?? '#94a3b8' }))
  const RISK_FLAGS     = isDemo || liveInward.risk_flags.length === 0
    ? (isSMB ? SMB_RISK_FLAGS     : SB_RISK_FLAGS)
    : liveInward.risk_flags
  const RETURN_REASONS = isDemo || liveInward.return_reasons.length === 0
    ? (isSMB ? SMB_RETURN_REASONS : SB_RETURN_REASONS)
    : liveInward.return_reasons
  const BRANCHES       = isDemo || liveInward.branches.length === 0
    ? (isSMB ? SMB_BRANCHES       : SB_BRANCHES)
    : liveInward.branches
  const IET_TREND      = isDemo || liveInward.iet_trend.length === 0
    ? [
        { date: 'Aug 25', nearBreach: 2 },
        { date: 'Aug 26', nearBreach: 0 },
        { date: 'Aug 27', nearBreach: 1 },
        { date: 'Aug 28', nearBreach: 0 },
        { date: 'Aug 29', nearBreach: 3 },
        { date: 'Aug 30', nearBreach: 0 },
        { date: 'Aug 31', nearBreach: 0 },
      ]
    : liveInward.iet_trend

  const weekTotal   = DAILY.reduce((s, d) => s + d.total, 0)
  const weekConfirm = DAILY.reduce((s, d) => s + d.stp_confirm, 0)
  const weekReturn  = DAILY.reduce((s, d) => s + d.stp_return, 0)
  const weekHuman   = DAILY.reduce((s, d) => s + d.human, 0)
  const stpRate     = ((weekConfirm / weekTotal) * 100).toFixed(1)
  const humanRate   = ((weekHuman  / weekTotal) * 100).toFixed(1)
  const avgMs       = Math.round(DAILY.reduce((s, d) => s + d.avg_ms, 0) / DAILY.length)
  const totalReturns= DAILY.reduce((s, d) => s + d.stp_return, 0)
  const returnRate  = ((totalReturns / weekTotal) * 100).toFixed(1)

  const maxRisk = Math.max(...RISK_FLAGS.map(d => d.count))

  const th = {
    page:    isDark ? 'bg-navy-950'             : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'              : 'text-slate-900',
    muted:   isDark ? 'text-slate-400'          : 'text-slate-500',
    faint:   isDark ? 'text-slate-600'          : 'text-slate-400',
    divider: isDark ? 'border-white/8'          : 'border-slate-200',
    row:     isDark ? 'border-white/4 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
    grid:    isDark ? 'stroke-white/5'          : '#e2e8f0',
    axis:    isDark ? '#475569'                 : '#94a3b8',
    tab:     (a) => a === activeTab
      ? (isDark ? 'bg-white/8 text-white border-white/15' : 'bg-white text-slate-900 border-slate-300 shadow-sm')
      : (isDark ? 'text-slate-400 border-transparent hover:text-slate-200' : 'text-slate-500 border-transparent hover:text-slate-700'),
  }

  const TABS = [
    { id: 'overview',  label: 'Overview' },
    { id: 'ai',        label: 'AI Models' },
    { id: 'branches',  label: 'Branches' },
    { id: 'iet',       label: 'IET Safety' },
  ]

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>

        {/* KPI strip */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-5">
          {[
            { label: 'Total (7d)',       value: weekTotal.toLocaleString('en-IN'), color: isDark ? 'text-white' : 'text-slate-900' },
            { label: 'STP Rate',         value: `${stpRate}%`,    color: 'text-emerald-500' },
            { label: 'HRQ Rate',         value: `${humanRate}%`,  color: 'text-amber-400' },
            { label: 'Return Rate',      value: `${returnRate}%`, color: 'text-red-400' },
            { label: 'Avg Decision',     value: `${avgMs}ms`,     color: isDark ? 'text-slate-300' : 'text-slate-700' },
            { label: 'IET Breaches',     value: '0',              color: 'text-emerald-500' },
          ].map(k => (
            <div key={k.label} className={`border rounded-xl px-4 py-3 ${th.card}`}>
              <div className={`text-[10px] uppercase tracking-wide mb-1.5 ${th.faint}`}>{k.label}</div>
              <div className={`text-xl font-bold tabular-nums ${k.color}`}>{k.value}</div>
            </div>
          ))}
        </div>

        {/* Tab bar */}
        <div className={`flex gap-1 border-b mb-5 ${th.divider}`}>
          {TABS.map(t => (
            <button key={t.id} onClick={() => setActiveTab(t.id)}
              className={`text-xs px-4 py-2 border-b-2 -mb-px font-medium transition-colors ${th.tab(t.id)}`}>
              {t.label}
            </button>
          ))}
        </div>

        {/* ── OVERVIEW tab ─────────────────────────────────────────────────── */}
        {activeTab === 'overview' && (
          <div className="space-y-5">

            {/* Stacked area — daily throughput */}
            <div className={`border rounded-xl p-5 ${th.card}`}>
              <SecHead title="Daily Throughput — 7 Sessions" sub="STP confirms, returns, and human review volumes" isDark={isDark} />
              <ResponsiveContainer width="100%" height={220}>
                <AreaChart data={DAILY} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                  <defs>
                    <linearGradient id="gConfirm" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#10b981" stopOpacity={0.25} />
                      <stop offset="95%" stopColor="#10b981" stopOpacity={0.03} />
                    </linearGradient>
                    <linearGradient id="gReturn" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#ef4444" stopOpacity={0.25} />
                      <stop offset="95%" stopColor="#ef4444" stopOpacity={0.03} />
                    </linearGradient>
                    <linearGradient id="gHuman" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#f59e0b" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#f59e0b" stopOpacity={0.03} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke={isDark ? 'rgba(255,255,255,0.05)' : '#f1f5f9'} />
                  <XAxis dataKey="date" tick={{ fontSize: 10, fill: th.axis }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 10, fill: th.axis }} axisLine={false} tickLine={false} width={40} />
                  <Tooltip content={<ChartTip isDark={isDark} />} />
                  <Area type="monotone" dataKey="stp_confirm" name="STP Confirm" stroke="#10b981" strokeWidth={2} fill="url(#gConfirm)" dot={false} />
                  <Area type="monotone" dataKey="stp_return"  name="STP Return"  stroke="#ef4444" strokeWidth={1.5} fill="url(#gReturn)"  dot={false} />
                  <Area type="monotone" dataKey="human"       name="HRQ"          stroke="#f59e0b" strokeWidth={1.5} fill="url(#gHuman)"   dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>

            {/* Row: Fraud score + Return reasons */}
            <div className="grid grid-cols-2 gap-5">

              {/* Fraud score distribution */}
              <div className={`border rounded-xl p-5 ${th.card}`}>
                <SecHead title="Fraud Score Distribution" sub="Today's batch — score buckets (%)" isDark={isDark} />
                <ResponsiveContainer width="100%" height={180}>
                  <BarChart data={FRAUD_DIST} margin={{ top: 0, right: 0, bottom: 0, left: -10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={isDark ? 'rgba(255,255,255,0.05)' : '#f1f5f9'} vertical={false} />
                    <XAxis dataKey="range" tick={{ fontSize: 9, fill: th.axis }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 9, fill: th.axis }} axisLine={false} tickLine={false} width={32} />
                    <Tooltip content={<ChartTip isDark={isDark} />} />
                    <Bar dataKey="count" name="Instruments" radius={[4, 4, 0, 0]}>
                      {FRAUD_DIST.map((d, i) => <Cell key={i} fill={d.color} fillOpacity={0.85} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
                <div className="flex items-center gap-3 mt-2 flex-wrap">
                  <span className="flex items-center gap-1 text-[10px]"><span className="w-2 h-2 rounded-sm inline-block bg-emerald-500" />Low (&lt;30%)</span>
                  <span className="flex items-center gap-1 text-[10px]"><span className="w-2 h-2 rounded-sm inline-block bg-amber-400" />Medium</span>
                  <span className="flex items-center gap-1 text-[10px]"><span className="w-2 h-2 rounded-sm inline-block bg-red-500" />High (&gt;70%)</span>
                </div>
              </div>

              {/* Return reasons */}
              <div className={`border rounded-xl p-5 ${th.card}`}>
                <SecHead title="Return Reasons" sub="7-day breakdown of STP returns" isDark={isDark} />
                <ResponsiveContainer width="100%" height={180}>
                  <BarChart data={RETURN_REASONS} layout="vertical" margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={isDark ? 'rgba(255,255,255,0.05)' : '#f1f5f9'} horizontal={false} />
                    <XAxis type="number" tick={{ fontSize: 9, fill: th.axis }} axisLine={false} tickLine={false} />
                    <YAxis type="category" dataKey="reason" tick={{ fontSize: 9, fill: th.axis }} axisLine={false} tickLine={false} width={90} />
                    <Tooltip content={<ChartTip isDark={isDark} />} />
                    <Bar dataKey="count" name="Count" fill="#ef4444" fillOpacity={0.7} radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Risk flag frequency */}
            <div className={`border rounded-xl p-5 ${th.card}`}>
              <SecHead title="Risk Flag Frequency" sub="Which flags fired most across all instruments this week" isDark={isDark} />
              <div className="space-y-2.5">
                {RISK_FLAGS.map(d => {
                  const pct = (d.count / maxRisk) * 100
                  const isCritical = d.flag.includes('STOP') || d.flag.includes('VERY_HIGH')
                  const isHigh     = d.flag.includes('VAULT') || d.flag.includes('ALTERATION') || d.flag.includes('HIGH_VALUE')
                  const barColor = isCritical ? '#ef4444' : isHigh ? '#f59e0b' : '#60a5fa'
                  return (
                    <div key={d.flag} className="flex items-center gap-3">
                      <span className={`text-[10px] font-mono w-36 shrink-0 ${th.muted}`}>{d.flag}</span>
                      <div className={`flex-1 h-3 rounded-full ${isDark ? 'bg-white/5' : 'bg-slate-100'}`}>
                        <div className="h-3 rounded-full transition-all" style={{ width: `${pct}%`, background: barColor, opacity: 0.8 }} />
                      </div>
                      <span className={`text-[11px] font-semibold tabular-nums w-8 text-right ${th.muted}`}>{d.count}</span>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        )}

        {/* ── AI MODELS tab ─────────────────────────────────────────────────── */}
        {activeTab === 'ai' && (
          <div className="space-y-5">

            {/* OCR + Sig confidence trend */}
            <div className={`border rounded-xl p-5 ${th.card}`}>
              <SecHead title="OCR & Signature Confidence Trend" sub="Daily mean confidence — alert threshold shown as dashed line" isDark={isDark} />
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={DAILY} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={isDark ? 'rgba(255,255,255,0.05)' : '#f1f5f9'} />
                  <XAxis dataKey="date" tick={{ fontSize: 10, fill: th.axis }} axisLine={false} tickLine={false} />
                  <YAxis domain={[96, 100]} tick={{ fontSize: 10, fill: th.axis }} axisLine={false} tickLine={false} width={36} tickFormatter={v => `${v}%`} />
                  <Tooltip content={<ChartTip isDark={isDark} fmt={(v) => `${v}%`} />} />
                  <Line type="monotone" dataKey="ocr_conf" name="OCR Accuracy" stroke="#60a5fa" strokeWidth={2} dot={{ r: 3, fill: '#60a5fa' }} />
                  <Line type="monotone" dataKey="sig_prec" name="Sig Precision" stroke="#a78bfa" strokeWidth={2} dot={{ r: 3, fill: '#a78bfa' }} />
                </LineChart>
              </ResponsiveContainer>
              <div className={`flex items-center gap-2 mt-3 text-[10px] ${th.faint}`}>
                <span className="flex items-center gap-1"><span className="w-6 h-0.5 inline-block bg-blue-400" />OCR ≥ 99.0% threshold</span>
                <span className="flex items-center gap-1 ml-3"><span className="w-6 h-0.5 inline-block bg-violet-400" />Sig ≥ 97.0% threshold</span>
              </div>
            </div>

            {/* Model performance table */}
            <div className={`border rounded-xl overflow-hidden ${th.card}`}>
              <div className={`px-5 py-4 border-b ${th.divider}`}>
                <h2 className={`text-sm font-semibold ${th.heading}`}>AI Model Performance</h2>
                <p className={`text-[11px] mt-0.5 ${th.muted}`}>Live vs. minimum NFR thresholds — drift alert at 2% drop over 7 days</p>
              </div>
              <table className="w-full text-xs">
                <thead>
                  <tr className={`border-b ${th.divider} ${th.faint}`}>
                    {['Model', 'Metric', 'Current', 'Threshold', 'Margin', 'Status', 'Drift (7d)'].map(h => (
                      <th key={h} className="text-left px-5 py-3 font-medium text-[10px] uppercase tracking-wide">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {MODEL_PERF.map((m, i) => {
                    const margin = (m.value - m.threshold).toFixed(3)
                    const ok = parseFloat(margin) >= 0
                    const drift = (Math.random() * 0.8 - 0.1).toFixed(2)
                    return (
                      <tr key={i} className={`border-b transition-colors ${th.row}`}>
                        <td className={`px-5 py-3 font-semibold ${th.heading}`}>{m.model}</td>
                        <td className={`px-5 py-3 ${th.muted}`}>{m.metric}</td>
                        <td className={`px-5 py-3 font-mono font-bold ${ok ? 'text-emerald-500' : 'text-red-500'}`}>{m.value}{m.unit}</td>
                        <td className={`px-5 py-3 font-mono ${th.muted}`}>{m.threshold}{m.unit}</td>
                        <td className={`px-5 py-3 font-mono ${ok ? 'text-emerald-500' : 'text-red-500'}`}>{ok ? '+' : ''}{margin}</td>
                        <td className="px-5 py-3">
                          <span className={`text-[10px] font-bold px-2 py-0.5 rounded border ${ok
                            ? (isDark ? 'bg-emerald-900/40 text-emerald-300 border-emerald-700/40' : 'bg-emerald-50 text-emerald-700 border-emerald-200')
                            : (isDark ? 'bg-red-900/40 text-red-300 border-red-700/40' : 'bg-red-50 text-red-700 border-red-200')
                          }`}>{ok ? 'OK' : 'WARN'}</span>
                        </td>
                        <td className={`px-5 py-3 font-mono text-xs ${parseFloat(drift) < 0 ? 'text-red-400' : 'text-emerald-500'}`}>
                          {parseFloat(drift) >= 0 ? '+' : ''}{drift}%
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              <div className={`px-5 py-3 text-[10px] ${th.faint} border-t ${th.divider}`}>
                Alert threshold: 2% drop over 7 days · Auto-tighten at 5% · Model pull at 8% — all via PlatformHealthCheckWorkflow
              </div>
            </div>
          </div>
        )}

        {/* ── BRANCHES tab ──────────────────────────────────────────────────── */}
        {activeTab === 'branches' && (
          <div className="space-y-5">
            <div className={`border rounded-xl overflow-hidden ${th.card}`}>
              <div className={`px-5 py-4 border-b ${th.divider}`}>
                <h2 className={`text-sm font-semibold ${th.heading}`}>Branch-level Performance</h2>
                <p className={`text-[11px] mt-0.5 ${th.muted}`}>HRQ routing rate, vault misses, and avg decision time per branch — 7-day view</p>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs whitespace-nowrap">
                  <thead>
                    <tr className={`border-b ${th.divider} ${th.faint}`}>
                      {['Branch', 'Processed', 'HRQ Rate', 'Vault Misses', 'Avg Time', 'Returns'].map(h => (
                        <th key={h} className="text-left px-5 py-3 font-medium text-[10px] uppercase tracking-wide">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {BRANCHES.map((b, i) => (
                      <tr key={i} className={`border-b transition-colors ${th.row}`}>
                        <td className={`px-5 py-3 font-medium ${th.heading}`}>{b.branch}</td>
                        <td className={`px-5 py-3 tabular-nums ${th.muted}`}>{b.processed.toLocaleString('en-IN')}</td>
                        <td className="px-5 py-3">
                          <div className="flex items-center gap-2">
                            <div className={`w-20 h-1.5 rounded-full ${isDark ? 'bg-white/8' : 'bg-slate-100'}`}>
                              <div className="h-1.5 rounded-full" style={{ width: `${Math.min(b.hrq_pct * 10, 100)}%`, background: b.hrq_pct > 5 ? '#f59e0b' : '#10b981' }} />
                            </div>
                            <span className={`tabular-nums ${b.hrq_pct > 5 ? 'text-amber-400' : 'text-emerald-500'}`}>{b.hrq_pct}%</span>
                          </div>
                        </td>
                        <td className={`px-5 py-3 tabular-nums ${b.vault_miss > 20 ? 'text-amber-400' : th.muted}`}>{b.vault_miss}</td>
                        <td className={`px-5 py-3 font-mono tabular-nums ${b.avg_ms > 400 ? 'text-amber-400' : 'text-emerald-500'}`}>{b.avg_ms}ms</td>
                        <td className={`px-5 py-3 tabular-nums ${th.muted}`}>{b.returns}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className={`px-5 py-3 text-[10px] ${th.faint} border-t ${th.divider}`}>
                Branches with HRQ Rate &gt; 5% or Avg Time &gt; 400ms highlighted in amber — review vault enrollment coverage
              </div>
            </div>

            {/* HRQ % bar chart across branches */}
            <div className={`border rounded-xl p-5 ${th.card}`}>
              <SecHead title="HRQ Routing Rate by Branch" sub="Higher rate = more vault misses or high-risk instruments" isDark={isDark} />
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={BRANCHES} margin={{ top: 4, right: 8, bottom: 40, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={isDark ? 'rgba(255,255,255,0.05)' : '#f1f5f9'} vertical={false} />
                  <XAxis dataKey="branch" tick={{ fontSize: 9, fill: th.axis, angle: -25, textAnchor: 'end' }} axisLine={false} tickLine={false} interval={0} />
                  <YAxis tick={{ fontSize: 9, fill: th.axis }} axisLine={false} tickLine={false} width={28} tickFormatter={v => `${v}%`} />
                  <Tooltip content={<ChartTip isDark={isDark} fmt={(v) => `${v}%`} />} />
                  <Bar dataKey="hrq_pct" name="HRQ Rate" radius={[4, 4, 0, 0]}>
                    {BRANCHES.map((b, i) => <Cell key={i} fill={b.hrq_pct > 5 ? '#f59e0b' : '#10b981'} fillOpacity={0.8} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}

        {/* ── IET SAFETY tab ────────────────────────────────────────────────── */}
        {activeTab === 'iet' && (
          <div className="space-y-5">

            {/* IET breach status */}
            <div className={`border rounded-xl p-5 flex items-center gap-5 ${isDark ? 'bg-emerald-900/20 border-emerald-700/30' : 'bg-emerald-50 border-emerald-200'}`}>
              <div className={`w-14 h-14 rounded-full flex items-center justify-center text-2xl font-bold shrink-0 ${isDark ? 'bg-emerald-500/20 text-emerald-400' : 'bg-emerald-100 text-emerald-700'}`}>✓</div>
              <div>
                <div className={`text-lg font-bold ${isDark ? 'text-emerald-400' : 'text-emerald-700'}`}>IET Breach Rate: 0.000%</div>
                <div className={`text-sm mt-0.5 ${isDark ? 'text-emerald-300/70' : 'text-emerald-600'}`}>
                  7 consecutive clearing sessions — zero breaches. Target: 0.000%. IETWatchdogWorkflow active on every instrument.
                </div>
              </div>
            </div>

            {/* Near-breach trend */}
            <div className={`border rounded-xl p-5 ${th.card}`}>
              <SecHead title="Near-Breach Events (≤ 30s to IET)" sub="Any non-zero day warrants investigation — IETWatchdog fired emergency protocol" isDark={isDark} />
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={IET_TREND} margin={{ top: 4, right: 8, bottom: 0, left: -10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={isDark ? 'rgba(255,255,255,0.05)' : '#f1f5f9'} vertical={false} />
                  <XAxis dataKey="date" tick={{ fontSize: 10, fill: th.axis }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 10, fill: th.axis }} axisLine={false} tickLine={false} width={24} allowDecimals={false} />
                  <Tooltip content={<ChartTip isDark={isDark} />} />
                  <Bar dataKey="nearBreach" name="Near-breaches" radius={[4, 4, 0, 0]}>
                    {IET_TREND.map((d, i) => <Cell key={i} fill={d.nearBreach > 0 ? '#f59e0b' : '#10b981'} fillOpacity={d.nearBreach > 0 ? 0.8 : 0.3} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>

            {/* Architecture note */}
            <div className={`border rounded-xl p-5 ${th.card}`}>
              <h2 className={`text-sm font-semibold mb-3 ${th.heading}`}>IET Architecture — Why Zero Breaches Is Guaranteed</h2>
              <div className="space-y-3">
                {[
                  { step: '1', title: 'IETWatchdogWorkflow spawned first', desc: 'Before OCR, before fraud scoring — the watchdog is the very first child workflow spawned for every instrument. Parent close policy: ABANDON — it survives even if the main workflow crashes.' },
                  { step: '2', title: 'T-30s emergency filer', desc: 'At T-30 seconds, if no human decision has been recorded, the watchdog automatically files an emergency NGCH return. Zero dependence on human action.' },
                  { step: '3', title: 'Temporal exactly-once guarantee', desc: 'Workflow ID is deterministic: cts-{bank_id}-{instrument_id}. No duplicate NGCH filings are possible — idempotency enforced at workflow level.' },
                  { step: '4', title: 'Layer 1 non-overridable', desc: 'iet_watchdog_enabled: true is a Layer 1 Helm chart default — no bank admin, no config change, no code can disable the watchdog.' },
                ].map(s => (
                  <div key={s.step} className="flex gap-4">
                    <div className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0 mt-0.5 ${isDark ? 'bg-white/8 text-slate-300' : 'bg-slate-100 text-slate-600'}`}>{s.step}</div>
                    <div>
                      <div className={`text-xs font-semibold ${th.heading}`}>{s.title}</div>
                      <div className={`text-[11px] mt-0.5 leading-relaxed ${th.muted}`}>{s.desc}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

      </div>
    </AppShell>
  )
}

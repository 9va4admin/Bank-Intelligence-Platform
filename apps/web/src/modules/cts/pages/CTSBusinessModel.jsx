import AppShell from '../../../shared/layout/AppShell'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useState, useMemo } from 'react'
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, Cell,
} from 'recharts'

// ─── Formatting helpers ────────────────────────────────────────────────────

function fmtRs(lakhs) {
  if (lakhs === null || lakhs === undefined || isNaN(lakhs)) return '—'
  if (Math.abs(lakhs) >= 100) return `₹${(lakhs / 100).toFixed(2)}Cr`
  if (Math.abs(lakhs) >= 1) return `₹${lakhs.toFixed(1)}L`
  const thou = lakhs * 100000
  return `₹${Math.round(thou).toLocaleString('en-IN')}`
}

function fmtVol(lakhs) {
  return `${lakhs.toLocaleString('en-IN')}L`
}

// ─── Core model ────────────────────────────────────────────────────────────

const TIER_DEFAULTS = {
  small:      200,
  medium:     800,
  large:      2000,
  enterprise: 6000,
}

const FIXED_COST_BASE = 124  // ₹ lakhs / year / bank
const VAR_COST_PER_CHEQUE_RS = 0.08
const IMPL_FEE = 25
const MANAGED_AI_RETAINER = 18
const SUPPORT_RETAINER = 12

function calcRevenue(volumeLakhs, pricingModel, year) {
  const vol = volumeLakhs * 100000
  const yoyFactor = Math.pow(1.2, year - 1)
  const adjVol = vol * yoyFactor

  let perChequeRevLakhs = 0
  let platformRevLakhs = 0

  if (pricingModel === 'saas') {
    const rate = year === 1 ? 1.20 : 1.10
    perChequeRevLakhs = (adjVol * rate) / 100000
  } else if (pricingModel === 'licence') {
    platformRevLakhs = 75
    const excessVol = Math.max(0, adjVol - 5000000)
    perChequeRevLakhs = (excessVol * 0.30) / 100000
  } else {
    platformRevLakhs = 40
    perChequeRevLakhs = (adjVol * 0.80) / 100000
  }

  const implAmortised = IMPL_FEE / 3
  const managedAI = MANAGED_AI_RETAINER
  const support = year >= 2 ? SUPPORT_RETAINER : 0
  const total = perChequeRevLakhs + platformRevLakhs + implAmortised + managedAI + support

  return { perChequeRevLakhs, platformRevLakhs, implAmortised, managedAI, support, total, adjVol }
}

function calcCosts(volumeLakhs, year) {
  const vol = volumeLakhs * 100000 * Math.pow(1.2, year - 1)
  const varCostLakhs = (vol * VAR_COST_PER_CHEQUE_RS) / 100000
  const totalFixed = FIXED_COST_BASE
  return {
    gpu: 42,
    engineering: 36,
    k8s: 22,
    modelOps: 15,
    compliance: 9,
    variable: varCostLakhs,
    total: totalFixed + varCostLakhs,
  }
}

function calcModel(volumeLakhs, pricingModel, year) {
  const rev = calcRevenue(volumeLakhs, pricingModel, year)
  const cost = calcCosts(volumeLakhs, year)
  const grossProfit = rev.total - cost.total
  const grossMarginPct = rev.total > 0 ? (grossProfit / rev.total) * 100 : 0
  const fixedCostBase = FIXED_COST_BASE
  const implFee = IMPL_FEE

  // Break-even volume (cheques/year) at per-cheque rate
  const perChequeRate = pricingModel === 'saas' ? (year === 1 ? 1.20 : 1.10)
    : pricingModel === 'licence' ? 0.30 : 0.80
  const marginalProfit = perChequeRate - VAR_COST_PER_CHEQUE_RS
  const fixedRevenue = rev.platformRevLakhs + rev.implAmortised + rev.managedAI + rev.support
  const breakEvenCheques = marginalProfit > 0
    ? ((fixedCostBase - fixedRevenue * 100000) / marginalProfit)
    : Infinity
  const breakEvenLakhs = breakEvenCheques / 100000

  // Bank ROI
  const avgChequeValue = 45000
  const manualCostPerCheque = 8
  const adjVol = volumeLakhs * 100000 * Math.pow(1.2, year - 1)
  const stpRate = 0.85
  const ietBreachRate = 0.0005
  const ietSavingsLakhs = (adjVol * ietBreachRate * avgChequeValue * 0.002) / 100000
  const fteSavingsLakhs = (adjVol * stpRate * manualCostPerCheque) / 100000
  const fraudSavingsLakhs = (adjVol * 0.0023 * avgChequeValue * 0.015) / 100000
  const floatSavingsLakhs = (adjVol * 0.00001 * avgChequeValue) / 100000
  const auditSavingsLakhs = 8
  const totalBankSaves = ietSavingsLakhs + fteSavingsLakhs + fraudSavingsLakhs + floatSavingsLakhs + auditSavingsLakhs

  // ARR = annual recurring (excl. one-time)
  const arr = rev.total - rev.implAmortised

  return {
    arr, implFee, rev, cost, grossProfit, grossMarginPct, breakEvenLakhs,
    ietSavingsLakhs, fteSavingsLakhs, fraudSavingsLakhs, floatSavingsLakhs,
    auditSavingsLakhs, totalBankSaves,
    paybackMonths: arr > 0 ? Math.max(1, Math.round((implFee / (arr / 12)))) : 99,
  }
}

// ─── Sensitivity table ─────────────────────────────────────────────────────

const SENS_VOLUMES = [100, 500, 1000, 2000]
const SENS_RATES = [0.80, 1.20, 1.50, 2.00]

function calcSensitivity(rate, vol) {
  const revenue = (vol * 100000 * rate) / 100000 + MANAGED_AI_RETAINER + SUPPORT_RETAINER
  const cost = FIXED_COST_BASE + (vol * 100000 * VAR_COST_PER_CHEQUE_RS) / 100000
  return revenue - cost
}

// ─── Colour helpers ─────────────────────────────────────────────────────────

const CHART_COLORS = {
  revenue: '#34d399',
  cost:    '#f59e0b',
  profit:  '#818cf8',
  infra:   '#f87171',
  platform:'#60a5fa',
  services:'#a78bfa',
}

const COST_SLICES = [
  { label: 'GPU Infra (A100s)', pct: 35, color: '#f87171', lakhs: 42 },
  { label: 'Engineering & Support', pct: 28, color: '#f59e0b', lakhs: 36 },
  { label: 'Kubernetes + Storage', pct: 18, color: '#60a5fa', lakhs: 22 },
  { label: 'AI Model Ops', pct: 12, color: '#a78bfa', lakhs: 15 },
  { label: 'Compliance Infra', pct: 7, color: '#34d399', lakhs: 9 },
]

// ─── Sub-components ────────────────────────────────────────────────────────

function KpiCard({ label, value, sub, color, isDark }) {
  const cardBg = isDark ? 'bg-navy-900 border border-white/8' : 'bg-white border border-slate-200'
  const labelCls = isDark ? 'text-slate-400' : 'text-slate-500'
  const subCls = isDark ? 'text-slate-500' : 'text-slate-400'
  return (
    <div className={`${cardBg} rounded-xl p-4 flex flex-col gap-1`}>
      <span className={`text-xs font-medium uppercase tracking-wide ${labelCls}`}>{label}</span>
      <span className={`text-2xl font-bold ${color}`}>{value}</span>
      {sub && <span className={`text-xs ${subCls}`}>{sub}</span>}
    </div>
  )
}

function PillTabs({ options, value, onChange, isDark }) {
  return (
    <div className={`flex rounded-lg p-0.5 gap-0.5 ${isDark ? 'bg-white/5' : 'bg-slate-100'}`}>
      {options.map(o => {
        const active = o.value === value
        return (
          <button
            key={o.value}
            onClick={() => onChange(o.value)}
            className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-all ${
              active
                ? isDark ? 'bg-amber-500 text-navy-950' : 'bg-amber-500 text-white'
                : isDark ? 'text-slate-400 hover:text-slate-200' : 'text-slate-500 hover:text-slate-700'
            }`}
          >
            {o.label}
          </button>
        )
      })}
    </div>
  )
}

function SectionHeader({ title, isDark }) {
  return (
    <div className={`text-xs font-semibold uppercase tracking-widest mb-3 ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>
      {title}
    </div>
  )
}

// ─── Main component ────────────────────────────────────────────────────────

export default function CTSBusinessModel() {
  const { isDark } = useTheme()
  usePageHeader({ title: 'CTS Business Model', subtitle: 'Cost · Revenue · Unit Economics' })

  const [tier, setTier] = useState('medium')
  const [volumeLakhs, setVolumeLakhs] = useState(800)
  const [pricingModel, setPricingModel] = useState('saas')
  const [year, setYear] = useState(1)

  const th = {
    page:    isDark ? 'bg-[#020817]'             : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'               : 'text-slate-900',
    body:    isDark ? 'text-slate-300'           : 'text-slate-700',
    muted:   isDark ? 'text-slate-400'           : 'text-slate-500',
    faint:   isDark ? 'text-slate-600'           : 'text-slate-400',
    divider: isDark ? 'border-white/8'           : 'border-slate-200',
    row:     isDark ? 'border-white/4 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
    input:   isDark ? 'bg-white/5 border-white/10 text-white' : 'bg-white border-slate-300 text-slate-900',
    strip:   isDark ? 'bg-navy-900/60 border-white/8' : 'bg-white border-slate-200',
    thead:   isDark ? 'bg-white/4 text-slate-400' : 'bg-slate-50 text-slate-500',
  }

  const model = useMemo(
    () => calcModel(volumeLakhs, pricingModel, year),
    [volumeLakhs, pricingModel, year]
  )

  const handleTierChange = (t) => {
    setTier(t)
    setVolumeLakhs(TIER_DEFAULTS[t])
  }

  // 3-year projection data
  const projData = [1, 2, 3].map(y => {
    const r = calcRevenue(volumeLakhs, pricingModel, y)
    return {
      name: `Year ${y}`,
      'Per-Cheque': parseFloat(r.perChequeRevLakhs.toFixed(1)),
      Platform:     parseFloat(r.platformRevLakhs.toFixed(1)),
      Services:     parseFloat((r.managedAI + r.support + r.implAmortised).toFixed(1)),
    }
  })

  // Unit economics per 1000 cheques
  const revPer1k = ((model.rev.total / (volumeLakhs * 100000 * Math.pow(1.2, year - 1))) * 1000)
  const infraPer1k = ((model.cost.gpu + model.cost.k8s) / (volumeLakhs * 100000 * Math.pow(1.2, year - 1)) * 100000 / 100000 * 1000) * (100000 / 100000)
  // simpler: cost per 1k
  const adjVol = volumeLakhs * 100000 * Math.pow(1.2, year - 1)
  const infraC = ((42 + 22) / adjVol) * 1000 * 100000
  const aiC    = (15 / adjVol) * 1000 * 100000
  const teamC  = ((36 + 9) / adjVol) * 1000 * 100000
  const varC   = VAR_COST_PER_CHEQUE_RS * 1000
  const revU   = (model.rev.total / adjVol) * 1000 * 100000
  const profU  = revU - infraC - aiC - teamC - varC

  const unitData = [
    { name: 'Revenue /1k', value: parseFloat(revU.toFixed(2)), fill: CHART_COLORS.revenue },
    { name: 'Infra Cost', value: -parseFloat(infraC.toFixed(2)), fill: CHART_COLORS.infra },
    { name: 'AI Inference', value: -parseFloat(aiC.toFixed(2)), fill: '#fb923c' },
    { name: 'Team Alloc', value: -parseFloat(teamC.toFixed(2)), fill: '#ef4444' },
    { name: 'Gross Profit', value: parseFloat(profU.toFixed(2)), fill: CHART_COLORS.profit },
  ]

  const marginColor = model.grossMarginPct >= 70 ? 'text-emerald-400'
    : model.grossMarginPct >= 50 ? 'text-amber-400' : 'text-red-400'

  const tooltipStyle = {
    backgroundColor: isDark ? '#0f172a' : '#ffffff',
    border: `1px solid ${isDark ? 'rgba(255,255,255,0.1)' : '#e2e8f0'}`,
    borderRadius: 8,
    color: isDark ? '#e2e8f0' : '#1e293b',
    fontSize: 12,
  }

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5 space-y-5`}>

        {/* ── Configurator Strip ── */}
        <div className={`${th.strip} border rounded-xl px-5 py-4 flex flex-wrap items-center gap-6`}>
          <div className="flex flex-col gap-1.5">
            <span className={`text-xs font-semibold uppercase tracking-wide ${th.muted}`}>Bank Tier</span>
            <PillTabs
              value={tier}
              onChange={handleTierChange}
              isDark={isDark}
              options={[
                { label: 'Small (<5M)', value: 'small' },
                { label: 'Medium (5–20M)', value: 'medium' },
                { label: 'Large (>20M)', value: 'large' },
                { label: 'Enterprise (>50M)', value: 'enterprise' },
              ]}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <span className={`text-xs font-semibold uppercase tracking-wide ${th.muted}`}>Volume (Lakhs/yr)</span>
            <input
              type="number"
              value={volumeLakhs}
              min={10}
              max={10000}
              onChange={e => setVolumeLakhs(Math.max(10, Number(e.target.value)))}
              className={`${th.input} border rounded-lg px-3 py-1.5 text-sm font-mono w-28 focus:outline-none`}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <span className={`text-xs font-semibold uppercase tracking-wide ${th.muted}`}>Pricing Model</span>
            <PillTabs
              value={pricingModel}
              onChange={setPricingModel}
              isDark={isDark}
              options={[
                { label: 'Per-Cheque SaaS', value: 'saas' },
                { label: 'Platform Licence', value: 'licence' },
                { label: 'Hybrid', value: 'hybrid' },
              ]}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <span className={`text-xs font-semibold uppercase tracking-wide ${th.muted}`}>Projection Year</span>
            <div className="flex items-center gap-3">
              <input
                type="range" min={1} max={3} step={1} value={year}
                onChange={e => setYear(Number(e.target.value))}
                className="w-24 accent-amber-500"
              />
              <span className={`text-sm font-bold ${th.heading}`}>Year {year}</span>
            </div>
          </div>

          <div className={`ml-auto text-xs ${th.faint} hidden xl:block`}>
            Volume: <span className="text-amber-400 font-semibold">{fmtVol(volumeLakhs)}</span> cheques/yr
            {year > 1 && <span className="ml-2">(YoY +20% → <span className="text-emerald-400 font-semibold">{fmtVol(parseFloat((volumeLakhs * Math.pow(1.2, year - 1)).toFixed(0)))}</span> by Yr{year})</span>}
          </div>
        </div>

        {/* ── KPI Row ── */}
        <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-5 gap-4">
          <KpiCard
            label="ARR" isDark={isDark}
            value={fmtRs(model.arr)} color="text-emerald-400"
            sub="Annual recurring revenue"
          />
          <KpiCard
            label="Impl. Fee (1-time)" isDark={isDark}
            value={fmtRs(IMPL_FEE)} color="text-blue-400"
            sub={`÷3 = ${fmtRs(IMPL_FEE / 3)}/yr amortised`}
          />
          <KpiCard
            label="Total Cost" isDark={isDark}
            value={fmtRs(model.cost.total)} color="text-amber-400"
            sub={`Fixed ${fmtRs(FIXED_COST_BASE)} + Var ${fmtRs(model.cost.variable)}`}
          />
          <KpiCard
            label="Gross Margin" isDark={isDark}
            value={`${model.grossMarginPct.toFixed(1)}%`} color={marginColor}
            sub={`Profit ${fmtRs(model.grossProfit)}`}
          />
          <KpiCard
            label="Break-even Vol" isDark={isDark}
            value={model.breakEvenLakhs > 0 && isFinite(model.breakEvenLakhs) ? fmtVol(parseFloat(model.breakEvenLakhs.toFixed(0))) : '—'}
            color="text-violet-400"
            sub="Cheques/yr to cover costs"
          />
        </div>

        {/* ── Main Two-Column Layout ── */}
        <div className="grid grid-cols-1 xl:grid-cols-[55%_45%] gap-5">

          {/* ── LEFT COLUMN ── */}
          <div className="space-y-5">

            {/* 3a. Revenue Breakdown Table */}
            <div className={`${th.card} border rounded-xl p-5`}>
              <SectionHeader title={`Revenue Streams — Year ${year}`} isDark={isDark} />
              <table className="w-full text-xs">
                <thead>
                  <tr className={`${th.thead} text-left`}>
                    {['Stream', 'Unit', 'Rate', 'Volume', '₹ Lakhs', '% Mix'].map(h => (
                      <th key={h} className="pb-2 pr-3 font-semibold uppercase tracking-wide">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {[
                    pricingModel !== 'licence' && {
                      stream: 'Per-Cheque Processing',
                      unit: 'per cheque',
                      rate: `₹${pricingModel === 'saas' ? (year === 1 ? '1.20' : '1.10') : '0.80'}`,
                      vol: fmtVol(parseFloat((volumeLakhs * Math.pow(1.2, year - 1)).toFixed(0))),
                      amt: model.rev.perChequeRevLakhs,
                      mix: model.rev.total > 0 ? (model.rev.perChequeRevLakhs / model.rev.total * 100).toFixed(0) : 0,
                      color: 'text-emerald-400',
                    },
                    (pricingModel === 'licence' || pricingModel === 'hybrid') && {
                      stream: 'Platform Licence',
                      unit: 'per year flat',
                      rate: pricingModel === 'licence' ? '₹75L/yr' : '₹40L/yr',
                      vol: '1 licence',
                      amt: model.rev.platformRevLakhs,
                      mix: model.rev.total > 0 ? (model.rev.platformRevLakhs / model.rev.total * 100).toFixed(0) : 0,
                      color: 'text-blue-400',
                    },
                    {
                      stream: 'Implementation & Onboarding',
                      unit: 'one-time ÷3',
                      rate: `₹${IMPL_FEE}L total`,
                      vol: 'amortised',
                      amt: model.rev.implAmortised,
                      mix: model.rev.total > 0 ? (model.rev.implAmortised / model.rev.total * 100).toFixed(0) : 0,
                      color: 'text-sky-400',
                    },
                    {
                      stream: 'Managed AI Services',
                      unit: 'annual retainer',
                      rate: `₹${MANAGED_AI_RETAINER}L/yr`,
                      vol: '1 retainer',
                      amt: model.rev.managedAI,
                      mix: model.rev.total > 0 ? (model.rev.managedAI / model.rev.total * 100).toFixed(0) : 0,
                      color: 'text-violet-400',
                    },
                    year >= 2 && {
                      stream: 'Support & SLA (Yr 2+)',
                      unit: 'annual retainer',
                      rate: `₹${SUPPORT_RETAINER}L/yr`,
                      vol: '1 retainer',
                      amt: model.rev.support,
                      mix: model.rev.total > 0 ? (model.rev.support / model.rev.total * 100).toFixed(0) : 0,
                      color: 'text-amber-400',
                    },
                  ].filter(Boolean).map((r, i) => (
                    <tr key={i} className={`border-t ${th.row}`}>
                      <td className={`py-2 pr-3 ${th.body} font-medium`}>{r.stream}</td>
                      <td className={`py-2 pr-3 ${th.muted}`}>{r.unit}</td>
                      <td className={`py-2 pr-3 ${th.muted} font-mono`}>{r.rate}</td>
                      <td className={`py-2 pr-3 ${th.muted}`}>{r.vol}</td>
                      <td className={`py-2 pr-3 ${r.color} font-semibold font-mono`}>{fmtRs(r.amt)}</td>
                      <td className={`py-2 ${th.faint}`}>{r.mix}%</td>
                    </tr>
                  ))}
                  <tr className={`border-t-2 ${isDark ? 'border-white/20' : 'border-slate-300'} font-bold`}>
                    <td colSpan={4} className={`py-2 pr-3 ${th.heading}`}>Total Revenue</td>
                    <td className="py-2 pr-3 text-emerald-400 font-mono">{fmtRs(model.rev.total)}</td>
                    <td className={`py-2 ${th.muted}`}>100%</td>
                  </tr>
                </tbody>
              </table>
            </div>

            {/* 3b. 3-Year Revenue Projection */}
            <div className={`${th.card} border rounded-xl p-5`}>
              <SectionHeader title="3-Year Revenue Projection (20% YoY Volume Growth)" isDark={isDark} />
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={projData} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                  <defs>
                    {[
                      ['rev', CHART_COLORS.revenue],
                      ['plat', CHART_COLORS.platform],
                      ['svc', CHART_COLORS.services],
                    ].map(([id, color]) => (
                      <linearGradient key={id} id={`grad-${id}`} x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor={color} stopOpacity={0.3} />
                        <stop offset="95%" stopColor={color} stopOpacity={0.05} />
                      </linearGradient>
                    ))}
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke={isDark ? 'rgba(255,255,255,0.06)' : '#f1f5f9'} />
                  <XAxis dataKey="name" tick={{ fill: isDark ? '#94a3b8' : '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: isDark ? '#94a3b8' : '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={v => `₹${v}L`} width={55} />
                  <Tooltip contentStyle={tooltipStyle} formatter={(v, n) => [`₹${v}L`, n]} />
                  <Legend wrapperStyle={{ fontSize: 11, color: isDark ? '#94a3b8' : '#64748b' }} />
                  <Area type="monotone" dataKey="Per-Cheque" stackId="1" stroke={CHART_COLORS.revenue} fill={`url(#grad-rev)`} strokeWidth={2} />
                  <Area type="monotone" dataKey="Platform" stackId="1" stroke={CHART_COLORS.platform} fill={`url(#grad-plat)`} strokeWidth={2} />
                  <Area type="monotone" dataKey="Services" stackId="1" stroke={CHART_COLORS.services} fill={`url(#grad-svc)`} strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>

            {/* 3c. Unit Economics */}
            <div className={`${th.card} border rounded-xl p-5`}>
              <SectionHeader title="Unit Economics — Per 1,000 Cheques Processed (₹)" isDark={isDark} />
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={unitData} layout="vertical" margin={{ top: 0, right: 30, left: 90, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke={isDark ? 'rgba(255,255,255,0.06)' : '#f1f5f9'} />
                  <XAxis type="number" tick={{ fill: isDark ? '#94a3b8' : '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={v => `₹${v}`} />
                  <YAxis type="category" dataKey="name" tick={{ fill: isDark ? '#cbd5e1' : '#475569', fontSize: 11 }} axisLine={false} tickLine={false} width={85} />
                  <Tooltip contentStyle={tooltipStyle} formatter={v => [`₹${Math.abs(v).toFixed(2)}`, 'per 1k cheques']} />
                  <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                    {unitData.map((entry, i) => <Cell key={i} fill={entry.fill} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* ── RIGHT COLUMN ── */}
          <div className="space-y-5">

            {/* 3d. Cost Structure */}
            <div className={`${th.card} border rounded-xl p-5`}>
              <SectionHeader title={`Cost Structure — ${fmtRs(model.cost.total)}/yr Total`} isDark={isDark} />
              <div className="space-y-2.5 mb-4">
                {COST_SLICES.map(s => {
                  const varPct = s.label === 'AI Model Ops' ? (model.cost.variable / model.cost.total * 100) : 0
                  const effectivePct = varPct > 0 ? varPct + s.pct : s.pct
                  return (
                    <div key={s.label}>
                      <div className="flex justify-between items-center mb-1">
                        <span className={`text-xs font-medium ${th.body}`}>{s.label}</span>
                        <div className="flex items-center gap-2">
                          <span className={`text-xs font-mono ${th.muted}`}>{fmtRs(s.lakhs + (s.label === 'AI Model Ops' ? model.cost.variable : 0))}</span>
                          <span className="text-xs font-semibold" style={{ color: s.color }}>{s.pct}%</span>
                        </div>
                      </div>
                      <div className={`w-full h-2 rounded-full ${isDark ? 'bg-white/5' : 'bg-slate-100'}`}>
                        <div className="h-2 rounded-full transition-all" style={{ width: `${s.pct}%`, backgroundColor: s.color }} />
                      </div>
                    </div>
                  )
                })}
              </div>
              <div className={`pt-3 border-t ${th.divider} flex items-center justify-between`}>
                <span className={`text-xs ${th.muted}`}>Variable (AI inference compute)</span>
                <span className="text-xs font-semibold text-orange-400 font-mono">{fmtRs(model.cost.variable)} this vol</span>
              </div>
            </div>

            {/* 3e. Bank ROI Panel */}
            <div className={`${th.card} border rounded-xl p-5`}>
              <SectionHeader title="Bank ROI — What the Bank Saves" isDark={isDark} />
              <div className="space-y-2 mb-4">
                {[
                  {
                    label: 'IET Compliance Savings',
                    sub: '0.05% breach rate × avg ₹45k × deemed-approval loss',
                    val: model.ietSavingsLakhs,
                    icon: '🛡',
                    color: 'text-emerald-400',
                  },
                  {
                    label: 'FTE Reduction',
                    sub: '85% STP → manual review drops ~85% · ₹8/cheque saved',
                    val: model.fteSavingsLakhs,
                    icon: '👥',
                    color: 'text-blue-400',
                  },
                  {
                    label: 'Fraud Prevention',
                    sub: '+2.3% catch rate on high-fraud cheques · ₹45k avg value',
                    val: model.fraudSavingsLakhs,
                    icon: '🔍',
                    color: 'text-violet-400',
                  },
                  {
                    label: 'Float Cost Savings',
                    sub: '<600ms vs hours → faster clearing = lower float exposure',
                    val: model.floatSavingsLakhs,
                    icon: '⚡',
                    color: 'text-amber-400',
                  },
                  {
                    label: 'Audit Cost Reduction',
                    sub: 'Automated immutable audit vs manual reconciliation',
                    val: model.auditSavingsLakhs,
                    icon: '📋',
                    color: 'text-sky-400',
                  },
                ].map(r => (
                  <div key={r.label} className={`flex items-center justify-between py-2 border-b ${th.divider} last:border-b-0`}>
                    <div className="flex-1 min-w-0 mr-3">
                      <div className={`text-xs font-semibold ${th.body}`}>{r.label}</div>
                      <div className={`text-xs ${th.faint} truncate`}>{r.sub}</div>
                    </div>
                    <span className={`text-sm font-bold font-mono shrink-0 ${r.color}`}>{fmtRs(r.val)}</span>
                  </div>
                ))}
              </div>
              <div className={`${isDark ? 'bg-emerald-500/10 border-emerald-500/30' : 'bg-emerald-50 border-emerald-200'} border rounded-lg px-4 py-3 flex items-center justify-between`}>
                <div>
                  <div className={`text-xs font-semibold ${isDark ? 'text-emerald-300' : 'text-emerald-700'}`}>Total Bank Saves</div>
                  <div className="text-xl font-bold text-emerald-400">{fmtRs(model.totalBankSaves)}<span className="text-sm font-normal ml-1">/year</span></div>
                </div>
                <div className={`${isDark ? 'bg-amber-500/20 border-amber-500/40 text-amber-300' : 'bg-amber-100 border-amber-300 text-amber-700'} border rounded-lg px-3 py-2 text-center`}>
                  <div className="text-xs font-medium">Payback</div>
                  <div className="text-lg font-bold">{model.paybackMonths}mo</div>
                </div>
              </div>
            </div>

            {/* 3f. Pricing Sensitivity Table */}
            <div className={`${th.card} border rounded-xl p-5`}>
              <SectionHeader title="Pricing Sensitivity — Gross Profit (₹ Lakhs)" isDark={isDark} />
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className={th.thead}>
                      <th className="py-2 pr-3 text-left font-semibold uppercase">₹/cheque</th>
                      {SENS_VOLUMES.map(v => (
                        <th key={v} className="py-2 px-2 text-right font-semibold uppercase">{fmtVol(v)}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {SENS_RATES.map(rate => (
                      <tr key={rate} className={`border-t ${th.row}`}>
                        <td className={`py-2 pr-3 font-mono font-semibold ${th.heading}`}>₹{rate.toFixed(2)}</td>
                        {SENS_VOLUMES.map(vol => {
                          const profit = calcSensitivity(rate, vol)
                          const margin = profit / ((vol * 100000 * rate) / 100000 + MANAGED_AI_RETAINER + SUPPORT_RETAINER)
                          const bg = profit < 0
                            ? (isDark ? 'bg-red-900/30 text-red-400' : 'bg-red-50 text-red-600')
                            : margin < 0.2
                              ? (isDark ? 'bg-amber-900/20 text-amber-400' : 'bg-amber-50 text-amber-700')
                              : (isDark ? 'bg-emerald-900/20 text-emerald-400' : 'bg-emerald-50 text-emerald-700')
                          return (
                            <td key={vol} className={`py-2 px-2 text-right font-mono font-semibold rounded ${bg}`}>
                              {profit >= 0 ? '+' : ''}{fmtRs(profit)}
                            </td>
                          )
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className={`mt-3 flex items-center gap-4 text-xs ${th.faint}`}>
                <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-red-500/60 inline-block" /> Loss</span>
                <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-amber-500/60 inline-block" /> &lt;20% margin</span>
                <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-emerald-500/60 inline-block" /> &gt;30% margin</span>
              </div>
            </div>

          </div>
        </div>
      </div>
    </AppShell>
  )
}

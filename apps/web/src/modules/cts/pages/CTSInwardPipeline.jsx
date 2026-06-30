import { useState, useEffect, useRef, useCallback } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'
import { useBankContext } from '../../../shared/context/BankContext'
import { getStpStream } from '../data/mockQueue'

// ─── Sub-member bank definitions (mock — live data via Kafka cts.smb.inbound) ─

// Sub-member UCBs routed through Saraswat as sponsor — smaller UCBs that
// do not have direct NGCH membership; Saraswat forwards on their behalf
const SMB_LIST = [
  { id: 'cosmos',     name: 'Cosmos Co-op',          ifsc: 'COSB0000001', city: 'Pune'      },
  { id: 'abhyudaya',  name: 'Abhyudaya Co-op',        ifsc: 'ABHY0065001', city: 'Mumbai'    },
  { id: 'shamrao',    name: 'Shamrao Vithal Co-op',   ifsc: 'SVCB0000001', city: 'Mumbai'    },
  { id: 'tjsb',       name: 'TJSB Sahakari Bank',     ifsc: 'TJSB0000001', city: 'Thane'     },
  { id: 'janata',     name: 'Janata Sahakari Bank',   ifsc: 'JNSB0000001', city: 'Pune'      },
]

// SMB pipeline has fewer stages — sponsor bank does forwarding, not full AI
const SMB_STAGES = [
  { id: 'recv',    label: 'Received',   icon: '⬇', color: 'sky'     },
  { id: 'valid',   label: 'Validated',  icon: '✓',  color: 'violet'  },
  { id: 'forward', label: 'Forwarded',  icon: '→',  color: 'indigo'  },
  { id: 'ngch',    label: 'NGCH Filed', icon: '📤', color: 'emerald' },
]

// ─── Pipeline stage definitions ───────────────────────────────────────────────

const STAGES = [
  {
    id: 'inward',
    label: 'NGCH Inward',
    sub: 'RBI clearing grid',
    icon: '⬇',
    color: 'sky',
    avgMs: null,
  },
  {
    id: 'ocr',
    label: 'OCR · MICR',
    sub: 'GOT-OCR2.0',
    icon: '🔤',
    color: 'violet',
    avgMs: 280,
  },
  {
    id: 'cts2010',
    label: 'CTS-2010',
    sub: 'Image quality',
    icon: '🖼',
    color: 'blue',
    avgMs: 140,
  },
  {
    id: 'sig',
    label: 'Signature',
    sub: 'Siamese SNN',
    icon: '✍',
    color: 'indigo',
    avgMs: 95,
  },
  {
    id: 'pps',
    label: 'PPS · CBS',
    sub: 'Vault + Finacle',
    icon: '🏦',
    color: 'cyan',
    avgMs: 60,
  },
  {
    id: 'fraud',
    label: 'Fraud Score',
    sub: 'XGBoost + SHAP',
    icon: '🛡',
    color: 'amber',
    avgMs: 45,
  },
  {
    id: 'decision',
    label: 'Decision',
    sub: 'AI synthesis',
    icon: '⚡',
    color: 'emerald',
    avgMs: 12,
  },
]

const COLOR = {
  sky:     { ring: 'ring-sky-500/40',     glow: '#0ea5e9', text: 'text-sky-400',     bg: 'bg-sky-500/10',     border: 'border-sky-500/30',     dot: 'bg-sky-400'     },
  violet:  { ring: 'ring-violet-500/40',  glow: '#8b5cf6', text: 'text-violet-400',  bg: 'bg-violet-500/10',  border: 'border-violet-500/30',  dot: 'bg-violet-400'  },
  blue:    { ring: 'ring-blue-500/40',    glow: '#3b82f6', text: 'text-blue-400',    bg: 'bg-blue-500/10',    border: 'border-blue-500/30',    dot: 'bg-blue-400'    },
  indigo:  { ring: 'ring-indigo-500/40',  glow: '#6366f1', text: 'text-indigo-400',  bg: 'bg-indigo-500/10',  border: 'border-indigo-500/30',  dot: 'bg-indigo-400'  },
  cyan:    { ring: 'ring-cyan-500/40',    glow: '#06b6d4', text: 'text-cyan-400',    bg: 'bg-cyan-500/10',    border: 'border-cyan-500/30',    dot: 'bg-cyan-400'    },
  amber:   { ring: 'ring-amber-500/40',   glow: '#f59e0b', text: 'text-amber-400',   bg: 'bg-amber-500/10',   border: 'border-amber-500/30',   dot: 'bg-amber-400'   },
  emerald: { ring: 'ring-emerald-500/40', glow: '#10b981', text: 'text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', dot: 'bg-emerald-400' },
  red:     { ring: 'ring-red-500/40',     glow: '#ef4444', text: 'text-red-400',     bg: 'bg-red-500/10',     border: 'border-red-500/30',     dot: 'bg-red-400'     },
}

// ─── Particle component — a dot travelling along an SVG path ─────────────────

function Particle({ id, color, delay, duration }) {
  const c = COLOR[color] || COLOR.sky
  return (
    <circle r="3" fill={c.glow} opacity="0.9" filter="url(#glow)">
      <animateMotion
        dur={`${duration}s`}
        begin={`${delay}s`}
        repeatCount="indefinite"
        rotate="auto"
        path="M 0 0 L 1 0"
        calcMode="linear"
      />
    </circle>
  )
}

// ─── Connector SVG between two stage cards ────────────────────────────────────

function Connector({ color = 'sky', active = true, particles = 2 }) {
  const c = COLOR[color] || COLOR.sky
  const ids = Array.from({ length: particles }, (_, i) => i)
  return (
    <div className="flex items-center shrink-0 w-10 relative" style={{ height: 88 }}>
      <svg width="40" height="88" viewBox="0 0 40 88" className="absolute inset-0">
        <defs>
          <filter id={`glow-${color}`} x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="1.5" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>
        {/* Static rail */}
        <line x1="0" y1="44" x2="40" y2="44" stroke={c.glow} strokeWidth="1" strokeOpacity="0.25" />
        {/* Animated particles */}
        {active && ids.map(i => (
          <circle key={i} r="2.5" fill={c.glow} opacity="0.85" filter={`url(#glow-${color})`}>
            <animateMotion
              dur={`${1.6 + i * 0.4}s`}
              begin={`${(i / particles) * 1.6}s`}
              repeatCount="indefinite"
              calcMode="linear"
            >
              <mpath href={`#rail-path-${color}-${i}`} />
            </animateMotion>
          </circle>
        ))}
        {active && ids.map(i => (
          <path key={`p-${i}`} id={`rail-path-${color}-${i}`} d="M 0 44 L 40 44" style={{ display: 'none' }} />
        ))}
      </svg>
      {/* Arrow tip */}
      <div className="absolute right-0 top-1/2 -translate-y-1/2 w-0 h-0"
        style={{ borderTop: '4px solid transparent', borderBottom: '4px solid transparent', borderLeft: `5px solid ${c.glow}`, opacity: 0.5 }} />
    </div>
  )
}

// ─── Stage card ───────────────────────────────────────────────────────────────

function StageCard({ stage, count, active, isDark }) {
  const c = COLOR[stage.color]
  const cardBase = isDark
    ? 'bg-white/4 border-white/10'
    : 'bg-white border-slate-200'
  const activeBorder = active ? `ring-2 ${c.ring}` : ''

  return (
    <div
      className={`relative rounded-xl border px-3 py-3 w-[108px] shrink-0 transition-all duration-500 ${cardBase} ${activeBorder}`}
      style={active ? { boxShadow: `0 0 18px 0 ${c.glow}28` } : {}}
    >
      {/* Pulsing activity dot */}
      {active && (
        <span className={`absolute top-2 right-2 w-1.5 h-1.5 rounded-full ${c.dot} animate-ping opacity-75`} />
      )}
      <div className="text-xl mb-2 leading-none">{stage.icon}</div>
      <div className={`text-[10px] font-bold leading-tight mb-0.5 ${isDark ? 'text-white' : 'text-slate-900'}`}>{stage.label}</div>
      <div className={`text-[9px] leading-tight mb-2 ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>{stage.sub}</div>
      {/* Count */}
      <div className={`text-xl font-black font-mono leading-none tabular-nums ${c.text}`}>{count}</div>
      <div className={`text-[9px] mt-0.5 ${isDark ? 'text-slate-600' : 'text-slate-400'}`}>processed</div>
      {stage.avgMs && (
        <div className={`text-[9px] mt-1 font-mono ${isDark ? 'text-slate-600' : 'text-slate-400'}`}>~{stage.avgMs}ms</div>
      )}
    </div>
  )
}

// ─── Fan-out decision branches ────────────────────────────────────────────────

function DecisionFanout({ confirms, returns, humanReview, isDark }) {
  const total = confirms + returns + humanReview
  const confirmPct  = total ? Math.round(confirms    / total * 100) : 0
  const returnPct   = total ? Math.round(returns     / total * 100) : 0
  const reviewPct   = total ? Math.round(humanReview / total * 100) : 0

  const Arm = ({ label, count, pct, color, icon }) => {
    const c = COLOR[color]
    return (
      <div className={`rounded-xl border px-3 py-2.5 w-[100px] transition-all duration-300 ${isDark ? 'bg-white/4 border-white/10' : 'bg-white border-slate-200'}`}
        style={{ boxShadow: `0 0 14px 0 ${c.glow}22` }}>
        <div className="text-base mb-1">{icon}</div>
        <div className={`text-[10px] font-bold ${c.text} leading-tight`}>{label}</div>
        <div className={`text-lg font-black font-mono ${c.text} tabular-nums`}>{count}</div>
        <div className={`text-[9px] ${isDark ? 'text-slate-600' : 'text-slate-400'}`}>{pct}% of total</div>
      </div>
    )
  }

  return (
    <div className="flex flex-col items-center gap-2 shrink-0">
      {/* Fan lines SVG */}
      <svg width="80" height="96" viewBox="0 0 80 96" className="shrink-0">
        <defs>
          <filter id="glow-fan">
            <feGaussianBlur stdDeviation="1" result="blur"/>
            <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>
        </defs>
        {/* Lines fanning from left to three outputs */}
        <line x1="0" y1="48" x2="80" y2="16" stroke="#10b981" strokeWidth="1" strokeOpacity="0.4" />
        <line x1="0" y1="48" x2="80" y2="48" stroke="#f59e0b" strokeWidth="1" strokeOpacity="0.4" />
        <line x1="0" y1="48" x2="80" y2="80" stroke="#ef4444" strokeWidth="1" strokeOpacity="0.4" />
        {/* Animated particles */}
        <circle r="2.5" fill="#10b981" filter="url(#glow-fan)">
          <animateMotion dur="1.4s" repeatCount="indefinite" calcMode="linear">
            <mpath href="#fan-confirm"/>
          </animateMotion>
        </circle>
        <circle r="2.5" fill="#f59e0b" filter="url(#glow-fan)">
          <animateMotion dur="1.8s" begin="0.3s" repeatCount="indefinite" calcMode="linear">
            <mpath href="#fan-human"/>
          </animateMotion>
        </circle>
        <circle r="2.5" fill="#ef4444" filter="url(#glow-fan)">
          <animateMotion dur="2.2s" begin="0.6s" repeatCount="indefinite" calcMode="linear">
            <mpath href="#fan-return"/>
          </animateMotion>
        </circle>
        <path id="fan-confirm" d="M 0 48 L 80 16" style={{ display: 'none' }} />
        <path id="fan-human"   d="M 0 48 L 80 48" style={{ display: 'none' }} />
        <path id="fan-return"  d="M 0 48 L 80 80" style={{ display: 'none' }} />
      </svg>
      {/* Three arm cards */}
      <div className="flex flex-col gap-1.5 -mt-10">
        <Arm label="STP Confirm"   count={confirms}    pct={confirmPct}  color="emerald" icon="✓" />
        <Arm label="Human Review"  count={humanReview} pct={reviewPct}   color="amber"   icon="👤" />
        <Arm label="STP Return"    count={returns}     pct={returnPct}   color="red"     icon="✕" />
      </div>
    </div>
  )
}

// ─── NGCH Filed terminus ──────────────────────────────────────────────────────

function FiledTerminus({ total, isDark }) {
  return (
    <div className="flex flex-col items-center gap-2 shrink-0">
      {/* Converging lines */}
      <svg width="60" height="96" viewBox="0 0 60 96">
        <line x1="0" y1="16" x2="60" y2="48" stroke="#6366f1" strokeWidth="1" strokeOpacity="0.35" />
        <line x1="0" y1="48" x2="60" y2="48" stroke="#6366f1" strokeWidth="1" strokeOpacity="0.35" />
        <line x1="0" y1="80" x2="60" y2="48" stroke="#6366f1" strokeWidth="1" strokeOpacity="0.35" />
        <circle r="2" fill="#6366f1">
          <animateMotion dur="1.6s" repeatCount="indefinite" calcMode="linear">
            <mpath href="#conv-top"/>
          </animateMotion>
        </circle>
        <circle r="2" fill="#6366f1">
          <animateMotion dur="1.6s" begin="0.5s" repeatCount="indefinite" calcMode="linear">
            <mpath href="#conv-mid"/>
          </animateMotion>
        </circle>
        <circle r="2" fill="#6366f1">
          <animateMotion dur="1.6s" begin="1s" repeatCount="indefinite" calcMode="linear">
            <mpath href="#conv-bot"/>
          </animateMotion>
        </circle>
        <path id="conv-top" d="M 0 16 L 60 48" style={{ display: 'none' }} />
        <path id="conv-mid" d="M 0 48 L 60 48" style={{ display: 'none' }} />
        <path id="conv-bot" d="M 0 80 L 60 48" style={{ display: 'none' }} />
      </svg>
      {/* Filed card */}
      <div className={`-mt-10 rounded-xl border px-3 py-3 w-[100px] ${isDark ? 'bg-indigo-900/20 border-indigo-500/30' : 'bg-indigo-50 border-indigo-200'}`}
        style={{ boxShadow: '0 0 18px 0 #6366f122' }}>
        <div className="text-xl mb-1">📤</div>
        <div className="text-[10px] font-bold text-indigo-400 leading-tight">NGCH Filed</div>
        <div className="text-lg font-black font-mono text-indigo-400 tabular-nums">{total}</div>
        <div className={`text-[9px] ${isDark ? 'text-slate-600' : 'text-slate-400'}`}>decisions filed</div>
        <div className={`text-[9px] font-mono mt-1 ${isDark ? 'text-slate-600' : 'text-slate-400'}`}>Immudb ✓</div>
      </div>
    </div>
  )
}

// ─── Live activity log ────────────────────────────────────────────────────────

function ActivityLog({ events, isDark }) {
  return (
    <div className={`rounded-xl border overflow-hidden ${isDark ? 'bg-white/2 border-white/6' : 'bg-white border-slate-200'}`}>
      <div className={`px-3 py-2 border-b flex items-center justify-between ${isDark ? 'border-white/6' : 'border-slate-100'}`}>
        <span className={`text-[10px] font-semibold uppercase tracking-widest ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>Live Activity</span>
        <span className="flex items-center gap-1 text-[9px] text-emerald-500">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
          Live
        </span>
      </div>
      <div className="divide-y" style={{ borderColor: isDark ? 'rgba(255,255,255,0.04)' : '#f1f5f9' }}>
        {events.slice(0, 12).map((ev, i) => (
          <div key={i} className={`flex items-center gap-3 px-4 py-2 text-[10px] ${i === 0 ? (isDark ? 'bg-white/3' : 'bg-slate-50') : ''}`}>
            <span className={`font-mono shrink-0 ${isDark ? 'text-slate-600' : 'text-slate-400'}`}>{ev.time}</span>
            <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${ev.outcome === 'CONFIRM' ? 'bg-emerald-400' : ev.outcome === 'RETURN' ? 'bg-red-400' : 'bg-amber-400'}`} />
            <span className={`font-mono truncate ${isDark ? 'text-slate-300' : 'text-slate-700'}`}>{ev.id}</span>
            <span className={`ml-auto shrink-0 font-semibold ${ev.outcome === 'CONFIRM' ? 'text-emerald-500' : ev.outcome === 'RETURN' ? 'text-red-500' : 'text-amber-500'}`}>
              {ev.outcome === 'CONFIRM' ? '✓ STP' : ev.outcome === 'RETURN' ? '✕ RTN' : '👤 HRQ'}
            </span>
            <span className={`shrink-0 font-mono ${isDark ? 'text-slate-600' : 'text-slate-400'}`}>{ev.ms}ms</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── SMB compact pipeline lane ───────────────────────────────────────────────

function SMBLane({ smb, counts, activeStage, alerts, isDark, onSelect, selected }) {
  const th = {
    row: isDark
      ? `border-white/6 ${selected ? 'bg-white/5' : 'hover:bg-white/3'}`
      : `border-slate-100 ${selected ? 'bg-slate-50' : 'hover:bg-slate-50/60'}`,
    name: isDark ? 'text-white'     : 'text-slate-900',
    sub:  isDark ? 'text-slate-500' : 'text-slate-400',
  }

  const total   = (counts.ngch || 0)
  const pending = (counts.recv || 0) - total
  const hasAlert = alerts > 0

  return (
    <button
      onClick={() => onSelect(smb.id)}
      className={`w-full flex items-center gap-4 px-4 py-2.5 border-b text-left transition-colors ${th.row}`}
    >
      {/* SMB identity */}
      <div className="w-36 shrink-0">
        <div className={`text-[11px] font-semibold leading-tight ${th.name}`}>{smb.name}</div>
        <div className={`text-[9px] font-mono ${th.sub}`}>{smb.ifsc} · {smb.city}</div>
      </div>

      {/* Mini stage dots */}
      <div className="flex items-center gap-1 shrink-0">
        {SMB_STAGES.map((stage, i) => {
          const c = COLOR[stage.color]
          const isActive = activeStage === stage.id
          const cnt = counts[stage.id] || 0
          return (
            <div key={stage.id} className="flex items-center gap-1">
              <div className="flex flex-col items-center gap-0.5">
                <div className={`w-6 h-6 rounded-lg border flex items-center justify-center text-[10px] transition-all duration-300
                  ${isActive
                    ? `${isDark ? 'bg-white/10 border-white/20' : 'bg-white border-slate-200'} ring-2 ${c.ring}`
                    : isDark ? 'bg-white/3 border-white/8' : 'bg-white border-slate-100'
                  }`}
                >
                  {stage.icon}
                </div>
                <div className={`text-[8px] font-mono tabular-nums ${c.text}`}>{cnt}</div>
              </div>
              {i < SMB_STAGES.length - 1 && (
                <div className={`w-4 h-px ${isActive ? c.dot : isDark ? 'bg-white/10' : 'bg-slate-200'} transition-colors`} />
              )}
            </div>
          )
        })}
      </div>

      {/* Stats */}
      <div className="flex items-center gap-4 ml-2 shrink-0">
        <div className="flex flex-col items-end">
          <span className={`text-[10px] font-mono font-semibold ${isDark ? 'text-emerald-400' : 'text-emerald-600'}`}>{total}</span>
          <span className={`text-[8px] ${isDark ? 'text-slate-600' : 'text-slate-400'}`}>filed</span>
        </div>
        <div className="flex flex-col items-end">
          <span className={`text-[10px] font-mono font-semibold ${isDark ? 'text-sky-400' : 'text-sky-600'}`}>{Math.max(0, pending)}</span>
          <span className={`text-[8px] ${isDark ? 'text-slate-600' : 'text-slate-400'}`}>in-flight</span>
        </div>
      </div>

      {/* Alert badge */}
      <div className="ml-auto shrink-0">
        {hasAlert ? (
          <span className="flex items-center gap-1 text-[9px] font-semibold text-amber-500 px-2 py-0.5 rounded-full bg-amber-500/10 border border-amber-500/20">
            ⚠ {alerts} alert{alerts > 1 ? 's' : ''}
          </span>
        ) : (
          <span className={`text-[9px] ${isDark ? 'text-slate-600' : 'text-slate-400'}`}>✓ nominal</span>
        )}
      </div>
    </button>
  )
}

// ─── IET countdown ring ───────────────────────────────────────────────────────

function IETRing({ minutesLeft = 180, isDark }) {
  const total = 180
  const pct = Math.max(0, minutesLeft / total)
  const r = 28
  const circ = 2 * Math.PI * r
  const dash = pct * circ
  const color = pct > 0.4 ? '#10b981' : pct > 0.15 ? '#f59e0b' : '#ef4444'
  const h = Math.floor(minutesLeft / 60)
  const m = minutesLeft % 60

  return (
    <div className="flex flex-col items-center gap-1">
      <svg width="72" height="72" viewBox="0 0 72 72">
        <circle cx="36" cy="36" r={r} fill="none" stroke={isDark ? 'rgba(255,255,255,0.06)' : '#e2e8f0'} strokeWidth="4" />
        <circle cx="36" cy="36" r={r} fill="none" stroke={color} strokeWidth="4"
          strokeLinecap="round"
          strokeDasharray={`${dash} ${circ}`}
          transform="rotate(-90 36 36)"
          style={{ transition: 'stroke-dasharray 1s linear, stroke 0.5s' }}
        />
        <text x="36" y="33" textAnchor="middle" fill={color} fontSize="11" fontWeight="700" fontFamily="monospace">
          {String(h).padStart(2,'0')}:{String(m).padStart(2,'0')}
        </text>
        <text x="36" y="44" textAnchor="middle" fill={isDark ? '#475569' : '#94a3b8'} fontSize="7">
          IET left
        </text>
      </svg>
    </div>
  )
}

// ─── Throughput sparkline ─────────────────────────────────────────────────────

function ThroughputSparkline({ data, isDark }) {
  const max = Math.max(...data, 1)
  const w = 120, h = 32, pts = data.length
  const step = w / (pts - 1)
  const points = data.map((v, i) => `${i * step},${h - (v / max) * h}`).join(' ')

  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`}>
      <polyline
        points={points}
        fill="none"
        stroke="#10b981"
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
        opacity="0.7"
      />
      {/* Fill */}
      <polygon
        points={`0,${h} ${points} ${(pts-1)*step},${h}`}
        fill="#10b981"
        opacity="0.08"
      />
    </svg>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

const STP_TICK_MS = 2800

export default function CTSInwardPipeline() {
  const { bankName, bankIfsc, bankCity, isSB, isSMB } = useBankContext()
  const SPONSOR_BANK = { name: bankName, ifsc: bankIfsc, city: bankCity || '' }
  const { isDark } = useTheme()
  const stpSource   = useRef(getStpStream())
  const stpIndexRef = useRef(0)

  const [view, setView] = useState('sb') // 'sb' | 'smb'

  const [stageCounts, setStageCounts] = useState(
    Object.fromEntries(STAGES.map(s => [s.id, Math.floor(Math.random() * 80) + 20]))
  )
  const [activeStages, setActiveStages] = useState(new Set(['ocr', 'sig', 'fraud']))
  const [confirms,    setConfirms]    = useState(312)
  const [returns,     setReturns]     = useState(48)
  const [humanReview, setHumanReview] = useState(17)
  const [activityLog, setActivityLog] = useState([])
  const [throughput,  setThroughput]  = useState(Array.from({ length: 20 }, () => Math.floor(Math.random() * 8) + 2))
  const [ietMinutes,  setIetMinutes]  = useState(142)
  const [totalMs,     setTotalMs]     = useState(612)
  const [now,         setNow]         = useState(new Date())

  // SMB child pipelines state
  const [smbCounts, setSmbCounts] = useState(() =>
    Object.fromEntries(SMB_LIST.map(smb => [smb.id, {
      recv:    Math.floor(Math.random() * 60) + 10,
      valid:   Math.floor(Math.random() * 50) + 8,
      forward: Math.floor(Math.random() * 40) + 6,
      ngch:    Math.floor(Math.random() * 35) + 5,
    }]))
  )
  const [smbActiveStages, setSmbActiveStages] = useState(() =>
    Object.fromEntries(SMB_LIST.map(smb => [smb.id, SMB_STAGES[Math.floor(Math.random() * SMB_STAGES.length)].id]))
  )
  const [smbAlerts, setSmbAlerts] = useState({ cosmos: 1, tjsb: 0, janata: 0, abhyudaya: 2, shamrao: 0 })
  const [selectedSmb, setSelectedSmb] = useState(null)

  // Clock
  useEffect(() => {
    const t = setInterval(() => {
      setNow(new Date())
      setIetMinutes(m => Math.max(0, m - 1))
    }, 60000)
    return () => clearInterval(t)
  }, [])

  // STP tick
  useEffect(() => {
    const timer = setInterval(() => {
      const items = stpSource.current
      if (stpIndexRef.current >= items.length) return
      const item = items[stpIndexRef.current]
      stpIndexRef.current++

      const outcome = item.outcome
      const stageSeq = ['ocr','cts2010','sig','pps','fraud','decision']
      const activeIdx = Math.floor(Math.random() * stageSeq.length)

      // Pulse active stages
      const next = new Set(stageSeq.slice(Math.max(0, activeIdx - 1), activeIdx + 2))
      setActiveStages(next)

      // Increment all stage counters slightly
      setStageCounts(prev => {
        const updated = { ...prev }
        stageSeq.forEach(s => { updated[s] = (updated[s] || 0) + 1 })
        updated.inward = (updated.inward || 0) + 1
        return updated
      })

      if (outcome === 'CONFIRM') setConfirms(c => c + 1)
      else if (outcome === 'RETURN') setReturns(r => r + 1)
      else setHumanReview(h => h + 1)

      const ms = 380 + Math.floor(Math.random() * 220)
      setTotalMs(ms)

      setActivityLog(prev => [{
        id: item.id,
        outcome,
        ms,
        time: new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }),
      }, ...prev].slice(0, 40))

      setThroughput(prev => [...prev.slice(1), Math.floor(Math.random() * 10) + 1])
    }, STP_TICK_MS)
    return () => clearInterval(timer)
  }, [])

  // SMB child pipeline tick — slower cadence (each SMB processes fewer cheques)
  useEffect(() => {
    const timer = setInterval(() => {
      const smbId = SMB_LIST[Math.floor(Math.random() * SMB_LIST.length)].id
      const stageSeq = SMB_STAGES.map(s => s.id)
      setSmbCounts(prev => {
        const updated = { ...prev }
        const smb = { ...updated[smbId] }
        stageSeq.forEach(s => { smb[s] = (smb[s] || 0) + 1 })
        updated[smbId] = smb
        return updated
      })
      setSmbActiveStages(prev => ({ ...prev, [smbId]: stageSeq[Math.floor(Math.random() * stageSeq.length)] }))
    }, STP_TICK_MS * 1.5)
    return () => clearInterval(timer)
  }, [])

  usePageHeader({
    subtitle: 'Inward Processing Pipeline · AI Agent Swarm · Real-time',
    actions: (
      <div className="flex items-center gap-3">
        <IETRing minutesLeft={ietMinutes} isDark={isDark} />
        <div className={`text-[10px] font-mono px-3 py-1.5 rounded-lg border ${isDark ? 'border-white/10 text-slate-400 bg-white/4' : 'border-slate-200 text-slate-500 bg-white'}`}>
          p99 · {totalMs}ms
        </div>
        <div className={`flex items-center gap-1.5 text-[10px] px-3 py-1.5 rounded-lg border ${isDark ? 'border-emerald-700/40 bg-emerald-900/20 text-emerald-300' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
          500 agents active
        </div>
      </div>
    ),
  })

  const total = confirms + returns + humanReview
  const stpRate = total ? ((confirms + returns) / total * 100).toFixed(1) : '0.0'

  const th = {
    page:    isDark ? 'bg-[#020817]'   : 'bg-slate-50',
    card:    isDark ? 'bg-white/4 border-white/8'  : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'     : 'text-slate-900',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    faint:   isDark ? 'text-slate-600' : 'text-slate-400',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
  }

  return (
    <AppShell>
      <div className={`flex flex-col h-full overflow-hidden ${th.page}`}>

        {/* ── View tabs ── */}
        <div className={`shrink-0 px-6 border-b ${th.divider} flex items-center gap-0`}>
          {[
            { id: 'sb',  label: 'Sponsor Bank Pipeline' },
            { id: 'smb', label: `Sub-Member Banks (${SMB_LIST.length})` },
          ].map(tab => (
            <button
              key={tab.id}
              onClick={() => setView(tab.id)}
              className={`px-4 py-2.5 text-[11px] font-semibold border-b-2 transition-colors
                ${view === tab.id
                  ? `border-violet-500 ${isDark ? 'text-white' : 'text-slate-900'}`
                  : `border-transparent ${isDark ? 'text-slate-500 hover:text-slate-300' : 'text-slate-400 hover:text-slate-600'}`
                }`}
            >
              {tab.label}
              {tab.id === 'smb' && Object.values(smbAlerts).some(a => a > 0) && (
                <span className="ml-1.5 px-1.5 py-0.5 text-[8px] font-bold rounded-full bg-amber-500/20 text-amber-500">
                  {Object.values(smbAlerts).reduce((a, b) => a + b, 0)}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* ── Top KPI strip (SB view) ── */}
        {view === 'sb' && <div className={`shrink-0 px-6 py-3 border-b ${th.divider} flex items-center gap-6`}>
          {[
            { label: 'Total Inward',    val: stageCounts.inward, color: isDark ? 'text-sky-400'     : 'text-sky-600'     },
            { label: 'STP Confirmed',   val: confirms,           color: isDark ? 'text-emerald-400' : 'text-emerald-600' },
            { label: 'STP Returned',    val: returns,            color: isDark ? 'text-red-400'     : 'text-red-600'     },
            { label: 'Human Review',    val: humanReview,        color: isDark ? 'text-amber-400'   : 'text-amber-600'   },
            { label: 'STP Rate',        val: `${stpRate}%`,      color: isDark ? 'text-violet-400'  : 'text-violet-600'  },
            { label: 'Immudb Writes',   val: total,              color: isDark ? 'text-indigo-400'  : 'text-indigo-600'  },
          ].map(k => (
            <div key={k.label} className="flex items-baseline gap-2">
              <span className={`text-2xl font-black font-mono tabular-nums ${k.color}`}>{k.val}</span>
              <span className={`text-[10px] ${th.faint}`}>{k.label}</span>
            </div>
          ))}
          <div className="ml-auto">
            <ThroughputSparkline data={throughput} isDark={isDark} />
            <div className={`text-[9px] text-center mt-0.5 ${th.faint}`}>cheques/tick</div>
          </div>
        </div>}

        {/* ── Pipeline diagram + right panel ── */}
        {view === 'smb' && (
          <div className="flex flex-1 min-h-0 overflow-hidden">
            {/* SMB list */}
            <div className="flex-1 overflow-y-auto">
              {/* Sponsor identity banner */}
              <div className={`px-4 py-2 border-b flex items-center gap-2 ${isDark ? 'bg-violet-900/10 border-violet-700/20' : 'bg-violet-50 border-violet-200'}`}>
                <span className="text-sm">🏦</span>
                <span className={`text-[10px] ${isDark ? 'text-violet-300' : 'text-violet-700'}`}>
                  Sponsor Bank: <span className="font-semibold">{SPONSOR_BANK.name}</span>
                  <span className={`ml-2 font-mono ${isDark ? 'text-violet-400/60' : 'text-violet-500/70'}`}>{SPONSOR_BANK.ifsc}</span>
                </span>
                <span className={`ml-auto text-[9px] ${isDark ? 'text-violet-400/50' : 'text-violet-400'}`}>
                  Forwarding instruments for {SMB_LIST.length} sub-members via SMBForwardingWorkflow
                </span>
              </div>

              {/* Header row */}
              <div className={`flex items-center gap-4 px-4 py-2 border-b ${th.divider} sticky top-0 z-10 ${isDark ? 'bg-[#020817]' : 'bg-slate-50'}`}>
                <div className={`w-36 shrink-0 text-[9px] font-semibold uppercase tracking-widest ${th.muted}`}>Sub-Member Bank</div>
                <div className="flex items-center gap-1 shrink-0">
                  {SMB_STAGES.map((stage, i) => (
                    <div key={stage.id} className="flex items-center gap-1">
                      <div className={`text-[9px] font-semibold w-6 text-center uppercase tracking-wide ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>{stage.label.slice(0,4)}</div>
                      {i < SMB_STAGES.length - 1 && <div className="w-4" />}
                    </div>
                  ))}
                </div>
                <div className="flex items-center gap-4 ml-2 shrink-0">
                  <span className={`text-[9px] font-semibold uppercase tracking-wide ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>Filed</span>
                  <span className={`text-[9px] font-semibold uppercase tracking-wide ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>In-Flight</span>
                </div>
                <div className="ml-auto">
                  <span className={`text-[9px] font-semibold uppercase tracking-wide ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>Status</span>
                </div>
              </div>

              {SMB_LIST.map(smb => (
                <SMBLane
                  key={smb.id}
                  smb={smb}
                  counts={smbCounts[smb.id] || {}}
                  activeStage={smbActiveStages[smb.id]}
                  alerts={smbAlerts[smb.id] || 0}
                  isDark={isDark}
                  onSelect={setSelectedSmb}
                  selected={selectedSmb === smb.id}
                />
              ))}

              {/* SMB aggregate footer */}
              <div className={`px-4 py-3 flex items-center gap-6 border-t ${th.divider} ${isDark ? 'bg-white/2' : 'bg-slate-50'}`}>
                <span className={`text-[10px] font-semibold ${th.muted}`}>All SMBs combined</span>
                {['recv','valid','forward','ngch'].map(stage => (
                  <div key={stage} className="flex items-baseline gap-1">
                    <span className={`text-base font-black font-mono tabular-nums ${isDark ? 'text-slate-300' : 'text-slate-700'}`}>
                      {SMB_LIST.reduce((sum, smb) => sum + (smbCounts[smb.id]?.[stage] || 0), 0)}
                    </span>
                    <span className={`text-[9px] ${th.faint}`}>{stage}</span>
                  </div>
                ))}
                <div className="ml-auto flex items-center gap-2">
                  {Object.values(smbAlerts).reduce((a, b) => a + b, 0) > 0 ? (
                    <span className="text-[10px] font-semibold text-amber-500">
                      ⚠ {Object.values(smbAlerts).reduce((a, b) => a + b, 0)} alerts need attention
                    </span>
                  ) : (
                    <span className={`text-[10px] ${isDark ? 'text-emerald-400' : 'text-emerald-600'}`}>✓ All SMBs nominal</span>
                  )}
                </div>
              </div>
            </div>

            {/* Right: selected SMB detail or instructions */}
            <div className={`w-72 shrink-0 border-l ${th.divider} flex flex-col`}>
              {selectedSmb ? (() => {
                const smb = SMB_LIST.find(s => s.id === selectedSmb)
                const counts = smbCounts[selectedSmb] || {}
                const alerts = smbAlerts[selectedSmb] || 0
                return (
                  <>
                    <div className={`px-4 py-3 border-b ${isDark ? 'border-white/5' : 'border-slate-100'}`}>
                      <div className={`text-xs font-semibold ${th.heading}`}>{smb.name}</div>
                      <div className={`text-[10px] font-mono mt-0.5 ${th.muted}`}>{smb.ifsc} · {smb.city}</div>
                    </div>
                    <div className="flex-1 p-4 flex flex-col gap-3">
                      {/* Per-stage breakdown */}
                      {SMB_STAGES.map(stage => {
                        const c = COLOR[stage.color]
                        const cnt = counts[stage.id] || 0
                        const max = Math.max(...SMB_STAGES.map(s => counts[s.id] || 0), 1)
                        return (
                          <div key={stage.id} className="flex items-center gap-3">
                            <span className="text-sm w-5 text-center">{stage.icon}</span>
                            <div className="flex-1">
                              <div className={`text-[10px] font-semibold mb-1 ${isDark ? 'text-slate-300' : 'text-slate-700'}`}>{stage.label}</div>
                              <div className={`h-1.5 rounded-full overflow-hidden ${isDark ? 'bg-white/6' : 'bg-slate-100'}`}>
                                <div className={`h-full rounded-full ${c.dot} transition-all duration-500`} style={{ width: `${(cnt / max) * 100}%` }} />
                              </div>
                            </div>
                            <span className={`text-[11px] font-mono font-semibold w-8 text-right ${c.text}`}>{cnt}</span>
                          </div>
                        )
                      })}
                      {/* Alert detail */}
                      {alerts > 0 && (
                        <div className={`mt-2 rounded-xl border px-3 py-2.5 ${isDark ? 'bg-amber-900/10 border-amber-700/30' : 'bg-amber-50 border-amber-200'}`}>
                          <div className={`text-[10px] font-semibold mb-1 ${isDark ? 'text-amber-300' : 'text-amber-700'}`}>
                            ⚠ {alerts} Active Alert{alerts > 1 ? 's' : ''}
                          </div>
                          <div className={`text-[9px] leading-relaxed ${isDark ? 'text-amber-400/70' : 'text-amber-600/80'}`}>
                            {alerts === 1
                              ? 'IET window narrowing — 1 instrument approaching T-30s. Watchdog monitoring.'
                              : `${alerts} instruments in forwarding stage with elevated IET risk. Immediate review recommended.`}
                          </div>
                        </div>
                      )}
                      {/* Routing info */}
                      <div className={`mt-2 rounded-xl border px-3 py-2.5 ${isDark ? 'bg-white/3 border-white/8' : 'bg-slate-50 border-slate-200'}`}>
                        <div className={`text-[9px] font-semibold uppercase tracking-widest mb-1.5 ${th.muted}`}>Routing</div>
                        <div className={`text-[9px] leading-relaxed ${th.faint}`}>
                          Instruments forwarded via <span className="font-mono">SMBForwardingWorkflow</span> → sponsor lot → NGCH submission. SMB bears return risk; SB bears IET responsibility.
                        </div>
                      </div>
                    </div>
                  </>
                )
              })() : (
                <div className={`flex-1 flex items-center justify-center p-6 text-center`}>
                  <div>
                    <div className="text-3xl mb-3">🏦</div>
                    <div className={`text-[11px] font-semibold mb-1 ${th.heading}`}>Select an SMB</div>
                    <div className={`text-[10px] ${th.muted}`}>Click any sub-member bank row to see its pipeline detail and alerts</div>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {view === 'sb' && (
        <div className="flex flex-1 min-h-0 overflow-hidden">

          {/* Pipeline canvas */}
          <div className="flex-1 overflow-hidden px-5 py-4 flex flex-col gap-4 min-w-0">

            {/* Row label */}
            <div className={`text-[9px] font-semibold uppercase tracking-widest shrink-0 ${th.faint}`}>
              Inward Cheque Processing — One AI Agent Per Cheque — Wall Clock &lt; 600ms
            </div>

            {/* Main pipeline flow — horizontally scrollable if viewport too narrow */}
            <div className="shrink-0 overflow-x-auto overflow-y-visible pb-1">
              <div className="flex items-center gap-0 flex-nowrap">
                {STAGES.map((stage, i) => {
                  const nextStage = STAGES[i + 1]
                  const connColor = nextStage?.color || stage.color
                  return (
                    <div key={stage.id} className="flex items-center gap-0">
                      <StageCard
                        stage={stage}
                        count={stageCounts[stage.id] || 0}
                        active={activeStages.has(stage.id)}
                        isDark={isDark}
                      />
                      {i < STAGES.length - 1 && (
                        <Connector
                          color={connColor}
                          active={activeStages.has(stage.id) || activeStages.has(nextStage?.id)}
                          particles={2}
                        />
                      )}
                    </div>
                  )
                })}

                {/* Fan-out after Decision */}
                <DecisionFanout
                  confirms={confirms}
                  returns={returns}
                  humanReview={humanReview}
                  isDark={isDark}
                />

                {/* Convergence to NGCH Filed */}
                <FiledTerminus total={total} isDark={isDark} />
              </div>
            </div>

            {/* Latency + IET banner — side by side to avoid vertical overflow */}
            <div className="shrink-0 flex gap-3">
              {/* Stage timing bar */}
              <div className={`flex-1 rounded-xl border px-3 py-2.5 ${th.card}`}>
                <div className={`text-[9px] font-semibold uppercase tracking-widest mb-2 ${th.muted}`}>
                  Latency Budget — &lt; 600ms target
                </div>
                <div className="flex items-end gap-1 h-10">
                  {STAGES.filter(s => s.avgMs).map((stage) => {
                    const c = COLOR[stage.color]
                    const pct = (stage.avgMs / 600) * 100
                    return (
                      <div key={stage.id} className="flex flex-col items-center gap-0.5 flex-1">
                        <div className={`text-[7px] font-mono ${c.text}`}>{stage.avgMs}ms</div>
                        <div
                          className={`w-full rounded-t ${c.dot} opacity-70 transition-all duration-500`}
                          style={{ height: `${Math.max(3, pct * 0.32)}px` }}
                        />
                        <div className={`text-[7px] truncate w-full text-center ${th.faint}`}>{stage.label.split(' ')[0]}</div>
                      </div>
                    )
                  })}
                  <div className="flex flex-col items-center gap-0.5 flex-1">
                    <div className="text-[7px] font-mono text-indigo-400">∑ {STAGES.filter(s=>s.avgMs).reduce((a,s)=>a+s.avgMs,0)}ms</div>
                    <div className="w-full rounded-t bg-indigo-400 opacity-70" style={{ height: '16px' }} />
                    <div className={`text-[7px] truncate w-full text-center ${th.faint}`}>Total</div>
                  </div>
                </div>
              </div>

              {/* IET watchdog banner */}
              <div className={`shrink-0 w-72 rounded-xl border px-3 py-2.5 flex items-start gap-2.5 ${isDark ? 'bg-amber-900/10 border-amber-700/30' : 'bg-amber-50 border-amber-200'}`}>
                <span className="text-base shrink-0 mt-0.5">⏱</span>
                <div>
                  <div className={`text-[10px] font-semibold mb-0.5 ${isDark ? 'text-amber-300' : 'text-amber-700'}`}>
                    IET Watchdog — T-30s Emergency Filing
                  </div>
                  <div className={`text-[9px] leading-relaxed ${isDark ? 'text-amber-400/70' : 'text-amber-600/80'}`}>
                    Parallel IETWatchdogWorkflow per cheque. Auto-files to NGCH before IET breach. {ietMinutes}m left in clearing window.
                  </div>
                </div>
              </div>
            </div>

          </div>

          {/* Right: live log */}
          <div className={`w-72 shrink-0 border-l ${th.divider} flex flex-col`}>
            <div className={`px-4 py-3 border-b ${isDark ? 'border-white/5' : 'border-slate-100'}`}>
              <div className={`text-xs font-semibold ${th.heading}`}>Live Decisions</div>
            </div>
            <div className="flex-1 overflow-y-auto p-3">
              <ActivityLog events={activityLog} isDark={isDark} />
            </div>

            {/* Session footer */}
            <div className={`shrink-0 px-4 py-4 border-t ${th.divider} space-y-3`}>
              <div className={`text-[10px] font-extrabold uppercase tracking-widest ${th.heading}`}>Session</div>
              {[
                { label: 'STP Confirmed',  val: confirms,    color: isDark ? 'text-emerald-400' : 'text-emerald-600' },
                { label: 'STP Returned',   val: returns,     color: isDark ? 'text-red-400'     : 'text-red-600'     },
                { label: 'Human Review',   val: humanReview, color: isDark ? 'text-amber-400'   : 'text-amber-600'   },
              ].map(row => (
                <div key={row.label} className="flex items-center justify-between">
                  <span className={`text-[11px] ${th.muted}`}>{row.label}</span>
                  <span className={`text-3xl font-black font-mono leading-none tabular-nums ${row.color}`}>{row.val}</span>
                </div>
              ))}
              <div className={`flex items-center justify-between pt-2 border-t ${th.divider}`}>
                <span className={`text-[11px] ${th.muted}`}>STP Rate</span>
                <span className={`text-3xl font-black font-mono leading-none tabular-nums ${isDark ? 'text-violet-400' : 'text-violet-600'}`}>{stpRate}%</span>
              </div>
            </div>
          </div>
        </div>
        )}

      </div>
    </AppShell>
  )
}

import { NavLink } from 'react-router-dom'
import { useTheme } from '../theme/ThemeContext'
import { BANK_CONFIG } from '../config/bank.config'

// ── Icons ────────────────────────────────────────────────────────────────────

function InwardIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" className="w-4 h-4">
      <rect x="3" y="5" width="14" height="10" rx="1.5" />
      <path d="M3 8h14" strokeWidth="1.4" />
      <path d="M10 12l-2-2m2 2l2-2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
function OutwardIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" className="w-4 h-4">
      <rect x="3" y="5" width="14" height="10" rx="1.5" />
      <path d="M3 8h14" strokeWidth="1.4" />
      <path d="M10 10l-2 2m2-2l2 2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
function FraudIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" className="w-4 h-4">
      <path d="M10 3l7 4v4c0 3.5-3 6-7 7-4-1-7-3.5-7-7V7l7-4z" strokeLinejoin="round" />
      <path d="M10 8v3m0 2v.5" strokeLinecap="round" />
    </svg>
  )
}
function AuditIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" className="w-4 h-4">
      <path d="M5 10h10M5 7h7M5 13h5" strokeLinecap="round" />
      <rect x="3" y="3" width="14" height="14" rx="2" />
    </svg>
  )
}
function AdminIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" className="w-4 h-4">
      <circle cx="10" cy="8" r="3" />
      <path d="M10 12.5c-3.5 0-5.5 1.5-5.5 3.5h11c0-2-2-3.5-5.5-3.5z" />
    </svg>
  )
}
function WatchdogIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" className="w-4 h-4">
      <circle cx="10" cy="10" r="7" />
      <path d="M10 6v4l3 2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

// ── Nav structure (no SMB gating — single bank) ───────────────────────────────

const NAV = [
  {
    section: 'Inward CTS',
    Icon: InwardIcon,
    items: [
      { to: '/inward/queue',      label: 'Live Queue' },
      { to: '/inward/decisions',  label: 'Decision History' },
      { to: '/inward/iet',        label: 'IET Monitor', Icon: WatchdogIcon },
    ],
  },
  {
    section: 'Outward CTS',
    Icon: OutwardIcon,
    items: [
      { to: '/outward/batches',      label: 'Batch Overview' },
      { to: '/outward/presentment',  label: 'Presentment Status' },
    ],
  },
  {
    section: 'Risk & Fraud',
    Icon: FraudIcon,
    items: [
      { to: '/fraud',           label: 'Fraud Analytics' },
      { to: '/analytics/ocr',  label: 'OCR Accuracy' },
    ],
  },
  {
    section: 'Compliance',
    Icon: AuditIcon,
    items: [
      { to: '/audit',    label: 'Audit Trail' },
      { to: '/reports',  label: 'Reports' },
    ],
  },
  {
    section: 'Admin',
    Icon: AdminIcon,
    items: [
      { to: '/admin/thresholds',  label: 'Thresholds & Config' },
      { to: '/admin/vault',       label: 'Vault Status' },
      { to: '/admin/users',       label: 'User Management' },
    ],
  },
]

// ── Dual Logo Block ───────────────────────────────────────────────────────────

function DualLogoBlock() {
  return (
    <div className="px-4 py-5 border-b border-white/8 select-none">
      {/* Bank logo — primary, larger */}
      <div className="flex items-center gap-3 mb-3">
        <img
          src={BANK_CONFIG.bank_logo}
          alt={BANK_CONFIG.bank_name}
          className="h-8 w-auto object-contain"
          onError={e => { e.currentTarget.style.display = 'none' }}
        />
      </div>
      {/* ASTRA logo — secondary, smaller, "Powered by" framing */}
      <div className="flex items-center gap-2 opacity-60">
        <span className="text-[10px] text-slate-400 leading-none">Powered by</span>
        <img
          src={BANK_CONFIG.astra_logo}
          alt="ASTRA"
          className="h-4 w-auto object-contain brightness-90"
        />
      </div>
    </div>
  )
}

// ── Sidebar ───────────────────────────────────────────────────────────────────

export default function Sidebar() {
  const { isDark } = useTheme()

  const navLinkClass = ({ isActive }) => [
    'flex items-center gap-2.5 px-3 py-1.5 rounded-md text-[13px] transition-colors',
    isActive
      ? 'text-white font-semibold'
      : isDark
        ? 'text-slate-400 hover:text-slate-200 hover:bg-white/5'
        : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100',
  ].join(' ')

  // Active nav indicator uses brand primary colour from config
  const activeStyle = { backgroundColor: `${BANK_CONFIG.primary_hex}22` }
  const activeBorder = { borderLeft: `2px solid ${BANK_CONFIG.primary_hex}` }

  return (
    <aside className={[
      'w-56 flex-shrink-0 flex flex-col h-full',
      isDark ? 'bg-shell-950 border-r border-white/8' : 'bg-white border-r border-slate-200',
    ].join(' ')}>

      <DualLogoBlock />

      <nav className="flex-1 overflow-y-auto sidebar-scroll py-3 space-y-5">
        {NAV.map(({ section, Icon, items }) => (
          <div key={section} className="px-3">
            <div className={[
              'flex items-center gap-2 text-[10px] font-semibold uppercase tracking-widest mb-1.5 px-1',
              isDark ? 'text-slate-500' : 'text-slate-400',
            ].join(' ')}>
              <Icon />
              {section}
            </div>
            <ul className="space-y-0.5">
              {items.map(({ to, label, Icon: ItemIcon }) => (
                <li key={to}>
                  <NavLink
                    to={to}
                    className={navLinkClass}
                    style={({ isActive }) => isActive ? { ...activeStyle, ...activeBorder } : {}}
                  >
                    {ItemIcon ? <ItemIcon /> : <span className="w-4" />}
                    {label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      {/* Bank tagline at bottom */}
      <div className={[
        'px-5 py-3 border-t text-[10px] italic',
        isDark ? 'border-white/8 text-slate-600' : 'border-slate-200 text-slate-400',
      ].join(' ')}>
        {BANK_CONFIG.tagline}
      </div>
    </aside>
  )
}

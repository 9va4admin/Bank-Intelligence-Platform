import { Link, NavLink } from 'react-router-dom'
import { useTheme } from '../../../shared/theme/ThemeContext'

const NAV_ITEMS = [
  { to: '/ej',               label: 'Command Center', end: true },
  { to: '/ej/incidents',     label: 'Incidents'                 },
  { to: '/ej/disputes',      label: 'Dispute Console'           },
  { to: '/ej/fleet',         label: 'Fleet Map'                 },
  { to: '/ej/portal',        label: 'Manager Portal'            },
  { to: '/ej/bre',           label: 'BRE Policy'                },
  { to: '/ej/notifications', label: 'Notifications'             },
]

const darkGradient = 'linear-gradient(145deg, #020917 0%, #0e1654 38%, #060d2e 65%, #03061a 100%)'

export default function EJShell({ children }) {
  const { isDark, toggle } = useTheme()

  return (
    <div
      className="flex flex-col h-screen"
      style={{ background: isDark ? darkGradient : '#f8fafc', color: isDark ? '#fff' : '#0f172a' }}
    >
      {/* ── Topbar ──────────────────────────────────────── */}
      <header
        className="shrink-0 flex items-center px-5 border-b border-slate-800"
        style={{ height: '52px', background: '#020817' }}
      >
        {/* Logo */}
        <Link to="/" className="flex items-center gap-2 shrink-0 group mr-4">
          <div className="relative w-6 h-6">
            <div className="absolute inset-0 rounded" style={{ background: 'rgba(212,175,55,0.2)' }} />
            <div className="absolute inset-[2px] rounded flex items-center justify-center" style={{ background: '#d4af37' }}>
              <span className="font-mono font-bold text-[10px]" style={{ color: '#020817' }}>A</span>
            </div>
          </div>
          <span className="text-sm font-bold tracking-tight leading-none text-white">stra</span>
        </Link>

        {/* ── Centered dark nav strip ─────────────────── */}
        <div className="flex-1 flex justify-center">
          <nav className="flex items-center gap-1">
            {NAV_ITEMS.map(({ to, label, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  `px-3 py-1.5 text-xs font-medium rounded-md transition-all whitespace-nowrap border ${
                    isActive
                      ? 'bg-cyan-600/20 text-cyan-300 border-cyan-500/30'
                      : 'text-slate-400 hover:text-white hover:bg-white/5 border-transparent'
                  }`
                }
              >
                {label}
              </NavLink>
            ))}
          </nav>
        </div>

        {/* ── Right: module tag + back link + toggle ── */}
        <div className="flex items-center gap-3 shrink-0 ml-4">
          <span className="hidden md:block text-[10px] font-semibold uppercase tracking-widest text-slate-500">EJ Intelligence</span>
          <Link to="/" className="text-[11px] text-slate-400 hover:text-slate-200 transition-colors">
            ← Portal
          </Link>
          <button
            onClick={toggle}
            title={isDark ? 'Switch to light' : 'Switch to dark'}
            className="w-7 h-7 rounded-lg flex items-center justify-center text-sm transition-all shrink-0 text-slate-400 hover:text-white hover:bg-white/8"
          >
            {isDark ? '☀' : '🌙'}
          </button>
        </div>
      </header>

      {/* ── Page content ─────────────────────────────────── */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        {children}
      </div>
    </div>
  )
}

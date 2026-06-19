import { NavLink, Link } from 'react-router-dom'
import { useTheme } from '../theme/ThemeContext'

const NAV = [
  { to: '/cts/outward',   label: 'Outward ↑'     },
  { to: '/cts',           label: 'Inward ↓'      },
  { to: '/cts/vault',     label: 'Vault Status'  },
  { to: '/cts/decisions',  label: 'Decisions Log' },
  { to: '/cts/exceptions',      label: 'Exceptions'      },
  { to: '/cts/reconciliation',  label: 'Reconciliation'  },
  { to: '/cts/compliance',      label: 'Compliance Cert' },
  { to: '/cts/scanner',         label: 'Scanner SDK'     },
  { to: '/cts/analytics',       label: 'Analytics'       },
  { to: '/cts/config',    label: 'Config'        },
]

export default function AppShell({ children }) {
  const { isDark, toggle } = useTheme()

  const shell   = isDark ? 'bg-navy-950 text-white'         : 'bg-slate-50 text-slate-900'
  const topbar  = isDark ? 'bg-navy-900/80 border-white/8'  : 'bg-white border-slate-200'
  const subtext = isDark ? 'text-slate-500'                 : 'text-slate-400'
  const navActive = isDark
    ? 'border-b-2 border-gold-400 text-gold-400 font-medium'
    : 'border-b-2 border-amber-500 text-amber-600 font-medium'
  const navIdle = isDark
    ? 'border-b-2 border-transparent text-slate-400 hover:text-slate-200'
    : 'border-b-2 border-transparent text-slate-500 hover:text-slate-800'
  const userBg  = isDark ? 'bg-gold-400/20 text-gold-400'  : 'bg-amber-100 text-amber-700'
  const userName = isDark ? 'text-slate-300'               : 'text-slate-700'
  const main    = isDark ? 'bg-navy-950'                   : 'bg-slate-50'

  return (
    <div className={`flex flex-col h-screen overflow-hidden ${shell}`}>
      {/* Topbar */}
      <header className={`shrink-0 border-b ${topbar} flex items-center px-5 gap-6`} style={{ height: '52px' }}>
        {/* Logo — links to portal */}
        <Link to="/" className="flex items-center gap-2.5 shrink-0 group">
          <div className="relative w-6 h-6">
            <div className="absolute inset-0 rounded bg-gold-400/20 group-hover:bg-gold-400/30 transition-colors" />
            <div className="absolute inset-[2px] rounded bg-gold-400 flex items-center justify-center">
              <span className="text-navy-950 font-mono font-bold text-[10px]">A</span>
            </div>
          </div>
          <div>
            <span className="text-sm font-bold">ASTRA</span>
            <span className={`text-[10px] ml-1.5 ${subtext}`}>CTS Workstation</span>
          </div>
        </Link>

        {/* Nav links */}
        <nav className="flex items-end h-full gap-1">
          {NAV.map(({ to, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/cts'}
              className={({ isActive }) =>
                `px-3 text-xs h-full flex items-center transition-colors ${isActive ? navActive : navIdle}`
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>

        {/* Right side — bank context + user + toggle */}
        <div className="ml-auto flex items-center gap-4">
          <div className="text-right hidden sm:block">
            <div className={`text-[11px] font-medium ${userName}`}>Saraswat Co-op Bank</div>
            <div className={`text-[10px] ${subtext}`}>Zone: MUMBAI · Finacle</div>
          </div>
          <div className="flex items-center gap-2">
            <div className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold ${userBg}`}>R</div>
            <div className="hidden sm:block">
              <div className={`text-[11px] ${userName}`}>Rahul S.</div>
              <div className={`text-[10px] ${subtext}`}>ops_reviewer</div>
            </div>
          </div>
          <button
            onClick={toggle}
            title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
            className={`w-7 h-7 rounded-lg flex items-center justify-center text-sm transition-all ${
              isDark ? 'hover:bg-white/8 text-slate-400' : 'hover:bg-slate-100 text-slate-500'
            }`}
          >
            {isDark ? '☀' : '🌙'}
          </button>
        </div>
      </header>

      {/* Main content — fills remaining height */}
      <div className={`flex-1 min-h-0 overflow-hidden ${main}`}>
        {children}
      </div>
    </div>
  )
}

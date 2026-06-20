import { useState } from 'react'
import { NavLink, Link, useLocation } from 'react-router-dom'
import { useTheme } from '../theme/ThemeContext'

const NAV_GROUPS = [
  {
    label: 'Processing',
    items: [
      { to: '/cts',          label: 'Inward',   end: true },
      { to: '/cts/outward',  label: 'Outward'  },
      { to: '/cts/vault',    label: 'Vault'    },
      { to: '/cts/scanner',  label: 'Scanner'  },
    ],
  },
  {
    label: 'Reports',
    items: [
      { to: '/cts/decisions',      label: 'Decisions'      },
      { to: '/cts/reconciliation', label: 'Reconciliation' },
      { to: '/cts/analytics',      label: 'Analytics'      },
      { to: '/cts/compliance',     label: 'Compliance'     },
    ],
  },
  {
    label: 'Operations',
    items: [
      { to: '/cts/exceptions',  label: 'Exceptions'  },
      { to: '/cts/endorsement', label: 'Endorsement' },
      { to: '/cts/rpc',         label: 'RPC'         },
      { to: '/cts/sub-member',  label: 'Sub-Member'  },
      { to: '/cts/config',      label: 'Config'      },
    ],
  },
]

export default function AppShell({ children }) {
  const { isDark, toggle } = useTheme()
  const location = useLocation()
  const [openGroup, setOpenGroup] = useState(null)

  const shell  = isDark ? 'bg-navy-950 text-white'        : 'bg-slate-50 text-slate-900'
  const topbar = isDark ? 'bg-navy-900/80 border-white/8' : 'bg-white border-slate-200'
  const subtext = isDark ? 'text-slate-500'               : 'text-slate-400'
  const userBg  = isDark ? 'bg-gold-400/20 text-gold-400' : 'bg-amber-100 text-amber-700'
  const userName = isDark ? 'text-slate-300'              : 'text-slate-700'
  const main   = isDark ? 'bg-navy-950'                   : 'bg-slate-50'

  const dropdownBg = isDark
    ? 'bg-navy-900 border-white/10 shadow-black/30'
    : 'bg-white border-slate-200 shadow-slate-200'

  // Group header: active if any child route matches
  const groupActive = (items) =>
    items.some(({ to, end }) =>
      end ? location.pathname === to : location.pathname.startsWith(to)
    )

  const groupHeaderClass = (items) => {
    const active = groupActive(items)
    if (active) {
      return isDark
        ? 'bg-gold-400/15 text-gold-400 rounded-lg font-medium'
        : 'bg-amber-100 text-amber-700 rounded-lg font-medium'
    }
    return isDark
      ? 'text-slate-400 hover:text-slate-200 hover:bg-white/5 rounded-lg'
      : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded-lg'
  }

  const itemClass = (isActive) => {
    if (isActive) {
      return isDark
        ? 'bg-gold-400/15 text-gold-400 rounded-lg font-medium'
        : 'bg-amber-100 text-amber-700 rounded-lg font-medium'
    }
    return isDark
      ? 'text-slate-400 hover:text-slate-200 hover:bg-white/5 rounded-lg'
      : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded-lg'
  }

  return (
    <div className={`flex flex-col h-screen overflow-hidden ${shell}`}>
      {/* Topbar */}
      <header
        className={`shrink-0 border-b ${topbar} flex items-center px-5 gap-4`}
        style={{ height: '52px' }}
      >
        {/* Logo */}
        <Link to="/" className="flex items-center gap-2.5 shrink-0 group">
          <div className="relative w-6 h-6">
            <div className="absolute inset-0 rounded bg-gold-400/20 group-hover:bg-gold-400/30 transition-colors" />
            <div className="absolute inset-[2px] rounded bg-gold-400 flex items-center justify-center">
              <span className="text-navy-950 font-mono font-bold text-[10px]">A</span>
            </div>
          </div>
          <span className="text-sm tracking-tight">
            <span className="font-bold">A</span>
            <span className="text-gold-400 font-bold">+</span>
            <span className="font-bold">stra</span>
          </span>
        </Link>

        {/* Nav groups */}
        <nav className="flex items-center h-full gap-1 min-w-0 overflow-x-auto shrink-0">
          {NAV_GROUPS.map((group) => (
            <div
              key={group.label}
              className="relative"
              onMouseEnter={() => setOpenGroup(group.label)}
              onMouseLeave={() => setOpenGroup(null)}
            >
              <button
                className={`px-3 py-1.5 text-xs flex items-center gap-1 transition-colors whitespace-nowrap ${groupHeaderClass(group.items)}`}
              >
                {group.label}
                <svg
                  className="w-3 h-3 opacity-60"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2.5}
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                </svg>
              </button>

              {openGroup === group.label && (
                <div
                  className={`absolute top-full left-0 mt-1 min-w-[150px] z-50 rounded-xl border shadow-lg py-1 ${dropdownBg}`}
                >
                  {group.items.map(({ to, label, end }) => (
                    <NavLink
                      key={to}
                      to={to}
                      end={end}
                      className={({ isActive }) =>
                        `block px-3 py-1.5 text-xs transition-colors mx-1 my-0.5 ${itemClass(isActive)}`
                      }
                      onClick={() => setOpenGroup(null)}
                    >
                      {label}
                    </NavLink>
                  ))}
                </div>
              )}
            </div>
          ))}
        </nav>

        {/* Right side — bank context + user + toggle */}
        <div className="ml-auto flex items-center gap-4 shrink-0">
          <div className="text-right hidden sm:block">
            <div className={`text-[11px] font-medium ${userName}`}>Saraswat Co-op Bank</div>
            <div className={`text-[10px] ${subtext}`}>Zone: MUMBAI · Finacle</div>
          </div>
          <div className="flex items-center gap-2">
            <div className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0 ${userBg}`}>R</div>
            <div className="hidden sm:block">
              <div className={`text-[11px] ${userName}`}>Rahul S.</div>
              <div className={`text-[10px] ${subtext}`}>ops_reviewer</div>
            </div>
          </div>
          <button
            onClick={toggle}
            title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
            className={`w-7 h-7 rounded-lg flex items-center justify-center text-sm transition-all shrink-0 ${
              isDark ? 'hover:bg-white/8 text-slate-400' : 'hover:bg-slate-100 text-slate-500'
            }`}
          >
            {isDark ? '☀' : '🌙'}
          </button>
        </div>
      </header>

      {/* Main content */}
      <div className={`flex-1 min-h-0 overflow-hidden ${main}`}>
        {children}
      </div>
    </div>
  )
}

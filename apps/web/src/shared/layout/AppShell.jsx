import { useState } from 'react'
import { NavLink, Link, useLocation } from 'react-router-dom'
import { useTheme } from '../theme/ThemeContext'

const FLAT_NAV = [
  { to: '/cts',         label: 'Inward',  end: true },
  { to: '/cts/outward', label: 'Outward' },
  { to: '/cts/vault',   label: 'Vault'   },
]

const NAV_GROUPS = [
  {
    label: 'Reports',
    items: [
      { to: '/cts/decisions',      label: 'Decisions Log'    },
      { to: '/cts/reconciliation', label: 'Reconciliation'   },
      { to: '/cts/analytics',      label: 'Analytics'        },
      { to: '/cts/compliance',     label: 'Compliance Cert'  },
    ],
  },
  {
    label: 'Operations',
    items: [
      { to: '/cts/sub-member',  label: 'Sub-Member'       },
      { to: '/cts/exceptions',  label: 'Exceptions'       },
      { to: '/cts/endorsement', label: 'Endorsement'      },
      { to: '/cts/scanner',     label: 'Scanner SDK'      },
      { to: '/cts/rpc',         label: 'RPC Consolidation'},
      { to: '/cts/config',      label: 'Config'           },
    ],
  },
]

// All nav entries in order (flat first, then group labels) for divider logic
const ALL_NAV_COUNT = FLAT_NAV.length + NAV_GROUPS.length

export default function AppShell({ children }) {
  const { isDark, toggle } = useTheme()
  const location = useLocation()
  const [openGroup, setOpenGroup] = useState(null)

  const shell    = isDark ? 'bg-navy-950 text-white'        : 'bg-slate-50 text-slate-900'
  const topbar   = isDark ? 'bg-navy-900/80 border-white/8' : 'bg-white border-slate-200'
  const subtext  = isDark ? 'text-slate-500'                : 'text-slate-400'
  const userBg   = isDark ? 'bg-gold-400/20 text-gold-400'  : 'bg-amber-100 text-amber-700'
  const userName = isDark ? 'text-slate-300'                : 'text-slate-700'
  const main     = isDark ? 'bg-navy-950'                   : 'bg-slate-50'

  // Pill container that wraps all nav items
  const navPill = isDark
    ? 'bg-navy-800/60 border border-white/8 rounded-full px-1 py-0.5'
    : 'bg-slate-100 border border-slate-200 rounded-full px-1 py-0.5'

  // Active item — dark capsule (same look as reference image)
  const activePill = isDark
    ? 'bg-slate-700 text-white shadow-sm'
    : 'bg-slate-800 text-white shadow-sm'

  // Idle item
  const idleItem = isDark
    ? 'text-slate-400 hover:text-white hover:bg-white/8'
    : 'text-slate-600 hover:text-slate-900 hover:bg-white'

  // Divider between items
  const divider = isDark ? 'bg-white/10' : 'bg-slate-300'

  // Whether a group has any active child
  const groupHasActive = (items) =>
    items.some(({ to }) => location.pathname.startsWith(to))

  // Dropdown panel
  const dropdownBg = isDark
    ? 'bg-navy-900 border-white/10 shadow-xl shadow-black/50'
    : 'bg-white border-slate-200 shadow-xl shadow-slate-300/50'

  const dropdownItem = isDark
    ? 'text-slate-300 hover:text-white hover:bg-white/8 rounded-lg'
    : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded-lg'

  const dropdownItemActive = isDark
    ? 'bg-slate-700 text-white rounded-lg font-medium'
    : 'bg-slate-800 text-white rounded-lg font-medium'

  // Build nav item list with index for divider rendering
  const flatCount = FLAT_NAV.length
  const totalItems = FLAT_NAV.length + NAV_GROUPS.length

  return (
    <div className={`flex flex-col h-screen overflow-hidden ${shell}`}>
      {/* Topbar */}
      <header
        className={`shrink-0 border-b ${topbar} flex items-center px-5 gap-4`}
        style={{ height: '52px' }}
      >
        {/* Logo: A+stra */}
        <Link to="/" className="flex items-center gap-2 shrink-0 group">
          <div className="relative w-6 h-6">
            <div className="absolute inset-0 rounded bg-gold-400/20 group-hover:bg-gold-400/30 transition-colors" />
            <div className="absolute inset-[2px] rounded bg-gold-400 flex items-center justify-center">
              <span className="text-navy-950 font-mono font-bold text-[10px]">A</span>
            </div>
          </div>
          <span className="text-sm tracking-tight leading-none">
            <span className="font-bold">A</span>
            <span className={`font-bold ${isDark ? 'text-gold-400' : 'text-amber-500'}`}>+</span>
            <span className="font-bold">stra</span>
          </span>
        </Link>

        {/* Pill nav container */}
        <nav className={`flex items-center ${navPill} gap-0 shrink-0`}>

          {/* Flat essential items */}
          {FLAT_NAV.map(({ to, label, end }, idx) => (
            <div key={to} className="flex items-center">
              <NavLink
                to={to}
                end={end}
                className={({ isActive }) =>
                  `px-3.5 py-1 text-xs rounded-full transition-all whitespace-nowrap ${
                    isActive ? activePill : idleItem
                  }`
                }
              >
                {label}
              </NavLink>
              {/* Divider after each item except before last group */}
              {idx < FLAT_NAV.length - 1 || NAV_GROUPS.length > 0 ? (
                <div className={`w-px h-3.5 mx-0.5 shrink-0 ${divider}`} />
              ) : null}
            </div>
          ))}

          {/* Grouped dropdown items */}
          {NAV_GROUPS.map((group, gIdx) => {
            const isGroupActive = groupHasActive(group.items)
            return (
              <div key={group.label} className="flex items-center">
                <div
                  className="relative"
                  onMouseEnter={() => setOpenGroup(group.label)}
                  onMouseLeave={() => setOpenGroup(null)}
                >
                  <button
                    className={`px-3.5 py-1 text-xs rounded-full transition-all whitespace-nowrap flex items-center gap-1 ${
                      isGroupActive ? activePill : idleItem
                    }`}
                  >
                    {group.label}
                    <svg className="w-2.5 h-2.5 opacity-60" fill="none" viewBox="0 0 24 24"
                      stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                    </svg>
                  </button>

                  {openGroup === group.label && (
                    <div className={`absolute top-full left-0 mt-2 min-w-[175px] z-50 rounded-xl border py-1.5 ${dropdownBg}`}>
                      {group.items.map(({ to, label }) => {
                        const isActive = location.pathname.startsWith(to)
                        return (
                          <NavLink
                            key={to}
                            to={to}
                            className={() =>
                              `block px-3 py-1.5 text-xs transition-colors mx-1 my-0.5 ${
                                isActive ? dropdownItemActive : dropdownItem
                              }`
                            }
                            onClick={() => setOpenGroup(null)}
                          >
                            {label}
                          </NavLink>
                        )
                      })}
                    </div>
                  )}
                </div>

                {/* Divider between groups */}
                {gIdx < NAV_GROUPS.length - 1 && (
                  <div className={`w-px h-3.5 mx-0.5 shrink-0 ${divider}`} />
                )}
              </div>
            )
          })}
        </nav>

        {/* Right side */}
        <div className="ml-auto flex items-center gap-4 shrink-0">
          <div className="text-right hidden md:block">
            <div className={`text-[11px] font-medium leading-tight ${userName}`}>Saraswat Co-op Bank</div>
            <div className={`text-[10px] leading-tight ${subtext}`}>Zone: MUMBAI · Finacle</div>
          </div>
          <div className="flex items-center gap-2">
            <div className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0 ${userBg}`}>R</div>
            <div className="hidden sm:block">
              <div className={`text-[11px] leading-tight ${userName}`}>Rahul S.</div>
              <div className={`text-[10px] leading-tight ${subtext}`}>ops_reviewer</div>
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

import { useState, useContext } from 'react'
import { NavLink, Link, useLocation } from 'react-router-dom'
import { useTheme } from '../theme/ThemeContext'
import { PageHeaderCtx } from './PageHeaderContext'
import ChequeSearchBar from './ChequeSearchBar'

// ── Sidebar navigation structure ────────────────────────────────────────────

function CtsIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" className="w-4 h-4">
      <rect x="3" y="5" width="14" height="10" rx="1.5" />
      <path d="M3 8h14" strokeWidth="1.4" />
      <path d="M7 12h2m2 0h2" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  )
}
function AdminIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" className="w-4 h-4">
      <circle cx="10" cy="7" r="3" />
      <path d="M4 17c0-3.314 2.686-5 6-5s6 1.686 6 5" strokeLinecap="round" />
    </svg>
  )
}
function ChevronIcon({ style }) {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" className="w-3 h-3 shrink-0 transition-transform duration-200" style={style}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M6 4l4 4-4 4" />
    </svg>
  )
}

const SIDEBAR_MODULES = [
  {
    id: 'cts',
    label: 'CTS',
    fullLabel: 'Cheque Truncation',
    Icon: CtsIcon,
    sections: [
      {
        label: 'Operations',
        items: [
          { to: '/cts',               label: 'Inward Queue',     end: true },
          { to: '/cts/ops-dashboard', label: 'Ops Dashboard'   },
          { to: '/cts/pipeline',      label: 'Inward Pipeline'  },
          { to: '/cts/outward',       label: 'Outward'          },
          { to: '/cts/drawee',        label: 'Drawee Position'  },
          { to: '/cts/settlement',    label: 'Settlement'       },
        ],
      },
      {
        label: 'Processing',
        items: [
          { to: '/cts/batches',       label: 'Batches'          },
          { to: '/cts/vault',         label: 'Vault'            },
          { to: '/cts/vault-sync',    label: 'PPS & Stop Cheque'},
          { to: '/cts/sub-member',    label: 'Sub-Member'       },
          { to: '/cts/smb/registry',      label: 'SMB Registry'     },
          { to: '/cts/smb/ledger',        label: 'SMB Ledger'       },
          { to: '/cts/smb/forwarding-log',label: 'SMB Fwd Log'      },
          { to: '/cts/endorsement',   label: 'Endorsement'      },
          { to: '/cts/exceptions',    label: 'Exceptions'       },
          { to: '/cts/iqa',           label: 'Image Quality'    },
          { to: '/cts/scanner',       label: 'Scanner SDK'      },
          { to: '/cts/rpc',           label: 'RPC Consolidation'},
        ],
      },
      {
        label: 'Reports',
        items: [
          { to: '/cts/decisions',      label: 'Decisions Log'   },
          { to: '/cts/discrepancy',    label: 'Discrepancy'     },
          { to: '/cts/reconciliation', label: 'Reconciliation'  },
          { to: '/cts/analytics',      label: 'Analytics'       },
          { to: '/cts/compliance',     label: 'Compliance Cert' },
        ],
      },
    ],
  },
  {
    id: 'admin',
    label: 'Admin',
    fullLabel: 'Administration',
    Icon: AdminIcon,
    sections: [
      {
        label: 'Admin',
        items: [
          { to: '/admin/users',                  label: 'User Management'   },
          { to: '/cts/schedules',                label: 'Schedules'         },
          { to: '/cts/config/sub-member-banks',  label: 'Sub-Member Banks'  },
          { to: '/cts/config/micr-prefixes',     label: 'MICR Prefixes'     },
          { to: '/cts/config/thresholds',        label: 'Thresholds'        },
          { to: '/cts/config/ngch-routing',      label: 'NGCH Routing'      },
        ],
      },
    ],
  },
]

const PROFILE_MENU = [
  { to: '/profile', label: 'My Profile', icon: '👤' },
  { to: '/logout',  label: 'Sign Out',   icon: '→'  },
]

const ROUTE_LABELS = {
  '/cts':               ['CTS', 'Inward Queue — Human Review'],
  '/cts/outward':       ['CTS', 'Outward'],
  '/cts/vault':         ['CTS', 'Vault Status'],
  '/cts/vault-sync':    ['Processing', 'Positive Pay & Stop Cheque'],
  '/cts/decisions':     ['Reports', 'Decisions Log'],
  '/cts/reconciliation':['Reports', 'Reconciliation'],
  '/cts/analytics':     ['Reports', 'Analytics'],
  '/cts/compliance':    ['Reports', 'Compliance Cert'],
  '/cts/sub-member':    ['Processing', 'Sub-Member Banks'],
  '/cts/exceptions':    ['Processing', 'Exceptions'],
  '/cts/endorsement':   ['Processing', 'Endorsement'],
  '/cts/iqa':           ['Processing', 'Image Quality Assessment'],
  '/cts/scanner':       ['Processing', 'Scanner SDK'],
  '/cts/rpc':           ['Processing', 'RPC Consolidation'],
  '/cts/pipeline':        ['CTS', 'Inward Pipeline — AI View'],
  '/cts/ops-dashboard':   ['CTS', 'Ops Dashboard'],
  '/cts/drawee':          ['CTS', 'Drawee & Outward Position'],
  '/cts/settlement':      ['CTS', 'Settlement Lifecycle'],
  '/cts/batches':         ['Processing', 'Batches'],
  '/cts/discrepancy':     ['Reports', 'Discrepancy'],
  '/admin/users':         ['Admin', 'User Management'],
  '/cts/schedules':       ['Admin', 'Temporal Schedules'],
  '/cts/config':          ['Admin', 'Configuration'],
  '/cts/config/sub-member-banks': ['Admin · Config', 'Sub-Member Banks'],
  '/cts/config/micr-prefixes':    ['Admin · Config', 'MICR Prefix Table'],
  '/cts/config/thresholds':       ['Admin · Config', 'Thresholds & Rules'],
  '/cts/config/ngch-routing':     ['Admin · Config', 'NGCH Routing'],
  '/cts/smb/registry':            ['Processing', 'SMB Registry'],
  '/cts/smb/ledger':              ['Processing', 'SMB Clearing Ledger'],
  '/cts/smb/forwarding-log':      ['Processing', 'SMB Forwarding Log'],
}

function useBreadcrumb(pathname) {
  const matched = Object.entries(ROUTE_LABELS)
    .filter(([key]) => pathname === key || pathname.startsWith(key + '/'))
    .sort((a, b) => b[0].length - a[0].length)[0]
  return matched ? matched[1] : ['ASTRA', '']
}

function activeModuleId(pathname) {
  if (pathname.startsWith('/admin') || pathname.startsWith('/cts/config')) return 'admin'
  return 'cts'
}

// ── AppShell ────────────────────────────────────────────────────────────────

export default function AppShell({ children }) {
  const { isDark, toggle } = useTheme()
  const location = useLocation()
  const [collapsed, setCollapsed] = useState(false)
  const [profileOpen, setProfileOpen] = useState(false)

  const [section, page] = useBreadcrumb(location.pathname)
  const currentModule = activeModuleId(location.pathname)

  const darkGradient = 'linear-gradient(145deg, #020917 0%, #0e1654 38%, #060d2e 65%, #03061a 100%)'

  const th = {
    shell:    isDark ? 'text-white' : 'bg-slate-100 text-slate-900',
    sidebar:  isDark ? 'bg-[#040d2a] border-white/8' : 'bg-white border-slate-200',
    topbar:   isDark ? 'bg-navy-950/95 backdrop-blur-md border-white/10' : 'bg-white border-slate-200',
    content:  isDark ? 'bg-black/15' : 'bg-slate-50',
  }

  return (
    <div
      className={`flex h-screen overflow-hidden ${th.shell}`}
      style={isDark ? { background: darkGradient } : undefined}
    >
      {/* ── Left Sidebar ──────────────────────────────────────────────────── */}
      <aside
        className={`shrink-0 flex flex-col border-r transition-all duration-200 ${th.sidebar}`}
        style={{ width: collapsed ? '52px' : '200px' }}
      >
        {/* Logo row */}
        <div className={`flex items-center h-[52px] px-3 border-b shrink-0 ${isDark ? 'border-white/8' : 'border-slate-200'}`}>
          <Link to="/" className="flex items-center gap-2 group min-w-0">
            <div className="relative w-6 h-6 shrink-0">
              <div className="absolute inset-0 rounded bg-gold-400/20 group-hover:bg-gold-400/30 transition-colors" />
              <div className="absolute inset-[2px] rounded bg-gold-400 flex items-center justify-center">
                <span className="text-navy-950 font-mono font-bold text-[10px]">A</span>
              </div>
            </div>
            {!collapsed && (
              <span className={`text-sm font-bold tracking-tight leading-none transition-opacity ${isDark ? 'text-white' : 'text-slate-900'}`}>
                stra
              </span>
            )}
          </Link>
          {!collapsed && (
            <button
              onClick={() => setCollapsed(true)}
              className={`ml-auto p-1 rounded-md opacity-40 hover:opacity-100 transition-opacity ${isDark ? 'hover:bg-white/10' : 'hover:bg-slate-100'}`}
              title="Collapse sidebar"
            >
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" className="w-3.5 h-3.5">
                <path strokeLinecap="round" strokeLinejoin="round" d="M10 4L6 8l4 4" />
              </svg>
            </button>
          )}
          {collapsed && (
            <button
              onClick={() => setCollapsed(false)}
              className={`w-full flex justify-center p-1 rounded-md opacity-40 hover:opacity-100 transition-opacity ${isDark ? 'hover:bg-white/10' : 'hover:bg-slate-100'}`}
              title="Expand sidebar"
            >
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" className="w-3.5 h-3.5">
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 4l4 4-4 4" />
              </svg>
            </button>
          )}
        </div>

        {/* Nav modules */}
        <nav className="flex-1 overflow-y-auto overflow-x-hidden py-2 scrollbar-thin">
          {SIDEBAR_MODULES.map((mod) => (
            <SidebarModule
              key={mod.id}
              mod={mod}
              collapsed={collapsed}
              isDark={isDark}
              isActiveModule={currentModule === mod.id}
              location={location}
            />
          ))}
        </nav>

        {/* Bottom: user info */}
        <div className={`shrink-0 border-t px-2 py-2 ${isDark ? 'border-white/8' : 'border-slate-200'}`}>
          <div className="relative">
            <button
              onClick={() => setProfileOpen((v) => !v)}
              className={`w-full flex items-center gap-2 rounded-lg px-1.5 py-1.5 transition-all ${isDark ? 'hover:bg-white/8' : 'hover:bg-slate-100'}`}
            >
              <div className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0 ${isDark ? 'bg-gold-400/20 text-gold-400' : 'bg-amber-100 text-amber-700'}`}>R</div>
              {!collapsed && (
                <div className="text-left min-w-0 flex-1">
                  <div className={`text-[11px] font-medium leading-tight truncate ${isDark ? 'text-white' : 'text-slate-700'}`}>Rahul S.</div>
                  <div className={`text-[10px] leading-tight truncate ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>ops_reviewer</div>
                </div>
              )}
            </button>

            {profileOpen && (
              <div
                className={`absolute bottom-full mb-2 ${collapsed ? 'left-full ml-2' : 'left-0'} w-48 z-50 rounded-xl border py-2 shadow-2xl ${isDark ? 'bg-[#0e1654]/98 backdrop-blur-xl border-white/10 shadow-black/60' : 'bg-white border-slate-200 shadow-slate-400/30'}`}
                style={{ minWidth: '160px' }}
              >
                {!collapsed && (
                  <div className={`px-3 pb-2 mb-1 border-b ${isDark ? 'border-white/8' : 'border-slate-100'}`}>
                    <div className={`text-[11px] font-semibold ${isDark ? 'text-white' : 'text-slate-700'}`}>Saraswat Co-op Bank</div>
                    <div className={`text-[10px] ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>Zone: MUMBAI · Finacle</div>
                  </div>
                )}
                {PROFILE_MENU.map((item) => (
                  <Link
                    key={item.to} to={item.to}
                    className={`flex items-center gap-2.5 px-3 py-1.5 text-xs mx-1 my-0.5 rounded-lg transition-colors ${isDark ? 'text-slate-300 hover:text-white hover:bg-white/10' : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'}`}
                    onClick={() => setProfileOpen(false)}
                  >
                    <span className="w-4 text-center opacity-70">{item.icon}</span>
                    {item.label}
                  </Link>
                ))}
              </div>
            )}
          </div>
        </div>
      </aside>

      {/* ── Main area ─────────────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">

        {/* Topbar */}
        <header className={`shrink-0 border-b flex items-center px-5 gap-4 ${th.topbar}`} style={{ height: '52px' }}>

          {/* Breadcrumb */}
          <div className="flex items-center gap-1.5 min-w-0 flex-1">
            <span className={`text-[11px] shrink-0 ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>{section}</span>
            <span className={`text-[11px] opacity-30 shrink-0 ${isDark ? 'text-slate-400' : 'text-slate-400'}`}>›</span>
            <span className={`text-[13px] font-semibold truncate ${isDark ? 'text-white' : 'text-slate-800'}`}>{page}</span>
          </div>

          {/* Search bar */}
          <ChequeSearchBar isDark={isDark} />

          {/* Right: bank info + theme toggle */}
          <div className="flex items-center gap-4 shrink-0">
            <div className="text-right hidden lg:block">
              <div className={`text-[11px] font-medium leading-tight ${isDark ? 'text-white' : 'text-slate-700'}`}>Saraswat Co-op Bank</div>
              <div className={`text-[10px] leading-tight ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>Zone: MUMBAI · Finacle</div>
            </div>
            <button
              onClick={toggle}
              title={isDark ? 'Switch to light' : 'Switch to dark'}
              className={`w-7 h-7 rounded-lg flex items-center justify-center text-sm transition-all shrink-0 ${isDark ? 'hover:bg-white/10 text-slate-200' : 'hover:bg-slate-100 text-slate-500'}`}
            >
              {isDark ? '☀' : '🌙'}
            </button>
          </div>
        </header>

        {/* Sub-header from pages */}
        <PageHeaderBar isDark={isDark} />

        {/* Content */}
        <div className={`flex-1 min-h-0 overflow-y-auto ${th.content}`}>
          {children}
        </div>
      </div>
    </div>
  )
}

// ── SidebarModule ────────────────────────────────────────────────────────────

function SidebarModule({ mod, collapsed, isDark, isActiveModule, location }) {
  const [open, setOpen] = useState(isActiveModule)
  const [expandedSections, setExpandedSections] = useState(() => {
    const set = new Set()
    mod.sections.forEach((sec) => {
      if (sec.items.some(({ to }) => location.pathname === to || location.pathname.startsWith(to + '/'))) {
        set.add(sec.label)
      }
    })
    if (set.size === 0 && mod.sections.length > 0) set.add(mod.sections[0].label)
    return set
  })

  const hasActiveItem = mod.sections.some((sec) =>
    sec.items.some(({ to }) => location.pathname === to || location.pathname.startsWith(to + '/'))
  )

  const toggleSection = (label) => {
    setExpandedSections((prev) => {
      const next = new Set(prev)
      if (next.has(label)) next.delete(label)
      else next.add(label)
      return next
    })
  }

  if (collapsed) {
    return (
      <div className="px-1.5 mb-1">
        <NavLink
          to={mod.sections[0]?.items[0]?.to ?? '/'}
          title={mod.fullLabel}
          className={`flex justify-center items-center w-8 h-8 mx-auto rounded-lg transition-all ${
            isActiveModule
              ? (isDark ? 'bg-white/20 text-white' : 'bg-slate-800 text-white')
              : (isDark ? 'text-slate-400 hover:text-white hover:bg-white/10' : 'text-slate-500 hover:text-slate-900 hover:bg-slate-100')
          }`}
        >
          <mod.Icon />
        </NavLink>
      </div>
    )
  }

  return (
    <div className="mb-1">
      {/* Module header */}
      <button
        onClick={() => setOpen((v) => !v)}
        className={`w-full flex items-center gap-2 px-3 py-2 text-[11px] font-semibold uppercase tracking-widest transition-all ${
          hasActiveItem
            ? (isDark ? 'text-gold-400' : 'text-amber-600')
            : (isDark ? 'text-slate-500 hover:text-slate-300' : 'text-slate-400 hover:text-slate-600')
        }`}
      >
        <span className={hasActiveItem ? (isDark ? 'text-gold-400' : 'text-amber-600') : (isDark ? 'text-slate-500' : 'text-slate-400')}>
          <mod.Icon />
        </span>
        <span className="flex-1 text-left">{mod.label}</span>
        <ChevronIcon style={{ transform: open ? 'rotate(90deg)' : 'rotate(0deg)' }} />
      </button>

      {/* Module sections */}
      {open && (
        <div>
          {mod.sections.map((sec) => (
            <SidebarSection
              key={sec.label}
              section={sec}
              isDark={isDark}
              location={location}
              showHeader={mod.sections.length > 1}
              expanded={expandedSections.has(sec.label)}
              onToggle={() => toggleSection(sec.label)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// ── SidebarSection ───────────────────────────────────────────────────────────

function SidebarSection({ section, isDark, location, showHeader, expanded, onToggle }) {
  const hasActive = section.items.some(({ to }) =>
    location.pathname === to || location.pathname.startsWith(to + '/')
  )

  return (
    <div>
      {showHeader && (
        <button
          onClick={onToggle}
          className={`w-full flex items-center gap-1.5 px-3 py-1 text-[10px] font-medium uppercase tracking-wider transition-all ${
            hasActive
              ? (isDark ? 'text-slate-300' : 'text-slate-600')
              : (isDark ? 'text-slate-600 hover:text-slate-400' : 'text-slate-400 hover:text-slate-600')
          }`}
        >
          <ChevronIcon style={{ transform: expanded ? 'rotate(90deg)' : 'rotate(0deg)' }} />
          {section.label}
        </button>
      )}

      {(expanded || !showHeader) && (
        <ul className="pb-1">
          {section.items.map(({ to, label, end }) => {
            const isActive = end ? location.pathname === to : (location.pathname === to || location.pathname.startsWith(to + '/'))
            return (
              <li key={to}>
                <NavLink
                  to={to} end={end}
                  className={`flex items-center gap-2 pl-6 pr-3 py-1.5 text-xs transition-all rounded-lg mx-1.5 my-0.5 ${
                    isActive
                      ? (isDark ? 'bg-white/15 text-white font-medium' : 'bg-slate-800 text-white font-medium')
                      : (isDark ? 'text-slate-400 hover:text-white hover:bg-white/8' : 'text-slate-500 hover:text-slate-900 hover:bg-slate-100')
                  }`}
                >
                  {isActive && (
                    <span className={`w-1 h-1 rounded-full shrink-0 ${isDark ? 'bg-gold-400' : 'bg-amber-500'}`} />
                  )}
                  <span className={isActive ? '' : 'pl-3'}>{label}</span>
                </NavLink>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

// ── PageHeaderBar ─────────────────────────────────────────────────────────────

function PageHeaderBar({ isDark }) {
  const { subtitle, actions } = useContext(PageHeaderCtx)
  if (!subtitle && !actions) return null

  return (
    <div
      className="shrink-0 border-b flex items-center px-6 gap-2"
      style={{
        height: '40px',
        background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(255,255,255,0.85)',
        borderColor: isDark ? 'rgba(255,255,255,0.08)' : 'rgb(241 245 249)',
        backdropFilter: 'blur(8px)',
      }}
    >
      <div className="ml-auto flex items-center gap-4">
        {subtitle && <span className={`text-[11px] ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>{subtitle}</span>}
        {actions}
      </div>
    </div>
  )
}

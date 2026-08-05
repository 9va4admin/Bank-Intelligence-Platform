import { useState, useEffect, useContext } from 'react'
import { NavLink, Link, useLocation } from 'react-router-dom'
import { useTheme } from '../theme/ThemeContext'
import { BANK_CONFIG } from '../config/bank.config'
import { PageHeaderCtx } from './PageHeaderContext'

// ── Icons ────────────────────────────────────────────────────────────────────

function CtsIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" className="w-4 h-4">
      <rect x="3" y="5" width="14" height="10" rx="1.5" />
      <path d="M3 8h14" strokeWidth="1.4" />
      <path d="M7 12h2m2 0h2" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  )
}
function OpsIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" className="w-4 h-4">
      <path d="M3 14l4-5 3 3 4-6 3 3" strokeLinecap="round" strokeLinejoin="round" />
      <rect x="2" y="3" width="16" height="14" rx="1.5" />
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
function BranchIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" className="w-4 h-4">
      <path d="M10 3v14M5 7l5-4 5 4" strokeLinecap="round" strokeLinejoin="round" />
      <rect x="3" y="12" width="4" height="5" rx="1" />
      <rect x="13" y="12" width="4" height="5" rx="1" />
      <rect x="8" y="12" width="4" height="5" rx="1" />
    </svg>
  )
}
function ChevronIcon({ style }) {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2"
      className="w-3 h-3 shrink-0 transition-transform duration-200" style={style}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M6 4l4 4-4 4" />
    </svg>
  )
}

// ── Nav — same labels/hierarchy as main app; sbOnly + smbOnly items removed ──

const SIDEBAR_MODULES = [
  {
    id: 'cts', label: 'CTS', fullLabel: 'Cheque Truncation', Icon: CtsIcon,
    sections: [
      {
        label: 'Dashboard', directLink: true,
        items: [{ to: '/cts/ops-dashboard', label: 'Ops Dashboard', end: true }],
      },
      {
        label: 'Settlement', directLink: true,
        items: [{ to: '/cts/settlement', label: 'Settlement' }],
      },
      {
        label: 'Outward Clearing',
        items: [
          { to: '/cts/outward',              label: 'Outward Monitor',  end: true },
          { to: '/cts/outward/verification', label: 'Verification OQ'            },
          { to: '/cts/outward/queue',        label: 'Validation OQ'              },
          { to: '/cts/outward/submission',   label: 'Submission OQ'              },
          { to: '/cts/presentment-file',     label: 'Outward File'               },
        ],
      },
      {
        label: 'Inward Clearing',
        items: [
          { to: '/cts/pipeline',            label: 'Inward Monitor'           },
          { to: '/cts/inward/verification', label: 'Verification IQ'          },
          { to: '/cts',                     label: 'Validation IQ', end: true  },
          { to: '/cts/inward/submission',   label: 'Submission IQ'            },
          { to: '/cts/inward/review-queue', label: 'Human Review Queue'       },
          { to: '/cts/hold-queue',          label: 'Hold Queue'               },
          { to: '/cts/recall',              label: 'Recall'                   },
        ],
      },
      {
        label: 'Processing',
        items: [
          { to: '/cts/batches',     label: 'Batches'                          },
          { to: '/cts/vault',       label: 'Vault'                            },
          { to: '/cts/vault-sync',  label: 'PPS & Stop Cheque'               },
          { to: '/cts/endorsement', label: 'Endorsement'                      },
          { to: '/cts/exceptions',  label: 'Exceptions'                       },
          { to: '/cts/iqa',         label: 'Image Quality'                    },
          { to: '/cts/scanner',     label: 'Scanner SDK'                      },
          { to: '/cts/rf-drawee',   label: 'Rejection File - By Drawee Bank'  },
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
      {
        label: 'Branch Portal',
        items: [
          { to: '/branch',          label: 'Branch Dashboard' },
          { to: '/branch/scan',     label: 'Scanner Monitor'  },
          { to: '/branch/mismatch', label: 'Mismatch Queue'   },
          { to: '/branch/history',  label: 'Session History'  },
        ],
      },
      {
        label: 'Miscellaneous',
        items: [
          { to: '/cts/demo',            label: '⚡ Live Demo'         },
          { to: '/cts/inward-pipeline', label: 'Pipeline (Animated)' },
          { to: '/cts/cloud-ai-demo',   label: '☁️ Cloud AI Extract' },
          { to: '/cts/sig-batch-test',  label: '🖊️ Sig Batch Test'   },
        ],
      },
    ],
  },
  {
    id: 'branch-ops', label: 'Branch', fullLabel: 'Branch Operations', Icon: BranchIcon,
    sections: [
      {
        label: 'Hold Queue', directLink: true,
        items: [{ to: '/branch/hold-queue', label: 'Inward Hold Queue' }],
      },
    ],
  },
  {
    id: 'ops', label: 'Ops', fullLabel: 'Platform Operations', Icon: OpsIcon,
    sections: [
      {
        label: 'ASTRA Ops Dashboard',
        items: [
          { to: '/ops/dashboard',    label: 'Ops Overview'  },
          { to: '/ops/model-health', label: 'Model Health'  },
          { to: '/ops/alerts',       label: 'Alert Log'     },
          { to: '/ops/system',       label: 'System Health' },
        ],
      },
    ],
  },
  {
    id: 'admin', label: 'Admin', fullLabel: 'Administration', Icon: AdminIcon,
    sections: [
      {
        label: 'Admin',
        items: [
          { to: '/admin/users',                label: 'User Management'   },
          { to: '/cts/schedules',              label: 'Schedules'         },
          { to: '/cts/config',                 label: 'Configuration'     },
          { to: '/cts/config/micr-prefixes',   label: 'MICR Prefixes'    },
          { to: '/cts/config/thresholds',      label: 'Thresholds'        },
          { to: '/cts/config/mcp-connections', label: 'MCP Connections'   },
          { to: '/admin/config/operations',    label: 'Operations Config' },
          { to: '/admin/config/platform',      label: 'Platform Config'   },
          { to: '/admin/allocation',           label: 'Allocation Panel'  },
          { to: '/admin/smoke-test',           label: '✓ Go-Live Test'    },
        ],
      },
    ],
  },
]

const ROUTE_LABELS = {
  '/cts':                        ['Inward Clearing',       'Validation IQ — Human Review'],
  '/cts/inward/verification':    ['Inward Clearing',       'Verification IQ — Stage 1 Review Queue'],
  '/cts/inward/submission':      ['Inward Clearing',       'Submission IQ — Stage 3 Confirm / Return'],
  '/cts/outward':                ['Outward Clearing',      'Outward Monitor'],
  '/cts/outward/verification':   ['Outward Clearing',      'Verification OQ — Stage 1 IQA / MICR Review'],
  '/cts/outward/queue':          ['Outward Clearing',      'Validation OQ — Stage 2 OCR Validation'],
  '/cts/outward/submission':     ['Outward Clearing',      'Submission OQ — Stage 3 NGCH Submission'],
  '/cts/presentment-file':       ['Presentation Process',  'Presentment File'],
  '/cts/rf-drawee':              ['Presentation Process',  'RF — Drawee Bank'],
  '/cts/vault':                  ['CTS',                   'Vault Status'],
  '/cts/vault-sync':             ['Processing',            'Positive Pay & Stop Cheque'],
  '/cts/decisions':              ['Reports',               'Decisions Log'],
  '/cts/reconciliation':         ['Reports',               'Reconciliation'],
  '/cts/analytics':              ['Reports',               'Analytics'],
  '/cts/compliance':             ['Reports',               'Compliance Cert'],
  '/cts/exceptions':             ['Processing',            'Exceptions'],
  '/cts/endorsement':            ['Processing',            'Endorsement'],
  '/cts/iqa':                    ['Processing',            'Image Quality Assessment'],
  '/cts/scanner':                ['Processing',            'Scanner SDK'],
  '/cts/pipeline':               ['Drawee Process',        'Inward Pipeline — AI View'],
  '/cts/inward-pipeline':        ['Drawee Process',        'Inward Pipeline — Animated'],
  '/cts/demo':                   ['Demo',                  'End-to-End Live Demo'],
  '/cts/cloud-ai-demo':          ['Demo',                  'Cloud AI Cheque Extraction'],
  '/cts/recall':                 ['Drawee Process',        'Recall'],
  '/cts/ops-dashboard':          ['Dashboard',             'Ops Dashboard'],
  '/cts/settlement':             ['Settlement',            'Settlement Lifecycle'],
  '/cts/batches':                ['Processing',            'Batches'],
  '/cts/discrepancy':            ['Reports',               'Discrepancy'],
  '/admin/users':                ['Admin',                 'User Management'],
  '/cts/schedules':              ['Admin',                 'Temporal Schedules'],
  '/cts/config':                 ['Admin',                 'Configuration'],
  '/cts/config/micr-prefixes':   ['Admin · Config',        'MICR Prefix Table'],
  '/cts/config/thresholds':      ['Admin · Config',        'Thresholds & Rules'],
  '/cts/config/mcp-connections': ['Admin · Config',        'MCP Connection Setup'],
  '/admin/config/operations':    ['Admin · Config',        'Operations Config'],
  '/admin/config/platform':      ['Admin · Config',        'Platform Config'],
  '/admin/allocation':           ['Admin · Queue',         'Allocation Control Panel'],
  '/admin/smoke-test':           ['Admin',                 'Pre-Live Smoke Test'],
  '/branch':                     ['Branch Portal',         'Dashboard'],
  '/branch/scan':                ['Branch Portal',         'Scanner Monitor'],
  '/branch/mismatch':            ['Branch Portal',         'Mismatch Queue'],
  '/branch/history':             ['Branch Portal',         'Session History'],
  '/branch/hold-queue':          ['Branch Operations',     'Inward Hold Queue'],
  '/cts/inward/review-queue':    ['Inward Clearing',       'Human Review Queue'],
  '/cts/hold-queue':             ['Inward Clearing',       'Hold Queue'],
  '/ops/dashboard':              ['Platform Ops',          'ASTRA Ops Overview'],
  '/ops/model-health':           ['Platform Ops',          'AI Model Health — 7-Day Drift'],
  '/ops/alerts':                 ['Platform Ops',          'Alert Log — CRITICAL/ERROR (24h)'],
  '/ops/system':                 ['Platform Ops',          'System Health'],
}

function itemMatches({ to, end }, pathname) {
  return end ? pathname === to : (pathname === to || pathname.startsWith(to + '/'))
}

function useBreadcrumb(pathname) {
  const matched = Object.entries(ROUTE_LABELS)
    .filter(([key]) => pathname === key || pathname.startsWith(key + '/'))
    .sort((a, b) => b[0].length - a[0].length)[0]
  return matched ? matched[1] : ['ASTRA', '']
}

function activeModuleId(pathname) {
  if (pathname.startsWith('/admin') || pathname.startsWith('/cts/config')) return 'admin'
  if (pathname.startsWith('/ops')) return 'ops'
  if (pathname.startsWith('/branch/hold-queue')) return 'branch-ops'
  return 'cts'
}

// ── Sidebar header: [A]stra ·············· [<] ───────────────────────────────

function SidebarHeader({ collapsed, isDark, onToggle }) {
  return (
    <div
      className={`flex items-center gap-2 border-b shrink-0 px-3 ${isDark ? 'border-white/8' : 'border-slate-200'}`}
      style={{ height: '52px' }}
    >
      <Link to="/" className="flex items-center gap-0.5 group shrink-0">
        <div className="relative w-6 h-6 shrink-0">
          <div className="absolute inset-0 rounded bg-gold-400/20 group-hover:bg-gold-400/30 transition-colors" />
          <div className="absolute inset-[2px] rounded bg-gold-400 flex items-center justify-center">
            <span className="text-navy-950 font-mono font-bold text-[10px]">A</span>
          </div>
        </div>
        {!collapsed && (
          <span className={`text-sm font-bold tracking-tight leading-none ${isDark ? 'text-white' : 'text-slate-900'}`}>
            stra
          </span>
        )}
      </Link>

      <button
        onClick={onToggle}
        className={`ml-auto p-1 rounded-md opacity-40 hover:opacity-100 transition-opacity shrink-0 ${isDark ? 'hover:bg-white/10' : 'hover:bg-slate-100'}`}
        title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" className="w-3.5 h-3.5">
          <path strokeLinecap="round" strokeLinejoin="round"
            d={collapsed ? 'M6 4l4 4-4 4' : 'M10 4L6 8l4 4'} />
        </svg>
      </button>
    </div>
  )
}

// ── Topbar right: bank logo | bell | theme | profile ─────────────────────────

function BellIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" className="w-4 h-4">
      <path d="M10 2a6 6 0 00-6 6c0 3-1.5 4-1.5 4h15s-1.5-1-1.5-4a6 6 0 00-6-6z" strokeLinejoin="round" />
      <path d="M11.73 17a2 2 0 01-3.46 0" strokeLinecap="round" />
    </svg>
  )
}

function TopbarRight({ isDark, toggle }) {
  const [profileOpen, setProfileOpen] = useState(false)

  return (
    <div className="flex items-center gap-1 shrink-0">

      {/* Bank logo */}
      <div className={`flex items-center px-3 mr-1 border-r ${isDark ? 'border-white/10' : 'border-slate-200'}`}>
        <img
          src={BANK_CONFIG.bank_logo}
          alt={BANK_CONFIG.bank_name}
          className="h-6 w-auto object-contain"
          style={{ maxWidth: '110px' }}
          onError={e => {
            e.currentTarget.style.display = 'none'
            if (e.currentTarget.nextSibling) e.currentTarget.nextSibling.style.display = 'block'
          }}
        />
        <span className={`text-xs font-semibold hidden ${isDark ? 'text-slate-200' : 'text-slate-700'}`}>
          {BANK_CONFIG.bank_short_name}
        </span>
      </div>

      {/* Notification bell */}
      <div className="relative">
        <button className={`w-8 h-8 flex items-center justify-center rounded-lg transition-colors ${isDark ? 'text-slate-400 hover:text-white hover:bg-white/8' : 'text-slate-500 hover:text-slate-800 hover:bg-slate-100'}`}>
          <BellIcon />
          {/* Unread dot — hide when no notifications */}
          <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 rounded-full bg-red-500" />
        </button>
      </div>

      {/* Theme toggle */}
      <button
        onClick={toggle}
        title={isDark ? 'Switch to light' : 'Switch to dark'}
        className={`w-8 h-8 flex items-center justify-center rounded-lg text-sm transition-colors ${isDark ? 'text-slate-400 hover:text-white hover:bg-white/8' : 'text-slate-500 hover:text-slate-800 hover:bg-slate-100'}`}
      >
        {isDark ? '☀' : '🌙'}
      </button>

      {/* Profile */}
      <div className="relative ml-1">
        <button
          onClick={() => setProfileOpen(v => !v)}
          className={`flex items-center gap-2 rounded-lg pl-2 pr-2.5 py-1.5 transition-colors ${isDark ? 'hover:bg-white/8' : 'hover:bg-slate-100'}`}
        >
          <div className={`w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-bold shrink-0 ${isDark ? 'bg-gold-400/20 text-gold-400' : 'bg-amber-100 text-amber-700'}`}>
            U
          </div>
          <div className="hidden md:block text-left leading-tight">
            <div className={`text-[11px] font-medium ${isDark ? 'text-white' : 'text-slate-700'}`}>User</div>
            <div className={`text-[10px] ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>{BANK_CONFIG.bank_short_name}</div>
          </div>
          <span className={`text-[9px] ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>▾</span>
        </button>

        {profileOpen && (
          <div
            className={`absolute right-0 top-full mt-2 w-48 z-50 rounded-xl border py-2 shadow-2xl ${isDark ? 'bg-[#0e1654] border-white/10' : 'bg-white border-slate-200'}`}
            onMouseLeave={() => setProfileOpen(false)}
          >
            <div className={`px-3 pb-2 mb-1 border-b ${isDark ? 'border-white/8' : 'border-slate-100'}`}>
              <div className={`text-[11px] font-semibold ${isDark ? 'text-white' : 'text-slate-700'}`}>{BANK_CONFIG.bank_name}</div>
              <div className={`text-[10px] mt-0.5 ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>{BANK_CONFIG.clearing_zone} · {BANK_CONFIG.ifsc_prefix}</div>
            </div>
            {[
              { label: 'My Profile',  icon: '👤', to: '/profile'  },
              { label: 'Settings',    icon: '⚙️',  to: '/settings' },
              { label: 'Sign Out',    icon: '→',   to: '/logout'   },
            ].map(item => (
              <button
                key={item.label}
                className={`w-full flex items-center gap-2.5 px-3 py-1.5 text-xs text-left mx-0 transition-colors ${isDark ? 'text-slate-300 hover:text-white hover:bg-white/8' : 'text-slate-600 hover:text-slate-900 hover:bg-slate-50'}`}
                onClick={() => setProfileOpen(false)}
              >
                <span className="w-4 text-center opacity-70">{item.icon}</span>
                {item.label}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ── AppShell ──────────────────────────────────────────────────────────────────

export default function AppShell({ children }) {
  const { isDark, toggle } = useTheme()
  const location = useLocation()
  const [collapsed, setCollapsed] = useState(false)

  const [section, page] = useBreadcrumb(location.pathname)
  const currentModule = activeModuleId(location.pathname)
  const [openModuleId, setOpenModuleId] = useState(currentModule)

  useEffect(() => { setOpenModuleId(currentModule) }, [currentModule])

  const darkGradient = 'linear-gradient(145deg, #020917 0%, #0e1654 38%, #060d2e 65%, #03061a 100%)'

  const th = {
    shell:   isDark ? 'text-white' : 'bg-slate-100 text-slate-900',
    sidebar: isDark ? 'bg-[#040d2a] border-white/8' : 'bg-white border-slate-200',
    topbar:  isDark ? 'bg-navy-950/95 backdrop-blur-md border-white/10' : 'bg-white border-slate-200',
    content: isDark ? 'bg-black/15' : 'bg-slate-50',
  }

  return (
    <div
      className={`flex h-screen overflow-hidden ${th.shell}`}
      style={isDark ? { background: darkGradient } : undefined}
    >
      {/* ── Sidebar ─────────────────────────────────────────────────────── */}
      <aside
        className={`shrink-0 flex flex-col border-r transition-all duration-200 ${th.sidebar}`}
        style={{ width: collapsed ? '52px' : '200px' }}
      >
        <SidebarHeader collapsed={collapsed} isDark={isDark} onToggle={() => setCollapsed(v => !v)} />

        <nav className="flex-1 overflow-y-auto overflow-x-hidden py-2">
          {SIDEBAR_MODULES.map(mod => (
            <SidebarModule
              key={mod.id}
              mod={mod}
              collapsed={collapsed}
              isDark={isDark}
              isActiveModule={currentModule === mod.id}
              open={openModuleId === mod.id}
              onToggle={() => setOpenModuleId(id => id === mod.id ? null : mod.id)}
              location={location}
            />
          ))}
        </nav>
      </aside>

      {/* ── Main area ───────────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <header
          className={`relative z-40 shrink-0 border-b flex items-center px-5 gap-4 ${th.topbar}`}
          style={{ height: '52px' }}
        >
          <div className="flex items-center gap-1.5 min-w-0 flex-1">
            <span className={`text-[11px] shrink-0 ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>{section}</span>
            <span className="text-[11px] opacity-30 shrink-0">›</span>
            <span className={`text-[13px] font-semibold truncate ${isDark ? 'text-white' : 'text-slate-800'}`}>{page}</span>
          </div>
          <TopbarRight isDark={isDark} toggle={toggle} />
        </header>

        {/* Sub-header from pages */}
        <PageHeaderBar isDark={isDark} />

        <div className={`flex-1 min-h-0 overflow-y-auto ${th.content}`}>
          {children}
        </div>
      </div>
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

// ── SidebarModule ─────────────────────────────────────────────────────────────

function SidebarModule({ mod, collapsed, isDark, isActiveModule, open, onToggle, location }) {
  const [expandedSections, setExpandedSections] = useState(() => {
    const active = mod.sections.find(sec => sec.items.some(item => itemMatches(item, location.pathname)))
    const label = active?.label ?? mod.sections[0]?.label
    return new Set(label ? [label] : [])
  })

  useEffect(() => {
    const active = mod.sections.find(sec => sec.items.some(item => itemMatches(item, location.pathname)))
    if (active) setExpandedSections(new Set([active.label]))
  }, [location.pathname])

  const hasActiveItem = mod.sections.some(sec => sec.items.some(item => itemMatches(item, location.pathname)))

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
      <button
        onClick={onToggle}
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

      {open && mod.sections.map(sec => (
        <SidebarSection
          key={sec.label}
          section={sec}
          isDark={isDark}
          location={location}
          showHeader={mod.sections.length > 1}
          expanded={expandedSections.has(sec.label)}
          onToggle={() => setExpandedSections(prev => prev.has(sec.label) ? new Set() : new Set([sec.label]))}
        />
      ))}
    </div>
  )
}

// ── SidebarSection ────────────────────────────────────────────────────────────

function SidebarSection({ section, isDark, location, showHeader, expanded, onToggle }) {
  const hasActive = section.items.some(item => itemMatches(item, location.pathname))

  if (showHeader && section.directLink) {
    const only = section.items[0]
    const active = only.end ? location.pathname === only.to : (location.pathname === only.to || location.pathname.startsWith(only.to + '/'))
    return (
      <NavLink
        to={only.to} end={only.end}
        className={`w-full flex items-center gap-1.5 px-3 py-1 text-[10px] font-medium uppercase tracking-wider transition-all ${
          active ? (isDark ? 'text-white' : 'text-slate-800') : (isDark ? 'text-slate-600 hover:text-slate-400' : 'text-slate-400 hover:text-slate-600')
        }`}
      >
        <span className={`w-1 h-1 rounded-full shrink-0 ${active ? (isDark ? 'bg-gold-400' : 'bg-amber-500') : 'bg-transparent'}`} />
        {section.label}
      </NavLink>
    )
  }

  return (
    <div>
      {showHeader && (
        <button
          onClick={onToggle}
          className={`w-full flex items-center gap-1.5 px-3 py-1 text-[10px] font-medium uppercase tracking-wider transition-all ${
            hasActive ? (isDark ? 'text-slate-300' : 'text-slate-600') : (isDark ? 'text-slate-600 hover:text-slate-400' : 'text-slate-400 hover:text-slate-600')
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
                  {isActive && <span className={`w-1 h-1 rounded-full shrink-0 ${isDark ? 'bg-gold-400' : 'bg-amber-500'}`} />}
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

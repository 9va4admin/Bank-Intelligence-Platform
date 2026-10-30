import { useState, useEffect, useContext } from 'react'
import { NavLink, Link, useLocation } from 'react-router-dom'
import { useTheme } from '../theme/ThemeContext'
import { BANK_CONFIG } from '../config/bank.config'
import { PageHeaderCtx } from './PageHeaderContext'
import { msg } from '../messages'

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
    id: 'cts', label: 'CTS', fullLabel: msg('UI_APPSHELL_CHEQUE_TRUNCATION_2'), Icon: CtsIcon,
    sections: [
      {
        label: msg('UI_APPSHELL_DASHBOARD_2'), directLink: true,
        items: [{ to: '/cts/ops-dashboard', label: msg('UI_APPSHELL_OPS_DASHBOARD'), end: true }],
      },
      {
        label: msg('UI_APPSHELL_SETTLEMENT'), directLink: true,
        items: [{ to: '/cts/settlement', label: msg('UI_APPSHELL_SETTLEMENT') }],
      },
      {
        label: msg('UI_APPSHELL_OUTWARD_CLEARING_2'),
        items: [
          { to: '/cts/outward',              label: msg('UI_APPSHELL_OUTWARD_MONITOR_2'),  end: true },
          { to: '/cts/outward/verification', label: msg('UI_APPSHELL_VERIFICATION_OQ_2')            },
          { to: '/cts/outward/queue',        label: msg('UI_VALIDATIONQUEUE_VALIDATION_OQ_2')              },
          { to: '/cts/outward/submission',   label: msg('UI_COMMON_SUBMISSION_OQ')              },
          { to: '/cts/presentment-file',     label: msg('UI_APPSHELL_OUTWARD_FILE_2')               },
        ],
      },
      {
        label: msg('UI_APPSHELL_INWARD_CLEARING_2'),
        items: [
          { to: '/cts/pipeline',            label: msg('UI_APPSHELL_INWARD_MONITOR_2')           },
          { to: '/cts/inward/verification', label: msg('UI_APPSHELL_VERIFICATION_IQ_2')          },
          { to: '/cts',                     label: msg('UI_VALIDATIONQUEUE_VALIDATION_IQ_2'), end: true  },
          { to: '/cts/inward/submission',   label: msg('UI_COMMON_SUBMISSION_IQ')            },
          { to: '/cts/inward/review-queue', label: msg('UI_WORKSTATION_HUMAN_REVIEW_QUEUE')       },
          { to: '/cts/hold-queue',          label: msg('UI_APPSHELL_HOLD_QUEUE_2')               },
          { to: '/cts/recall',              label: msg('UI_APPSHELL_RECALL')                   },
        ],
      },
      {
        label: msg('UI_APPSHELL_PROCESSING'),
        items: [
          { to: '/cts/batches',     label: msg('UI_APPSHELL_BATCHES_2')                          },
          { to: '/cts/vault',       label: msg('UI_COMMON_VAULT_2')                            },
          { to: '/cts/vault-sync',  label: msg('UI_APPSHELL_PPS_STOP_CHEQUE_2')               },
          { to: '/cts/endorsement', label: msg('UI_APPSHELL_ENDORSEMENT_2')                      },
          { to: '/cts/exceptions',  label: msg('UI_APPSHELL_EXCEPTIONS')                       },
          { to: '/cts/iqa',         label: msg('UI_DEMOLIVE_IMAGE_QUALITY_2')                    },
          { to: '/cts/scanner',     label: msg('UI_APPSHELL_SCANNER_SDK_2')                      },
          { to: '/cts/rf-drawee',   label: msg('UI_APPSHELL_REJECTION_FILE_BY_DRAWEE_BANK_2')  },
        ],
      },
      {
        label: msg('UI_APPSHELL_REPORTS_2'),
        items: [
          { to: '/cts/decisions',      label: msg('UI_APPSHELL_DECISIONS_LOG')   },
          { to: '/cts/discrepancy',    label: msg('UI_APPSHELL_DISCREPANCY_2')     },
          { to: '/cts/reconciliation', label: msg('UI_APPSHELL_RECONCILIATION_2')  },
          { to: '/cts/analytics',      label: msg('UI_APPSHELL_ANALYTICS_2')       },
          { to: '/cts/compliance',     label: msg('UI_APPSHELL_COMPLIANCE_CERT_2') },
        ],
      },
      {
        label: msg('UI_APPSHELL_BRANCH_PORTAL'),
        items: [
          { to: '/branch',          label: msg('UI_APPSHELL_BRANCH_DASHBOARD_2') },
          { to: '/branch/scan',     label: msg('UI_APPSHELL_SCANNER_MONITOR')  },
          { to: '/branch/mismatch', label: msg('UI_APPSHELL_MISMATCH_QUEUE')   },
          { to: '/branch/history',  label: msg('UI_APPSHELL_SESSION_HISTORY')  },
        ],
      },
      {
        label: msg('UI_APPSHELL_MISCELLANEOUS'),
        items: [
          { to: '/cts/demo',            label: msg('UI_APPSHELL_LIVE_DEMO_2')         },
          { to: '/cts/inward-pipeline', label: msg('UI_APPSHELL_PIPELINE_ANIMATED_2') },
          { to: '/cts/cloud-ai-demo',   label: msg('UI_APPSHELL_CLOUD_AI_EXTRACT_2') },
          { to: '/cts/sig-batch-test',  label: msg('UI_APPSHELL_SIG_BATCH_TEST_2')   },
        ],
      },
    ],
  },
  {
    id: 'branch-ops', label: msg('UI_COMMON_BRANCH'), fullLabel: msg('UI_APPSHELL_BRANCH_OPERATIONS'), Icon: BranchIcon,
    sections: [
      {
        label: msg('UI_APPSHELL_HOLD_QUEUE_2'), directLink: true,
        items: [{ to: '/branch/hold-queue', label: msg('UI_COMMON_INWARD_HOLD_QUEUE_2') }],
      },
    ],
  },
  {
    id: 'ops', label: msg('UI_APPSHELL_OPS_2'), fullLabel: msg('UI_APPSHELL_PLATFORM_OPERATIONS_2'), Icon: OpsIcon,
    sections: [
      {
        label: msg('UI_APPSHELL_ASTRA_OPS_DASHBOARD'),
        items: [
          { to: '/ops/dashboard',    label: msg('UI_APP_OPS_OVERVIEW')  },
          { to: '/ops/model-health', label: msg('UI_APP_MODEL_HEALTH')  },
          { to: '/ops/alerts',       label: msg('UI_APP_ALERT_LOG')     },
          { to: '/ops/system',       label: msg('UI_APP_SYSTEM_HEALTH') },
        ],
      },
    ],
  },
  {
    id: 'admin', label: msg('UI_APPSHELL_ADMIN_2'), fullLabel: msg('UI_APPSHELL_ADMINISTRATION_2'), Icon: AdminIcon,
    sections: [
      {
        label: msg('UI_APPSHELL_ADMIN_2'),
        items: [
          { to: '/admin/users',                label: msg('UI_APPSHELL_USER_MANAGEMENT')   },
          { to: '/cts/schedules',              label: msg('UI_APPSHELL_SCHEDULES_2')         },
          { to: '/cts/config',                 label: msg('UI_APPSHELL_CONFIGURATION_2')     },
          { to: '/cts/config/micr-prefixes',   label: msg('UI_APPSHELL_MICR_PREFIXES_2')    },
          { to: '/cts/config/thresholds',      label: msg('UI_THRESHOLDS_THRESHOLDS_2')        },
          { to: '/cts/config/mcp-connections', label: msg('UI_APPSHELL_MCP_CONNECTIONS_2')   },
          { to: '/admin/config/operations',    label: msg('UI_OPERATIONSCONFIG_OPERATIONS_CONFIG_2') },
          { to: '/admin/config/platform',      label: msg('UI_PLATFORMCONFIG_PLATFORM_CONFIG_2')   },
          { to: '/admin/allocation',           label: msg('UI_APPSHELL_ALLOCATION_PANEL_2')  },
          { to: '/admin/smoke-test',           label: msg('UI_APPSHELL_GO_LIVE_TEST_2')    },
        ],
      },
    ],
  },
]

const ROUTE_LABELS = {
  '/cts':                        [msg('UI_APPSHELL_INWARD_CLEARING_2'),       msg('UI_APPSHELL_VALIDATION_IQ_HUMAN_REVIEW')],
  '/cts/inward/verification':    [msg('UI_APPSHELL_INWARD_CLEARING_2'),       msg('UI_APPSHELL_VERIFICATION_IQ_STAGE_1_REVIEW')],
  '/cts/inward/submission':      [msg('UI_APPSHELL_INWARD_CLEARING_2'),       msg('UI_APPSHELL_SUBMISSION_IQ_STAGE_3_CONFIRM')],
  '/cts/outward':                [msg('UI_APPSHELL_OUTWARD_CLEARING_2'),      msg('UI_APPSHELL_OUTWARD_MONITOR_2')],
  '/cts/outward/verification':   [msg('UI_APPSHELL_OUTWARD_CLEARING_2'),      msg('UI_APPSHELL_VERIFICATION_OQ_STAGE_1_IQA')],
  '/cts/outward/queue':          [msg('UI_APPSHELL_OUTWARD_CLEARING_2'),      msg('UI_APPSHELL_VALIDATION_OQ_STAGE_2_OCR')],
  '/cts/outward/submission':     [msg('UI_APPSHELL_OUTWARD_CLEARING_2'),      msg('UI_APPSHELL_SUBMISSION_OQ_STAGE_3_NGCH')],
  '/cts/presentment-file':       [msg('UI_APPSHELL_PRESENTATION_PROCESS'),  msg('UI_APPSHELL_PRESENTMENT_FILE')],
  '/cts/rf-drawee':              [msg('UI_APPSHELL_PRESENTATION_PROCESS'),  msg('UI_APPSHELL_RF_DRAWEE_BANK')],
  '/cts/vault':                  ['CTS',                   msg('UI_APPSHELL_VAULT_STATUS')],
  '/cts/vault-sync':             [msg('UI_APPSHELL_PROCESSING'),            msg('UI_APPSHELL_POSITIVE_PAY_STOP_CHEQUE')],
  '/cts/decisions':              [msg('UI_APPSHELL_REPORTS_2'),               msg('UI_APPSHELL_DECISIONS_LOG')],
  '/cts/reconciliation':         [msg('UI_APPSHELL_REPORTS_2'),               msg('UI_APPSHELL_RECONCILIATION_2')],
  '/cts/analytics':              [msg('UI_APPSHELL_REPORTS_2'),               msg('UI_APPSHELL_ANALYTICS_2')],
  '/cts/compliance':             [msg('UI_APPSHELL_REPORTS_2'),               msg('UI_APPSHELL_COMPLIANCE_CERT_2')],
  '/cts/exceptions':             [msg('UI_APPSHELL_PROCESSING'),            msg('UI_APPSHELL_EXCEPTIONS')],
  '/cts/endorsement':            [msg('UI_APPSHELL_PROCESSING'),            msg('UI_APPSHELL_ENDORSEMENT_2')],
  '/cts/iqa':                    [msg('UI_APPSHELL_PROCESSING'),            msg('UI_APPSHELL_IMAGE_QUALITY_ASSESSMENT')],
  '/cts/scanner':                [msg('UI_APPSHELL_PROCESSING'),            msg('UI_APPSHELL_SCANNER_SDK_2')],
  '/cts/pipeline':               [msg('UI_APPSHELL_DRAWEE_PROCESS'),        msg('UI_APPSHELL_INWARD_PIPELINE_AI_VIEW')],
  '/cts/inward-pipeline':        [msg('UI_APPSHELL_DRAWEE_PROCESS'),        msg('UI_APPSHELL_INWARD_PIPELINE_ANIMATED')],
  '/cts/demo':                   [msg('UI_APPSHELL_DEMO'),                  msg('UI_APPSHELL_END_TO_END_LIVE_DEMO_2')],
  '/cts/cloud-ai-demo':          [msg('UI_APPSHELL_DEMO'),                  msg('UI_CLOUDAIDEMO_CLOUD_AI_CHEQUE_EXTRACTION_2')],
  '/cts/recall':                 [msg('UI_APPSHELL_DRAWEE_PROCESS'),        msg('UI_APPSHELL_RECALL')],
  '/cts/ops-dashboard':          [msg('UI_APPSHELL_DASHBOARD_2'),             msg('UI_APPSHELL_OPS_DASHBOARD')],
  '/cts/settlement':             [msg('UI_APPSHELL_SETTLEMENT'),            msg('UI_APPSHELL_SETTLEMENT_LIFECYCLE')],
  '/cts/batches':                [msg('UI_APPSHELL_PROCESSING'),            msg('UI_APPSHELL_BATCHES_2')],
  '/cts/discrepancy':            [msg('UI_APPSHELL_REPORTS_2'),               msg('UI_APPSHELL_DISCREPANCY_2')],
  '/admin/users':                [msg('UI_APPSHELL_ADMIN_2'),                 msg('UI_APPSHELL_USER_MANAGEMENT')],
  '/cts/schedules':              [msg('UI_APPSHELL_ADMIN_2'),                 msg('UI_APPSHELL_TEMPORAL_SCHEDULES')],
  '/cts/config':                 [msg('UI_APPSHELL_ADMIN_2'),                 msg('UI_APPSHELL_CONFIGURATION_2')],
  '/cts/config/micr-prefixes':   [msg('UI_APPSHELL_ADMIN_CONFIG'),        msg('UI_APPSHELL_MICR_PREFIX_TABLE')],
  '/cts/config/thresholds':      [msg('UI_APPSHELL_ADMIN_CONFIG'),        msg('UI_APPSHELL_THRESHOLDS_RULES')],
  '/cts/config/mcp-connections': [msg('UI_APPSHELL_ADMIN_CONFIG'),        msg('UI_APPSHELL_MCP_CONNECTION_SETUP')],
  '/admin/config/operations':    [msg('UI_APPSHELL_ADMIN_CONFIG'),        msg('UI_OPERATIONSCONFIG_OPERATIONS_CONFIG_2')],
  '/admin/config/platform':      [msg('UI_APPSHELL_ADMIN_CONFIG'),        msg('UI_PLATFORMCONFIG_PLATFORM_CONFIG_2')],
  '/admin/allocation':           [msg('UI_APPSHELL_ADMIN_QUEUE'),         msg('UI_ALLOCATIONADMIN_ALLOCATION_CONTROL_PANEL_2')],
  '/admin/smoke-test':           [msg('UI_APPSHELL_ADMIN_2'),                 msg('UI_SMOKETEST_PRE_LIVE_SMOKE_TEST')],
  '/branch':                     [msg('UI_APPSHELL_BRANCH_PORTAL'),         msg('UI_APPSHELL_DASHBOARD_2')],
  '/branch/scan':                [msg('UI_APPSHELL_BRANCH_PORTAL'),         msg('UI_APPSHELL_SCANNER_MONITOR')],
  '/branch/mismatch':            [msg('UI_APPSHELL_BRANCH_PORTAL'),         msg('UI_APPSHELL_MISMATCH_QUEUE')],
  '/branch/history':             [msg('UI_APPSHELL_BRANCH_PORTAL'),         msg('UI_APPSHELL_SESSION_HISTORY')],
  '/branch/hold-queue':          [msg('UI_APPSHELL_BRANCH_OPERATIONS'),     msg('UI_COMMON_INWARD_HOLD_QUEUE_2')],
  '/cts/inward/review-queue':    [msg('UI_APPSHELL_INWARD_CLEARING_2'),       msg('UI_WORKSTATION_HUMAN_REVIEW_QUEUE')],
  '/cts/hold-queue':             [msg('UI_APPSHELL_INWARD_CLEARING_2'),       msg('UI_APPSHELL_HOLD_QUEUE_2')],
  '/ops/dashboard':              [msg('UI_APPSHELL_PLATFORM_OPS'),          msg('UI_APPSHELL_ASTRA_OPS_OVERVIEW')],
  '/ops/model-health':           [msg('UI_APPSHELL_PLATFORM_OPS'),          msg('UI_APPSHELL_AI_MODEL_HEALTH_7_DAY')],
  '/ops/alerts':                 [msg('UI_APPSHELL_PLATFORM_OPS'),          msg('UI_APPSHELL_ALERT_LOG_CRITICAL_ERROR_24H')],
  '/ops/system':                 [msg('UI_APPSHELL_PLATFORM_OPS'),          msg('UI_APP_SYSTEM_HEALTH')],
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
           {msg('UI_APPSHELL_STRA_2')}
          </span>
        )}
      </Link>

      <button
        onClick={onToggle}
        className={`ml-auto p-1 rounded-md opacity-40 hover:opacity-100 transition-opacity shrink-0 ${isDark ? 'hover:bg-white/10' : 'hover:bg-slate-100'}`}
        title={collapsed ? msg('UI_APPSHELL_EXPAND_SIDEBAR_2') : msg('UI_APPSHELL_COLLAPSE_SIDEBAR_2')}
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
        title={isDark ? msg('UI_BUSINESSMODEL_SWITCH_TO_LIGHT_2') : msg('UI_BUSINESSMODEL_SWITCH_TO_DARK_2')}
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
            <div className={`text-[11px] font-medium ${isDark ? 'text-white' : 'text-slate-700'}`}>{msg('UI_COMMON_USER')}</div>
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
              <div className={`text-[10px] mt-0.5 ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>{BANK_CONFIG.ifsc_prefix}</div>
            </div>
            {[
              { label: msg('UI_PROFILE_MY_PROFILE_2'),  icon: '👤', to: '/profile'  },
              { label: msg('UI_APPSHELL_SETTINGS'),    icon: '⚙️',  to: '/settings' },
              { label: msg('UI_APPSHELL_SIGN_OUT_2'),    icon: '→',   to: '/logout'   },
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

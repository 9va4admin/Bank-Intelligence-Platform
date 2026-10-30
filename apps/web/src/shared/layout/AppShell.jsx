import { useState, useContext, useEffect, useCallback } from 'react'
import { NavLink, Link, useLocation } from 'react-router-dom'
import { useTheme } from '../theme/ThemeContext'
import { PageHeaderCtx } from './PageHeaderContext'
import ChequeSearchBar from './ChequeSearchBar'
import { useBankContext } from '../context/BankContext'
import { BANK_CONFIG } from '../config/bank.config'
import CommandPalette from './CommandPalette'import { msg } from '../messages'
import { msg as uiMsg } from '../messages'


// ── Notification data ────────────────────────────────────────────────────────

const _ago = (mins) => Date.now() - mins * 60000

const MOCK_NOTIFICATIONS = [
  { id: 'n1', severity: 'CRITICAL', read: false, ts: _ago(3),
    title: uiMsg('UI_APPSHELL_IET_RISK_22_MIN_REMAINING'),
    body: uiMsg('UI_APPSHELL_INS_20260812_00144_VERY_HIGH'),
    action: '/cts/inward/review-queue' },
  { id: 'n2', severity: 'CRITICAL', read: false, ts: _ago(9),
    title: uiMsg('UI_APPSHELL_STOP_PAYMENT_DETECTED'),
    body: uiMsg('UI_APPSHELL_ACTIVE_STOP_PAYMENT_ON_INS'),
    action: '/cts/inward/review-queue' },
  { id: 'n3', severity: 'WARN', read: false, ts: _ago(16),
    title: uiMsg('UI_APPSHELL_VAULT_MISS_3_ACCOUNTS'),
    body: uiMsg('UI_APPSHELL_SIGNATURE_VAULT_RETURNED_NO_MATCH'),
    action: '/cts/vault/gaps' },
  { id: 'n4', severity: 'WARN', read: true, ts: _ago(34),
    title: uiMsg('UI_APPSHELL_OCR_CONFIDENCE_DEGRADED'),
    body: uiMsg('UI_APPSHELL_GOT_OCR2_0_RETURNED_CONFIDENCE'),
    action: '/cts/decisions' },
  { id: 'n5', severity: 'INFO', read: true, ts: _ago(52),
    title: uiMsg('UI_APPSHELL_VAULT_SYNC_COMPLETED'),
    body: uiMsg('UI_APPSHELL_2_847_SIGNATURE_RECORDS_REFRESHED'),
    action: '/cts/vault/status' },
  { id: 'n6', severity: 'INFO', read: true, ts: _ago(94),
    title: uiMsg('UI_APPSHELL_MORNING_SESSION_CLEARED'),
    body: uiMsg('UI_APPSHELL_CLEARING_SESSION_2026_08_12'),
    action: null },
]

function fmtNotifTs(ts) {
  const mins = Math.floor((Date.now() - ts) / 60000)
  if (mins < 1)  return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  return `${hrs}h ago`
}

const SEV_D = {
  CRITICAL: { dot: 'bg-red-500',    badge: uiMsg('UI_APPSHELL_BG_RED_900_50_TEXT'),    ring: 'border-red-700/30' },
  WARN:     { dot: 'bg-amber-400',  badge: uiMsg('UI_APPSHELL_BG_AMBER_900_40_TEXT'), ring: 'border-amber-700/20' },
  INFO:     { dot: 'bg-blue-400',   badge: uiMsg('UI_APPSHELL_BG_BLUE_900_40_TEXT'),  ring: 'border-white/8' },
}
const SEV_L = {
  CRITICAL: { dot: 'bg-red-500',    badge: uiMsg('UI_APPSHELL_BG_RED_50_TEXT_RED'),     ring: 'border-red-200' },
  WARN:     { dot: 'bg-amber-400',  badge: uiMsg('UI_APPSHELL_BG_AMBER_50_TEXT_AMBER'), ring: 'border-amber-100' },
  INFO:     { dot: 'bg-blue-400',   badge: uiMsg('UI_APPSHELL_BG_BLUE_50_TEXT_BLUE'),   ring: 'border-slate-200' },
}

// Nav item visibility is controlled by two independent gates:
//   1. sbOnly: true  — SB bank type required (structural — SMB never sees SB management pages)
//   2. smbOnly: true — SMB bank type required (structural — SB never sees SMB-only screens)
//   3. perm: 'cts:view_queue' — user's role must have this permission
// An item with no perm is visible to all authenticated users of the correct bank type.

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
        label: uiMsg('UI_APPSHELL_DASHBOARD'),
        directLink: true,
        items: [
          { to: '/cts/ops-dashboard', label: uiMsg('UI_COMMON_OPS_DASHBOARD'), end: true, perm: 'cts:view_queue' },
        ],
      },
      {
        label: uiMsg('UI_COMMON_SETTLEMENT'),
        directLink: true,
        items: [
          { to: '/cts/settlement', label: uiMsg('UI_COMMON_SETTLEMENT'), perm: 'smb:view_ledger' },
        ],
      },
      {
        label: uiMsg('UI_APPSHELL_OUTWARD_CLEARING'),
        items: [
          { to: '/cts/hub',                         label: uiMsg('UI_HUBDASHBOARD_HUB_MANAGER'),                  perm: 'cts:submit_decision', sbOnly: true },
          { to: '/cts/outward',                     label: uiMsg('UI_APPSHELL_OUTWARD_MONITOR'),   end: true, perm: 'cts:view_queue'      },
          { to: '/cts/outward/pipeline-monitor',    label: uiMsg('UI_APPSHELL_PIPELINE_MONITOR'),            perm: 'cts:view_analytics'  },
          { to: '/cts/outward/verification',        label: uiMsg('UI_APPSHELL_VERIFICATION_OQ'),             perm: 'cts:view_queue'      },
          { to: '/cts/outward/queue',               label: uiMsg('UI_APPSHELL_VALIDATION_OQ'),               perm: 'cts:submit_decision' },
          { to: '/cts/outward/submission',          label: uiMsg('UI_APPSHELL_SUBMISSION_OQ'),               perm: 'cts:submit_decision' },
          { to: '/cts/outward/custody',             label: uiMsg('UI_APPSHELL_ORIGINALS_CUSTODY'),           perm: 'cts:view_queue'      },
          { to: '/cts/presentment-file',            label: uiMsg('UI_APPSHELL_OUTWARD_FILE'),                perm: 'cts:view_queue'      },
        ],
      },
      {
        label: uiMsg('UI_APPSHELL_INWARD_CLEARING'),
        items: [
          { to: '/cts/pipeline',               label: uiMsg('UI_APPSHELL_INWARD_MONITOR'),              perm: 'cts:view_analytics'  },
          { to: '/cts/inward/verification',    label: uiMsg('UI_APPSHELL_VERIFICATION_IQ'),             perm: 'cts:view_queue'      },
          { to: '/cts',                        label: uiMsg('UI_APPSHELL_VALIDATION_IQ'),  end: true,   perm: 'cts:view_queue'      },
          { to: '/cts/inward/submission',      label: uiMsg('UI_APPSHELL_SUBMISSION_IQ'),               perm: 'cts:submit_decision' },
          { to: '/cts/inward/review-queue',    label: uiMsg('UI_APPSHELL_HUMAN_REVIEW_QUEUE'),          perm: 'cts:view_queue'      },
          { to: '/cts/hold-queue',             label: uiMsg('UI_APPSHELL_HOLD_QUEUE'),                  perm: 'cts:view_queue'      },
          { to: '/cts/recall',                 label: uiMsg('UI_RECALL_RECALL'),                      perm: 'cts:submit_decision' },
          // SMB Dashboard removed — "Dashboard" nav item shows it directly to SMB users now
          { to: '/cts/smb/review-queue',       label: uiMsg('UI_APPSHELL_SMB_REVIEW_QUEUE'),           smbOnly: true, smbMgmt: true, perm: 'cts:view_queue'   },
          { to: '/cts/smb/reports',            label: uiMsg('UI_APPSHELL_SMB_REPORTS'),                smbOnly: true, smbMgmt: true, perm: 'smb:view_ledger'  },
        ],
      },
      {
        label: uiMsg('UI_COMMON_PROCESSING'),
        items: [
          { to: '/cts/batches',            label: uiMsg('UI_APPSHELL_BATCHES'),          perm: 'cts:submit_decision'                },
          { to: '/cts/vault',              label: uiMsg('UI_COMMON_VAULT'),            perm: 'cts:view_queue'                     },
          { to: '/cts/vault-sync',         label: uiMsg('UI_APPSHELL_PPS_STOP_CHEQUE'),perm: 'cts:view_queue'                     },
          { to: '/cts/vault/upload',       label: uiMsg('UI_COMMON_VAULT_UPLOAD'),     perm: 'admin:manage'                       },
          { to: '/cts/sub-member',         label: uiMsg('UI_APPSHELL_SMB_SESSION_MONITOR'), sbOnly: true, smbMgmt: true, perm: 'smb:view_ledger'      },
          { to: '/cts/smb/registry',       label: uiMsg('UI_SMBREGISTRY_SMB_VAULT_CBS'),    sbOnly: true, smbMgmt: true, perm: 'smb:register'         },
          { to: '/cts/smb/ledger',         label: uiMsg('UI_APPSHELL_SMB_LEDGER'),       sbOnly: true, smbMgmt: true, perm: 'smb:view_ledger'      },
          { to: '/cts/smb/forwarding-log', label: uiMsg('UI_APPSHELL_SMB_FWD_LOG'),      sbOnly: true, smbMgmt: true, perm: 'smb:view_ledger'      },
          { to: '/cts/endorsement',        label: uiMsg('UI_APPSHELL_ENDORSEMENT'),      perm: 'cts:submit_decision'                },
          { to: '/cts/exceptions',         label: uiMsg('UI_COMMON_EXCEPTIONS'),       perm: 'cts:view_queue'                     },
          { to: '/cts/iqa',               label: uiMsg('UI_DEMOLIVE_IMAGE_QUALITY'),    perm: 'cts:view_queue'                     },
          { to: '/cts/scanner',            label: uiMsg('UI_APPSHELL_SCANNER_SDK'),      perm: 'cts:submit_decision'                },
          { to: '/cts/agency-cc',         label: uiMsg('UI_APPSHELL_AGENCY_CMD_CENTER'), perm: 'cts:view_analytics', sbOnly: true      },
          { to: '/cts/rf-drawee',         label: uiMsg('UI_APPSHELL_REJECTION_FILE_BY_DRAWEE_BANK'), perm: 'cts:submit_decision' },
        ],
      },
      {
        label: uiMsg('UI_APPSHELL_REPORTS'),
        items: [
          { to: '/cts/decisions',       label: uiMsg('UI_DECISIONSLOG_DECISIONS_LOG'),      perm: 'cts:view_analytics'  },
          { to: '/cts/vault-gaps',      label: uiMsg('UI_APPSHELL_VAULT_GAP_REPORT'),   perm: 'cts:view_analytics'  },
          { to: '/cts/discrepancy',     label: uiMsg('UI_APPSHELL_DISCREPANCY'),        perm: 'cts:view_analytics'  },
          { to: '/cts/reconciliation',  label: uiMsg('UI_APPSHELL_RECONCILIATION'),     perm: 'smb:view_ledger'     },
          { to: '/cts/analytics',       label: uiMsg('UI_APPSHELL_ANALYTICS'),          perm: 'cts:view_analytics'  },
          { to: '/cts/compliance',      label: uiMsg('UI_APPSHELL_COMPLIANCE_CERT'),    perm: 'audit:read'          },
        ],
      },
      {
        label: uiMsg('UI_BRANCHDASHBOARD_BRANCH_PORTAL'),
        items: [
          { to: '/branch',              label: uiMsg('UI_APPSHELL_BRANCH_DASHBOARD'),  perm: 'cts:view_queue'      },
          { to: '/branch/scan',         label: uiMsg('UI_COMMON_SCANNER_MONITOR'),   perm: 'cts:submit_decision' },
          { to: '/branch/mismatch',     label: uiMsg('UI_COMMON_MISMATCH_QUEUE'),    perm: 'cts:submit_decision' },
          { to: '/branch/history',      label: uiMsg('UI_COMMON_SESSION_HISTORY'),   perm: 'cts:view_queue'      },
          { to: '/branch/hold-queue',   label: uiMsg('UI_COMMON_INWARD_HOLD_QUEUE'), perm: 'cts:view_queue'      },
        ],
      },
      {
        label: uiMsg('CTS_WF_BUCKET_MISC'),
        items: [
          { to: '/cts/demo',            label: uiMsg('UI_APPSHELL_LIVE_DEMO'),        perm: 'cts:view_queue'     },
          { to: '/cts/inward-pipeline', label: uiMsg('UI_APPSHELL_PIPELINE_ANIMATED'), perm: 'cts:view_analytics' },
          { to: '/cts/cloud-ai-demo',   label: uiMsg('UI_APPSHELL_CLOUD_AI_EXTRACT'), perm: 'cts:view_queue'     },
          { to: '/cts/sig-batch-test',  label: uiMsg('UI_APPSHELL_SIG_BATCH_TEST'),   perm: 'cts:view_queue'     },
        ],
      },
    ],
  },
  {
    id: 'ops',
    label: uiMsg('UI_APPSHELL_OPS'),
    fullLabel: 'Platform Operations',
    Icon: OpsIcon,
    sections: [
      {
        label: uiMsg('UI_OPSDASHBOARD_ASTRA_OPS_DASHBOARD'),
        items: [
          { to: '/ops/dashboard',    label: uiMsg('UI_APPSHELL_OPS_OVERVIEW'),  perm: 'cts:view_analytics' },
          { to: '/ops/model-health',   label: uiMsg('UI_COMMON_MODEL_HEALTH'),   perm: 'ai:model_metrics' },
          { to: '/ops/ocr-feedback',   label: uiMsg('UI_OCRFEEDBACK_OCR_FEEDBACK'),   perm: 'ai:model_metrics' },
          { to: '/ops/alerts',       label: uiMsg('UI_COMMON_ALERT_LOG'),     perm: 'cts:view_analytics' },
          { to: '/ops/system',       label: uiMsg('UI_COMMON_SYSTEM_HEALTH'), perm: 'cts:view_analytics' },
        ],
      },
    ],
  },
  {
    id: 'admin',
    label: uiMsg('UI_APPSHELL_ADMIN'),
    fullLabel: 'Administration',
    Icon: AdminIcon,
    sections: [
      {
        label: uiMsg('UI_APPSHELL_ADMIN'),
        items: [
          { to: '/admin/users',                  label: uiMsg('UI_USERMANAGEMENT_USER_MANAGEMENT'),  perm: 'user:manage'          },
          { to: '/cts/schedules',                label: uiMsg('UI_APPSHELL_SCHEDULES'),        perm: 'config:layer3:submit' },
          { to: '/cts/config',                   label: uiMsg('UI_APPSHELL_CONFIGURATION'),    perm: 'config:layer3:submit' },
          { to: '/cts/config/sub-member-banks',  label: uiMsg('UI_COMMON_SUB_MEMBER_BANKS'), perm: 'smb:config_change',  sbOnly: true, smbMgmt: true },
          { to: '/cts/config/micr-prefixes',     label: uiMsg('UI_APPSHELL_MICR_PREFIXES'),    perm: 'config:layer2:change' },
          { to: '/cts/config/thresholds',        label: uiMsg('UI_APPSHELL_THRESHOLDS'),       perm: 'config:layer3:submit' },
          { to: '/cts/config/ngch-routing',      label: uiMsg('UI_NGCHROUTING_NGCH_ROUTING'),     perm: 'config:layer2:change', sbOnly: true },
          { to: '/cts/config/mcp-connections',   label: uiMsg('UI_APPSHELL_MCP_CONNECTIONS'),  perm: 'config:layer2:change' },
          { to: '/cts/admin/branches',            label: uiMsg('UI_BRANCHMASTER_BRANCH_MASTER'),    perm: 'config:layer2:change' },
          { to: '/admin/scanner-setup-guide',     label: uiMsg('UI_APPSHELL_SCANNER_SETUP_GUIDE'), perm: 'config:layer2:change' },
          { to: '/cts/admin/processing-units',    label: uiMsg('UI_APPSHELL_PU_MASTER'),        perm: 'config:layer2:change' },
          { to: '/admin/config/operations',      label: uiMsg('UI_OPERATIONSCONFIG_OPERATIONS_CONFIG'), perm: 'config:layer3:submit' },
          { to: '/admin/config/platform',       label: uiMsg('UI_PLATFORMCONFIG_PLATFORM_CONFIG'),   perm: 'config:layer2:change' },
          { to: '/admin/allocation',            label: uiMsg('UI_APPSHELL_ALLOCATION_PANEL'),  perm: 'config:layer3:submit' },
          { to: '/admin/config/buckets',        label: uiMsg('UI_APPSHELL_BUCKET_CONFIG'),     perm: 'config:layer3:submit' },
          { to: '/admin/security-violations',    label: uiMsg('UI_APPSHELL_SECURITY_ALERTS'),  perm: 'admin:console', sbOnly: true },
          { to: '/admin/smoke-test',            label: uiMsg('UI_APPSHELL_GO_LIVE_TEST'),   perm: 'config:layer2:change' },
        ],
      },
    ],
  },
]

const PROFILE_MENU = [
  { to: '/profile', label: uiMsg('UI_PROFILE_MY_PROFILE'), icon: '👤' },
  { to: '/logout',  label: uiMsg('UI_APPSHELL_SIGN_OUT'),   icon: '→'  },
]

const ROUTE_LABELS = {
  '/cts':                       ['Inward Clearing', 'Validation IQ — Human Review'],
  '/cts/inward/verification':  ['Inward Clearing', 'Verification IQ — Stage 1 Review Queue'],
  '/cts/inward/submission':    ['Inward Clearing', 'Submission IQ — Stage 3 Confirm / Return'],
  '/cts/outward':              ['Outward Clearing', 'Outward Monitor'],
  '/cts/outward/verification': ['Outward Clearing', 'Verification OQ — Stage 1 IQA / MICR Review'],
  '/cts/outward/queue':        ['Outward Clearing', 'Validation OQ — Stage 2 OCR Validation'],
  '/cts/outward/submission':   ['Outward Clearing', 'Submission OQ — Stage 3 NGCH Submission'],
  '/cts/outward/custody':      ['Outward Clearing', 'Originals Custody'],
  '/cts/presentment-file':     ['Presentation Process', 'Presentment File'],
  '/cts/rf-drawee':         ['Presentation Process', 'RF — Drawee Bank'],
  '/cts/vault':         ['CTS', 'Vault Status'],
  '/cts/vault-sync':    ['Processing', 'Positive Pay & Stop Cheque'],
  '/cts/decisions':     ['Reports', 'Decisions Log'],
  '/cts/vault-gaps':    ['Reports', 'Signature Vault Gap Report — Overnight Enrollment'],
  '/cts/reconciliation':['Reports', 'Reconciliation'],
  '/cts/analytics':     ['Reports', 'Analytics'],
  '/cts/compliance':    ['Reports', 'Compliance Cert'],
  '/cts/sub-member':    ['Processing', 'SMB Session Monitor'],
  '/cts/exceptions':    ['Processing', 'Exceptions'],
  '/cts/endorsement':   ['Processing', 'Endorsement'],
  '/cts/iqa':           ['Processing', 'Image Quality Assessment'],
  '/cts/scanner':       ['Processing', 'Scanner SDK'],
  '/cts/pipeline':          ['Drawee Process', 'Inward Pipeline — AI View'],
  '/cts/inward-pipeline':   ['Drawee Process', 'Inward Pipeline — Animated'],
  '/cts/demo':              ['Demo', 'End-to-End Live Demo — Presentment · NPCI · Drawee'],
  '/cts/cloud-ai-demo':     ['Demo', 'Cloud AI Cheque Extraction (temporary)'],
  '/cts/recall':            ['Drawee Process', 'Recall'],
  '/cts/ops-dashboard':     ['Dashboard', 'Ops Dashboard'],
  '/cts/drawee':            ['Drawee Process', 'Drawee Position'],
  '/cts/settlement':        ['Settlement', 'Settlement Lifecycle'],
  '/cts/batches':         ['Processing', 'Batches'],
  '/cts/discrepancy':     ['Reports', 'Discrepancy'],
  '/admin/users':         ['Admin', 'User Management'],
  '/cts/schedules':       ['Admin', 'Temporal Schedules'],
  '/cts/config':          ['Admin', 'Configuration'],
  '/cts/config/sub-member-banks': ['Admin · Config', 'Sub-Member Banks'],
  '/cts/config/micr-prefixes':    ['Admin · Config', 'MICR Prefix Table'],
  '/cts/config/thresholds':       ['Admin · Config', 'Thresholds & Rules'],
  '/cts/admin/branches':          ['Admin', 'Branch Master'],
  '/admin/scanner-setup-guide':   ['Admin', 'Scanner Setup Guide'],
  '/cts/admin/processing-units': ['Admin', 'Processing Unit Master'],
  '/cts/config/ngch-routing':     ['Admin · Config', 'NGCH Routing'],
  '/cts/config/mcp-connections':  ['Admin · Config', 'MCP Connection Setup'],
  '/cts/smb/registry':            ['Processing', 'SMB Vault & CBS'],
  '/cts/smb/ledger':              ['Processing', 'SMB Clearing Ledger'],
  '/cts/smb/forwarding-log':      ['Processing', 'SMB Forwarding Log'],
  '/cts/agency-cc':               ['Processing', 'Agency Command Center'],
  '/cts/smb/dashboard':           ['Inward Clearing', 'SMB Dashboard'],
  '/cts/smb/review-queue':        ['Inward Clearing', 'SMB Human Review Queue'],
  '/cts/smb/reports':             ['Inward Clearing', 'SMB Reports'],
  '/admin/config/operations':     ['Admin · Config', 'Operations Config — Layer 3 Business Rules'],
  '/admin/config/platform':       ['Admin · Config', 'Platform Config — Layer 2 Deployment Topology'],
  '/admin/allocation':            ['Admin · Queue', 'Allocation Control Panel — Reviewer Claims'],
  '/admin/config/buckets':        ['Admin · Configuration', 'Bucket Configuration — CA / IP Account Lists and Rules'],
  '/admin/security-violations':   ['Admin', 'Security Violation Log'],
  '/admin/smoke-test':            ['Admin', 'Pre-Live Smoke Test — Connection & Infrastructure Validation'],
  '/branch':                      ['Branch Portal', 'Dashboard'],
  '/branch/scan':                 ['Branch Portal', 'Scanner Monitor'],
  '/branch/mismatch':             ['Branch Portal', 'Mismatch Queue'],
  '/branch/history':              ['Branch Portal', 'Session History'],
  '/branch/hold-queue':           ['Branch Portal', 'Inward Hold Queue — Held Instruments'],
  '/cts/inward/review-queue':     ['Inward Clearing', 'Human Review Queue — Claim · Hold · Confirm · Return'],
  '/cts/hold-queue':              ['Inward Clearing', 'Hold Queue — Instruments Awaiting Branch Confirmation'],
  '/cts/hub':                     ['Outward Clearing', 'Hub Manager — Branch Sessions & Lot Sealing'],
  '/ops/dashboard':               ['Platform Ops', 'ASTRA Ops Overview'],
  '/ops/model-health':            ['Platform Ops', 'AI Model Health — 7-Day Drift'],
  '/ops/alerts':                  ['Platform Ops', 'Alert Log — CRITICAL/ERROR (24h)'],
  '/ops/system':                  ['Platform Ops', 'System Health — Infrastructure Connectivity'],
}

// Mirrors NavLink's `end` prop: when end=true, only exact match is active.
// Without this, { to: '/cts', end: true } would match /cts/demo via startsWith.
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
  if (
    pathname.startsWith('/admin') ||
    pathname.startsWith('/cts/config') ||
    pathname.startsWith('/cts/admin') ||
    pathname === '/cts/schedules'
  ) return 'admin'
  if (pathname.startsWith('/ops')) return 'ops'
  return 'cts'   // /cts/* and all /branch/* routes live under the CTS module tab
}

// ── AppShell ────────────────────────────────────────────────────────────────

export default function AppShell({ children }) {
  const { isDark, toggle } = useTheme()
  const location = useLocation()
  const [collapsed, setCollapsed] = useState(false)
  const [profileOpen, setProfileOpen] = useState(false)
  const [notifOpen, setNotifOpen] = useState(false)
  const [cmdOpen, setCmdOpen] = useState(false)
  const [notifications, setNotifications] = useState(MOCK_NOTIFICATIONS)
  const { bankType, bankName, bankIfsc, isSB, isSMB, userRole, userName, hasPermission, bankMode } = useBankContext()

  const unreadCount = notifications.filter(n => !n.read).length

  // Ctrl+K — open command palette
  useEffect(() => {
    const handler = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault()
        setCmdOpen(v => !v)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  const markAllRead = useCallback(() => {
    setNotifications(prev => prev.map(n => ({ ...n, read: true })))
  }, [])

  const [section, page] = useBreadcrumb(location.pathname)
  const currentModule = activeModuleId(location.pathname)

  // Single-open accordion: track which top-level module is expanded.
  // Initialise to the active module so the correct panel opens on load.
  const [openModuleId, setOpenModuleId] = useState(currentModule)

  // When the user navigates to a page in a different module (e.g. via a
  // direct link or browser back), auto-expand that module and collapse the rest.
  useEffect(() => {
    setOpenModuleId(currentModule)
  }, [currentModule])

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
               {uiMsg('UI_APPSHELL_STRA')}
              </span>
            )}
          </Link>
          {!collapsed && (
            <button
              onClick={() => setCollapsed(true)}
              className={`ml-auto p-1 rounded-md opacity-40 hover:opacity-100 transition-opacity ${isDark ? 'hover:bg-white/10' : 'hover:bg-slate-100'}`}
              title={uiMsg('UI_APPSHELL_COLLAPSE_SIDEBAR')}
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
              title={uiMsg('UI_APPSHELL_EXPAND_SIDEBAR')}
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
              open={openModuleId === mod.id}
              onToggle={() => setOpenModuleId((id) => (id === mod.id ? null : mod.id))}
              location={location}
              isSB={isSB}
              isSMB={isSMB}
              hasPermission={hasPermission}
              bankMode={bankMode}
            />
          ))}
        </nav>

      </aside>

      {/* ── Main area ─────────────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">

        {/* Topbar */}
        <header className={`relative z-40 shrink-0 border-b flex items-center px-5 gap-4 ${th.topbar}`} style={{ height: '52px' }}>

          {/* Breadcrumb */}
          <div className="flex items-center gap-1.5 min-w-0 flex-1">
            <span className={`text-[11px] shrink-0 ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>{section}</span>
            <span className={`text-[11px] opacity-30 shrink-0 ${isDark ? 'text-slate-400' : 'text-slate-400'}`}>›</span>
            <span className={`text-[13px] font-semibold truncate ${isDark ? 'text-white' : 'text-slate-800'}`}>{page}</span>
          </div>

          {/* Search bar */}
          <ChequeSearchBar isDark={isDark} />

          {/* Right: bank logo + notifications + theme toggle + user menu */}
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
                  const fb = e.currentTarget.nextSibling
                  if (fb) fb.style.display = 'block'
                }}
              />
              <span className={`text-xs font-semibold hidden ${isDark ? 'text-slate-200' : 'text-slate-700'}`}>
                {BANK_CONFIG.bank_short_name}
              </span>
            </div>

            {/* Command palette trigger */}
            <button
              onClick={() => setCmdOpen(true)}
              title={uiMsg('UI_APPSHELL_COMMAND_PALETTE_CTRL_K')}
              className={`hidden sm:flex items-center gap-1.5 text-[11px] rounded-lg px-2 py-1.5 border transition-colors ${isDark ? 'border-white/10 text-slate-400 hover:text-white hover:bg-white/8' : 'border-slate-200 text-slate-500 hover:text-slate-800 hover:bg-slate-50'}`}
            >
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.7" className="w-3 h-3">
                <circle cx="6.5" cy="6.5" r="4.5" />
                <path d="M10 10l3.5 3.5" strokeLinecap="round" />
              </svg>
              <span className="hidden md:inline">{uiMsg('UI_APPSHELL_SEARCH')}</span>
              <kbd className={`hidden md:inline font-mono text-[9px] px-1 py-0.5 rounded ${isDark ? 'bg-white/10' : 'bg-slate-100'}`}>⌘K</kbd>
            </button>

            {/* Notification bell */}
            <div className="relative">
              <button
                onClick={() => setNotifOpen(v => !v)}
                title={uiMsg('UI_APPSHELL_NOTIFICATIONS')}
                className={`w-8 h-8 flex items-center justify-center rounded-lg transition-colors ${notifOpen ? (isDark ? 'bg-white/10 text-white' : 'bg-slate-100 text-slate-800') : (isDark ? 'text-slate-400 hover:text-white hover:bg-white/8' : 'text-slate-500 hover:text-slate-800 hover:bg-slate-100')}`}
              >
                <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" className="w-4 h-4">
                  <path d="M10 2a6 6 0 00-6 6v2l-2 4h16l-2-4V8a6 6 0 00-6-6z" strokeLinecap="round" strokeLinejoin="round" />
                  <path d="M10 18a2 2 0 01-2-2h4a2 2 0 01-2 2z" />
                </svg>
              </button>
              {unreadCount > 0 && (
                <span className="absolute -top-0.5 -right-0.5 min-w-[14px] h-[14px] rounded-full bg-red-500 text-white text-[9px] font-bold flex items-center justify-center px-0.5 pointer-events-none">
                  {unreadCount > 9 ? '9+' : unreadCount}
                </span>
              )}
            </div>

            {/* Theme toggle */}
            <button
              onClick={toggle}
              title={isDark ? 'Switch to light' : 'Switch to dark'}
              className={`w-7 h-7 rounded-lg flex items-center justify-center text-sm transition-all shrink-0 ${isDark ? 'hover:bg-white/10 text-slate-200' : 'hover:bg-slate-100 text-slate-500'}`}
            >
              {isDark ? '☀' : '🌙'}
            </button>

            {/* User menu */}
            <div className="relative">
              <button
                onClick={() => setProfileOpen((v) => !v)}
                className={`flex items-center gap-2 rounded-lg pl-1.5 pr-2 py-1 transition-all ${isDark ? 'hover:bg-white/8' : 'hover:bg-slate-100'}`}
              >
                <div className={`w-7 h-7 rounded-full flex items-center justify-center text-[11px] font-bold shrink-0 ${isDark ? 'bg-gold-400/20 text-gold-400' : 'bg-amber-100 text-amber-700'}`}>
                  {(userName || 'U').charAt(0).toUpperCase()}
                </div>
                <div className="text-left hidden md:block leading-tight">
                  <div className={`text-[11px] font-medium truncate max-w-[130px] ${isDark ? 'text-white' : 'text-slate-700'}`}>{userName || 'User'}</div>
                  <div className={`text-[10px] truncate ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>{BANK_CONFIG.bank_short_name}</div>
                </div>
                <span className={`text-[9px] ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>▾</span>
              </button>

              {profileOpen && (
                <div className={`absolute right-0 top-full mt-2 w-52 z-[100] rounded-xl border py-2 shadow-2xl ${isDark ? 'bg-[#0e1654] backdrop-blur-xl border-white/10 shadow-black/60' : 'bg-white border-slate-200 shadow-slate-400/30'}`}>
                  <div className={`px-3 pb-2 mb-1 border-b ${isDark ? 'border-white/8' : 'border-slate-100'}`}>
                    <div className={`text-[11px] font-semibold ${isDark ? 'text-white' : 'text-slate-700'}`}>{bankName}</div>
                    <div className={`text-[10px] ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>{bankIfsc} · {bankType}</div>
                  </div>
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
        </header>

        {/* Sub-header from pages */}
        <PageHeaderBar isDark={isDark} />

        {/* Content */}
        <div className={`flex-1 min-h-0 overflow-y-auto ${th.content}`}>
          {children}
        </div>
      </div>

      {/* ── Notification drawer ──────────────────────────────────────────────── */}
      {notifOpen && (
        <>
          {/* backdrop */}
          <div className="fixed inset-0 z-[200]" onClick={() => setNotifOpen(false)} />
          <div
            className={`fixed top-0 right-0 bottom-0 z-[201] flex flex-col border-l shadow-2xl transition-all ${isDark ? 'bg-[#06102a] border-white/10' : 'bg-white border-slate-200'}`}
            style={{ width: 380 }}
          >
            {/* Header */}
            <div className={`flex items-center justify-between px-5 py-4 border-b shrink-0 ${isDark ? 'border-white/8' : 'border-slate-200'}`}>
              <div>
                <h2 className={`text-sm font-semibold ${isDark ? 'text-white' : 'text-slate-900'}`}>{uiMsg('UI_APPSHELL_NOTIFICATIONS')}</h2>
                <p className={`text-[11px] mt-0.5 ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>
                  {unreadCount > 0 ? `${unreadCount} unread` : 'All caught up'}
                </p>
              </div>
              <div className="flex items-center gap-2">
                {unreadCount > 0 && (
                  <button
                    onClick={markAllRead}
                    className={`text-[11px] px-2.5 py-1 rounded-lg border font-medium transition-colors ${isDark ? 'border-white/10 text-slate-400 hover:text-white hover:bg-white/8' : 'border-slate-200 text-slate-500 hover:bg-slate-50'}`}
                  >
                   {uiMsg('UI_APPSHELL_MARK_ALL_READ')}
                  </button>
                )}
                <button
                  onClick={() => setNotifOpen(false)}
                  className={`w-7 h-7 flex items-center justify-center rounded-lg ${isDark ? 'text-slate-400 hover:text-white hover:bg-white/8' : 'text-slate-500 hover:text-slate-800 hover:bg-slate-100'}`}
                >
                  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" className="w-3.5 h-3.5">
                    <path strokeLinecap="round" d="M4 4l8 8M12 4l-8 8" />
                  </svg>
                </button>
              </div>
            </div>

            {/* Notification list */}
            <div className="flex-1 overflow-y-auto">
              {notifications.map((n) => {
                const SEV = isDark ? SEV_D : SEV_L
                const s = SEV[n.severity] ?? SEV.INFO
                return (
                  <div
                    key={n.id}
                    className={`relative px-5 py-4 border-b cursor-pointer transition-colors ${isDark ? 'border-white/5 hover:bg-white/3' : 'border-slate-100 hover:bg-slate-50'} ${!n.read ? (isDark ? 'bg-white/2' : 'bg-blue-50/40') : ''}`}
                    onClick={() => {
                      setNotifications(prev => prev.map(x => x.id === n.id ? { ...x, read: true } : x))
                      if (n.action) window.location.href = n.action
                    }}
                  >
                    {/* Unread indicator */}
                    {!n.read && (
                      <span className={`absolute left-2 top-1/2 -translate-y-1/2 w-1.5 h-1.5 rounded-full ${s.dot}`} />
                    )}
                    <div className="flex items-start gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1 flex-wrap">
                          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${s.badge}`}>
                            {n.severity}
                          </span>
                          <span className={`text-[10px] ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>{fmtNotifTs(n.ts)}</span>
                        </div>
                        <p className={`text-xs font-semibold leading-snug mb-1 ${isDark ? (n.read ? 'text-slate-300' : 'text-white') : (n.read ? 'text-slate-600' : 'text-slate-900')}`}>{n.title}</p>
                        <p className={`text-[11px] leading-relaxed ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>{n.body}</p>
                      </div>
                      {n.action && (
                        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" className="w-3.5 h-3.5 shrink-0 mt-1" style={{ color: isDark ? '#64748b' : '#94a3b8' }}>
                          <path d="M6 3l5 5-5 5" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>

            {/* Footer */}
            <div className={`px-5 py-3 border-t shrink-0 ${isDark ? 'border-white/8' : 'border-slate-200'}`}>
              <p className={`text-[10px] text-center ${isDark ? 'text-slate-600' : 'text-slate-400'}`}>
               {uiMsg('UI_APPSHELL_POWERED_BY_PLATFORMHEALTHCHECKWORKFL')}
              </p>
            </div>
          </div>
        </>
      )}

      {/* ── Command palette ──────────────────────────────────────────────────── */}
      <CommandPalette
        open={cmdOpen}
        onClose={() => setCmdOpen(false)}
        onToggleTheme={toggle}
        isDark={isDark}
      />
    </div>
  )
}

// ── SidebarModule ────────────────────────────────────────────────────────────

function SidebarModule({ mod, collapsed, isDark, isActiveModule, open, onToggle, location, isSB, isSMB, hasPermission, bankMode }) {
  // Hide the entire module tab when no items are visible to this user.
  // This uses the same four-gate filter as SidebarSection so branch-ops
  // is invisible to all roles except branch_manager.
  const hasVisibleItems = mod.sections.some(sec =>
    sec.items.some(item => {
      if (item.sbOnly && !isSB) return false
      if (item.smbOnly && !isSMB) return false
      if (item.smbMgmt && bankMode === 'SB_ONLY') return false
      if (item.perm && !hasPermission(item.perm)) return false
      return true
    })
  )

  const [expandedSections, setExpandedSections] = useState(() => {
    // Single-open accordion: start with the active section (or the first).
    const active = mod.sections.find((sec) =>
      sec.items.some((item) => itemMatches(item, location.pathname))
    )
    const label = active?.label ?? mod.sections[0]?.label
    return new Set(label ? [label] : [])
  })

  // When navigating to a page inside this module, expand its section so the
  // active item is always visible. itemMatches() respects `end: true` so that
  // { to: '/cts', end: true } does not falsely match /cts/demo etc.
  useEffect(() => {
    const active = mod.sections.find((sec) =>
      sec.items.some((item) => itemMatches(item, location.pathname))
    )
    if (active) setExpandedSections(new Set([active.label]))
  }, [location.pathname])

  const hasActiveItem = mod.sections.some((sec) =>
    sec.items.some((item) => itemMatches(item, location.pathname))
  )

  const toggleSection = (label) => {
    // Accordion: opening a group collapses the rest; clicking the open one closes it.
    setExpandedSections((prev) => (prev.has(label) ? new Set() : new Set([label])))
  }

  if (!hasVisibleItems) return null

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
              isSB={isSB}
              isSMB={isSMB}
              hasPermission={hasPermission}
              bankMode={bankMode}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// ── SidebarSection ───────────────────────────────────────────────────────────

function SidebarSection({ section, isDark, location, showHeader, expanded, onToggle, isSB, isSMB, hasPermission, bankMode }) {
  // Four-gate filter:
  // 1. sbOnly gate  — structural bank-type wall (SMB never sees SB management pages)
  // 2. smbOnly gate — structural bank-type wall (SB never sees SMB-only screens)
  // 3. smbMgmt gate — deployment-mode wall (SB_ONLY deployments hide SMB management items)
  // 4. perm gate    — role-based permission (user only sees items their role allows)
  const visibleItems = section.items.filter(item => {
    if (item.sbOnly && !isSB) return false
    if (item.smbOnly && !isSMB) return false
    if (item.smbMgmt && bankMode === 'SB_ONLY') return false
    if (item.perm && !hasPermission(item.perm)) return false
    return true
  })

  const hasActive = visibleItems.some((item) => itemMatches(item, location.pathname))

  if (visibleItems.length === 0) return null

  // A single-item section behaves as a direct link — no accordion, no nested
  // sub-item. Clicking the section label navigates straight to that page.
  if (showHeader && section.directLink && visibleItems.length >= 1) {
    const only = visibleItems[0]
    const active = only.end
      ? location.pathname === only.to
      : (location.pathname === only.to || location.pathname.startsWith(only.to + '/'))
    return (
      <NavLink
        to={only.to} end={only.end}
        className={`w-full flex items-center gap-1.5 px-3 py-1 text-[10px] font-medium uppercase tracking-wider transition-all ${
          active
            ? (isDark ? 'text-white' : 'text-slate-800')
            : (isDark ? 'text-slate-600 hover:text-slate-400' : 'text-slate-400 hover:text-slate-600')
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
          {visibleItems.map(({ to, label, end }) => {
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

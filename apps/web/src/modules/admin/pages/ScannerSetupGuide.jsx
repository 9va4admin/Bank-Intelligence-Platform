import { useTheme } from '../../../shared/theme/ThemeContext'
import AppShell from '../../../shared/layout/AppShell'
import { msg } from '../../../shared/messages'

/* ─────────────────────────────────────────────────────────────
   Flow data — phases × steps for the scanner registration guide
   ───────────────────────────────────────────────────────────── */
const PHASES = [
  {
    id: 'generate',
    phase: 'Phase 1',
    title: msg('UI_SCANNERSETUPGUIDE_GENERATE_REGISTRATION_CODE'),
    actor: 'Ops Manager · Bank HQ',
    accentD: 'border-violet-500',
    accentL: 'border-violet-500',
    headerBgD: 'bg-violet-950/60',
    headerBgL: 'bg-violet-50',
    labelD: 'text-violet-400',
    labelL: 'text-violet-700',
    dotD: 'bg-violet-500',
    dotL: 'bg-violet-500',
    iconBgD: 'bg-violet-900/60',
    iconBgL: 'bg-violet-100',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
          d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
      </svg>
    ),
    steps: [
      {
        n: 1,
        title: msg('UI_SCANNERSETUPGUIDE_OPEN_BRANCH_MASTER'),
        detail: msg('UI_SCANNERSETUPGUIDE_GO_TO_ADMIN_BRANCH_MASTER'),
        security: null,
      },
      {
        n: 2,
        title: msg('UI_SCANNERSETUPGUIDE_CLICK_THE_REGISTER_SCANNER_ICON'),
        detail: msg('UI_SCANNERSETUPGUIDE_A_KEY_ICON_APPEARS_ON'),
        security: null,
      },
      {
        n: 3,
        title: msg('UI_SCANNERSETUPGUIDE_CLICK_GENERATE_REGISTRATION_CODE'),
        detail: msg('UI_SCANNERSETUPGUIDE_THE_ASTRA_SERVER_CREATES_AN'),
        security: 'Only one active code per branch at a time. Generating a new code automatically invalidates any previous pending code for this branch.',
      },
    ],
  },
  {
    id: 'handoff',
    phase: 'Handoff',
    title: msg('UI_SCANNERSETUPGUIDE_SECURE_CODE_DELIVERY'),
    actor: 'Ops Manager → Branch IT Coordinator',
    accentD: 'border-amber-500',
    accentL: 'border-amber-500',
    headerBgD: 'bg-amber-950/40',
    headerBgL: 'bg-amber-50',
    labelD: 'text-amber-400',
    labelL: 'text-amber-700',
    dotD: 'bg-amber-500',
    dotL: 'bg-amber-500',
    iconBgD: 'bg-amber-900/50',
    iconBgL: 'bg-amber-100',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
          d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z" />
      </svg>
    ),
    steps: [
      {
        n: 4,
        title: msg('UI_SCANNERSETUPGUIDE_READ_THE_CODE_TO_THE'),
        detail: msg('UI_SCANNERSETUPGUIDE_CALL_THE_BRANCH_IT_COORDINATOR'),
        security: 'The code expires in 24 hours and is single-use. Even if intercepted, it only works for the exact branch it was generated for — the branch identity is server-authoritative.',
      },
    ],
  },
  {
    id: 'install',
    phase: 'Phase 2',
    title: msg('UI_SCANNERSETUPGUIDE_RUN_INSTALLER_AT_THE_BRANCH'),
    actor: 'Branch IT Coordinator · Teller PC',
    accentD: 'border-sky-500',
    accentL: 'border-sky-500',
    headerBgD: 'bg-sky-950/50',
    headerBgL: 'bg-sky-50',
    labelD: 'text-sky-400',
    labelL: 'text-sky-700',
    dotD: 'bg-sky-500',
    dotL: 'bg-sky-500',
    iconBgD: 'bg-sky-900/50',
    iconBgL: 'bg-sky-100',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
          d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
      </svg>
    ),
    steps: [
      {
        n: 5,
        title: msg('UI_SCANNERSETUPGUIDE_OBTAIN_THE_INSTALLER_FROM_IT'),
        detail: msg('UI_SCANNERSETUPGUIDE_DOWNLOAD_ASTRA_SCANNER_SETUP_V', { version: '{version}' }),
        security: null,
      },
      {
        n: 6,
        title: msg('UI_SCANNERSETUPGUIDE_RUN_INSTALLER_AS_WINDOWS_ADMINISTRAT'),
        detail: msg('UI_SCANNERSETUPGUIDE_RIGHT_CLICK_THE_EXE_RUN'),
        security: null,
      },
      {
        n: 7,
        title: msg('UI_SCANNERSETUPGUIDE_ENTER_EXACTLY_2_FIELDS'),
        detail: msg('UI_SCANNERSETUPGUIDE_THE_INSTALLER_WIZARD_SHOWS_ONLY'),
        security: 'No branch name, no branch ID, no region — these are returned by the server and cannot be overridden by the installer. This prevents any branch from impersonating another.',
      },
      {
        n: 8,
        title: msg('UI_SCANNERSETUPGUIDE_CLICK_VERIFY'),
        detail: msg('UI_SCANNERSETUPGUIDE_THE_INSTALLER_CONTACTS_THE_ASTRA'),
        security: null,
      },
    ],
  },
  {
    id: 'server',
    phase: 'Automatic',
    title: msg('UI_SCANNERSETUPGUIDE_SERVER_SIDE_EXCHANGE'),
    actor: 'ASTRA Platform · No human action',
    accentD: 'border-slate-500',
    accentL: 'border-slate-400',
    headerBgD: 'bg-slate-800/60',
    headerBgL: 'bg-slate-100',
    labelD: 'text-slate-400',
    labelL: 'text-slate-600',
    dotD: 'bg-slate-500',
    dotL: 'bg-slate-500',
    iconBgD: 'bg-slate-700/60',
    iconBgL: 'bg-slate-200',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
          d="M5 12h14M12 5l7 7-7 7" />
      </svg>
    ),
    steps: [
      {
        n: 9,
        title: msg('UI_SCANNERSETUPGUIDE_CODE_ATOMICALLY_CONSUMED_FROM_REDIS'),
        detail: msg('UI_SCANNERSETUPGUIDE_THE_SERVER_EXECUTES_A_SINGLE', { bank_id: '{bank_id}', code: '{code}' }),
        security: 'Atomic single-use: even if the network request arrives twice simultaneously, only one exchange succeeds. The second attempt gets a 401.',
      },
      {
        n: 10,
        title: msg('UI_SCANNERSETUPGUIDE_BRANCH_CONFIG_LOADED_MACHINE_BOUND'),
        detail: msg('UI_SCANNERSETUPGUIDE_THE_SERVER_READS_BRANCH_DETAILS'),
        security: null,
      },
      {
        n: 11,
        title: msg('UI_SCANNERSETUPGUIDE_FULL_CONFIG_RETURNED_TO_INSTALLER'),
        detail: msg('UI_SCANNERSETUPGUIDE_RESPONSE_INCLUDES_BRANCH_ID_BANK'),
        security: null,
      },
    ],
  },
  {
    id: 'live',
    phase: 'Phase 3',
    title: msg('UI_SCANNERSETUPGUIDE_SCANNER_GOES_LIVE'),
    actor: 'Installer → Windows Service → Teller PC',
    accentD: 'border-emerald-500',
    accentL: 'border-emerald-500',
    headerBgD: 'bg-emerald-950/50',
    headerBgL: 'bg-emerald-50',
    labelD: 'text-emerald-400',
    labelL: 'text-emerald-600',
    dotD: 'bg-emerald-500',
    dotL: 'bg-emerald-500',
    iconBgD: 'bg-emerald-900/50',
    iconBgL: 'bg-emerald-100',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
          d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
    steps: [
      {
        n: 12,
        title: msg('UI_SCANNERSETUPGUIDE_CONFIG_INI_WRITTEN_TO_INSTALLATION'),
        detail: msg('UI_SCANNERSETUPGUIDE_NON_SECRET_CONFIGURATION_IS_SAVED'),
        security: null,
      },
      {
        n: 13,
        title: msg('UI_SCANNERSETUPGUIDE_TOKEN_DAT_WRITTEN_WITH_RESTRICTED'),
        detail: msg('UI_SCANNERSETUPGUIDE_THE_API_TOKEN_IS_SAVED'),
        security: 'Even if a teller\'s Windows account is compromised, the attacker cannot extract the scanner token. Only the service (running as SYSTEM) can read it.',
      },
      {
        n: 14,
        title: msg('UI_SCANNERSETUPGUIDE_ASTRASCANNERAGENT_SERVICE_INSTALLED'),
        detail: msg('UI_SCANNERSETUPGUIDE_THE_INSTALLER_REGISTERS_ASTRASCANNER'),
        security: null,
      },
      {
        n: 15,
        title: msg('UI_SCANNERSETUPGUIDE_SCANNER_OPERATIONAL_TELLER_CAN_BEGIN'),
        detail: msg('UI_SCANNERSETUPGUIDE_LOAD_CHEQUES_INTO_THE_CANON'),
        security: null,
      },
    ],
  },
]

const SECURITY_PRINCIPLES = [
  {
    icon: '🔒',
    title: msg('UI_SCANNERSETUPGUIDE_BRANCH_ID_IS_SERVER_AUTHORITATIVE'),
    desc: msg('UI_SCANNERSETUPGUIDE_THE_IT_COORDINATOR_ENTERS_ZERO'),
  },
  {
    icon: '⚡',
    title: msg('UI_SCANNERSETUPGUIDE_SINGLE_USE_CODE_ATOMIC'),
    desc: msg('UI_SCANNERSETUPGUIDE_REDIS_GETDEL_CODE_VANISHES_ON'),
  },
  {
    icon: '🖥️',
    title: msg('UI_SCANNERSETUPGUIDE_MACHINE_BOUND_TOKEN'),
    desc: msg('UI_SCANNERSETUPGUIDE_TOKEN_STORED_IN_CTS_SCANNER'),
  },
  {
    icon: '🛡️',
    title: msg('UI_SCANNERSETUPGUIDE_TOKEN_DAT_IS_UNREADABLE_BY'),
    desc: msg('UI_SCANNERSETUPGUIDE_NTFS_ACL_SYSTEM_ADMINISTRATORS_ONLY'),
  },
  {
    icon: '⏰',
    title: msg('UI_SCANNERSETUPGUIDE_24_HOUR_CODE_EXPIRY'),
    desc: msg('UI_SCANNERSETUPGUIDE_UNEXCHANGED_CODES_AUTO_EXPIRE_FROM'),
  },
  {
    icon: '🔑',
    title: msg('UI_SCANNERSETUPGUIDE_ONE_ACTIVE_CODE_PER_BRANCH'),
    desc: msg('UI_SCANNERSETUPGUIDE_GENERATING_A_NEW_CODE_INVALIDATES'),
  },
]

/* ─────────────────────────────────────────────────────────────
   Sub-components
   ───────────────────────────────────────────────────────────── */

function PhaseCard({ phase, idx, isDark }) {
  const accent = isDark ? phase.accentD : phase.accentL
  const headerBg = isDark ? phase.headerBgD : phase.headerBgL
  const label = isDark ? phase.labelD : phase.labelL
  const dot = isDark ? phase.dotD : phase.dotL
  const iconBg = isDark ? phase.iconBgD : phase.iconBgL

  const cardBg = isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200'
  const body = isDark ? 'text-slate-300' : 'text-slate-700'
  const muted = isDark ? 'text-slate-400' : 'text-slate-500'
  const numBg = isDark ? 'bg-navy-800 text-slate-200' : 'bg-slate-100 text-slate-700'
  const secBg = isDark ? 'bg-amber-950/40 border-amber-700/40 text-amber-300' : 'bg-amber-50 border-amber-300 text-amber-800'
  const divider = isDark ? 'border-white/6' : 'border-slate-100'

  return (
    <div className={`border ${cardBg} border-l-[3px] ${accent} rounded-xl overflow-hidden`}>
      {/* Phase header */}
      <div className={`${headerBg} px-5 py-3 flex items-center gap-3`}>
        <span className={`${iconBg} ${label} p-1.5 rounded-lg flex-shrink-0`}>
          {phase.icon}
        </span>
        <div>
          <div className={`text-xs font-semibold uppercase tracking-widest ${label} opacity-80`}>
            {phase.phase}
          </div>
          <div className={`text-sm font-semibold ${isDark ? 'text-white' : 'text-slate-900'}`}>
            {phase.title}
          </div>
        </div>
        <div className={`ml-auto text-xs ${muted} hidden sm:block`}>
          {phase.actor}
        </div>
      </div>

      {/* Steps */}
      <div className="px-5 py-4 space-y-0">
        {phase.steps.map((step, si) => (
          <div key={step.n}>
            <div className="flex gap-4 py-4">
              {/* Step number + connecting line */}
              <div className="flex flex-col items-center flex-shrink-0">
                <span className={`w-7 h-7 rounded-full ${numBg} text-xs font-bold flex items-center justify-center flex-shrink-0 tabular-nums`}>
                  {step.n}
                </span>
                {si < phase.steps.length - 1 && (
                  <div className={`w-px flex-1 mt-1.5 ${isDark ? 'bg-white/10' : 'bg-slate-200'}`} style={{ minHeight: '16px' }} />
                )}
              </div>
              {/* Content */}
              <div className="flex-1 pb-1">
                <div className={`text-sm font-semibold mb-1 ${isDark ? 'text-white' : 'text-slate-900'}`}>
                  {step.title}
                </div>
                <div className={`text-sm leading-relaxed ${body}`}>
                  {step.detail}
                </div>
                {step.security && (
                  <div className={`mt-2 text-xs leading-relaxed px-3 py-2 rounded-lg border ${secBg} flex gap-2`}>
                    <span className="flex-shrink-0 mt-px">🔐</span>
                    <span>{step.security}</span>
                  </div>
                )}
              </div>
            </div>
            {si < phase.steps.length - 1 && (
              <div className={`ml-11 border-t ${divider}`} />
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function HandoffArrow({ isDark }) {
  return (
    <div className="flex items-center justify-center py-1">
      <div className="flex flex-col items-center gap-0.5">
        <div className={`w-px h-3 ${isDark ? 'bg-white/20' : 'bg-slate-300'}`} />
        <svg className={`w-4 h-4 ${isDark ? 'text-white/30' : 'text-slate-400'}`} fill="currentColor" viewBox="0 0 20 20">
          <path fillRule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clipRule="evenodd" />
        </svg>
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────
   Main page
   ───────────────────────────────────────────────────────────── */
export default function ScannerSetupGuide() {
  const { isDark } = useTheme()

  const th = {
    page:    isDark ? 'bg-navy-950'              : 'bg-slate-50',
    heading: isDark ? 'text-white'               : 'text-slate-900',
    body:    isDark ? 'text-slate-300'           : 'text-slate-700',
    muted:   isDark ? 'text-slate-400'           : 'text-slate-500',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    secCard: isDark ? 'bg-navy-900/80 border-white/8' : 'bg-white border-slate-200',
    tag:     isDark ? 'bg-violet-900/50 text-violet-300 border-violet-700/40'
                    : 'bg-violet-50 text-violet-700 border-violet-200',
    badge:   isDark ? 'bg-emerald-900/50 text-emerald-300 border-emerald-700/40'
                    : 'bg-emerald-50 text-emerald-700 border-emerald-200',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
  }

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page}`}>
        <div className="max-w-3xl mx-auto px-6 py-6 pb-16">

          {/* ── Header ─────────────────────────────────── */}
          <div className="mb-6">
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <span className={`text-xs font-semibold uppercase tracking-widest px-2 py-0.5 rounded border ${th.tag}`}>
                   {msg('UI_SCANNERSETUPGUIDE_TRAINING_GUIDE')}
                  </span>
                  <span className={`text-xs font-semibold uppercase tracking-widest px-2 py-0.5 rounded border ${th.badge}`}>
                   {msg('UI_SCANNERSETUPGUIDE_FOR_BANK_IT_ADMIN')}
                  </span>
                </div>
                <h1 className={`text-2xl font-bold ${th.heading} mt-2`}>
                 {msg('UI_SCANNERSETUPGUIDE_SCANNER_REGISTRATION_FLOW')}
                </h1>
                <p className={`text-sm mt-1 ${th.muted}`}>
                 {msg('UI_SCANNERSETUPGUIDE_CANON_CR_120_CR_150')}
                </p>
              </div>
              <div className={`text-right text-xs ${th.muted} flex-shrink-0`}>
                <div>{msg('UI_SCANNERSETUPGUIDE_ASTRA_PLATFORM')}</div>
                <div>{msg('UI_SCANNERSETUPGUIDE_CTS_SCANNER_SETUP_001')}</div>
                <div>{msg('UI_SCANNERSETUPGUIDE_REV_2026_09_01')}</div>
              </div>
            </div>

            {/* Intro */}
            <div className={`mt-4 p-4 rounded-xl border ${th.card} text-sm ${th.body} leading-relaxed`}>
              <strong className={th.heading}>{msg('UI_SCANNERSETUPGUIDE_OVERVIEW')}</strong> {msg('UI_SCANNERSETUPGUIDE_THIS_GUIDE_WALKS_THROUGH_THE')}
            </div>

            {/* Quick stats */}
            <div className="grid grid-cols-3 gap-3 mt-3">
              {[
                { label: msg('UI_SCANNERSETUPGUIDE_STEPS_TOTAL'), value: '15' },
                { label: msg('UI_SCANNERSETUPGUIDE_FIELDS_IN_INSTALLER'), value: '2' },
                { label: msg('UI_SCANNERSETUPGUIDE_TIME_TO_LIVE'), value: '< 10 min' },
              ].map(s => (
                <div key={s.label} className={`rounded-xl border ${th.card} px-4 py-3 text-center`}>
                  <div className={`text-2xl font-bold tabular-nums ${th.heading}`}>{s.value}</div>
                  <div className={`text-xs ${th.muted} mt-0.5`}>{s.label}</div>
                </div>
              ))}
            </div>
          </div>

          {/* ── Who Does What ──────────────────────────── */}
          <div className={`mb-6 p-4 rounded-xl border ${th.card}`}>
            <div className={`text-xs font-semibold uppercase tracking-widest ${th.muted} mb-3`}>{msg('UI_SCANNERSETUPGUIDE_ACTORS_IN_THIS_PROCESS')}</div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-sm">
              {[
                { color: 'violet', label: msg('UI_SCANNERSETUPGUIDE_OPS_MANAGER'), loc: 'Bank HQ', desc: msg('UI_SCANNERSETUPGUIDE_GENERATES_REGISTRATION_CODE_IN_BRANC') },
                { color: 'sky', label: msg('UI_SCANNERSETUPGUIDE_BRANCH_IT'), loc: 'At branch', desc: msg('UI_SCANNERSETUPGUIDE_RUNS_INSTALLER_ON_TELLER_PC') },
                { color: 'slate', label: msg('UI_SCANNERSETUPGUIDE_ASTRA_SERVER'), loc: 'Automatic', desc: msg('UI_SCANNERSETUPGUIDE_VALIDATES_CODE_ISSUES_MACHINE_BOUND') },
              ].map(a => (
                <div key={a.label} className={`flex gap-3 p-3 rounded-lg ${isDark ? 'bg-navy-800/60' : 'bg-slate-50'}`}>
                  <div className={`w-2 rounded-full flex-shrink-0 mt-0.5 self-stretch ${
                    a.color === 'violet' ? 'bg-violet-500' :
                    a.color === 'sky'    ? 'bg-sky-500' : 'bg-slate-500'
                  }`} />
                  <div>
                    <div className={`font-semibold ${th.heading}`}>{a.label}</div>
                    <div className={`text-xs ${th.muted} mb-1`}>{a.loc}</div>
                    <div className={`text-xs ${th.body}`}>{a.desc}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* ── Flow phases ────────────────────────────── */}
          <div className="space-y-2">
            {PHASES.map((phase, idx) => (
              <div key={phase.id}>
                <PhaseCard phase={phase} idx={idx} isDark={isDark} />
                {idx < PHASES.length - 1 && <HandoffArrow isDark={isDark} />}
              </div>
            ))}
          </div>

          {/* ── Security Principles ────────────────────── */}
          <div className="mt-8">
            <div className={`text-xs font-semibold uppercase tracking-widest ${th.muted} mb-3`}>{msg('UI_SCANNERSETUPGUIDE_SECURITY_DESIGN_WHY_IT_IS')}</div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {SECURITY_PRINCIPLES.map(p => (
                <div key={p.title} className={`rounded-xl border ${th.card} p-4 flex gap-3`}>
                  <span className="text-xl flex-shrink-0">{p.icon}</span>
                  <div>
                    <div className={`text-sm font-semibold ${th.heading} mb-0.5`}>{p.title}</div>
                    <div className={`text-xs leading-relaxed ${th.body}`}>{p.desc}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* ── Installer fields reference ─────────────── */}
          <div className="mt-6">
            <div className={`text-xs font-semibold uppercase tracking-widest ${th.muted} mb-3`}>{msg('UI_SCANNERSETUPGUIDE_QUICK_REFERENCE_WHAT_THE_INSTALLER')}</div>
            <div className={`rounded-xl border ${th.card} overflow-hidden`}>
              <div className={`px-5 py-3 border-b ${th.divider} flex items-center gap-2`}>
                <div className="flex gap-1.5">
                  <div className="w-3 h-3 rounded-full bg-red-500/70" />
                  <div className="w-3 h-3 rounded-full bg-amber-500/70" />
                  <div className="w-3 h-3 rounded-full bg-emerald-500/70" />
                </div>
                <span className={`text-xs ${th.muted}`}>{msg('UI_SCANNERSETUPGUIDE_ASTRA_SCANNER_SETUP_STEP_2')}</span>
              </div>
              <div className="p-5">
                <div className={`font-semibold ${th.heading} mb-4`}>{msg('UI_SCANNERSETUPGUIDE_CONNECT_TO_ASTRA_SERVER')}</div>
                <div className="space-y-4">
                  <div>
                    <label className={`block text-xs font-semibold uppercase tracking-wide ${th.muted} mb-1`}>
                     {msg('UI_SCANNERSETUPGUIDE_ASTRA_SERVER_URL')}
                    </label>
                    <div className={`rounded-lg border px-3 py-2 text-sm font-mono ${
                      isDark ? 'bg-navy-800 border-white/10 text-slate-300' : 'bg-slate-50 border-slate-300 text-slate-700'
                    }`}>
                     {msg('UI_SCANNERSETUPGUIDE_HTTPS_ASTRA_YOURBANK_IN')}
                    </div>
                    <div className={`text-xs ${th.muted} mt-1`}>{msg('UI_SCANNERSETUPGUIDE_PROVIDED_BY_BANK_IT_SAME')}</div>
                  </div>
                  <div>
                    <label className={`block text-xs font-semibold uppercase tracking-wide ${th.muted} mb-1`}>
                     {msg('UI_SCANNERSETUPGUIDE_REGISTRATION_CODE')}
                    </label>
                    <div className={`rounded-lg border px-3 py-2 text-xl font-mono tracking-[0.25em] font-bold ${
                      isDark ? 'bg-navy-800 border-white/10 text-violet-300' : 'bg-slate-50 border-slate-300 text-violet-700'
                    }`}>
                     {msg('UI_SCANNERSETUPGUIDE_SARAS3X7')}
                    </div>
                    <div className={`text-xs ${th.muted} mt-1`}>{msg('UI_SCANNERSETUPGUIDE_8_CHARACTERS_CASE_INSENSITIVE_EXPIRE')}</div>
                  </div>
                  <div className={`flex justify-between items-center pt-2 border-t ${th.divider}`}>
                    <span className={`text-sm ${th.muted}`}>{msg('UI_SCANNERSETUPGUIDE_BACK')}</span>
                    <div className="flex items-center gap-2">
                      <div className={`text-xs px-3 py-2 rounded-lg ${
                        isDark ? 'bg-violet-600 text-white' : 'bg-violet-600 text-white'
                      } font-semibold`}>
                       {msg('UI_SCANNERSETUPGUIDE_VERIFY')}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <div className={`mt-2 text-xs ${th.muted} text-center`}>
             {msg('UI_SCANNERSETUPGUIDE_AFTER_VERIFY_SUCCEEDS_THE_INSTALLER')}
            </div>
          </div>

          {/* ── Troubleshooting ────────────────────────── */}
          <div className="mt-6">
            <div className={`text-xs font-semibold uppercase tracking-widest ${th.muted} mb-3`}>{msg('UI_SCANNERSETUPGUIDE_COMMON_ISSUES')}</div>
            <div className={`rounded-xl border ${th.card} divide-y ${th.divider}`}>
              {[
                {
                  q: '"Invalid code" error on Verify',
                  a: 'Code has been used already, or has expired (24h). Ask Ops Manager to generate a new code from Branch Master.',
                },
                {
                  q: 'Installer says "Branch not eligible"',
                  a: 'Check that the branch Scanner Mode is set to SDK_PUSH in Branch Master. FOLDER_DROP branches do not get a token.',
                },
                {
                  q: 'Service installs but scanner shows Disconnected',
                  a: 'Check firewall: outbound HTTPS (port 443) to the ASTRA server URL must be allowed. Also verify the Canon scanner USB driver is installed.',
                },
                {
                  q: 'Need to re-register (PC replaced / token expired)',
                  a: 'Ask Ops Manager to generate a fresh code. Run the installer again — it will revoke the old token automatically and issue a new one for the new machine.',
                },
              ].map(item => (
                <div key={item.q} className="px-5 py-4 flex gap-4">
                  <span className={`text-amber-500 flex-shrink-0 mt-px text-sm`}>?</span>
                  <div>
                    <div className={`text-sm font-semibold ${th.heading} mb-0.5`}>{item.q}</div>
                    <div className={`text-sm ${th.body}`}>{item.a}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* ── Footer ────────────────────────────────── */}
          <div className={`mt-8 pt-4 border-t ${th.divider} flex justify-between items-center text-xs ${th.muted}`}>
            <span>{msg('UI_SCANNERSETUPGUIDE_ASTRA_CTS_SCANNER_REGISTRATION_GUIDE')}</span>
            <span>{msg('UI_SCANNERSETUPGUIDE_REV_2026_09_01')}</span>
          </div>

        </div>
      </div>
    </AppShell>
  )
}

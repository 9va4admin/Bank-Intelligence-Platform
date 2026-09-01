import { useTheme } from '../../../shared/theme/ThemeContext'
import AppShell from '../../../shared/layout/AppShell'

/* ─────────────────────────────────────────────────────────────
   Flow data — phases × steps for the scanner registration guide
   ───────────────────────────────────────────────────────────── */
const PHASES = [
  {
    id: 'generate',
    phase: 'Phase 1',
    title: 'Generate Registration Code',
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
        title: 'Open Branch Master',
        detail: 'Go to Admin → Branch Master. Locate the target branch. Confirm Scanner Mode is SDK_PUSH and Status is Active. Branches in FOLDER_DROP or UI_UPLOAD mode do not get a scanner token.',
        security: null,
      },
      {
        n: 2,
        title: 'Click the Register Scanner icon (🔑)',
        detail: 'A key icon appears on every row where Scanner Mode = SDK_PUSH. Click it to open the Registration panel for that branch.',
        security: null,
      },
      {
        n: 3,
        title: 'Click "Generate Registration Code"',
        detail: 'The ASTRA server creates an 8-character one-time code tied exclusively to this branch. A 24-hour countdown starts immediately. The code appears in large monospace type — easy to read over the phone.',
        security: 'Only one active code per branch at a time. Generating a new code automatically invalidates any previous pending code for this branch.',
      },
    ],
  },
  {
    id: 'handoff',
    phase: 'Handoff',
    title: 'Secure Code Delivery',
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
        title: 'Read the code to the Branch IT Coordinator',
        detail: 'Call the branch IT coordinator and read the 8-character code aloud (e.g. "SARAS-3X7Q"). Alternatively use your bank\'s secure internal messaging system. Do not send via plain email or SMS.',
        security: 'The code expires in 24 hours and is single-use. Even if intercepted, it only works for the exact branch it was generated for — the branch identity is server-authoritative.',
      },
    ],
  },
  {
    id: 'install',
    phase: 'Phase 2',
    title: 'Run Installer at the Branch',
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
        title: 'Obtain the installer from IT portal',
        detail: 'Download ASTRA-Scanner-Setup-v{version}.exe from the bank\'s internal software portal. Verify the SHA-256 checksum printed on the portal matches before running. The installer is built once in CI and deployed to all branches — no branch-specific build needed.',
        security: null,
      },
      {
        n: 6,
        title: 'Run installer as Windows Administrator',
        detail: 'Right-click the .exe → "Run as administrator". Accept the UAC prompt. The installer requires admin rights to install the Windows service and set token.dat file permissions.',
        security: null,
      },
      {
        n: 7,
        title: 'Enter exactly 2 fields',
        detail: 'The installer wizard shows only two input fields: (1) ASTRA Server URL — same for all branches in your bank, provided by bank IT; (2) Registration Code — the 8-character code you received from Ops Manager.',
        security: 'No branch name, no branch ID, no region — these are returned by the server and cannot be overridden by the installer. This prevents any branch from impersonating another.',
      },
      {
        n: 8,
        title: 'Click "Verify →"',
        detail: 'The installer contacts the ASTRA server, submits the code and the PC\'s machine name, and receives all branch configuration automatically. A green tick confirms a successful exchange.',
        security: null,
      },
    ],
  },
  {
    id: 'server',
    phase: 'Automatic',
    title: 'Server-Side Exchange',
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
        title: 'Code atomically consumed from Redis',
        detail: 'The server executes a single atomic GETDEL on the Redis key scanner_reg:{bank_id}:{code}. The code is gone the instant it is read — it cannot be replayed, even within the same millisecond.',
        security: 'Atomic single-use: even if the network request arrives twice simultaneously, only one exchange succeeds. The second attempt gets a 401.',
      },
      {
        n: 10,
        title: 'Branch config loaded & machine-bound token issued',
        detail: 'The server reads branch details (branch_id, IFSC, endorsement settings, UV scan flags) from YugabyteDB and generates a random API token. The token is stored in cts.scanner_tokens bound to this machine name — it will not authenticate from any other PC.',
        security: null,
      },
      {
        n: 11,
        title: 'Full config returned to installer',
        detail: 'Response includes: branch_id, bank_id, bank_ifsc, api_url, endorsement_text, enable_imprinter, enable_uv_scan, and the raw API token (shown only once, never stored on the server).',
        security: null,
      },
    ],
  },
  {
    id: 'live',
    phase: 'Phase 3',
    title: 'Scanner Goes Live',
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
        title: 'config.ini written to installation folder',
        detail: 'Non-secret configuration is saved: [server] url, [branch] id, ifsc, [scanner] enable_uv, enable_imprinter, endorsement_text. This file can be read by any Windows user — it contains no credentials.',
        security: null,
      },
      {
        n: 13,
        title: 'token.dat written with restricted NTFS permissions',
        detail: 'The API token is saved to token.dat immediately next to config.ini. The installer then calls the Windows AccessControl API to restrict permissions: Read/Write for SYSTEM and Administrators group only. Standard user accounts (including the teller login) cannot read this file.',
        security: 'Even if a teller\'s Windows account is compromised, the attacker cannot extract the scanner token. Only the service (running as SYSTEM) can read it.',
      },
      {
        n: 14,
        title: 'ASTRAScannerAgent service installed and started',
        detail: 'The installer registers ASTRAScannerAgent as a Windows service set to Automatic (start on boot). The service starts immediately. On the Branch Scan Monitor in ASTRA, the branch will show as "Connected" within seconds.',
        security: null,
      },
      {
        n: 15,
        title: '✅ Scanner Operational — Teller can begin',
        detail: 'Load cheques into the Canon CR-120 / CR-150 feeder. Each cheque is automatically captured (front + back image, hardware MICR), UV scanned, and submitted to ASTRA CTS. The teller sees real-time status in the BranchScan monitor on their workstation.',
        security: null,
      },
    ],
  },
]

const SECURITY_PRINCIPLES = [
  {
    icon: '🔒',
    title: 'Branch ID is server-authoritative',
    desc: 'The IT coordinator enters zero branch identity. The server returns it. No forgery possible.',
  },
  {
    icon: '⚡',
    title: 'Single-use code (atomic)',
    desc: 'Redis GETDEL — code vanishes on first successful exchange. No replay window.',
  },
  {
    icon: '🖥️',
    title: 'Machine-bound token',
    desc: 'Token stored in cts.scanner_tokens with machine_id = COMPUTERNAME. Fails auth on any other PC.',
  },
  {
    icon: '🛡️',
    title: 'token.dat is unreadable by users',
    desc: 'NTFS ACL: SYSTEM + Administrators only. Standard teller account cannot read it.',
  },
  {
    icon: '⏰',
    title: '24-hour code expiry',
    desc: 'Unexchanged codes auto-expire from Redis. No dangling codes after installation window.',
  },
  {
    icon: '🔑',
    title: 'One active code per branch',
    desc: 'Generating a new code invalidates the previous one. No duplicate registrations.',
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
                    Training Guide
                  </span>
                  <span className={`text-xs font-semibold uppercase tracking-widest px-2 py-0.5 rounded border ${th.badge}`}>
                    For Bank IT Admin
                  </span>
                </div>
                <h1 className={`text-2xl font-bold ${th.heading} mt-2`}>
                  Scanner Registration Flow
                </h1>
                <p className={`text-sm mt-1 ${th.muted}`}>
                  Canon CR-120 / CR-150 · ASTRA CTS Edge Agent · Windows Service
                </p>
              </div>
              <div className={`text-right text-xs ${th.muted} flex-shrink-0`}>
                <div>ASTRA Platform</div>
                <div>CTS-SCANNER-SETUP-001</div>
                <div>Rev 2026-09-01</div>
              </div>
            </div>

            {/* Intro */}
            <div className={`mt-4 p-4 rounded-xl border ${th.card} text-sm ${th.body} leading-relaxed`}>
              <strong className={th.heading}>Overview:</strong> This guide walks through the complete process
              of registering a new branch scanner with ASTRA CTS — from generating a one-time code at
              bank headquarters to the scanner agent going live on the teller PC. The entire setup
              takes under 10 minutes. The branch IT coordinator needs to enter only 2 fields.
            </div>

            {/* Quick stats */}
            <div className="grid grid-cols-3 gap-3 mt-3">
              {[
                { label: 'Steps total', value: '15' },
                { label: 'Fields in installer', value: '2' },
                { label: 'Time to live', value: '< 10 min' },
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
            <div className={`text-xs font-semibold uppercase tracking-widest ${th.muted} mb-3`}>Actors in this process</div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-sm">
              {[
                { color: 'violet', label: 'Ops Manager', loc: 'Bank HQ', desc: 'Generates registration code in Branch Master' },
                { color: 'sky', label: 'Branch IT', loc: 'At branch', desc: 'Runs installer on teller PC with the code' },
                { color: 'slate', label: 'ASTRA Server', loc: 'Automatic', desc: 'Validates code, issues machine-bound token' },
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
            <div className={`text-xs font-semibold uppercase tracking-widest ${th.muted} mb-3`}>Security design — why it is safe</div>
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
            <div className={`text-xs font-semibold uppercase tracking-widest ${th.muted} mb-3`}>Quick reference — what the installer shows</div>
            <div className={`rounded-xl border ${th.card} overflow-hidden`}>
              <div className={`px-5 py-3 border-b ${th.divider} flex items-center gap-2`}>
                <div className="flex gap-1.5">
                  <div className="w-3 h-3 rounded-full bg-red-500/70" />
                  <div className="w-3 h-3 rounded-full bg-amber-500/70" />
                  <div className="w-3 h-3 rounded-full bg-emerald-500/70" />
                </div>
                <span className={`text-xs ${th.muted}`}>ASTRA Scanner Setup — Step 2 of 4</span>
              </div>
              <div className="p-5">
                <div className={`font-semibold ${th.heading} mb-4`}>Connect to ASTRA Server</div>
                <div className="space-y-4">
                  <div>
                    <label className={`block text-xs font-semibold uppercase tracking-wide ${th.muted} mb-1`}>
                      ASTRA Server URL
                    </label>
                    <div className={`rounded-lg border px-3 py-2 text-sm font-mono ${
                      isDark ? 'bg-navy-800 border-white/10 text-slate-300' : 'bg-slate-50 border-slate-300 text-slate-700'
                    }`}>
                      https://astra.yourbank.in
                    </div>
                    <div className={`text-xs ${th.muted} mt-1`}>Provided by bank IT — same URL for all branches</div>
                  </div>
                  <div>
                    <label className={`block text-xs font-semibold uppercase tracking-wide ${th.muted} mb-1`}>
                      Registration Code
                    </label>
                    <div className={`rounded-lg border px-3 py-2 text-xl font-mono tracking-[0.25em] font-bold ${
                      isDark ? 'bg-navy-800 border-white/10 text-violet-300' : 'bg-slate-50 border-slate-300 text-violet-700'
                    }`}>
                      SARAS3X7
                    </div>
                    <div className={`text-xs ${th.muted} mt-1`}>8 characters · case-insensitive · expires in 24 hours</div>
                  </div>
                  <div className={`flex justify-between items-center pt-2 border-t ${th.divider}`}>
                    <span className={`text-sm ${th.muted}`}>← Back</span>
                    <div className="flex items-center gap-2">
                      <div className={`text-xs px-3 py-2 rounded-lg ${
                        isDark ? 'bg-violet-600 text-white' : 'bg-violet-600 text-white'
                      } font-semibold`}>
                        Verify →
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <div className={`mt-2 text-xs ${th.muted} text-center`}>
              After "Verify" succeeds, the installer completes automatically — no more input needed.
            </div>
          </div>

          {/* ── Troubleshooting ────────────────────────── */}
          <div className="mt-6">
            <div className={`text-xs font-semibold uppercase tracking-widest ${th.muted} mb-3`}>Common issues</div>
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
            <span>ASTRA CTS · Scanner Registration Guide · CTS-SCANNER-SETUP-001</span>
            <span>Rev 2026-09-01</span>
          </div>

        </div>
      </div>
    </AppShell>
  )
}

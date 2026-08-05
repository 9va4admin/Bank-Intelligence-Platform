import { useState, useRef } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'

// ── Entity test registry ─────────────────────────────────────────────────────

const ENTITY_SECTIONS = {
  sb: {
    label: 'SB',
    fullName: 'Sponsor Bank',
    sections: {
      'Core Infrastructure': [
        { id: 'test_cbs',             name: 'CBS Connectivity',              desc: 'Finacle/BaNCS/FlexCube API ping' },
        { id: 'test_ngch',            name: 'NGCH Adapter',                  desc: 'SFTP/REST transport to NGCH' },
        { id: 'test_kafka',           name: 'Kafka Topics',                  desc: 'Produce + consume cts.inward test event' },
        { id: 'test_immudb',          name: 'Immudb Audit Trail',            desc: 'Write + Merkle verify a test AuditEvent' },
      ],
      'Vaults': [
        { id: 'test_signature_vault', name: 'Signature Vault (Redis CTS)',   desc: 'Ping Redis + sample signature lookup' },
        { id: 'test_pps_vault',       name: 'PPS Vault (Redis CTS)',         desc: 'PPS vault ping + seeding count check' },
      ],
      'Authentication': [
        { id: 'test_auth_sb',         name: 'SB Auth — SAML / LDAP IdP',    desc: 'IdP metadata fetch + XML validation' },
      ],
      'End-to-End': [
        { id: 'test_iet_watchdog',    name: 'IET Watchdog (Synthetic Cheque)', desc: 'ChequeProcessingWorkflow < 600ms + watchdog armed' },
      ],
    },
  },
  smb: {
    label: 'SMB',
    fullName: 'Sub-Member Bank',
    sections: {
      'Authentication': [
        { id: 'test_auth_smb',     name: 'SMB Auth Connector',         desc: 'Local argon2 DB reachable + verify test' },
      ],
      'Connectivity': [
        { id: 'test_sftp_push',    name: 'Agency SFTP Push',           desc: 'Write test file to Agency SFTP drop path' },
      ],
      'Vault Seeding': [
        { id: 'test_vault_seeded', name: 'Signature Vault Seeding',    desc: 'Count seeded signatures for SMB accounts' },
        { id: 'test_smb_cbs',     name: 'SMB CBS Connectivity',        desc: 'SMB CBS ping (skips if no SMB_CBS configured)' },
      ],
    },
  },
  branch: {
    label: 'Branch',
    fullName: 'Branch / Scanner',
    sections: {
      'Authentication': [
        { id: 'test_auth_branch',    name: 'Branch Auth — LDAP-AD',      desc: 'LDAPS bind + group resolution' },
      ],
      'Scanner': [
        { id: 'test_scanner_folder', name: 'Scanner Drop Folder',        desc: 'Path exists + write permission check' },
      ],
      'Session': [
        { id: 'test_eeh_connectivity', name: 'EEH/IEH Session (gRPC)',  desc: 'gRPC ping to eeh-service' },
      ],
    },
  },
  pu: {
    label: 'PU',
    fullName: 'Processing Unit',
    sections: {
      'Authentication': [
        { id: 'test_auth_pu',         name: 'PU Auth — LDAP-AD',          desc: 'LDAPS bind + group resolution' },
      ],
      'SB Connectivity': [
        { id: 'test_sb_connector',    name: 'Agency → SB Connector',      desc: 'SFTP write to SB lots path' },
      ],
      'Scanner & Session': [
        { id: 'test_scanner_folder',  name: 'Scanner Drop Folder',        desc: 'Path exists + write permission check' },
        { id: 'test_eeh_connectivity', name: 'EEH/IEH Session (gRPC)',   desc: 'gRPC ping to eeh-service' },
      ],
    },
  },
}

// Demo results (cycle through 3 scenarios on repeat runs)
const DEMO_OUTCOMES = [
  { // all pass
    test_cbs: ['PASS', 'Finacle API /accounts/ping → 200 in 18ms'],
    test_ngch: ['PASS', 'SFTP handshake OK, root listing verified in 45ms'],
    test_kafka: ['PASS', 'Produced + consumed cts.inward test event in 22ms'],
    test_immudb: ['PASS', 'AuditEvent written + Merkle leaf verified in 14ms'],
    test_signature_vault: ['PASS', 'Redis CTS ping 1ms · sample sig lookup 3ms'],
    test_pps_vault: ['PASS', 'PPS vault ping OK · 4 PPS entries seeded for test accounts'],
    test_auth_sb: ['PASS', 'ADFS metadata at /FederationMetadata fetched, XML valid'],
    test_iet_watchdog: ['PASS', 'ChequeProcessingWorkflow: STP_CONFIRM in 487ms · IET watchdog armed'],
    test_auth_smb: ['PASS', 'Local auth DB reachable · argon2 verify test OK in 8ms'],
    test_sftp_push: ['PASS', 'SFTP write to Agency sftp://saraswat-coop:22/smb-push OK in 120ms'],
    test_vault_seeded: ['WARN', '8 of 12 accounts seeded — 4 accounts missing signatures, seed before go-live'],
    test_smb_cbs: ['SKIP', 'No SMB_CBS MCP connection configured — skipping'],
    test_auth_branch: ['PASS', 'LDAP bind OK: CN=astra-svc,OU=ServiceAccounts,DC=saraswat-coop,DC=local'],
    test_scanner_folder: ['PASS', '/opt/astra/scanner/dadar-001 exists and is writable'],
    test_eeh_connectivity: ['PASS', 'gRPC ping to eeh-service.astra-cts-saraswat-coop:50051 → OK 4ms'],
    test_auth_pu: ['PASS', 'LDAP bind OK: CN=astra-svc,OU=ServiceAccounts,DC=saraswat-coop,DC=local'],
    test_sb_connector: ['PASS', 'SFTP to saraswat-sb.ngch.local:22 connected, /agency-cc/lots writable'],
  },
  { // failures + warns
    test_cbs: ['FAIL', 'Finacle API unreachable — check cbs.finacle.base_url in Vault'],
    test_ngch: ['PASS', 'SFTP handshake OK in 45ms'],
    test_kafka: ['WARN', 'Kafka ACK took 480ms — consumer lag may build during high volume'],
    test_immudb: ['PASS', 'AuditEvent written + verified in 14ms'],
    test_signature_vault: ['WARN', 'Redis hit but lookup took 28ms — check memory pressure'],
    test_pps_vault: ['WARN', 'PPS vault OK but only 2 entries seeded — seed all accounts before go-live'],
    test_auth_sb: ['PASS', 'ADFS metadata fetched, XML valid'],
    test_iet_watchdog: ['PASS', 'ChequeProcessingWorkflow: STP_CONFIRM in 487ms'],
    test_auth_smb: ['PASS', 'Local auth DB reachable'],
    test_sftp_push: ['FAIL', 'SFTP connection refused — check Agency SFTP endpoint config'],
    test_vault_seeded: ['WARN', 'Only 2 of 12 signatures seeded'],
    test_smb_cbs: ['SKIP', 'No SMB_CBS MCP connection configured — skipping'],
    test_auth_branch: ['FAIL', 'LDAP server unreachable: ldaps://dc.saraswat-coop.local:636 — check network or AD status'],
    test_scanner_folder: ['FAIL', '/opt/astra/scanner/dadar-001 not found — create directory and grant ASTRA write permission'],
    test_eeh_connectivity: ['PASS', 'gRPC ping OK 4ms'],
    test_auth_pu: ['WARN', 'LDAP bind OK but took 190ms — verify AD health under load'],
    test_sb_connector: ['WARN', 'SFTP connected but write test took 2.8s — check SB SFTP bandwidth'],
  },
  { // mostly warns, a few passes
    test_cbs: ['PASS', 'Finacle API responded in 18ms'],
    test_ngch: ['WARN', 'SFTP slow: 2.1s handshake — NGCH link may be congested'],
    test_kafka: ['PASS', 'Produced + consumed in 22ms'],
    test_immudb: ['PASS', 'AuditEvent verified in 14ms'],
    test_signature_vault: ['PASS', 'Redis CTS ping OK 1ms'],
    test_pps_vault: ['WARN', 'Only 2 entries seeded — complete seeding before go-live'],
    test_auth_sb: ['WARN', 'SAML cert expires in 8 days — renew before go-live'],
    test_iet_watchdog: ['WARN', 'Cheque processed OK but took 580ms — close to 600ms SLA; add GPU capacity'],
    test_auth_smb: ['PASS', 'Local auth OK 8ms'],
    test_sftp_push: ['WARN', 'SFTP connected but write took 3.2s — check network path to Agency'],
    test_vault_seeded: ['PASS', '12 of 12 signatures seeded'],
    test_smb_cbs: ['SKIP', 'No SMB_CBS MCP connection configured — skipping'],
    test_auth_branch: ['PASS', 'LDAP bind OK'],
    test_scanner_folder: ['WARN', '/opt/astra/scanner exists but scanner user lacks write permission — check ACL'],
    test_eeh_connectivity: ['WARN', 'gRPC OK but TLS handshake took 1.2s — check mTLS cert rotation'],
    test_auth_pu: ['PASS', 'LDAP bind OK 14ms'],
    test_sb_connector: ['PASS', 'SFTP to SB connected and writable'],
  },
]

const BASE_LATENCY = {
  test_cbs: 18, test_ngch: 45, test_kafka: 22, test_immudb: 14,
  test_signature_vault: 3, test_pps_vault: 4, test_auth_sb: 55,
  test_iet_watchdog: 487, test_auth_smb: 8, test_sftp_push: 120,
  test_vault_seeded: 5, test_smb_cbs: null, test_auth_branch: 12,
  test_scanner_folder: 2, test_eeh_connectivity: 4, test_auth_pu: 14,
  test_sb_connector: 65,
}

const STATUS_CLASSES = {
  PASS:    { pill: 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30', bar: 'bg-emerald-500', text: 'text-emerald-400' },
  WARN:    { pill: 'bg-amber-500/15 text-amber-400 border border-amber-500/30',       bar: 'bg-amber-400',  text: 'text-amber-400'  },
  FAIL:    { pill: 'bg-red-500/15 text-red-400 border border-red-500/30',             bar: 'bg-red-500',    text: 'text-red-400'    },
  SKIP:    { pill: 'bg-slate-500/15 text-slate-400 border border-slate-500/20',       bar: 'bg-slate-600',  text: 'text-slate-400'  },
  RUNNING: { pill: 'bg-violet-500/15 text-violet-400 border border-violet-500/30',    bar: 'bg-violet-500', text: 'text-violet-400' },
  PENDING: { pill: 'bg-slate-700/30 text-slate-500 border border-slate-700/20',       bar: 'bg-slate-700',  text: 'text-slate-500'  },
}

const STATUS_CLASSES_LIGHT = {
  PASS:    { pill: 'bg-emerald-50 text-emerald-700 border border-emerald-200',   bar: 'bg-emerald-500', text: 'text-emerald-600' },
  WARN:    { pill: 'bg-amber-50 text-amber-700 border border-amber-200',         bar: 'bg-amber-400',   text: 'text-amber-600'  },
  FAIL:    { pill: 'bg-red-50 text-red-700 border border-red-200',               bar: 'bg-red-500',     text: 'text-red-600'    },
  SKIP:    { pill: 'bg-slate-100 text-slate-500 border border-slate-200',        bar: 'bg-slate-300',   text: 'text-slate-500'  },
  RUNNING: { pill: 'bg-violet-50 text-violet-700 border border-violet-200',      bar: 'bg-violet-500',  text: 'text-violet-600' },
  PENDING: { pill: 'bg-slate-100 text-slate-400 border border-slate-200',        bar: 'bg-slate-200',   text: 'text-slate-400'  },
}

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)) }

export default function CTSSmokeTest() {
  const { isDark } = useTheme()
  const { isSB, isSMB } = useBankContext()

  // SB IT admin can initiate tests for all entity types; SMB users see only their own
  const availableEntities = isSB
    ? ['sb', 'smb', 'branch', 'pu']
    : ['smb']

  const [activeEntity, setActiveEntity] = useState(availableEntities[0])
  const [testStates, setTestStates] = useState({})   // { [test_id]: { status, message, latency } }
  const [running, setRunning] = useState(false)
  const [ran, setRan] = useState(false)
  const scenarioRef = useRef(0)

  const sc = isDark ? STATUS_CLASSES : STATUS_CLASSES_LIGHT

  const th = {
    page:     isDark ? 'bg-navy-950'           : 'bg-slate-50',
    card:     isDark ? 'bg-navy-900/60 border-white/8' : 'bg-white border-slate-200',
    heading:  isDark ? 'text-white'            : 'text-slate-900',
    body:     isDark ? 'text-slate-300'        : 'text-slate-700',
    muted:    isDark ? 'text-slate-400'        : 'text-slate-500',
    faint:    isDark ? 'text-slate-600'        : 'text-slate-400',
    divider:  isDark ? 'border-white/8'        : 'border-slate-200',
    tabBar:   isDark ? 'bg-navy-950 border-white/8' : 'bg-slate-50 border-slate-200',
    tabActive: isDark ? 'bg-white/10 text-white border-white/20' : 'bg-white text-slate-900 border-slate-200 shadow-sm',
    tabInact:  isDark ? 'text-slate-400 hover:text-slate-200 border-transparent' : 'text-slate-500 hover:text-slate-700 border-transparent',
    rowHover:  isDark ? 'hover:bg-white/3'     : 'hover:bg-slate-50',
    secLabel:  isDark ? 'text-slate-600'       : 'text-slate-400',
    mono:      'font-mono',
  }

  function getAllTests() {
    const edata = ENTITY_SECTIONS[activeEntity]
    return Object.values(edata.sections).flat()
  }

  function buildSummary() {
    const vals = Object.values(testStates)
    const total = getAllTests().length
    const pass = vals.filter((r) => r.status === 'PASS').length
    const fail = vals.filter((r) => r.status === 'FAIL').length
    const warn = vals.filter((r) => r.status === 'WARN').length
    const done = vals.length
    return { total, done, pass, fail, warn, allClear: fail === 0 && done === total }
  }

  async function runAll() {
    if (running) return
    setRunning(true)
    setRan(false)
    setTestStates({})

    const outcomes = DEMO_OUTCOMES[scenarioRef.current % DEMO_OUTCOMES.length]
    const tests = getAllTests()

    for (const t of tests) {
      setTestStates((prev) => ({ ...prev, [t.id]: { status: 'RUNNING', message: 'Checking…', latency: null } }))
      await sleep(300 + Math.random() * 250)

      const [status, message] = outcomes[t.id] || ['PASS', 'OK']
      const baseMs = BASE_LATENCY[t.id]
      const latency = baseMs === null ? null : (status === 'FAIL' ? null : baseMs + Math.floor(Math.random() * 30))
      setTestStates((prev) => ({ ...prev, [t.id]: { status, message, latency } }))
    }

    scenarioRef.current += 1
    setRunning(false)
    setRan(true)
  }

  function handleEntityChange(eid) {
    if (running) return
    setActiveEntity(eid)
    setTestStates({})
    setRan(false)
  }

  function downloadReport() {
    if (!ran) return
    const tests = getAllTests()
    const report = {
      entity_type: activeEntity,
      bank_id: 'saraswat-coop',
      run_at: new Date().toISOString(),
      results: tests.map((t) => {
        const r = testStates[t.id] || { status: 'SKIP', message: 'Not run', latency: null }
        return { test_id: t.id, name: t.name, status: r.status, latency_ms: r.latency, message: r.message }
      }),
      summary: buildSummary(),
    }
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `astra-smoke-test-${activeEntity}-${new Date().toISOString().split('T')[0]}.json`
    a.click()
  }

  const summary = buildSummary()

  return (
    <AppShell>
      <div className={`flex-1 min-h-full ${th.page}`}>

        {/* ── Page header ──────────────────────────────────────────────── */}
        <div className={`px-6 pt-5 pb-4 border-b ${th.divider}`}>
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <h1 className={`text-base font-semibold ${th.heading}`}>Pre-Live Smoke Test</h1>
              <p className={`text-xs mt-0.5 ${th.muted}`}>
                Validate all connections, vaults, auth connectors, and IET infrastructure before go-live.
                Run one entity at a time; all tests must be PASS or WARN before activating.
              </p>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button
                onClick={downloadReport}
                disabled={!ran || running}
                className={`text-xs px-3 py-1.5 rounded-md border font-medium transition-all
                  ${ran && !running
                    ? (isDark ? 'border-white/15 text-slate-300 hover:text-white hover:border-white/30' : 'border-slate-200 text-slate-600 hover:border-slate-400 hover:text-slate-800')
                    : 'opacity-30 cursor-default border-transparent ' + th.muted
                  }`}
              >
                ↓ Download Report
              </button>
              <button
                onClick={runAll}
                disabled={running}
                className={`text-xs px-4 py-1.5 rounded-md font-semibold transition-all
                  ${running
                    ? 'bg-violet-600/40 text-violet-300 cursor-default'
                    : 'bg-violet-600 hover:bg-violet-500 text-white'
                  }`}
              >
                {running ? '◌ Running…' : ran ? '↺ Run Again' : '▶ Run All Tests'}
              </button>
            </div>
          </div>

          {/* Summary strip */}
          {(ran || running) && (
            <div className="flex items-center gap-3 mt-3 flex-wrap">
              <span className={`text-xs ${th.faint} ${th.mono}`}>{summary.done}/{summary.total}</span>
              {summary.pass > 0 && (
                <span className={`text-xs font-mono font-semibold ${isDark ? 'text-emerald-400' : 'text-emerald-600'}`}>
                  ✓ {summary.pass} pass
                </span>
              )}
              {summary.fail > 0 && (
                <span className={`text-xs font-mono font-semibold ${isDark ? 'text-red-400' : 'text-red-600'}`}>
                  ✗ {summary.fail} fail
                </span>
              )}
              {summary.warn > 0 && (
                <span className={`text-xs font-mono font-semibold ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>
                  △ {summary.warn} warn
                </span>
              )}
              {ran && summary.done === summary.total && (
                summary.fail === 0
                  ? <span className={`ml-auto text-xs font-mono font-bold px-2.5 py-0.5 rounded ${isDark ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30' : 'bg-emerald-50 text-emerald-700 border border-emerald-200'}`}>
                      ALL CLEAR
                    </span>
                  : <span className={`ml-auto text-xs font-mono font-bold px-2.5 py-0.5 rounded ${isDark ? 'bg-red-500/15 text-red-400 border border-red-500/30' : 'bg-red-50 text-red-700 border border-red-200'}`}>
                      {summary.fail} FAILURE{summary.fail > 1 ? 'S' : ''} — RESOLVE BEFORE GO-LIVE
                    </span>
              )}
            </div>
          )}
        </div>

        {/* ── Entity tabs ──────────────────────────────────────────────── */}
        <div className={`px-6 pt-3 flex gap-1 border-b ${th.divider}`}>
          {availableEntities.map((eid) => {
            const edata = ENTITY_SECTIONS[eid]
            const testCount = Object.values(edata.sections).flat().length
            const isActive = activeEntity === eid
            return (
              <button
                key={eid}
                onClick={() => handleEntityChange(eid)}
                className={`flex items-center gap-2 px-3 py-2 mb-[-1px] text-xs font-semibold rounded-t-md border transition-all
                  ${isActive ? th.tabActive : th.tabInact}`}
              >
                <span className={`font-mono text-[10px] font-bold px-1.5 py-0.5 rounded
                  ${isActive
                    ? (isDark ? 'bg-violet-500/20 text-violet-400' : 'bg-violet-600 text-white')
                    : (isDark ? 'bg-white/5 text-slate-500' : 'bg-slate-100 text-slate-500')
                  }`}
                >
                  {edata.label}
                </span>
                {edata.fullName}
                <span className={`text-[10px] font-mono ${isActive ? (isDark ? 'text-slate-400' : 'text-slate-400') : th.faint}`}>
                  {testCount}
                </span>
              </button>
            )
          })}
        </div>

        {/* ── Test list ─────────────────────────────────────────────────── */}
        <div className="px-6 py-4 space-y-6">
          {Object.entries(ENTITY_SECTIONS[activeEntity].sections).map(([sectionName, tests]) => (
            <div key={sectionName}>
              <div className={`text-[10px] font-bold uppercase tracking-widest ${th.secLabel} mb-2 pb-1 border-b ${th.divider}`}>
                {sectionName}
              </div>
              <div className="space-y-1.5">
                {tests.map((t) => {
                  const res = testStates[t.id]
                  const status = res?.status || 'PENDING'
                  const styles = sc[status] || sc.PENDING
                  const isRunning = status === 'RUNNING'

                  return (
                    <div
                      key={t.id}
                      className={`flex items-stretch rounded-md border overflow-hidden transition-all ${th.card} ${th.rowHover}`}
                    >
                      {/* Left status bar */}
                      <div
                        className={`w-1 shrink-0 ${styles.bar} transition-colors duration-300 ${isRunning ? 'animate-pulse' : ''}`}
                      />

                      {/* Main content */}
                      <div className="flex-1 px-3 py-2.5 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className={`text-sm font-medium ${th.heading}`}>{t.name}</span>
                          <span className={`text-[10px] font-mono font-bold px-1.5 py-0.5 rounded transition-all ${styles.pill}`}>
                            {status}
                          </span>
                        </div>
                        <div className={`text-xs mt-0.5 ${res?.message ? th.body : th.faint}`}>
                          {res?.message || t.desc}
                        </div>
                      </div>

                      {/* Right: latency + test id */}
                      <div className="shrink-0 px-3 py-2.5 flex flex-col items-end justify-center text-right">
                        {res?.latency !== null && res?.latency !== undefined && status !== 'RUNNING' ? (
                          <>
                            <span className={`text-xs font-mono font-semibold tabular-nums
                              ${res.latency < 200
                                ? (isDark ? 'text-emerald-400' : 'text-emerald-600')
                                : res.latency > 600
                                  ? (isDark ? 'text-red-400' : 'text-red-600')
                                  : (isDark ? 'text-amber-400' : 'text-amber-600')
                              }`}
                            >
                              {res.latency}ms
                            </span>
                            <span className={`text-[10px] ${th.faint} font-mono uppercase tracking-wider`}>latency</span>
                          </>
                        ) : isRunning ? (
                          <span className={`text-xs font-mono ${isDark ? 'text-violet-400' : 'text-violet-600'} animate-pulse`}>···</span>
                        ) : (
                          <span className={`text-xs font-mono ${th.faint}`}>—</span>
                        )}
                        <span className={`text-[10px] font-mono mt-1 ${th.faint}`}>{t.id}</span>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          ))}

          {/* Bottom note */}
          <p className={`text-[11px] ${th.faint} pt-2 pb-4`}>
            WARN is advisory and does not block go-live. FAIL must be resolved. SKIP means the test
            is not applicable or the integration is not configured for this entity.
          </p>
        </div>
      </div>
    </AppShell>
  )
}

import { useState, useRef, useEffect, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'

const API = import.meta.env.VITE_API_BASE || ''

// ── Entity test registry (mirrors backend _ENTITY_TESTS) ─────────────────

const ENTITY_SECTIONS = {
  sb: {
    label: 'SB', fullName: 'Sponsor Bank',
    sections: {
      'Core Infrastructure': [
        { id: 'test_cbs',             name: 'CBS Connectivity',                desc: 'Finacle/BaNCS/FlexCube API ping' },
        { id: 'test_ngch',            name: 'NGCH Adapter',                    desc: 'SFTP/REST transport to NGCH' },
        { id: 'test_kafka',           name: 'Kafka Topics',                    desc: 'Produce + consume cts.inward test event' },
        { id: 'test_immudb',          name: 'Immudb Audit Trail',              desc: 'Write + Merkle verify a test AuditEvent' },
      ],
      'Vaults': [
        { id: 'test_signature_vault', name: 'Signature Vault (Redis CTS)',     desc: 'Ping Redis + sample signature lookup' },
        { id: 'test_pps_vault',       name: 'PPS Vault (Redis CTS)',           desc: 'PPS vault ping + seeding count check' },
      ],
      'Authentication': [
        { id: 'test_auth_sb',         name: 'SB Auth — SAML / LDAP IdP',      desc: 'IdP metadata fetch + XML validation' },
      ],
      'End-to-End': [
        { id: 'test_iet_watchdog',    name: 'IET Watchdog (Synthetic Cheque)', desc: 'Temporal namespace reachable · IET workers assumed active' },
      ],
    },
  },
  smb: {
    label: 'SMB', fullName: 'Sub-Member Bank',
    sections: {
      'Authentication': [{ id: 'test_auth_smb',     name: 'SMB Auth Connector',      desc: 'Local argon2 DB reachable + verify test' }],
      'Connectivity':   [{ id: 'test_sftp_push',    name: 'Agency SFTP Push',         desc: 'Write test file to Agency SFTP drop path' }],
      'Vault Seeding':  [
        { id: 'test_vault_seeded', name: 'Signature Vault Seeding', desc: 'Count seeded signatures for SMB accounts' },
        { id: 'test_smb_cbs',     name: 'SMB CBS Connectivity',     desc: 'SMB CBS ping (skips if no SMB_CBS configured)' },
      ],
    },
  },
  branch: {
    label: 'Branch', fullName: 'Branch / Scanner',
    sections: {
      'Authentication': [{ id: 'test_auth_branch',      name: 'Branch Auth — LDAP-AD',      desc: 'LDAPS bind + group resolution' }],
      'Scanner':        [{ id: 'test_scanner_folder',   name: 'Scanner Drop Folder',         desc: 'Path exists + write permission check' }],
      'Session':        [{ id: 'test_eeh_connectivity', name: 'EEH/IEH Session (gRPC)',      desc: 'gRPC ping to eeh-service' }],
    },
  },
  pu: {
    label: 'PU', fullName: 'Processing Unit',
    sections: {
      'Authentication':   [{ id: 'test_auth_pu',         name: 'PU Auth — LDAP-AD',      desc: 'LDAPS bind + group resolution' }],
      'SB Connectivity':  [{ id: 'test_sb_connector',    name: 'Agency → SB Connector',  desc: 'SFTP write to SB lots path' }],
      'Scanner & Session':[
        { id: 'test_scanner_folder',   name: 'Scanner Drop Folder',   desc: 'Path exists + write permission check' },
        { id: 'test_eeh_connectivity', name: 'EEH/IEH Session (gRPC)',desc: 'gRPC ping to eeh-service' },
      ],
    },
  },
}

// ── Infrastructure services (maps to /v1/ops/system response keys) ────────

const SERVICES = [
  { id: 'yugabyte',  label: 'YugabyteDB', stateKey: 'yugabyte',  connKey: 'connected', critical: true  },
  { id: 'kafka',     label: 'Kafka',       stateKey: 'kafka',     connKey: 'connected', critical: true  },
  { id: 'redis-cts', label: 'Redis CTS',   stateKey: 'redis_cts', connKey: 'connected', critical: true  },
  { id: 'temporal',  label: 'Temporal',    stateKey: 'temporal',  connKey: 'connected', critical: true  },
  { id: 'vault',     label: 'Vault',       stateKey: 'vault',     connKey: 'connected', critical: true  },
  { id: 'minio',     label: 'MinIO',       stateKey: null,        connKey: null,         critical: false },
  { id: 'immudb',    label: 'Immudb',      stateKey: null,        connKey: null,         critical: true  },
  { id: 'vllm',      label: 'vLLM (AI)',   stateKey: null,        connKey: null,         critical: false },
]

// ── Startup sequence (mirrors _STARTUP_SEQUENCE in platform.py) ──────────
// afterMs = wait before advancing the visual progress indicator to the next tier.
// These match the _INTER_TIER_SLEEP on the backend (15s) plus startup buffer.
const STARTUP_TIERS = [
  { tier: 1, label: 'Foundation',    ids: ['vault', 'redis-cts', 'minio', 'immudb'], afterMs: 18_000 },
  { tier: 2, label: 'Data Layer',    ids: ['yugabyte', 'kafka'],                      afterMs: 20_000 },
  { tier: 3, label: 'Orchestration', ids: ['temporal'],                               afterMs: 5_000  },
  { tier: 4, label: 'AI Inference',  ids: ['vllm'],                                   afterMs: 0      },
]
// In POC mode these services run on HuggingFace — no local container, never Down.
const POC_HF_IDS = new Set(['vllm'])

// ── Demo fallback data (used when deploymentMode === 'DEMO') ──────────────

const DEMO_SYSTEM_HEALTH = {
  yugabyte:  { connected: true,  active_connections: 4, pool_size: 10, degraded: false },
  kafka:     { connected: true,  total_lag: 0, degraded: false },
  redis_cts: { connected: true,  hit_rate_pct: 99.2, degraded: false },
  temporal:  { connected: true,  degraded: false },
  vault:     { connected: true,  seal_status: 'unsealed', degraded: false },
}

const DEMO_READINESS_ITEMS = [
  { check_id: 'branches_loaded',  label: 'Branch Master loaded',      status: 'PASS', detail: '12 active branches' },
  { check_id: 'sig_vault_seeded', label: 'Signature Vault seeded',    status: 'WARN', detail: '847/1200 accounts (71%) — seed remaining before go-live', action_url: '/cts/vaults' },
  { check_id: 'pps_vault_seeded', label: 'PPS Vault seeded',          status: 'PASS', detail: '4 PPS entries in Redis' },
  { check_id: 'micr_prefixes',    label: 'MICR Prefixes configured',  status: 'PASS', detail: '3 prefixes configured' },
  { check_id: 'ops_users',        label: 'Ops reviewers configured',  status: 'PASS', detail: '2 reviewers, 1 manager' },
  { check_id: 'inward_folder',    label: 'Inward watch folder (POC)', status: 'PASS', detail: '/opt/astra/inward — writable', deployment_modes: ['POC'] },
  { check_id: 'outward_folder',   label: 'Outward output folder (POC)',status:'PASS', detail: '/opt/astra/outward — writable', deployment_modes: ['POC'] },
]

const DEMO_OUTCOMES = [
  {
    test_cbs: ['PASS', 'Finacle API /accounts/ping → 200 in 18ms'],
    test_ngch: ['PASS', 'SFTP handshake OK, root listing verified in 45ms'],
    test_kafka: ['PASS', 'Produced + consumed cts.inward test event in 22ms'],
    test_immudb: ['PASS', 'AuditEvent written + Merkle leaf verified in 14ms'],
    test_signature_vault: ['PASS', 'Redis CTS ping 1ms · sample sig lookup 3ms'],
    test_pps_vault: ['PASS', 'PPS vault ping OK · 4 PPS entries seeded for test accounts'],
    test_auth_sb: ['PASS', 'ADFS metadata at /FederationMetadata fetched, XML valid'],
    test_iet_watchdog: ['PASS', 'Temporal namespace reachable in 8ms · IET workers assumed active'],
    test_auth_smb: ['PASS', 'Local auth DB reachable · argon2 verify test OK in 8ms'],
    test_sftp_push: ['PASS', 'SFTP write to Agency sftp://saraswat-coop:22/smb-push OK in 120ms'],
    test_vault_seeded: ['WARN', '847 of 1200 accounts seeded — seed remaining before go-live'],
    test_smb_cbs: ['SKIP', 'No SMB_CBS MCP connection configured — skipping'],
    test_auth_branch: ['PASS', 'LDAP bind OK: CN=astra-svc,OU=ServiceAccounts,DC=saraswat-coop,DC=local'],
    test_scanner_folder: ['PASS', '/opt/astra/scanner/dadar-001 exists and is writable'],
    test_eeh_connectivity: ['PASS', 'gRPC ping to eeh-service.astra-cts-saraswat-coop:50051 → OK 4ms'],
    test_auth_pu: ['PASS', 'LDAP bind OK: CN=astra-svc,OU=ServiceAccounts,DC=saraswat-coop,DC=local'],
    test_sb_connector: ['PASS', 'SFTP to saraswat-sb.ngch.local:22 connected, /agency-cc/lots writable'],
  },
  {
    test_cbs: ['FAIL', 'Finacle API unreachable — check cbs.finacle.base_url in Vault'],
    test_ngch: ['PASS', 'SFTP handshake OK in 45ms'],
    test_kafka: ['WARN', 'Kafka ACK took 480ms — consumer lag may build during high volume'],
    test_immudb: ['PASS', 'AuditEvent written + verified in 14ms'],
    test_signature_vault: ['WARN', 'Redis hit but lookup took 28ms — check memory pressure'],
    test_pps_vault: ['WARN', 'PPS vault OK but only 2 entries seeded — seed all accounts before go-live'],
    test_auth_sb: ['PASS', 'ADFS metadata fetched, XML valid'],
    test_iet_watchdog: ['PASS', 'Temporal namespace reachable in 12ms'],
    test_auth_smb: ['PASS', 'Local auth DB reachable'],
    test_sftp_push: ['FAIL', 'SFTP connection refused — check Agency SFTP endpoint config'],
    test_vault_seeded: ['WARN', 'Only 2 of 12 signatures seeded'],
    test_smb_cbs: ['SKIP', 'No SMB_CBS MCP connection configured — skipping'],
    test_auth_branch: ['FAIL', 'LDAP server unreachable: ldaps://dc.saraswat-coop.local:636'],
    test_scanner_folder: ['FAIL', '/opt/astra/scanner/dadar-001 not found — create directory'],
    test_eeh_connectivity: ['PASS', 'gRPC ping OK 4ms'],
    test_auth_pu: ['WARN', 'LDAP bind OK but took 190ms — verify AD health under load'],
    test_sb_connector: ['WARN', 'SFTP connected but write test took 2.8s — check SB SFTP bandwidth'],
  },
  {
    test_cbs: ['PASS', 'Finacle API responded in 18ms'],
    test_ngch: ['WARN', 'SFTP slow: 2.1s handshake — NGCH link may be congested'],
    test_kafka: ['PASS', 'Produced + consumed in 22ms'],
    test_immudb: ['PASS', 'AuditEvent verified in 14ms'],
    test_signature_vault: ['PASS', 'Redis CTS ping OK 1ms'],
    test_pps_vault: ['WARN', 'Only 2 entries seeded — complete seeding before go-live'],
    test_auth_sb: ['WARN', 'SAML cert expires in 8 days — renew before go-live'],
    test_iet_watchdog: ['WARN', 'Temporal OK but took 580ms — check Temporal server load'],
    test_auth_smb: ['PASS', 'Local auth OK 8ms'],
    test_sftp_push: ['WARN', 'SFTP connected but write took 3.2s — check network path to Agency'],
    test_vault_seeded: ['PASS', '1200 of 1200 signatures seeded'],
    test_smb_cbs: ['SKIP', 'No SMB_CBS MCP connection configured — skipping'],
    test_auth_branch: ['PASS', 'LDAP bind OK'],
    test_scanner_folder: ['WARN', '/opt/astra/scanner exists but scanner user lacks write permission'],
    test_eeh_connectivity: ['WARN', 'gRPC OK but TLS handshake took 1.2s — check mTLS cert rotation'],
    test_auth_pu: ['PASS', 'LDAP bind OK 14ms'],
    test_sb_connector: ['PASS', 'SFTP to SB connected and writable'],
  },
]

const BASE_LATENCY = {
  test_cbs: 18, test_ngch: 45, test_kafka: 22, test_immudb: 14,
  test_signature_vault: 3, test_pps_vault: 4, test_auth_sb: 55,
  test_iet_watchdog: 8, test_auth_smb: 8, test_sftp_push: 120,
  test_vault_seeded: 5, test_smb_cbs: null, test_auth_branch: 12,
  test_scanner_folder: 2, test_eeh_connectivity: 4, test_auth_pu: 14,
  test_sb_connector: 65,
}

// ── Status style maps ─────────────────────────────────────────────────────

const SC_DARK = {
  PASS:    { pill: 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30', bar: 'bg-emerald-500', text: 'text-emerald-400', dot: 'bg-emerald-500' },
  WARN:    { pill: 'bg-amber-500/15 text-amber-400 border border-amber-500/30',       bar: 'bg-amber-400',  text: 'text-amber-400',  dot: 'bg-amber-400'   },
  FAIL:    { pill: 'bg-red-500/15 text-red-400 border border-red-500/30',             bar: 'bg-red-500',    text: 'text-red-400',    dot: 'bg-red-500'     },
  SKIP:    { pill: 'bg-slate-500/15 text-slate-400 border border-slate-500/20',       bar: 'bg-slate-600',  text: 'text-slate-400',  dot: 'bg-slate-600'   },
  RUNNING: { pill: 'bg-violet-500/15 text-violet-400 border border-violet-500/30',    bar: 'bg-violet-500', text: 'text-violet-400', dot: 'bg-violet-400'  },
  PENDING: { pill: 'bg-slate-700/30 text-slate-500 border border-slate-700/20',       bar: 'bg-slate-700',  text: 'text-slate-500',  dot: 'bg-slate-700'   },
}
const SC_LIGHT = {
  PASS:    { pill: 'bg-emerald-50 text-emerald-700 border border-emerald-200',  bar: 'bg-emerald-500', text: 'text-emerald-600', dot: 'bg-emerald-500' },
  WARN:    { pill: 'bg-amber-50 text-amber-700 border border-amber-200',        bar: 'bg-amber-400',   text: 'text-amber-600',  dot: 'bg-amber-400'   },
  FAIL:    { pill: 'bg-red-50 text-red-700 border border-red-200',              bar: 'bg-red-500',     text: 'text-red-600',    dot: 'bg-red-500'     },
  SKIP:    { pill: 'bg-slate-100 text-slate-500 border border-slate-200',       bar: 'bg-slate-300',   text: 'text-slate-500',  dot: 'bg-slate-300'   },
  RUNNING: { pill: 'bg-violet-50 text-violet-700 border border-violet-200',     bar: 'bg-violet-500',  text: 'text-violet-600', dot: 'bg-violet-400'  },
  PENDING: { pill: 'bg-slate-100 text-slate-400 border border-slate-200',       bar: 'bg-slate-200',   text: 'text-slate-400',  dot: 'bg-slate-200'   },
}

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)) }

// ── API helpers ───────────────────────────────────────────────────────────

async function apiFetch(path, opts = {}) {
  const csrf = sessionStorage.getItem('astra-csrf') || ''
  const res = await fetch(`${API}${path}`, {
    credentials: 'include',
    headers: { 'X-CSRF-Token': csrf, ...opts.headers },
    ...opts,
  })
  if (!res.ok) { const b = await res.json().catch(() => ({})); throw new Error(b.detail || `HTTP ${res.status}`) }
  return res.json()
}

const fetchSystemHealth = () => apiFetch('/v1/ops/system')
const fetchDockerStatus = () => apiFetch('/v1/platform/services/status')
const fetchReadiness    = () => apiFetch('/v1/platform/readiness')
const postStartService  = (id) => apiFetch(`/v1/platform/services/${id}/start`, { method: 'POST' })
const postStartAll      = ()   => apiFetch('/v1/platform/services/start-all',    { method: 'POST' })
const postRunSmokeTests = (entity, bankId) => apiFetch('/v1/platform/smoke-test/run', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ entity, bank_id: bankId }),
})

// ── ServiceControlPanel ───────────────────────────────────────────────────

function ServiceControlPanel({ isDark, isDemo, isPOC, bankId, isAdmin }) {
  const th = {
    card:    isDark ? 'bg-navy-900/60 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'     : 'text-slate-900',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    faint:   isDark ? 'text-slate-600' : 'text-slate-400',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    secLabel:isDark ? 'text-slate-600' : 'text-slate-400',
    seqCard: isDark ? 'bg-navy-900/40 border-white/6' : 'bg-slate-50 border-slate-200',
  }

  const qc = useQueryClient()
  const { data: health, isLoading, dataUpdatedAt } = useQuery({
    queryKey: ['system-health', bankId],
    queryFn: fetchSystemHealth,
    refetchInterval: 15_000,
    enabled: !isDemo,
    retry: 1,
  })
  // Docker container running state — authoritative even when app.state has no live connections
  const { data: dockerStatus } = useQuery({
    queryKey: ['docker-status', bankId],
    queryFn: fetchDockerStatus,
    refetchInterval: 10_000,
    enabled: !isDemo,
    retry: 1,
  })

  // ── Individual service start ──
  const startMut = useMutation({
    mutationFn: postStartService,
    onSuccess: () => setTimeout(() => {
      qc.invalidateQueries(['system-health', bankId])
      qc.invalidateQueries(['docker-status', bankId])
    }, 3000),
  })

  // ── Start-All sequence state ──
  // seqState: null | { running: bool, activeTier: number, elapsed: number, results: {[id]: ServiceStartResponse} }
  const [seqState, setSeqState] = useState(null)
  const timerRef = useRef(null)

  // Animate elapsed time while start-all is running (used to advance tier indicators visually)
  useEffect(() => {
    if (seqState?.running) {
      timerRef.current = setInterval(
        () => setSeqState(s => s && s.running ? { ...s, elapsed: (s.elapsed ?? 0) + 1 } : s),
        1000,
      )
    } else {
      clearInterval(timerRef.current)
    }
    return () => clearInterval(timerRef.current)
  }, [seqState?.running])

  // Derive the visually-active tier from elapsed seconds when waiting for the backend.
  // Thresholds loosely match _INTER_TIER_SLEEP (15s) + startup buffer on the backend.
  function estimatedTier(elapsed) {
    if (elapsed < 20) return 1
    if (elapsed < 40) return 2
    if (elapsed < 55) return 3
    return 4
  }

  async function handleStartAll() {
    if (seqState?.running || isDemo) return
    // Pre-populate HF entries so they show immediately in the sequence panel
    const initResults = {}
    if (isPOC) POC_HF_IDS.forEach(id => {
      initResults[id] = { service: id, success: true, skipped: true, message: 'HF Inference API' }
    })
    setSeqState({ running: true, activeTier: 1, elapsed: 0, results: initResults })
    try {
      const data = await postStartAll()
      // Flatten tier results into a map keyed by service id
      const flatResults = {}
      for (const tier of (data?.tiers ?? [])) {
        for (const svc of tier.services) flatResults[svc.service] = svc
      }
      setSeqState(s => ({ ...s, running: false, results: { ...s.results, ...flatResults } }))
    } catch (err) {
      setSeqState(s => ({ ...s, running: false, error: err.message || 'Backend unreachable' }))
    }
    setTimeout(() => {
      qc.invalidateQueries(['system-health', bankId])
      qc.invalidateQueries(['docker-status', bankId])
    }, 3000)
  }

  const effectiveHealth = isDemo ? DEMO_SYSTEM_HEALTH : health

  function _healthDetail(svc, panel) {
    if (svc.id === 'yugabyte')  return `${panel.active_connections ?? 0} active conn`
    if (svc.id === 'kafka')     return `lag: ${panel.total_lag ?? 0}`
    if (svc.id === 'redis-cts') return `${panel.hit_rate_pct ?? 0}% hit rate`
    if (svc.id === 'temporal')  return 'namespace reachable'
    if (svc.id === 'vault')     return panel.seal_status ?? 'unsealed'
    return ''
  }

  function svcStatus(svc) {
    // vLLM is HF-hosted in POC — never shown as DOWN
    if (isPOC && POC_HF_IDS.has(svc.id)) return { up: true, detail: 'Hugging Face API', hf: true }

    // Docker container state — authoritative source (works even when app.state has no connections)
    if (dockerStatus) {
      const running = dockerStatus[svc.id]
      if (running === false) return { up: false, detail: 'container stopped', hf: false }
      if (running === true) {
        // Overlay real health details if the backend is also connected
        if (effectiveHealth && svc.stateKey) {
          const panel = effectiveHealth[svc.stateKey]
          if (panel && Boolean(panel[svc.connKey])) {
            return { up: true, detail: _healthDetail(svc, panel), hf: false }
          }
        }
        return { up: true, detail: 'running', hf: false }
      }
      // running === undefined means service not in docker status (minio, immudb, vllm)
    }

    // Fall back to health check (PROD: app.state connections are real)
    if (!effectiveHealth || !svc.stateKey) return { up: isDemo, detail: isDemo ? 'OK' : '—' }
    const panel = effectiveHealth[svc.stateKey]
    if (!panel) return { up: false, detail: 'not in response' }
    const up = Boolean(panel[svc.connKey])
    return { up, detail: up ? _healthDetail(svc, panel) : 'DOWN', hf: false }
  }

  const lastRefreshed = dataUpdatedAt ? new Date(dataUpdatedAt).toLocaleTimeString() : '—'
  const anyDown = !isDemo && SERVICES.some(svc => !svcStatus(svc).up)

  // When start-all is running, derive active tier from elapsed if backend hasn't
  // returned yet (gives real-time visual feedback during the blocking API call).
  const displayTier = seqState?.running
    ? estimatedTier(seqState.elapsed ?? 0)
    : (seqState?.activeTier ?? 0)

  return (
    <div className={`px-6 pt-4 pb-4 border-b ${th.divider}`}>

      {/* ── Header ── */}
      <div className="flex items-center justify-between mb-3">
        <div className={`text-[10px] font-bold uppercase tracking-widest ${th.secLabel}`}>
          Infrastructure Services
        </div>
        <div className="flex items-center gap-3">
          {!isDemo && (
            <span className={`text-[10px] ${th.faint}`}>
              {isLoading ? 'checking…' : `refreshed ${lastRefreshed} · auto 15s`}
            </span>
          )}
          {isDemo && (
            <span className={`text-[10px] px-2 py-0.5 rounded border ${isDark ? 'bg-amber-500/10 border-amber-500/30 text-amber-400' : 'bg-amber-50 border-amber-200 text-amber-600'}`}>
              DEMO — simulated
            </span>
          )}
          {/* Start All — bank_it_admin only; ops_manager can view status but not start */}
          {!isDemo && isAdmin && anyDown && (
            <button
              onClick={handleStartAll}
              disabled={seqState?.running}
              title="Start all infra services in dependency order via docker compose"
              className={`text-[10px] px-2.5 py-1 rounded font-semibold border transition-all ${
                seqState?.running
                  ? (isDark ? 'bg-violet-500/10 border-violet-500/20 text-violet-400 cursor-default' : 'bg-violet-50 border-violet-200 text-violet-500 cursor-default')
                  : (isDark ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/20' : 'bg-emerald-50 border-emerald-200 text-emerald-700 hover:bg-emerald-100')
              }`}
            >
              {seqState?.running ? `◌ Starting… (${seqState.elapsed ?? 0}s)` : '⬤ Start All Services'}
            </button>
          )}
        </div>
      </div>

      {/* ── Service cards grid ── */}
      <div className="grid grid-cols-4 gap-2">
        {SERVICES.map(svc => {
          const { up, detail, hf } = svcStatus(svc)
          const starting = startMut.isPending && startMut.variables === svc.id

          return (
            <div key={svc.id} className={`rounded-lg border px-3 py-2.5 ${th.card} transition-all`}>
              <div className="flex items-center justify-between gap-1 mb-1">
                <div className="flex items-center gap-1.5 min-w-0">
                  <span className={`w-2 h-2 shrink-0 rounded-full ${up ? 'bg-emerald-500' : 'bg-red-500 animate-pulse'}`} />
                  <span className={`text-[11px] font-semibold truncate ${th.heading}`}>{svc.label}</span>
                </div>
                {/* HF badge — for POC-hosted services */}
                {hf && (
                  <span className={`shrink-0 text-[8px] px-1.5 py-0.5 rounded font-bold border ${isDark ? 'bg-amber-500/10 border-amber-500/30 text-amber-400' : 'bg-amber-50 border-amber-200 text-amber-700'}`}>
                    HF
                  </span>
                )}
                {/* Start button — bank_it_admin only */}
                {!up && !isDemo && !hf && isAdmin && (
                  <button
                    onClick={() => startMut.mutate(svc.id)}
                    disabled={starting || seqState?.running}
                    title={starting ? 'Starting…' : `docker compose up -d ${svc.id}`}
                    className={`shrink-0 text-[9px] px-1.5 py-0.5 rounded font-semibold border transition-all ${
                      starting
                        ? 'bg-violet-500/10 border-violet-500/20 text-violet-400'
                        : (isDark
                          ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/20 disabled:opacity-30'
                          : 'bg-emerald-50 border-emerald-200 text-emerald-700 hover:bg-emerald-100 disabled:opacity-30')
                    }`}
                  >
                    {starting ? '◌' : 'Start'}
                  </button>
                )}
              </div>
              <div className={`text-[10px] truncate ${
                hf ? (isDark ? 'text-amber-500/70' : 'text-amber-600/70') :
                up  ? th.faint : (isDark ? 'text-red-400' : 'text-red-600')
              }`}>
                {detail}
              </div>
              {startMut.isSuccess && startMut.variables === svc.id && (
                <div className={`text-[9px] mt-0.5 truncate ${isDark ? 'text-emerald-400' : 'text-emerald-600'}`}>
                  {startMut.data?.message?.slice(0, 60)}
                </div>
              )}
              {startMut.isError && startMut.variables === svc.id && (
                <div className="text-[9px] mt-0.5 truncate text-red-400">
                  {startMut.error?.message?.slice(0, 55) || 'Backend unreachable'}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* ── Startup sequence progress panel ── */}
      {seqState && (
        <div className={`mt-3 rounded-lg border px-4 py-3 ${th.seqCard}`}>
          <div className="flex items-center justify-between mb-2.5">
            <div className={`text-[10px] font-bold uppercase tracking-widest ${th.secLabel}`}>
              Startup Sequence
              {seqState.running && <span className={`ml-2 font-normal normal-case ${th.faint}`}>— waiting for backend ({seqState.elapsed ?? 0}s)</span>}
              {!seqState.running && !seqState.error && <span className={`ml-2 font-normal normal-case ${isDark ? 'text-emerald-500' : 'text-emerald-600'}`}>— complete</span>}
              {seqState.error && <span className={`ml-2 font-normal normal-case text-red-400`}>— {seqState.error}</span>}
            </div>
            {!seqState.running && (
              <button
                onClick={() => setSeqState(null)}
                className={`text-[9px] ${th.faint} hover:${th.muted} transition-colors`}
              >
                dismiss
              </button>
            )}
          </div>

          <div className="space-y-2">
            {STARTUP_TIERS.map(({ tier, label, ids }) => {
              const isActive = seqState.running && displayTier === tier
              const isPast   = !seqState.running || displayTier > tier
              const isFuture = seqState.running && displayTier < tier

              return (
                <div key={tier} className={`flex items-start gap-2.5 transition-opacity ${isFuture ? 'opacity-30' : ''}`}>
                  {/* Tier badge */}
                  <span className={`mt-0.5 shrink-0 text-[8px] w-7 text-center py-0.5 rounded font-mono font-bold ${
                    isActive ? (isDark ? 'bg-violet-500/20 text-violet-300 ring-1 ring-violet-500/40' : 'bg-violet-100 text-violet-700 ring-1 ring-violet-300') :
                    isPast   ? (isDark ? 'bg-emerald-500/15 text-emerald-400' : 'bg-emerald-50 text-emerald-700') :
                               (isDark ? 'bg-slate-700/60 text-slate-500' : 'bg-slate-100 text-slate-400')
                  }`}>
                    T{tier}
                  </span>

                  <div className="flex-1 min-w-0">
                    <div className={`text-[10px] font-semibold mb-1 ${isActive ? (isDark ? 'text-violet-300' : 'text-violet-700') : th.heading}`}>
                      {label}
                      {isActive && <span className={`ml-1.5 font-normal ${th.faint}`}>starting…</span>}
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {ids.map(id => {
                        const r = seqState.results[id]
                        const chip = !r
                          ? { cls: isDark ? 'border-slate-700 text-slate-600 bg-transparent' : 'border-slate-200 text-slate-400 bg-transparent', prefix: '' }
                          : r.skipped
                          ? { cls: isDark ? 'border-amber-700/40 text-amber-400 bg-amber-900/15' : 'border-amber-200 text-amber-700 bg-amber-50', prefix: '' }
                          : r.success
                          ? { cls: isDark ? 'border-emerald-700/40 text-emerald-400 bg-emerald-900/15' : 'border-emerald-200 text-emerald-700 bg-emerald-50', prefix: '✓ ' }
                          : { cls: isDark ? 'border-red-700/40 text-red-400 bg-red-900/15' : 'border-red-200 text-red-700 bg-red-50', prefix: '✗ ' }
                        return (
                          <span
                            key={id}
                            title={r?.message}
                            className={`text-[9px] px-1.5 py-0.5 rounded border font-mono ${chip.cls}`}
                          >
                            {chip.prefix}{id}
                            {r?.skipped && <span className={`ml-1 text-[8px] ${isDark ? 'text-amber-500/60' : 'text-amber-600/60'}`}>HF</span>}
                          </span>
                        )
                      })}
                    </div>
                    {/* Per-service error messages from the backend */}
                    {ids.map(id => {
                      const r = seqState.results[id]
                      if (!r || r.success) return null
                      return (
                        <div key={id} className={`mt-0.5 text-[9px] ${isDark ? 'text-red-400' : 'text-red-600'} truncate`}>
                          {id}: {r.message?.slice(0, 80)}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )
            })}
          </div>

          {/* Compose file hint */}
          {!seqState.running && (
            <div className={`mt-2.5 pt-2 border-t ${th.divider} text-[9px] font-mono ${th.faint}`}>
              docker compose -f infra/docker-compose.dev.yml up -d
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── ReadinessPanel ────────────────────────────────────────────────────────

function ReadinessPanel({ isDark, isDemo, bankId, deploymentMode }) {
  const navigate = useNavigate()
  const th = {
    divider:  isDark ? 'border-white/8' : 'border-slate-200',
    secLabel: isDark ? 'text-slate-600' : 'text-slate-400',
    label:    isDark ? 'text-slate-300' : 'text-slate-700',
    detail:   isDark ? 'text-slate-500' : 'text-slate-400',
    rowHover: isDark ? 'hover:bg-white/2' : 'hover:bg-slate-50',
  }

  const { data: readiness, isLoading, dataUpdatedAt } = useQuery({
    queryKey: ['readiness', bankId],
    queryFn: fetchReadiness,
    refetchInterval: 60_000,
    enabled: !isDemo,
    retry: 1,
  })

  const rawItems  = isDemo ? DEMO_READINESS_ITEMS : (readiness?.items ?? [])
  const items = rawItems.filter(item =>
    !item.deployment_modes || item.deployment_modes.includes(deploymentMode)
  )

  const allReady = items.length > 0 && items.every(i => i.status === 'PASS' || i.status === 'SKIP')
  const failCount = items.filter(i => i.status === 'FAIL').length

  const statusIcon = { PASS: '✓', WARN: '△', FAIL: '✗', SKIP: '—' }
  const statusColor = {
    PASS: isDark ? 'text-emerald-400' : 'text-emerald-600',
    WARN: isDark ? 'text-amber-400'   : 'text-amber-600',
    FAIL: isDark ? 'text-red-400'     : 'text-red-600',
    SKIP: isDark ? 'text-slate-500'   : 'text-slate-400',
  }

  return (
    <div className={`px-6 pt-4 pb-4 border-b ${th.divider}`}>
      <div className="flex items-center justify-between mb-3">
        <div className={`text-[10px] font-bold uppercase tracking-widest ${th.secLabel}`}>
          Master Data Readiness
        </div>
        <div className="flex items-center gap-2">
          {!isDemo && isLoading && <span className={`text-[10px] ${th.detail}`}>checking…</span>}
          {!isDemo && !isLoading && dataUpdatedAt && (
            <span className={`text-[10px] ${th.detail}`}>
              updated {new Date(dataUpdatedAt).toLocaleTimeString()} · auto 60s
            </span>
          )}
          {allReady && (
            <span className={`text-[10px] font-bold px-2 py-0.5 rounded border ${isDark ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30' : 'bg-emerald-50 text-emerald-700 border-emerald-200'}`}>
              READY
            </span>
          )}
          {failCount > 0 && (
            <span className={`text-[10px] font-bold px-2 py-0.5 rounded border ${isDark ? 'bg-red-500/15 text-red-400 border-red-500/30' : 'bg-red-50 text-red-700 border-red-200'}`}>
              {failCount} FAIL{failCount > 1 ? 'S' : ''}
            </span>
          )}
        </div>
      </div>

      {items.length === 0 && !isDemo && (
        <div className={`text-xs ${th.detail} py-3 text-center`}>
          {isLoading ? 'Fetching readiness checklist…' : 'No items returned — backend may be unreachable'}
        </div>
      )}

      <div className="grid grid-cols-2 gap-x-6 gap-y-1">
        {items.map(item => (
          <div
            key={item.check_id}
            className={`flex items-center justify-between py-1.5 rounded transition-all ${th.rowHover} px-1`}
          >
            <div className="flex items-center gap-2 min-w-0">
              <span className={`text-sm font-bold w-4 text-center shrink-0 ${statusColor[item.status] ?? th.detail}`}>
                {statusIcon[item.status] ?? '?'}
              </span>
              <div className="min-w-0">
                <div className={`text-[11px] font-medium ${th.label} truncate`}>{item.label}</div>
                <div className={`text-[10px] ${th.detail} truncate`}>{item.detail}</div>
              </div>
            </div>
            {item.action_url && item.status !== 'PASS' && (
              <button
                onClick={() => navigate(item.action_url)}
                className={`shrink-0 ml-2 text-[9px] px-1.5 py-0.5 rounded border font-semibold ${isDark ? 'border-violet-500/30 bg-violet-500/10 text-violet-400 hover:bg-violet-500/20' : 'border-violet-200 bg-violet-50 text-violet-600 hover:bg-violet-100'}`}
              >
                → Fix
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────

export default function CTSSmokeTest() {
  const { isDark } = useTheme()
  const { bankId, isSB, isSMB, bankMode, deploymentMode, isDemo, isPOC, userRole } = useBankContext()
  const sc = isDark ? SC_DARK : SC_LIGHT

  const availableEntities = isSMB
    ? ['smb']
    : bankMode === 'SB_ONLY'
      ? ['sb', 'branch', 'pu']
      : ['sb', 'smb', 'branch', 'pu']
  const [activeEntity, setActiveEntity] = useState(availableEntities[0])
  const [testStates, setTestStates]     = useState({})
  const [running, setRunning]           = useState(false)
  const [ran, setRan]                   = useState(false)
  const scenarioRef = useRef(0)

  const th = {
    page:      isDark ? 'bg-navy-950'               : 'bg-slate-50',
    card:      isDark ? 'bg-navy-900/60 border-white/8' : 'bg-white border-slate-200',
    heading:   isDark ? 'text-white'                : 'text-slate-900',
    body:      isDark ? 'text-slate-300'            : 'text-slate-700',
    muted:     isDark ? 'text-slate-400'            : 'text-slate-500',
    faint:     isDark ? 'text-slate-600'            : 'text-slate-400',
    divider:   isDark ? 'border-white/8'            : 'border-slate-200',
    tabActive: isDark ? 'bg-white/10 text-white border-white/20' : 'bg-white text-slate-900 border-slate-200 shadow-sm',
    tabInact:  isDark ? 'text-slate-400 hover:text-slate-200 border-transparent' : 'text-slate-500 hover:text-slate-700 border-transparent',
    secLabel:  isDark ? 'text-slate-600'            : 'text-slate-400',
    rowHover:  isDark ? 'hover:bg-white/3'          : 'hover:bg-slate-50',
  }

  function getAllTests() {
    return Object.values(ENTITY_SECTIONS[activeEntity].sections).flat()
  }

  function buildSummary() {
    const vals = Object.values(testStates)
    const total = getAllTests().length
    return {
      total,
      done: vals.length,
      pass: vals.filter(r => r.status === 'PASS').length,
      fail: vals.filter(r => r.status === 'FAIL').length,
      warn: vals.filter(r => r.status === 'WARN').length,
      skip: vals.filter(r => r.status === 'SKIP').length,
      allClear: vals.filter(r => r.status === 'FAIL').length === 0 && vals.length === total,
    }
  }

  async function runAll() {
    if (running) return
    setRunning(true)
    setRan(false)
    setTestStates({})
    const tests = getAllTests()

    if (isDemo) {
      // DEMO mode: animate through canned outcomes
      const outcomes = DEMO_OUTCOMES[scenarioRef.current % DEMO_OUTCOMES.length]
      for (const t of tests) {
        setTestStates(prev => ({ ...prev, [t.id]: { status: 'RUNNING', message: 'Checking…', latency: null } }))
        await sleep(280 + Math.random() * 220)
        const [sts, msg] = outcomes[t.id] || ['PASS', 'OK']
        const base = BASE_LATENCY[t.id]
        const latency = base == null ? null : (sts === 'FAIL' ? null : base + Math.floor(Math.random() * 30))
        setTestStates(prev => ({ ...prev, [t.id]: { status: sts, message: msg, latency } }))
      }
      scenarioRef.current += 1
    } else {
      // POC / PROD: call real backend
      // Mark all RUNNING first for visual feedback
      const initial = {}
      tests.forEach(t => { initial[t.id] = { status: 'RUNNING', message: 'Checking…', latency: null } })
      setTestStates(initial)

      try {
        const data = await postRunSmokeTests(activeEntity, bankId)
        const newState = {}
        for (const r of (data.results ?? [])) {
          newState[r.test_id] = { status: r.status, message: r.message, latency: r.latency_ms }
        }
        // Any test the backend didn't return → mark SKIP
        tests.forEach(t => { if (!newState[t.id]) newState[t.id] = { status: 'SKIP', message: 'No result returned', latency: null } })
        setTestStates(newState)
      } catch (err) {
        const errState = {}
        tests.forEach(t => { errState[t.id] = { status: 'FAIL', message: err.message, latency: null } })
        setTestStates(errState)
      }
    }

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
      deployment_mode: deploymentMode,
      entity_type: activeEntity,
      bank_id: bankId,
      run_at: new Date().toISOString(),
      results: tests.map(t => {
        const r = testStates[t.id] || { status: 'SKIP', message: 'Not run', latency: null }
        return { test_id: t.id, name: t.name, status: r.status, latency_ms: r.latency, message: r.message }
      }),
      summary: buildSummary(),
    }
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `astra-smoke-test-${activeEntity}-${deploymentMode.toLowerCase()}-${new Date().toISOString().split('T')[0]}.json`
    a.click()
  }

  const summary = buildSummary()

  const deployPill = {
    DEMO: isDark ? 'bg-slate-700/50 text-slate-300 border-slate-600/40' : 'bg-slate-100 text-slate-600 border-slate-200',
    POC:  isDark ? 'bg-amber-500/15 text-amber-300 border-amber-500/30' : 'bg-amber-50 text-amber-700 border-amber-200',
    PROD: isDark ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' : 'bg-emerald-50 text-emerald-700 border-emerald-200',
  }[deploymentMode] ?? ''

  return (
    <AppShell>
      <div className={`flex-1 min-h-full ${th.page}`}>

        {/* ── Page header ───────────────────────────────────────────── */}
        <div className={`px-6 pt-5 pb-4 border-b ${th.divider}`}>
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <div className="flex items-center gap-2 mb-0.5">
                <h1 className={`text-base font-semibold ${th.heading}`}>Go-Live Readiness</h1>
                <span className={`text-[10px] font-bold px-2 py-0.5 rounded border ${deployPill}`}>
                  {deploymentMode}
                </span>
              </div>
              <p className={`text-xs ${th.muted}`}>
                Infrastructure status · master data completeness · connectivity smoke tests.
                {isDemo ? ' Running in DEMO mode — simulated results.' : ` Running in ${deploymentMode} mode — real connectivity checks.`}
              </p>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button
                onClick={downloadReport}
                disabled={!ran || running}
                className={`text-xs px-3 py-1.5 rounded-md border font-medium transition-all
                  ${ran && !running
                    ? (isDark ? 'border-white/15 text-slate-300 hover:text-white hover:border-white/30' : 'border-slate-200 text-slate-600 hover:border-slate-400')
                    : 'opacity-30 cursor-default border-transparent ' + th.muted}`}
              >
                ↓ Download Report
              </button>
              <button
                onClick={runAll}
                disabled={running}
                className={`text-xs px-4 py-1.5 rounded-md font-semibold transition-all
                  ${running ? 'bg-violet-600/40 text-violet-300 cursor-default' : 'bg-violet-600 hover:bg-violet-500 text-white'}`}
              >
                {running ? '◌ Running…' : ran ? '↺ Run Again' : '▶ Run Smoke Tests'}
              </button>
            </div>
          </div>

          {/* Summary strip */}
          {(ran || running) && (
            <div className="flex items-center gap-3 mt-3 flex-wrap">
              <span className={`text-xs font-mono ${th.faint}`}>{summary.done}/{summary.total} tests</span>
              {summary.pass > 0 && <span className={`text-xs font-mono font-semibold ${isDark ? 'text-emerald-400' : 'text-emerald-600'}`}>✓ {summary.pass}</span>}
              {summary.fail > 0 && <span className={`text-xs font-mono font-semibold ${isDark ? 'text-red-400' : 'text-red-600'}`}>✗ {summary.fail}</span>}
              {summary.warn > 0 && <span className={`text-xs font-mono font-semibold ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>△ {summary.warn}</span>}
              {summary.skip > 0 && <span className={`text-xs font-mono ${th.faint}`}>○ {summary.skip} skip</span>}
              {ran && summary.done === summary.total && (
                summary.fail === 0
                  ? <span className={`ml-auto text-xs font-mono font-bold px-2.5 py-0.5 rounded ${isDark ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30' : 'bg-emerald-50 text-emerald-700 border border-emerald-200'}`}>ALL CLEAR</span>
                  : <span className={`ml-auto text-xs font-mono font-bold px-2.5 py-0.5 rounded ${isDark ? 'bg-red-500/15 text-red-400 border border-red-500/30' : 'bg-red-50 text-red-700 border border-red-200'}`}>
                      {summary.fail} FAILURE{summary.fail > 1 ? 'S' : ''} — RESOLVE BEFORE GO-LIVE
                    </span>
              )}
            </div>
          )}
        </div>

        {/* ── Section 1: Infrastructure Services ───────────────────── */}
        <ServiceControlPanel isDark={isDark} isDemo={isDemo} isPOC={isPOC} bankId={bankId} isAdmin={userRole === 'bank_it_admin'} />

        {/* ── Section 2: Master Data Readiness ─────────────────────── */}
        <ReadinessPanel isDark={isDark} isDemo={isDemo} bankId={bankId} deploymentMode={deploymentMode} />

        {/* ── Section 3: Entity tabs + smoke tests ─────────────────── */}
        <div className={`px-6 pt-3 flex gap-1 border-b ${th.divider}`}>
          {availableEntities.map(eid => {
            const edata = ENTITY_SECTIONS[eid]
            const cnt = Object.values(edata.sections).flat().length
            const isActive = activeEntity === eid
            return (
              <button
                key={eid}
                onClick={() => handleEntityChange(eid)}
                className={`flex items-center gap-2 px-3 py-2 mb-[-1px] text-xs font-semibold rounded-t-md border transition-all
                  ${isActive ? th.tabActive : th.tabInact}`}
              >
                <span className={`font-mono text-[10px] font-bold px-1.5 py-0.5 rounded
                  ${isActive ? (isDark ? 'bg-violet-500/20 text-violet-400' : 'bg-violet-600 text-white') : (isDark ? 'bg-white/5 text-slate-500' : 'bg-slate-100 text-slate-500')}`}>
                  {edata.label}
                </span>
                {edata.fullName}
                <span className={`text-[10px] font-mono ${isActive ? th.muted : th.faint}`}>{cnt}</span>
              </button>
            )
          })}
        </div>

        <div className="px-6 py-4 space-y-6">
          {Object.entries(ENTITY_SECTIONS[activeEntity].sections).map(([sectionName, tests]) => (
            <div key={sectionName}>
              <div className={`text-[10px] font-bold uppercase tracking-widest ${th.secLabel} mb-2 pb-1 border-b ${th.divider}`}>
                {sectionName}
              </div>
              <div className="space-y-1.5">
                {tests.map(t => {
                  const res = testStates[t.id]
                  const sts = res?.status || 'PENDING'
                  const styles = sc[sts] || sc.PENDING
                  const isRunning = sts === 'RUNNING'

                  return (
                    <div key={t.id} className={`flex items-stretch rounded-md border overflow-hidden transition-all ${th.card} ${th.rowHover}`}>
                      <div className={`w-1 shrink-0 ${styles.bar} transition-colors ${isRunning ? 'animate-pulse' : ''}`} />
                      <div className="flex-1 px-3 py-2.5 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className={`text-sm font-medium ${th.heading}`}>{t.name}</span>
                          <span className={`text-[10px] font-mono font-bold px-1.5 py-0.5 rounded ${styles.pill}`}>{sts}</span>
                        </div>
                        <div className={`text-xs mt-0.5 ${res?.message ? th.body : th.faint}`}>
                          {res?.message || t.desc}
                        </div>
                      </div>
                      <div className="shrink-0 px-3 py-2.5 flex flex-col items-end justify-center text-right">
                        {res?.latency != null && sts !== 'RUNNING' ? (
                          <>
                            <span className={`text-xs font-mono font-semibold tabular-nums ${res.latency < 200 ? (isDark ? 'text-emerald-400' : 'text-emerald-600') : res.latency > 600 ? (isDark ? 'text-red-400' : 'text-red-600') : (isDark ? 'text-amber-400' : 'text-amber-600')}`}>
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

          <p className={`text-[11px] ${th.faint} pt-2 pb-4`}>
            WARN is advisory and does not block go-live. FAIL must be resolved. SKIP means the test
            is not applicable or the integration is not configured for this deployment mode.
          </p>
        </div>
      </div>
    </AppShell>
  )
}

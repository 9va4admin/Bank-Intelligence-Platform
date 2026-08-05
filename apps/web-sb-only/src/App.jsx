import { HashRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider } from './shared/theme/ThemeContext'
import { BankProvider } from './shared/context/BankContext'
import { AuthProvider } from './shared/context/AuthContext'
import { PageHeaderProvider } from './shared/layout/PageHeaderContext'
import AppShell from './shared/layout/AppShell'
import ComingSoon from './shared/layout/ComingSoon'

// ── CTS pages ────────────────────────────────────────────────────────────────
import CTSWorkstation     from './modules/cts/pages/CTSWorkstation'
import CTSDraweeView      from './modules/cts/pages/CTSDraweeView'
import CTSValidationQueue from './modules/cts/pages/CTSValidationQueue'
import CTSSubmissionQueue from './modules/cts/pages/CTSSubmissionQueue'
import CTSInwardReviewQueue from './modules/cts/pages/CTSInwardReviewQueue'
import CTSHoldQueue       from './modules/cts/pages/CTSHoldQueue'
import CTSRecall          from './modules/cts/pages/CTSRecall'
import CTSPipelineVisualizer from './modules/cts/pages/CTSPipelineVisualizer'
import CTSOutwardQueue    from './modules/cts/pages/CTSOutwardQueue'
import CTSPresentmentFile from './modules/cts/pages/CTSPresentmentFile'
import CTSOpsDashboard    from './modules/cts/pages/CTSOpsDashboard'
import CTSSettlement      from './modules/cts/pages/CTSSettlement'
import CTSBatches         from './modules/cts/pages/CTSBatches'
import CTSVaultStatus     from './modules/cts/pages/CTSVaultStatus'
import CTSVaultSync       from './modules/cts/pages/CTSVaultSync'
import CTSEndorsement     from './modules/cts/pages/CTSEndorsement'
import CTSExceptions      from './modules/cts/pages/CTSExceptions'
import CTSImageQuality    from './modules/cts/pages/CTSImageQuality'
import CTSScanner         from './modules/cts/pages/CTSScanner'
import CTSRFDrawee        from './modules/cts/pages/CTSRFDrawee'
import CTSDecisionsLog    from './modules/cts/pages/CTSDecisionsLog'
import CTSDiscrepancy     from './modules/cts/pages/CTSDiscrepancy'
import CTSReconciliation  from './modules/cts/pages/CTSReconciliation'
import CTSAnalytics       from './modules/cts/pages/CTSAnalytics'
import CTSCompliance      from './modules/cts/pages/CTSCompliance'
import CTSDemoLive        from './modules/cts/pages/CTSDemoLive'
import CTSInwardPipeline  from './modules/cts/pages/CTSInwardPipeline'
import CTSCloudAIDemo     from './modules/cts/pages/CTSCloudAIDemo'
import CTSSigBatchTest    from './modules/cts/pages/CTSSigBatchTest'
import CTSSchedules       from './modules/cts/pages/CTSSchedules'
import CTSConfig          from './modules/cts/pages/CTSConfig'
import CTSMICRPrefixes    from './modules/cts/pages/CTSMICRPrefixes'
import CTSThresholds      from './modules/cts/pages/CTSThresholds'
import CTSMCPConfig       from './modules/cts/pages/CTSMCPConfig'
import CTSAllocationAdmin from './modules/cts/pages/CTSAllocationAdmin'
import CTSSmokeTest       from './modules/cts/pages/CTSSmokeTest'

// ── Branch pages ─────────────────────────────────────────────────────────────
import BranchDashboard    from './modules/cts/pages/branch/BranchDashboard'
import BranchScanMonitor  from './modules/cts/pages/branch/BranchScanMonitor'
import BranchMismatchQueue from './modules/cts/pages/branch/BranchMismatchQueue'
import BranchSessionHistory from './modules/cts/pages/branch/BranchSessionHistory'
import BranchHoldQueue    from './modules/cts/pages/branch/BranchHoldQueue'

// ── Admin pages ──────────────────────────────────────────────────────────────
import UserManagement     from './modules/admin/pages/UserManagement'
import OperationsConfig   from './modules/admin/pages/OperationsConfig'
import PlatformConfig     from './modules/admin/pages/PlatformConfig'
import CTSBranchMaster    from './modules/cts/pages/CTSBranchMaster'

const qc = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
})

// Stub for pages that have no real component yet
function Stub({ label }) {
  return <AppShell><ComingSoon page={label} /></AppShell>
}

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <AuthProvider>
          <BankProvider>
            <PageHeaderProvider>
              <HashRouter>
                <Routes>
                  {/* Default */}
                  <Route path="/" element={<Navigate to="/cts" replace />} />

                  {/* ── CTS — Inward ── */}
                  <Route path="/cts"                     element={<CTSWorkstation />} />
                  <Route path="/cts/pipeline"            element={<CTSDraweeView />} />
                  <Route path="/cts/inward/verification" element={<CTSValidationQueue />} />
                  <Route path="/cts/inward/submission"   element={<CTSSubmissionQueue />} />
                  <Route path="/cts/inward/review-queue" element={<CTSInwardReviewQueue />} />
                  <Route path="/cts/hold-queue"          element={<CTSHoldQueue />} />
                  <Route path="/cts/recall"              element={<CTSRecall />} />

                  {/* ── CTS — Outward ── */}
                  <Route path="/cts/outward"              element={<CTSPipelineVisualizer />} />
                  <Route path="/cts/outward/verification" element={<CTSValidationQueue />} />
                  <Route path="/cts/outward/queue"        element={<CTSOutwardQueue />} />
                  <Route path="/cts/outward/submission"   element={<CTSSubmissionQueue />} />
                  <Route path="/cts/presentment-file"     element={<CTSPresentmentFile />} />

                  {/* ── CTS — Dashboard & Settlement ── */}
                  <Route path="/cts/ops-dashboard" element={<CTSOpsDashboard />} />
                  <Route path="/cts/settlement"    element={<CTSSettlement />} />

                  {/* ── CTS — Processing ── */}
                  <Route path="/cts/batches"     element={<CTSBatches />} />
                  <Route path="/cts/vault"       element={<CTSVaultStatus />} />
                  <Route path="/cts/vault-sync"  element={<CTSVaultSync />} />
                  <Route path="/cts/endorsement" element={<CTSEndorsement />} />
                  <Route path="/cts/exceptions"  element={<CTSExceptions />} />
                  <Route path="/cts/iqa"         element={<CTSImageQuality />} />
                  <Route path="/cts/scanner"     element={<CTSScanner />} />
                  <Route path="/cts/rf-drawee"   element={<CTSRFDrawee />} />

                  {/* ── CTS — Reports ── */}
                  <Route path="/cts/decisions"      element={<CTSDecisionsLog />} />
                  <Route path="/cts/discrepancy"    element={<CTSDiscrepancy />} />
                  <Route path="/cts/reconciliation" element={<CTSReconciliation />} />
                  <Route path="/cts/analytics"      element={<CTSAnalytics />} />
                  <Route path="/cts/compliance"     element={<CTSCompliance />} />

                  {/* ── CTS — Misc / Demo ── */}
                  <Route path="/cts/demo"            element={<CTSDemoLive />} />
                  <Route path="/cts/inward-pipeline" element={<CTSInwardPipeline />} />
                  <Route path="/cts/cloud-ai-demo"   element={<CTSCloudAIDemo />} />
                  <Route path="/cts/sig-batch-test"  element={<CTSSigBatchTest />} />

                  {/* ── Branch ── */}
                  <Route path="/branch"            element={<BranchDashboard />} />
                  <Route path="/branch/scan"       element={<BranchScanMonitor />} />
                  <Route path="/branch/mismatch"   element={<BranchMismatchQueue />} />
                  <Route path="/branch/history"    element={<BranchSessionHistory />} />
                  <Route path="/branch/hold-queue" element={<BranchHoldQueue />} />

                  {/* ── Ops — no pages yet, keep stubs ── */}
                  <Route path="/ops/dashboard"    element={<Stub label="Ops Overview" />} />
                  <Route path="/ops/model-health" element={<Stub label="Model Health" />} />
                  <Route path="/ops/alerts"       element={<Stub label="Alert Log" />} />
                  <Route path="/ops/system"       element={<Stub label="System Health" />} />

                  {/* ── Admin ── */}
                  <Route path="/admin/users"              element={<UserManagement />} />
                  <Route path="/admin/branches"           element={<CTSBranchMaster />} />
                  <Route path="/cts/schedules"            element={<CTSSchedules />} />
                  <Route path="/cts/config"               element={<CTSConfig />} />
                  <Route path="/cts/config/micr-prefixes" element={<CTSMICRPrefixes />} />
                  <Route path="/cts/config/thresholds"    element={<CTSThresholds />} />
                  <Route path="/cts/config/mcp-connections" element={<CTSMCPConfig />} />
                  <Route path="/admin/config/operations"  element={<OperationsConfig />} />
                  <Route path="/admin/config/platform"    element={<PlatformConfig />} />
                  <Route path="/admin/allocation"         element={<CTSAllocationAdmin />} />
                  <Route path="/admin/smoke-test"         element={<CTSSmokeTest />} />
                </Routes>
              </HashRouter>
            </PageHeaderProvider>
          </BankProvider>
        </AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  )
}

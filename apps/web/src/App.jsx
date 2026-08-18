import { HashRouter as BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { PageHeaderProvider } from './shared/layout/PageHeaderContext'
import { BankProvider } from './shared/context/BankContext'
import LandingPage from './pages/LandingPage'
import CTSWorkstation from './modules/cts/pages/CTSWorkstation'
import CTSVaultStatus from './modules/cts/pages/CTSVaultStatus'
import CTSVaultUpload from './modules/cts/pages/CTSVaultUpload'
import CTSDecisionsLog from './modules/cts/pages/CTSDecisionsLog'
import CTSAnalytics from './modules/cts/pages/CTSAnalytics'
import CTSConfig from './modules/cts/pages/CTSConfig'
import CTSAllocationAdmin from './modules/cts/pages/CTSAllocationAdmin'
import CTSMCPConfig from './modules/cts/pages/CTSMCPConfig'
import CTSPresentment from './modules/cts/pages/CTSPresentment'
import CTSOutwardQueue from './modules/cts/pages/CTSOutwardQueue'
import CTSValidationQueue from './modules/cts/pages/CTSValidationQueue'
import CTSSubmissionQueue from './modules/cts/pages/CTSSubmissionQueue'
import CTSExceptions from './modules/cts/pages/CTSExceptions'
import CTSReconciliation from './modules/cts/pages/CTSReconciliation'
import CTSCompliance from './modules/cts/pages/CTSCompliance'
import CTSScanner from './modules/cts/pages/CTSScanner'
import CTSEndorsement from './modules/cts/pages/CTSEndorsement'
import CTSRPCConsolidation from './modules/cts/pages/CTSRPCConsolidation'
import CTSSubMember from './modules/cts/pages/CTSSubMember'
import CTSImageQuality from './modules/cts/pages/CTSImageQuality'
import CTSPipelineVisualizer from './modules/cts/pages/CTSPipelineVisualizer'
import CTSDiscrepancy from './modules/cts/pages/CTSDiscrepancy'
import CTSBatches from './modules/cts/pages/CTSBatches'
import CTSBusinessModel from './modules/cts/pages/CTSBusinessModel'
import CTSOpsDashboard from './modules/cts/pages/CTSOpsDashboard'
import CTSDraweeView from './modules/cts/pages/CTSDraweeView'
import CTSSettlement from './modules/cts/pages/CTSSettlement'
import CTSVaultSync from './modules/cts/pages/CTSVaultSync'
import CTSSchedules from './modules/cts/pages/CTSSchedules'
import CTSSubMemberBanks from './modules/cts/pages/CTSSubMemberBanks'
import CTSMICRPrefixes from './modules/cts/pages/CTSMICRPrefixes'
import CTSThresholds from './modules/cts/pages/CTSThresholds'
import CTSBranchMaster from './modules/cts/pages/CTSBranchMaster'
import CTSProcessingUnits from './modules/cts/pages/CTSProcessingUnits'
import CTSNGCHRouting from './modules/cts/pages/CTSNGCHRouting'
import CTSSMBRegistry from './modules/cts/pages/CTSSMBRegistry'
import CTSSMBLedger from './modules/cts/pages/CTSSMBLedger'
import CTSSMBForwardingLog from './modules/cts/pages/CTSSMBForwardingLog'
import CTSSMBDashboard from './modules/cts/pages/CTSSMBDashboard'
import CTSSMBReports from './modules/cts/pages/CTSSMBReports'
import CTSSMBReviewQueue from './modules/cts/pages/CTSSMBReviewQueue'
import CTSInwardPipeline from './modules/cts/pages/CTSInwardPipeline'
import CTSDemoPipeline from './modules/cts/pages/CTSDemoPipeline'
import CTSCloudAIDemo from './modules/cts/pages/CTSCloudAIDemo'
import CTSSigBatchTest from './modules/cts/pages/CTSSigBatchTest'
import CTSPresentmentFile from './modules/cts/pages/CTSPresentmentFile'
import CTSHubDashboard from './modules/cts/pages/CTSHubDashboard'
import CTSHoldQueue from './modules/cts/pages/CTSHoldQueue'
import CTSInwardReviewQueue from './modules/cts/pages/CTSInwardReviewQueue'
import BranchDashboard from './modules/cts/pages/branch/BranchDashboard'
import BranchScanMonitor from './modules/cts/pages/branch/BranchScanMonitor'
import BranchMismatchQueue from './modules/cts/pages/branch/BranchMismatchQueue'
import BranchSessionHistory from './modules/cts/pages/branch/BranchSessionHistory'
import BranchHoldQueue from './modules/cts/pages/branch/BranchHoldQueue'
import CTSRFDrawee from './modules/cts/pages/CTSRFDrawee'
import CTSRecall from './modules/cts/pages/CTSRecall'
import CTSAgencyCC from './modules/cts/pages/CTSAgencyCC'
import CTSSmokeTest from './modules/cts/pages/CTSSmokeTest'
import OpsDashboard from './modules/observability/pages/OpsDashboard'
import ModelHealth from './modules/observability/pages/ModelHealth'
import CTSOCRFeedback from './modules/observability/pages/CTSOCRFeedback'
import AlertLog from './modules/observability/pages/AlertLog'
import SystemHealth from './modules/observability/pages/SystemHealth'
import UserManagement from './modules/admin/pages/UserManagement'
import LoginLog from './modules/admin/pages/LoginLog'
import SecurityViolations from './modules/admin/pages/SecurityViolations'
import OperationsConfig from './modules/admin/pages/OperationsConfig'
import PlatformConfig from './modules/admin/pages/PlatformConfig'
import LoginPage from './modules/auth/pages/LoginPage'
import Logout from './modules/auth/pages/Logout'
import Profile from './modules/auth/pages/Profile'
import { AuthProvider } from './shared/context/AuthContext'
import RequireAuth from './shared/auth/RequireAuth'
import RequirePermission from './shared/auth/RequirePermission'
import AccessDenied from './modules/auth/pages/AccessDenied'
import './index.css'

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
      <BankProvider>
      <PageHeaderProvider>
      <Routes>
        {/* Public: landing + login. Everything else requires a session. */}
        <Route path="/" element={<LandingPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/logout" element={<Logout />} />
        <Route path="/access-denied" element={<AccessDenied />} />
        <Route element={<RequireAuth />}>
        {/* CTS module */}
        {/* Inward 3-stage pipeline */}
        <Route path="/cts/inward/verification" element={<CTSWorkstation />} />
        <Route path="/cts"                     element={<CTSValidationQueue mode="inward" />} />
        <Route path="/cts/inward/submission"   element={<CTSSubmissionQueue mode="inward" />} />
        {/* Outward 3-stage pipeline */}
        <Route path="/cts/outward"             element={<CTSPresentment />} />
        <Route path="/cts/outward/verification" element={<CTSOutwardQueue />} />
        <Route path="/cts/outward/queue"        element={<CTSValidationQueue mode="outward" />} />
        <Route path="/cts/outward/submission"   element={<CTSSubmissionQueue mode="outward" />} />
        <Route path="/cts/vault" element={<CTSVaultStatus />} />
        <Route path="/cts/vault/upload" element={<CTSVaultUpload />} />
        <Route path="/cts/decisions" element={<CTSDecisionsLog />} />
        <Route path="/cts/exceptions" element={<CTSExceptions />} />
        <Route path="/cts/reconciliation" element={<CTSReconciliation />} />
        <Route path="/cts/compliance" element={<CTSCompliance />} />
        <Route path="/cts/iqa" element={<CTSImageQuality />} />
        <Route path="/cts/scanner" element={<CTSScanner />} />
        <Route path="/cts/endorsement" element={<CTSEndorsement />} />
        <Route path="/cts/rpc" element={<CTSRPCConsolidation />} />
        <Route path="/cts/sub-member" element={<CTSSubMember />} />
        <Route path="/cts/pipeline" element={<CTSPipelineVisualizer />} />
        <Route path="/cts/inward-pipeline" element={<CTSInwardPipeline />} />
        <Route path="/cts/demo" element={<CTSDemoPipeline />} />
        <Route path="/cts/cloud-ai-demo" element={<CTSCloudAIDemo />} />
        <Route path="/cts/sig-batch-test" element={<CTSSigBatchTest />} />
        <Route path="/cts/presentment-file" element={<CTSPresentmentFile />} />
        <Route path="/cts/rf-drawee" element={<CTSRFDrawee />} />
        <Route path="/cts/recall" element={<CTSRecall />} />
        <Route path="/cts/agency-cc" element={<CTSAgencyCC />} />
        <Route path="/cts/discrepancy" element={<CTSDiscrepancy />} />
        <Route path="/cts/batches" element={<CTSBatches />} />
        <Route path="/cts/analytics" element={<CTSAnalytics />} />
        <Route path="/cts/business-model" element={<CTSBusinessModel />} />
        <Route path="/cts/config" element={<CTSConfig />} />
        <Route path="/cts/config/mcp-connections" element={<CTSMCPConfig />} />
        <Route path="/cts/ops-dashboard" element={<CTSOpsDashboard />} />
        <Route path="/cts/drawee" element={<CTSDraweeView />} />
        <Route path="/cts/settlement" element={<CTSSettlement />} />
        <Route path="/cts/vault-sync" element={<CTSVaultSync />} />
        <Route path="/cts/schedules" element={<CTSSchedules />} />
        <Route path="/cts/config/sub-member-banks" element={<CTSSubMemberBanks />} />
        <Route path="/cts/config/micr-prefixes" element={<CTSMICRPrefixes />} />
        <Route path="/cts/config/thresholds" element={<CTSThresholds />} />
        <Route path="/cts/admin/branches" element={<CTSBranchMaster />} />
        <Route path="/cts/admin/processing-units" element={<CTSProcessingUnits />} />
        <Route path="/cts/config/ngch-routing" element={<CTSNGCHRouting />} />
        <Route path="/cts/smb/registry" element={<CTSSMBRegistry />} />
        <Route path="/cts/smb/ledger" element={<CTSSMBLedger />} />
        <Route path="/cts/smb/forwarding-log" element={<CTSSMBForwardingLog />} />
        <Route path="/cts/smb/dashboard" element={<CTSSMBDashboard />} />
        <Route path="/cts/smb/review-queue" element={<CTSSMBReviewQueue />} />
        <Route path="/cts/smb/reports" element={<CTSSMBReports />} />
        {/* Hub Manager — SB clearing hub command centre */}
        <Route path="/cts/hub" element={<CTSHubDashboard />} />
        {/* Hold Queue — ops_manager view of all holds */}
        <Route path="/cts/hold-queue" element={<CTSHoldQueue />} />
        {/* Inward Human Review Queue — CLAIM / HOLD / CONFIRM / RETURN */}
        <Route path="/cts/inward/review-queue" element={<CTSInwardReviewQueue />} />
        {/* Branch Portal — EEH branch operator screens */}
        <Route path="/branch" element={<BranchDashboard />} />
        <Route path="/branch/scan" element={<BranchScanMonitor />} />
        <Route path="/branch/mismatch" element={<BranchMismatchQueue />} />
        <Route path="/branch/history" element={<BranchSessionHistory />} />
        <Route path="/branch/hold-queue" element={<BranchHoldQueue />} />
        {/* Admin */}
        <Route path="/profile" element={<Profile />} />
        <Route path="/admin/security-violations" element={<SecurityViolations />} />
        <Route path="/admin/login-log" element={<LoginLog />} />
        <Route path="/admin/smoke-test" element={<CTSSmokeTest />} />
        <Route path="/admin/config/operations" element={<OperationsConfig />} />
        <Route path="/admin/config/platform" element={<PlatformConfig />} />
        <Route path="/admin/allocation" element={<CTSAllocationAdmin />} />
        {/* ASTRA Ops Dashboard — ops_manager + bank_it_admin (analytics) */}
        <Route path="/ops/dashboard"    element={<OpsDashboard />} />
        <Route path="/ops/alerts"       element={<AlertLog />} />
        <Route path="/ops/system"       element={<SystemHealth />} />
        {/* AI model pages — ops_manager + bank_it_admin + ml_engineer only */}
        <Route element={<RequirePermission permission="ai:model_metrics" />}>
          <Route path="/ops/model-health"   element={<ModelHealth />} />
          <Route path="/ops/ocr-feedback"   element={<CTSOCRFeedback />} />
        </Route>
        {/* Admin — bank_it_admin only */}
        <Route element={<RequirePermission permission="user:manage" />}>
          <Route path="/admin/users" element={<UserManagement />} />
        </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      </PageHeaderProvider>
      </BankProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}

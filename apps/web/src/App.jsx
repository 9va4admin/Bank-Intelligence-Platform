import { HashRouter as BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { PageHeaderProvider } from './shared/layout/PageHeaderContext'
import { BankProvider } from './shared/context/BankContext'
import LandingPage from './pages/LandingPage'
import CTSWorkstation from './modules/cts/pages/CTSWorkstation'
import CTSVaultStatus from './modules/cts/pages/CTSVaultStatus'
import CTSDecisionsLog from './modules/cts/pages/CTSDecisionsLog'
import CTSAnalytics from './modules/cts/pages/CTSAnalytics'
import CTSConfig from './modules/cts/pages/CTSConfig'
import CTSMCPConfig from './modules/cts/pages/CTSMCPConfig'
import CTSPresentment from './modules/cts/pages/CTSPresentment'
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
import CTSNGCHRouting from './modules/cts/pages/CTSNGCHRouting'
import CTSSMBRegistry from './modules/cts/pages/CTSSMBRegistry'
import CTSSMBLedger from './modules/cts/pages/CTSSMBLedger'
import CTSSMBForwardingLog from './modules/cts/pages/CTSSMBForwardingLog'
import CTSSMBDashboard from './modules/cts/pages/CTSSMBDashboard'
import CTSSMBReports from './modules/cts/pages/CTSSMBReports'
import CTSSMBReviewQueue from './modules/cts/pages/CTSSMBReviewQueue'
import CTSInwardPipeline from './modules/cts/pages/CTSInwardPipeline'
import CTSDemoPipeline from './modules/cts/pages/CTSDemoPipeline'
import CTSPresentmentFile from './modules/cts/pages/CTSPresentmentFile'
import BranchDashboard from './modules/cts/pages/branch/BranchDashboard'
import BranchScanMonitor from './modules/cts/pages/branch/BranchScanMonitor'
import BranchMismatchQueue from './modules/cts/pages/branch/BranchMismatchQueue'
import BranchSessionHistory from './modules/cts/pages/branch/BranchSessionHistory'
import CTSRFDrawee from './modules/cts/pages/CTSRFDrawee'
import CTSRecall from './modules/cts/pages/CTSRecall'
import CTSAgencyCC from './modules/cts/pages/CTSAgencyCC'
import CTSSmokeTest from './modules/cts/pages/CTSSmokeTest'
import EJSchedules from './modules/ej/pages/EJSchedules'
import UserManagement from './modules/admin/pages/UserManagement'
import LoginLog from './modules/admin/pages/LoginLog'
import SecurityViolations from './modules/admin/pages/SecurityViolations'
import LoginPage from './modules/auth/pages/LoginPage'
import { AuthProvider } from './shared/context/AuthContext'
import RequireAuth from './shared/auth/RequireAuth'
import { EJDashboard } from './modules/ej'
import IncidentManagement from './modules/ej/pages/IncidentManagement'
import ManagerPortal from './modules/ej/pages/ManagerPortal'
import BREPolicyManager from './modules/ej/pages/BREPolicyManager'
import NotificationCenter from './modules/ej/pages/NotificationCenter'
import DisputeConsole from './modules/ej/pages/DisputeConsole'
import ATMFleetMap from './modules/ej/pages/ATMFleetMap'
import './index.css'

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
      <BankProvider>
      <PageHeaderProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<RequireAuth />}>
        <Route path="/" element={<LandingPage />} />
        {/* CTS module */}
        <Route path="/cts" element={<CTSWorkstation />} />
        <Route path="/cts/outward" element={<CTSPresentment />} />
        <Route path="/cts/vault" element={<CTSVaultStatus />} />
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
        <Route path="/cts/config/ngch-routing" element={<CTSNGCHRouting />} />
        <Route path="/cts/smb/registry" element={<CTSSMBRegistry />} />
        <Route path="/cts/smb/ledger" element={<CTSSMBLedger />} />
        <Route path="/cts/smb/forwarding-log" element={<CTSSMBForwardingLog />} />
        <Route path="/cts/smb/dashboard" element={<CTSSMBDashboard />} />
        <Route path="/cts/smb/review-queue" element={<CTSSMBReviewQueue />} />
        <Route path="/cts/smb/reports" element={<CTSSMBReports />} />
        {/* Branch Portal — EEH branch operator screens */}
        <Route path="/branch" element={<BranchDashboard />} />
        <Route path="/branch/scan" element={<BranchScanMonitor />} />
        <Route path="/branch/mismatch" element={<BranchMismatchQueue />} />
        <Route path="/branch/history" element={<BranchSessionHistory />} />
        {/* Admin */}
        <Route path="/admin/users" element={<UserManagement />} />
        <Route path="/admin/security-violations" element={<SecurityViolations />} />
        <Route path="/admin/login-log" element={<LoginLog />} />
        <Route path="/admin/smoke-test" element={<CTSSmokeTest />} />
        {/* EJ module — own routes, no overlap with CTS */}
        <Route path="/ej" element={<EJDashboard />} />
        <Route path="/ej/incidents" element={<IncidentManagement />} />
        <Route path="/ej/portal" element={<ManagerPortal />} />
        <Route path="/ej/bre" element={<BREPolicyManager />} />
        <Route path="/ej/disputes" element={<DisputeConsole />} />
        <Route path="/ej/fleet" element={<ATMFleetMap />} />
        <Route path="/ej/notifications" element={<NotificationCenter />} />
        <Route path="/ej/schedules" element={<EJSchedules />} />
        {/* EJ deep-links from landing page cards */}
        <Route path="/fleet" element={<EJDashboard defaultTab="fleet" />} />
        <Route path="/disputes" element={<EJDashboard defaultTab="disputes" />} />
        <Route path="/audit" element={<ManagerPortal />} />
        <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
      </PageHeaderProvider>
      </BankProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}

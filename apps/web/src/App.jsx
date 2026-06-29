import { HashRouter as BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { PageHeaderProvider } from './shared/layout/PageHeaderContext'
import LandingPage from './pages/LandingPage'
import CTSWorkstation from './modules/cts/pages/CTSWorkstation'
import CTSVaultStatus from './modules/cts/pages/CTSVaultStatus'
import CTSDecisionsLog from './modules/cts/pages/CTSDecisionsLog'
import CTSAnalytics from './modules/cts/pages/CTSAnalytics'
import CTSConfig from './modules/cts/pages/CTSConfig'
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
import CTSInwardPipeline from './modules/cts/pages/CTSInwardPipeline'
import EJSchedules from './modules/ej/pages/EJSchedules'
import UserManagement from './modules/admin/pages/UserManagement'
import LoginLog from './modules/admin/pages/LoginLog'
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
      <PageHeaderProvider>
      <Routes>
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
        <Route path="/cts/pipeline" element={<CTSInwardPipeline />} />
        <Route path="/cts/discrepancy" element={<CTSDiscrepancy />} />
        <Route path="/cts/batches" element={<CTSBatches />} />
        <Route path="/cts/analytics" element={<CTSAnalytics />} />
        <Route path="/cts/business-model" element={<CTSBusinessModel />} />
        <Route path="/cts/config" element={<CTSConfig />} />
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
        {/* Admin */}
        <Route path="/admin/users" element={<UserManagement />} />
        <Route path="/admin/login-log" element={<LoginLog />} />
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
      </Routes>
      </PageHeaderProvider>
    </BrowserRouter>
  )
}

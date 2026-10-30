import AppShell from '../../shared/layout/AppShell'
import ComingSoon from '../../shared/layout/ComingSoon'
import { msg } from '../../shared/messages'

export default function FraudAnalyticsPage() {
  return (
    <AppShell title={msg('UI_FRAUDANALYTICSPAGE_RISK_FRAUD_ANALYTICS')}>
      <ComingSoon page="Fraud Analytics" />
    </AppShell>
  )
}

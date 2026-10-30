import AppShell from '../../shared/layout/AppShell'
import ComingSoon from '../../shared/layout/ComingSoon'
import { msg } from '../../shared/messages'

export default function AuditTrailPage() {
  return (
    <AppShell title={msg('UI_COMMON_AUDIT_TRAIL_2')}>
      <ComingSoon page="Audit Trail" />
    </AppShell>
  )
}

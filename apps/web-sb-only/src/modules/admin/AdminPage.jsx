import AppShell from '../../shared/layout/AppShell'
import ComingSoon from '../../shared/layout/ComingSoon'
import { msg } from '../../shared/messages'

export default function AdminPage() {
  return (
    <AppShell title={msg('UI_ADMINPAGE_ADMIN_THRESHOLDS_CONFIG')}>
      <ComingSoon page="Admin" />
    </AppShell>
  )
}

import AppShell from '../../shared/layout/AppShell'
import ComingSoon from '../../shared/layout/ComingSoon'
import { msg } from '../../shared/messages'

export default function DecisionsPage() {
  return (
    <AppShell title={msg('UI_DECISIONSPAGE_DECISION_HISTORY')}>
      <ComingSoon page="Decision History" />
    </AppShell>
  )
}

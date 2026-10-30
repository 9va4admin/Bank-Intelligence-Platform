import AppShell from '../../shared/layout/AppShell'
import ComingSoon from '../../shared/layout/ComingSoon'
import { msg } from '../../shared/messages'

export default function BatchOverviewPage() {
  return (
    <AppShell title={msg('UI_BATCHOVERVIEWPAGE_OUTWARD_BATCH_OVERVIEW')}>
      <ComingSoon page="Outward Batch Overview" />
    </AppShell>
  )
}

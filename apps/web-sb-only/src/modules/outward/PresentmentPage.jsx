import AppShell from '../../shared/layout/AppShell'
import ComingSoon from '../../shared/layout/ComingSoon'
import { msg } from '../../shared/messages'

export default function PresentmentPage() {
  return (
    <AppShell title={msg('UI_PRESENTMENTPAGE_OUTWARD_PRESENTMENT_STATUS')}>
      <ComingSoon page="Presentment Status" />
    </AppShell>
  )
}

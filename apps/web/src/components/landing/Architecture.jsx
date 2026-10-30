import { msg } from '../../shared/messages'
const CONFIG_LAYERS = [
  {
    num: '1',
    name: 'Platform Constraints',
    who: 'ASTRA vendor — via Helm chart',
    examples: 'min_tls_version: 1.3 · audit_trail_enabled: true · exactly_once_ngch: true',
    reload: 'New chart release',
    color: 'border-red-300 bg-red-50',
    textColor: 'text-red-700',
  },
  {
    num: '2',
    name: 'Deployment Topology',
    who: 'Bank IT Admin — via PR to ASTRA repo',
    examples: 'module_cts_enabled · cbs_connector_type: finacle · gpu_profile: production',
    reload: 'ArgoCD sync (Helm upgrade)',
    color: 'border-orange-300 bg-orange-50',
    textColor: 'text-orange-700',
  },
  {
    num: '3',
    name: 'Business Rules / Thresholds',
    who: 'Ops Manager (maker) + Bank IT Admin (checker)',
    examples: 'iet_minutes: 180 · stp_threshold: 0.92 · high_value_limit: 5,00,000',
    reload: '< 30 seconds, hot-reload, no restart',
    color: 'border-amber-300 bg-amber-50',
    textColor: 'text-amber-700',
  },
  {
    num: '4',
    name: 'OPA Policy Rules',
    who: 'Compliance Officer (author) + Bank IT Admin (approve)',
    examples: '"Govt cheques always human review" · "Frozen account → immediate return"',
    reload: 'OPA live bundle reload — no restart',
    color: 'border-teal-300 bg-teal-50',
    textColor: 'text-teal-700',
  },
]

export default function Architecture() {
  return (
    <section id="architecture" className="bg-cream-100 py-20 px-6">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-14">
          <span className="inline-block text-xs font-semibold text-slate-400 tracking-widest uppercase mb-3">{msg('UI_ARCHITECTURE_ARCHITECTURE')}</span>
          <h2 className="text-3xl sm:text-4xl font-bold text-slate-900 mb-4">
           {msg('UI_ARCHITECTURE_BANK_CONTROLS_EVERYTHING')}<br />
            <span className="text-teal-500">{msg('UI_ARCHITECTURE_ASTRA_CHANGES_NOTHING_WITHOUT_PERMIS')}</span>
          </h2>
          <p className="text-slate-500 max-w-2xl mx-auto text-sm leading-relaxed">
           {msg('UI_ARCHITECTURE_ASTRA_IS_NOT_SAAS_EACH')}
          </p>
        </div>

        {/* Config layers */}
        <div className="space-y-3 mb-10">
          {CONFIG_LAYERS.map(({ num, name, who, examples, reload, color, textColor }) => (
            <div key={num} className={`rounded-2xl border p-5 ${color}`}>
              <div className="flex flex-col sm:flex-row sm:items-center gap-4">
                <div className="flex items-center gap-3 sm:w-64 flex-shrink-0">
                  <span className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold border-2 ${color} ${textColor}`}>{num}</span>
                  <div>
                    <div className="font-semibold text-slate-900 text-sm">{name}</div>
                    <div className={`text-xs ${textColor}`}>{who}</div>
                  </div>
                </div>
                <div className="flex-1">
                  <div className="text-xs text-slate-500 mb-1 font-medium">{msg('UI_ARCHITECTURE_EXAMPLES')}</div>
                  <code className="text-xs text-slate-700">{examples}</code>
                </div>
                <div className="sm:text-right flex-shrink-0">
                  <div className="text-xs text-slate-400 mb-0.5">{msg('UI_ARCHITECTURE_HOT_RELOAD')}</div>
                  <div className={`text-xs font-medium ${textColor}`}>{reload}</div>
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Deployment model */}
        <div className="grid sm:grid-cols-3 gap-5">
          {[
            {
              icon: '🏛',
              title: msg('UI_ARCHITECTURE_THREE_INDEPENDENT_HELM_CHARTS'),
              body: msg('UI_ARCHITECTURE_ASTRA_PLATFORM_EVERY_BANK_ASTRA'),
            },
            {
              icon: '🔄',
              title: msg('UI_ARCHITECTURE_GITOPS_PULL_MODEL'),
              body: msg('UI_ARCHITECTURE_ARGOCD_IN_EACH_BANK_S'),
            },
            {
              icon: '⚡',
              title: msg('UI_ARCHITECTURE_CROSS_SELL_ONE_CONFIG_FLAG'),
              body: msg('UI_ARCHITECTURE_A_BANK_THAT_BUYS_CTS'),
            },
          ].map(({ icon, title, body }) => (
            <div key={title} className="bg-white rounded-2xl border border-slate-200 p-6">
              <div className="text-2xl mb-3">{icon}</div>
              <h3 className="font-semibold text-slate-900 mb-2 text-sm">{title}</h3>
              <p className="text-xs text-slate-500 leading-relaxed">{body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

import { msg } from '../../shared/messages'
const PILLARS = [
  {
    icon: '🔒',
    title: msg('UI_SECURITYSECTION_100_ON_PREMISES'),
    body: msg('UI_SECURITYSECTION_ZERO_CLOUD_DEPENDENCIES_YOUR_DATA'),
  },
  {
    icon: '🏦',
    title: msg('UI_SECURITYSECTION_RBI_IT_FRAMEWORK'),
    body: msg('UI_SECURITYSECTION_CERTIFIED_ONCE_FOR_RBI_COMPLIANCE'),
  },
  {
    icon: '🔑',
    title: msg('UI_SECURITYSECTION_ZERO_TRUST_ARCHITECTURE'),
    body: msg('UI_SECURITYSECTION_ISTIO_SERVICE_MESH_WITH_MTLS'),
  },
  {
    icon: '📊',
    title: msg('UI_SECURITYSECTION_EXPLAINABLE_AI_ONLY'),
    body: msg('UI_SECURITYSECTION_EVERY_AI_DECISION_INCLUDES_SHAP'),
  },
  {
    icon: '🛡',
    title: msg('UI_SECURITYSECTION_ACTIVE_ACTIVE_RESILIENCE'),
    body: msg('UI_SECURITYSECTION_TWO_DATA_CENTERS_SERVING_LIVE'),
  },
  {
    icon: '📝',
    title: msg('UI_SECURITYSECTION_IMMUTABLE_AUDIT_TRAIL'),
    body: msg('UI_SECURITYSECTION_EVERY_DECISION_CONFIG_CHANGE_AND'),
  },
]

export default function SecuritySection() {
  return (
    <section id="security" className="bg-white py-20 px-6">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-14">
          <span className="inline-block text-xs font-semibold text-slate-400 tracking-widest uppercase mb-3">{msg('UI_FOOTER_SECURITY_COMPLIANCE')}</span>
          <h2 className="text-3xl sm:text-4xl font-bold text-slate-900 mb-4">
           {msg('UI_SECURITYSECTION_BUILT_FOR_RBI_OWNED_BY')}
          </h2>
          <p className="text-slate-500 max-w-2xl mx-auto text-sm leading-relaxed">
           {msg('UI_SECURITYSECTION_BANKING_GRADE_SECURITY_IS_NOT')}
          </p>
        </div>

        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {PILLARS.map(({ icon, title, body }) => (
            <div key={title} className="rounded-2xl border border-slate-200 bg-slate-50 p-6">
              <div className="text-2xl mb-3">{icon}</div>
              <h3 className="font-semibold text-slate-900 mb-2">{title}</h3>
              <p className="text-sm text-slate-500 leading-relaxed">{body}</p>
            </div>
          ))}
        </div>

        {/* Compliance strip */}
        <div className="mt-10 bg-forest-900 rounded-2xl p-7 text-white">
          <div className="grid sm:grid-cols-3 gap-6 text-center">
            {[
              { label: msg('UI_SECURITYSECTION_ENCRYPTION'), value: 'AES-256 at rest · TLS 1.3 in transit · Column-level PII' },
              { label: 'HSM', value: 'FIPS 140-2 Level 3 · NGCH PKI signing · Key custody' },
              { label: msg('UI_SECURITYSECTION_ACCESS'), value: 'SAML 2.0 via bank IdP · 7-role RBAC · OPA policy engine' },
            ].map(({ label, value }) => (
              <div key={label}>
                <div className="text-teal-400 text-xs font-semibold tracking-widest uppercase mb-2">{label}</div>
                <div className="text-slate-300 text-sm">{value}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}

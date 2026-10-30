import { useState } from 'react'
import { msg } from '../../shared/messages'

export default function ContactSection() {
  const [form, setForm] = useState({ name: '', bank: '', role: '', email: '', message: '' })
  const [submitted, setSubmitted] = useState(false)

  const handleSubmit = (e) => {
    e.preventDefault()
    setSubmitted(true)
  }

  return (
    <section id="contact" className="bg-cream-100 py-20 px-6">
      <div className="max-w-5xl mx-auto">
        <div className="grid lg:grid-cols-2 gap-12 items-start">
          {/* Left */}
          <div>
            <span className="inline-block text-xs font-semibold text-teal-600 tracking-widest uppercase mb-3">{msg('UI_CONTACTSECTION_GET_STARTED')}</span>
            <h2 className="text-3xl sm:text-4xl font-bold text-slate-900 mb-5">
             {msg('UI_CONTACTSECTION_SCHEDULE_A_DEMO')}<br />{msg('UI_CONTACTSECTION_WITH_THE_ASTRA_TEAM')}
            </h2>
            <p className="text-slate-500 mb-8 leading-relaxed">
             {msg('UI_CONTACTSECTION_WE_RUN_STRUCTURED_90_MINUTE')}
            </p>

            <div className="space-y-5">
              {[
                { icon: '👤', label: msg('UI_CONTACTSECTION_EXPERT_LED_DEMO'), detail: msg('UI_CONTACTSECTION_WITH_NILESH_SHAH_EX_NPCI') },
                { icon: '🏦', label: msg('UI_CONTACTSECTION_BANK_SPECIFIC_WALKTHROUGH'), detail: msg('UI_CONTACTSECTION_WE_MAP_ASTRA_TO_YOUR') },
                { icon: '📋', label: msg('UI_CONTACTSECTION_RBI_COMPLIANCE_MAPPING'), detail: msg('UI_CONTACTSECTION_WE_SHOW_THE_EXACT_CONTROL') },
              ].map(({ icon, label, detail }) => (
                <div key={label} className="flex items-start gap-3">
                  <span className="text-xl">{icon}</span>
                  <div>
                    <div className="font-medium text-slate-900 text-sm">{label}</div>
                    <div className="text-xs text-slate-400">{detail}</div>
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-8 pt-8 border-t border-slate-200">
              <div className="text-xs text-slate-400 uppercase tracking-widest font-semibold mb-3">{msg('UI_CONTACTSECTION_18_MONTH_FIRST_MOVER_WINDOW')}</div>
              <p className="text-sm text-slate-500">{msg('UI_CONTACTSECTION_THE_T_3_REGIME_BEGINS')}</p>
            </div>
          </div>

          {/* Right — form */}
          <div className="bg-white rounded-2xl border border-slate-200 p-8 shadow-sm">
            {submitted ? (
              <div className="text-center py-8">
                <div className="text-4xl mb-4">✅</div>
                <h3 className="text-xl font-bold text-slate-900 mb-2">{msg('UI_CONTACTSECTION_REQUEST_RECEIVED')}</h3>
                <p className="text-slate-500 text-sm">{msg('UI_CONTACTSECTION_THE_ASTRA_TEAM_WILL_REACH')}</p>
              </div>
            ) : (
              <form onSubmit={handleSubmit} className="space-y-4">
                <h3 className="font-semibold text-slate-900 mb-5">{msg('UI_CONTACTSECTION_REQUEST_A_DEMO')}</h3>
                {[
                  { id: 'name', label: msg('UI_CONTACTSECTION_YOUR_NAME'), type: 'text', placeholder: msg('UI_CONTACTSECTION_FULL_NAME') },
                  { id: 'bank', label: msg('UI_CONTACTSECTION_BANK_INSTITUTION'), type: 'text', placeholder: msg('UI_CONTACTSECTION_BANK_NAME') },
                  { id: 'role', label: msg('UI_CONTACTSECTION_YOUR_ROLE'), type: 'text', placeholder: msg('UI_CONTACTSECTION_E_G_HEAD_IT_CTO') },
                  { id: 'email', label: msg('UI_CONTACTSECTION_OFFICIAL_EMAIL'), type: 'email', placeholder: 'you@yourbank.com' },
                ].map(({ id, label, type, placeholder }) => (
                  <div key={id}>
                    <label className="block text-xs font-medium text-slate-600 mb-1.5">{label}</label>
                    <input
                      type={type}
                      value={form[id]}
                      onChange={e => setForm(f => ({ ...f, [id]: e.target.value }))}
                      placeholder={placeholder}
                      required
                      className="w-full px-4 py-2.5 rounded-lg border border-slate-200 text-sm focus:outline-none focus:border-teal-400 bg-slate-50"
                    />
                  </div>
                ))}
                <div>
                  <label className="block text-xs font-medium text-slate-600 mb-1.5">{msg('UI_CONTACTSECTION_WHAT_WOULD_YOU_LIKE_TO')}</label>
                  <textarea
                    rows={3}
                    value={form.message}
                    onChange={e => setForm(f => ({ ...f, message: e.target.value }))}
                    placeholder={msg('UI_CONTACTSECTION_CTS_PIPELINE_DEMO_EJ_DISPUTE')}
                    className="w-full px-4 py-2.5 rounded-lg border border-slate-200 text-sm focus:outline-none focus:border-teal-400 bg-slate-50 resize-none"
                  />
                </div>
                <button
                  type="submit"
                  className="w-full bg-teal-400 hover:bg-teal-500 text-forest-900 font-semibold py-3 rounded-xl text-sm transition-colors"
                >
                 {msg('UI_CONTACTSECTION_SCHEDULE_DEMO')}
                </button>
                <p className="text-xs text-slate-400 text-center">{msg('UI_CONTACTSECTION_NO_VENDOR_DATA_ACCESS_NO')}</p>
              </form>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}

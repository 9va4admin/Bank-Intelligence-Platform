import { useState } from 'react'

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
            <span className="inline-block text-xs font-semibold text-teal-600 tracking-widest uppercase mb-3">Get Started</span>
            <h2 className="text-3xl sm:text-4xl font-bold text-slate-900 mb-5">
              Schedule a Demo<br />with the ASTRA Team.
            </h2>
            <p className="text-slate-500 mb-8 leading-relaxed">
              We run structured 90-minute demos tailored to your bank's current CTS and ATM estate. We cover the live pipeline, the What If configuration scenarios, and RBI compliance mapping for your environment.
            </p>

            <div className="space-y-5">
              {[
                { icon: '👤', label: 'Expert-led demo', detail: 'With Nilesh Shah — Ex-NPCI, Piramal, Fullerton/SMFG' },
                { icon: '🏦', label: 'Bank-specific walkthrough', detail: 'We map ASTRA to your CBS, ATM estate, and clearing zone' },
                { icon: '📋', label: 'RBI compliance mapping', detail: 'We show the exact control-to-mandate mapping for your bank type' },
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
              <div className="text-xs text-slate-400 uppercase tracking-widest font-semibold mb-3">18-Month First-Mover Window</div>
              <p className="text-sm text-slate-500">The T+3 regime begins January 2026. Banks that deploy ASTRA in H1 FY26 establish operational muscle before the mandate tightens further. The window to move first is open now.</p>
            </div>
          </div>

          {/* Right — form */}
          <div className="bg-white rounded-2xl border border-slate-200 p-8 shadow-sm">
            {submitted ? (
              <div className="text-center py-8">
                <div className="text-4xl mb-4">✅</div>
                <h3 className="text-xl font-bold text-slate-900 mb-2">Request Received</h3>
                <p className="text-slate-500 text-sm">The ASTRA team will reach out within one business day to schedule your demo.</p>
              </div>
            ) : (
              <form onSubmit={handleSubmit} className="space-y-4">
                <h3 className="font-semibold text-slate-900 mb-5">Request a Demo</h3>
                {[
                  { id: 'name', label: 'Your Name', type: 'text', placeholder: 'Full name' },
                  { id: 'bank', label: 'Bank / Institution', type: 'text', placeholder: 'Bank name' },
                  { id: 'role', label: 'Your Role', type: 'text', placeholder: 'e.g. Head - IT, CTO, GM Operations' },
                  { id: 'email', label: 'Official Email', type: 'email', placeholder: 'you@yourbank.com' },
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
                  <label className="block text-xs font-medium text-slate-600 mb-1.5">What would you like to see? (optional)</label>
                  <textarea
                    rows={3}
                    value={form.message}
                    onChange={e => setForm(f => ({ ...f, message: e.target.value }))}
                    placeholder="CTS pipeline demo, EJ dispute demo, RBI compliance mapping..."
                    className="w-full px-4 py-2.5 rounded-lg border border-slate-200 text-sm focus:outline-none focus:border-teal-400 bg-slate-50 resize-none"
                  />
                </div>
                <button
                  type="submit"
                  className="w-full bg-teal-400 hover:bg-teal-500 text-forest-900 font-semibold py-3 rounded-xl text-sm transition-colors"
                >
                  Schedule Demo →
                </button>
                <p className="text-xs text-slate-400 text-center">No vendor data access. No cold calls. Just the demo.</p>
              </form>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}

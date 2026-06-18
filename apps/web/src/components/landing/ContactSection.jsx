import { useState } from 'react'

export default function ContactSection() {
  const [form, setForm] = useState({ name: '', bank: '', role: '', email: '', message: '' })
  const [submitted, setSubmitted] = useState(false)

  const handleSubmit = (e) => {
    e.preventDefault()
    // In production: POST to /v1/api/demo-request
    setSubmitted(true)
  }

  return (
    <section id="contact" className="py-24 px-6 relative overflow-hidden">
      {/* Background */}
      <div className="absolute inset-0 grid-pattern opacity-20" />
      <div className="absolute top-0 inset-x-0 h-px bg-gradient-to-r from-transparent via-gold-400/30 to-transparent" />

      <div className="max-w-3xl mx-auto relative">
        <div className="text-center mb-12">
          <div className="inline-flex items-center gap-2 glass-gold rounded-full px-4 py-1.5 mb-4">
            <span className="text-xs font-medium text-gold-400 uppercase tracking-wide">Get Started</span>
          </div>
          <h2 className="text-3xl sm:text-4xl font-bold text-white mb-4">
            Ready to Solve IET?
          </h2>
          <p className="text-slate-400">
            Schedule a demo with Nilesh Shah — Ex-NPCI, Ex-Piramal, Ex-Fullerton/SMFG.
            We&apos;ll walk through your cheque volume, CBS type, and deployment timeline.
            No sales pitch. Just the platform.
          </p>
        </div>

        {!submitted ? (
          <form onSubmit={handleSubmit} className="glass rounded-2xl p-8 space-y-5">
            <div className="grid sm:grid-cols-2 gap-5">
              <div>
                <label className="block text-xs font-medium text-slate-400 mb-2">Your Name</label>
                <input
                  type="text"
                  required
                  value={form.name}
                  onChange={e => setForm({ ...form, name: e.target.value })}
                  className="w-full bg-white/4 border border-white/8 rounded-xl px-4 py-3 text-sm text-white placeholder-slate-600 focus:outline-none focus:border-gold-400/40 focus:bg-white/6 transition-all"
                  placeholder="Rahul Sharma"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-400 mb-2">Bank / Institution</label>
                <input
                  type="text"
                  required
                  value={form.bank}
                  onChange={e => setForm({ ...form, bank: e.target.value })}
                  className="w-full bg-white/4 border border-white/8 rounded-xl px-4 py-3 text-sm text-white placeholder-slate-600 focus:outline-none focus:border-gold-400/40 focus:bg-white/6 transition-all"
                  placeholder="Saraswat Co-op Bank"
                />
              </div>
            </div>

            <div className="grid sm:grid-cols-2 gap-5">
              <div>
                <label className="block text-xs font-medium text-slate-400 mb-2">Your Role</label>
                <select
                  value={form.role}
                  onChange={e => setForm({ ...form, role: e.target.value })}
                  className="w-full bg-white/4 border border-white/8 rounded-xl px-4 py-3 text-sm text-slate-300 focus:outline-none focus:border-gold-400/40 transition-all appearance-none"
                >
                  <option value="" className="bg-navy-900">Select role</option>
                  {['CTO / IT Head', 'CISO', 'Operations Head', 'Compliance Officer', 'CEO / MD', 'Other'].map(r => (
                    <option key={r} value={r} className="bg-navy-900">{r}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-400 mb-2">Work Email</label>
                <input
                  type="email"
                  required
                  value={form.email}
                  onChange={e => setForm({ ...form, email: e.target.value })}
                  className="w-full bg-white/4 border border-white/8 rounded-xl px-4 py-3 text-sm text-white placeholder-slate-600 focus:outline-none focus:border-gold-400/40 focus:bg-white/6 transition-all"
                  placeholder="rahul@saraswatbank.com"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-400 mb-2">
                Cheque volume / ATM fleet size <span className="text-slate-600">(optional)</span>
              </label>
              <textarea
                rows={3}
                value={form.message}
                onChange={e => setForm({ ...form, message: e.target.value })}
                className="w-full bg-white/4 border border-white/8 rounded-xl px-4 py-3 text-sm text-white placeholder-slate-600 focus:outline-none focus:border-gold-400/40 focus:bg-white/6 transition-all resize-none"
                placeholder="e.g. ~500 cheques/day, Finacle CBS, 45 ATMs (NCR + Diebold), looking to go live before June IET deadline"
              />
            </div>

            <button
              type="submit"
              className="w-full bg-gold-400 hover:bg-gold-500 text-navy-950 font-semibold py-3.5 rounded-xl text-sm transition-all duration-200 hover:shadow-xl hover:shadow-gold-400/20 hover:-translate-y-0.5"
            >
              Request a Demo
            </button>

            <p className="text-center text-xs text-slate-600">
              Your data stays confidential. No cold calls. Response within 24 hours.
            </p>
          </form>
        ) : (
          <div className="glass glass-gold rounded-2xl p-12 text-center">
            <div className="w-16 h-16 rounded-full bg-gold-400/15 flex items-center justify-center mx-auto mb-6">
              <svg className="w-8 h-8 text-gold-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <h3 className="text-xl font-bold text-white mb-3">Request Received</h3>
            <p className="text-slate-400 text-sm">
              We&apos;ll reach out to <span className="text-white">{form.email}</span> within 24 hours
              to schedule a walkthrough tailored to {form.bank || 'your institution'}.
            </p>
          </div>
        )}
      </div>
    </section>
  )
}

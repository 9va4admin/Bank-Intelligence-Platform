import AppShell from './AppShell'

export default function ComingSoon({ module, icon, desc }) {
  return (
    <AppShell>
      <div className="flex flex-col items-center justify-center h-full gap-6 text-center px-8">
        <div className="text-6xl opacity-30">{icon}</div>
        <div>
          <h2 className="text-2xl font-semibold text-white/80 mb-2">{module}</h2>
          <p className="text-white/40 text-sm max-w-sm">{desc}</p>
        </div>
        <div className="px-4 py-1.5 rounded-full border border-gold-400/30 text-gold-400 text-xs font-medium tracking-widest uppercase">
          Coming in Phase {module === 'Fleet' || module === 'Disputes' ? '4' : '3'}
        </div>
      </div>
    </AppShell>
  )
}

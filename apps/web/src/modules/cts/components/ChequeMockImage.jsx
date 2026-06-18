export default function ChequeMockImage({ fields, alterations }) {
  return (
    <div className="rounded-xl border border-white/8 bg-white/3 p-5 font-mono text-xs relative overflow-hidden">
      {/* Watermark */}
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none select-none">
        <div className="text-white/3 text-6xl font-bold rotate-[-30deg] tracking-widest">SPECIMEN</div>
      </div>

      {/* Bank header */}
      <div className="flex justify-between items-start mb-4">
        <div>
          <div className="text-slate-300 font-bold text-sm">Saraswat Co-operative Bank</div>
          <div className="text-slate-600 text-[10px]">Branch: Andheri (W), Mumbai — IFSC: SRCB0000001</div>
        </div>
        <div className="text-right">
          <div className="text-slate-500 text-[10px]">CTS-2010 Compliant</div>
          <div className="text-slate-600 text-[10px]">Mumbai Clearing Zone</div>
        </div>
      </div>

      {/* Date */}
      <div className="flex justify-end mb-3">
        <div className="border border-white/10 rounded px-3 py-1 text-slate-300">
          Date: <span className="text-gold-400">{fields.date}</span>
        </div>
      </div>

      {/* Pay line */}
      <div className="border-b border-dashed border-white/10 pb-2 mb-3">
        <span className="text-slate-500">Pay </span>
        <span className="text-white font-semibold">{fields.payee}</span>
        <span className="text-slate-500"> or Bearer</span>
      </div>

      {/* Amount words */}
      <div className="border-b border-dashed border-white/10 pb-2 mb-3 flex items-center gap-2">
        <span className="text-slate-500">Rupees </span>
        <span className={`text-white ${alterations ? 'line-through text-red-400/70 decoration-red-400' : ''}`}>
          {fields.amount_words}
        </span>
        {alterations && (
          <span className="text-[10px] text-red-400 border border-red-400/30 rounded px-1 py-0.5 ml-1">
            ⚠ POSSIBLE ALTERATION
          </span>
        )}
      </div>

      {/* Amount box */}
      <div className="flex justify-end mb-4">
        <div className="border-2 border-white/15 rounded px-4 py-2 text-lg font-bold text-gold-400">
          {fields.amount_figures}
        </div>
      </div>

      {/* MICR band */}
      <div className="mt-4 pt-3 border-t border-white/8 flex justify-between items-center">
        <div className="text-slate-600 font-mono tracking-widest text-[11px]">
          ⑈ {fields.micr} ⑈  400160002 ⑆  ****7234 ⑈
        </div>
        <div className="text-slate-600 text-[10px]">MICR Band</div>
      </div>
    </div>
  )
}

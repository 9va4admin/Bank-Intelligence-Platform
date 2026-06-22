export default function ChequeMockImage({ fields, alterations }) {
  const wrap   = 'border-slate-200 bg-slate-50 dark:border-white/10 dark:bg-white/5'
  const bank   = 'text-slate-800 dark:text-slate-300'
  const sub    = 'text-slate-500 dark:text-slate-600'
  const dateBx = 'border-slate-300 text-slate-700 dark:border-white/10 dark:text-slate-300'
  const dateVl = 'text-amber-600 dark:text-gold-400'
  const payLbl = 'text-slate-500 dark:text-slate-500'
  const payNm  = 'text-slate-900 dark:text-white'
  const wordTx = 'text-slate-900 dark:text-white'
  const amtBox = 'border-slate-400 text-amber-600 dark:border-white/15 dark:text-gold-400'
  const micrTx = 'text-slate-400 dark:text-slate-600'
  const wmark  = 'text-slate-200 dark:text-white/3'
  const divDash= 'border-slate-200 dark:border-white/10'
  const micrBd = 'border-slate-200 dark:border-white/10'

  return (
    <div className={`rounded-xl border ${wrap} p-5 font-mono text-xs relative overflow-hidden`}>
      {/* Watermark */}
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none select-none">
        <div className={`${wmark} text-6xl font-bold rotate-[-30deg] tracking-widest`}>SPECIMEN</div>
      </div>

      {/* Bank header */}
      <div className="flex justify-between items-start mb-4">
        <div>
          <div className={`${bank} font-bold text-sm`}>Saraswat Co-operative Bank</div>
          <div className={`${sub} text-[10px]`}>Branch: Andheri (W), Mumbai — IFSC: SRCB0000001</div>
        </div>
        <div className="text-right">
          <div className={`${sub} text-[10px]`}>CTS-2010 Compliant</div>
          <div className={`${sub} text-[10px]`}>Mumbai Clearing Zone</div>
        </div>
      </div>

      {/* Date */}
      <div className="flex justify-end mb-3">
        <div className={`border rounded px-3 py-1 ${dateBx}`}>
          Date: <span className={dateVl}>{fields.date}</span>
        </div>
      </div>

      {/* Pay line */}
      <div className={`border-b border-dashed ${divDash} pb-2 mb-3`}>
        <span className={payLbl}>Pay </span>
        <span className={`${payNm} font-semibold`}>{fields.payee}</span>
        <span className={payLbl}> or Bearer</span>
      </div>

      {/* Amount words */}
      <div className={`border-b border-dashed ${divDash} pb-2 mb-3 flex items-center gap-2`}>
        <span className={payLbl}>Rupees </span>
        <span className={`${wordTx} ${alterations ? 'line-through text-red-400/70 decoration-red-400' : ''}`}>
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
        <div className={`border-2 rounded px-4 py-2 text-lg font-bold ${amtBox}`}>
          {fields.amount_figures}
        </div>
      </div>

      {/* MICR band */}
      <div className={`mt-4 pt-3 border-t ${micrBd} flex justify-between items-center`}>
        <div className={`${micrTx} font-mono tracking-widest text-[11px]`}>
          ⑈ {fields.micr} ⑈  400160002 ⑆  ****7234 ⑈
        </div>
        <div className={`${micrTx} text-[10px]`}>MICR Band</div>
      </div>
    </div>
  )
}

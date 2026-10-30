import { msg } from '../../../shared/messages'
export default function ChequeMockImage({ fields, alterations, isDark }) {
  const wrap   = isDark ? 'border-white/10 bg-white/5' : 'border-slate-200 bg-slate-50'
  const bank   = isDark ? 'text-slate-300' : 'text-slate-800'
  const sub    = isDark ? 'text-slate-600' : 'text-slate-500'
  const dateBx = isDark ? 'border-white/10 text-slate-300' : 'border-slate-300 text-slate-700'
  const dateVl = isDark ? 'text-gold-400' : 'text-amber-600'
  const payLbl = isDark ? 'text-slate-500' : 'text-slate-500'
  const payNm  = isDark ? 'text-white' : 'text-slate-900'
  const wordTx = isDark ? 'text-white' : 'text-slate-900'
  const amtBox = isDark ? 'border-white/15 text-gold-400' : 'border-slate-400 text-amber-600'
  const micrTx = isDark ? 'text-slate-600' : 'text-slate-400'
  const wmark  = isDark ? 'text-white/3' : 'text-slate-200'
  const divDash= isDark ? 'border-white/10' : 'border-slate-200'
  const micrBd = isDark ? 'border-white/10' : 'border-slate-200'

  return (
    <div className={`rounded-xl border ${wrap} p-5 font-mono text-xs relative overflow-hidden`}>
      {/* Watermark */}
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none select-none">
        <div className={`${wmark} text-6xl font-bold rotate-[-30deg] tracking-widest`}>{msg('UI_CHEQUEMOCKIMAGE_SPECIMEN_2')}</div>
      </div>

      {/* Bank header */}
      <div className="flex justify-between items-start mb-4">
        <div>
          <div className={`${bank} font-bold text-sm`}>{msg('UI_CHEQUEMOCKIMAGE_SARASWAT_CO_OPERATIVE_BANK')}</div>
          <div className={`${sub} text-[10px]`}>{msg('UI_CHEQUEMOCKIMAGE_BRANCH_ANDHERI_W_MUMBAI_IFSC_2')}</div>
        </div>
        <div className="text-right">
          <div className={`${sub} text-[10px]`}>{msg('UI_CHEQUEMOCKIMAGE_CTS_2010_COMPLIANT_2')}</div>
        </div>
      </div>

      {/* Date */}
      <div className="flex justify-end mb-3">
        <div className={`border rounded px-3 py-1 ${dateBx}`}>
         {msg('UI_CHEQUEMOCKIMAGE_DATE_2')} <span className={dateVl}>{fields.date}</span>
        </div>
      </div>

      {/* Pay line */}
      <div className={`border-b border-dashed ${divDash} pb-2 mb-3`}>
        <span className={payLbl}>{msg('UI_CHEQUEMOCKIMAGE_PAY_2')} </span>
        <span className={`${payNm} font-semibold`}>{fields.payee}</span>
        <span className={payLbl}> {msg('UI_CHEQUEMOCKIMAGE_OR_BEARER_2')}</span>
      </div>

      {/* Amount words */}
      <div className={`border-b border-dashed ${divDash} pb-2 mb-3 flex items-center gap-2`}>
        <span className={payLbl}>{msg('UI_CHEQUEMOCKIMAGE_RUPEES_2')} </span>
        <span className={`${wordTx} ${alterations ? 'line-through text-red-400/70 decoration-red-400' : ''}`}>
          {fields.amount_words}
        </span>
        {alterations && (
          <span className="text-[10px] text-red-400 border border-red-400/30 rounded px-1 py-0.5 ml-1">
           {msg('UI_CHEQUEMOCKIMAGE_POSSIBLE_ALTERATION_2')}
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
        <div className={`${micrTx} text-[10px]`}>{msg('UI_CHEQUEMOCKIMAGE_MICR_BAND_2')}</div>
      </div>
    </div>
  )
}

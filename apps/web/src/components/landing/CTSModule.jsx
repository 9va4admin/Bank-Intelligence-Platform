import { msg } from '../../shared/messages'
const PIPELINE = [
  { step: '01', name: 'Image + MICR OCR', model: 'GOT-OCR2.0', detail: msg('UI_MODULE_MICR_LINE_AMOUNT_IN_FIGURES') },
  { step: '02', name: 'Alteration Detection', model: 'Qwen2-VL 72B', detail: msg('UI_MODULE_OVERWRITING_ERASURE_CORRECTION_FLUID') },
  { step: '03', name: 'Signature Verification', model: 'Siamese Network', detail: msg('UI_MODULE_VS_CBS_STORED_SPECIMEN_VAULT') },
  { step: '04', name: 'Positive Pay Check', model: 'PPS Vault', detail: msg('UI_MODULE_ISSUER_SUBMITTED_CHEQUE_DETAILS_MATC') },
  { step: '05', name: 'Fraud Scoring', model: 'XGBoost + SHAP', detail: msg('UI_MODULE_SCORE_HUMAN_READABLE_RATIONALE_NO') },
  { step: '06', name: 'Decision + NGCH Filing', model: 'Temporal Agent', detail: msg('UI_MODULE_STP_CONFIRM_STP_RETURN_HUMAN') },
]

export default function CTSModule() {
  return (
    <section id="cts" className="bg-white py-20 px-6">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="flex flex-col lg:flex-row gap-12 mb-14">
          <div className="lg:w-1/2">
            <span className="inline-block text-xs font-semibold text-teal-600 tracking-widest uppercase mb-3">{msg('UI_MODULE_MODULE_1_CTS')}</span>
            <h2 className="text-3xl sm:text-4xl font-bold text-slate-900 mb-4">
             {msg('UI_MODULE_ONE_AI_AGENT')}<br />{msg('UI_MODULE_ONE_CHEQUE')}<br />
              <span className="text-teal-500">{msg('UI_MODULE_UNDER_600_MILLISECONDS')}</span>
            </h2>
            <p className="text-slate-500 leading-relaxed mb-4">
             {msg('UI_MODULE_500_INWARD_CHEQUES_ARRIVE_ASTRA')}
            </p>
            <p className="text-slate-500 leading-relaxed">
             {msg('UI_MODULE_THE_IET_WATCHDOG_RUNS_AS')} <strong className="text-slate-800">0.000%</strong>{msg('UI_MODULE_NOT_A_TARGET_A_STRUCTURAL')}
            </p>
          </div>

          {/* What If panel */}
          <div className="lg:w-1/2">
            <div className="bg-forest-900 rounded-2xl p-7 text-white h-full">
              <div className="flex items-center gap-2 mb-4">
                <span className="text-lg">💡</span>
                <span className="text-xs font-semibold text-teal-400 tracking-widest uppercase">{msg('UI_MODULE_WHAT_IF_THE_MANDATE_TIGHTENS')}</span>
              </div>
              <p className="text-slate-300 text-sm mb-5 leading-relaxed">
               {msg('UI_MODULE_TODAY_T_3_HOURS_180')}
              </p>
              <div className="space-y-3 mb-5">
                {[
                  { label: msg('UI_MODULE_T_3_HRS_TODAY'), value: 'item_expiry_minutes = 180', active: false },
                  { label: msg('UI_MODULE_T_30_MIN_NEXT_PHASE'), value: 'item_expiry_minutes = 30', active: true },
                  { label: msg('UI_MODULE_T_5_MIN_REAL_TIME'), value: 'item_expiry_minutes = 5', active: false },
                ].map(({ label, value, active }) => (
                  <div key={label} className={`flex items-center justify-between rounded-lg px-4 py-3 ${active ? 'bg-teal-400/15 border border-teal-400/30' : 'bg-white/4'}`}>
                    <span className={`text-xs ${active ? 'text-teal-300' : 'text-slate-400'}`}>{label}</span>
                    <code className={`text-xs font-mono ${active ? 'text-teal-200' : 'text-slate-500'}`}>{value}</code>
                  </div>
                ))}
              </div>
              <div className="border-t border-white/10 pt-4">
                <p className="text-sm text-white font-medium mb-1">{msg('UI_MODULE_FOR_ASTRA_ADMIN_UI_CONFIG')}</p>
                <p className="text-sm text-slate-400">{msg('UI_MODULE_FOR_COMPETITORS_18_24_MONTH')}</p>
              </div>
            </div>
          </div>
        </div>

        {/* Pipeline */}
        <div className="bg-slate-50 rounded-2xl border border-slate-200 p-7">
          <h3 className="text-sm font-semibold text-slate-500 uppercase tracking-widest mb-6">{msg('UI_MODULE_6_STEP_AGENT_PIPELINE_EXACTLY')}</h3>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {PIPELINE.map(({ step, name, model, detail }) => (
              <div key={step} className="bg-white rounded-xl border border-slate-200 p-4 flex items-start gap-3">
                <span className="text-xs font-mono text-teal-500 font-bold pt-0.5">{step}</span>
                <div>
                  <div className="font-medium text-slate-900 text-sm">{name}</div>
                  <div className="text-xs text-teal-600 mb-1">{model}</div>
                  <div className="text-xs text-slate-400">{detail}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Key guarantees */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-5">
          {[
            { val: '0.000%', label: msg('UI_MODULE_IET_BREACH_RATE'), color: 'text-teal-500' },
            { val: '<600ms', label: msg('UI_MODULE_ANY_BATCH_SIZE_P99'), color: 'text-sky-500' },
            { val: '500+', label: msg('UI_MODULE_PARALLEL_AGENTS'), color: 'text-violet-500' },
            { val: '100%', label: msg('UI_MODULE_ON_PREMISES_NO_CLOUD'), color: 'text-slate-700' },
          ].map(({ val, label, color }) => (
            <div key={label} className="text-center rounded-xl bg-slate-50 border border-slate-200 py-5">
              <div className={`text-2xl font-bold mb-1 ${color}`}>{val}</div>
              <div className="text-xs text-slate-400">{label}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

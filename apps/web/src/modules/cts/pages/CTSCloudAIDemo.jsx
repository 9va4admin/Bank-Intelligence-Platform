/**
 * CTSCloudAIDemo — real (not simulated) cheque field extraction via a
 * cloud Vision LLM (Hugging Face Inference Providers).
 *
 * Deliberate, temporary exception to ASTRA's zero-cloud-LLM rule — see
 * apps/api/routers/demo_cloud_extract.py's module docstring for the full
 * rationale. Exists so live demos can show real AI extraction ahead of an
 * on-prem vLLM GPU deployment; the banner below is not decorative, it is
 * the point of this page.
 */

import { useState } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'
import { msg } from '../../../shared/messages'

const MODEL_OPTIONS = [
  { value: 'qwen-72b',          label: msg('UI_CLOUDAIDEMO_QWEN_72B_CLOUD_VLM') },
  { value: 'qwen-32b',          label: msg('UI_CLOUDAIDEMO_QWEN_32B_CLOUD_VLM') },
  { value: 'gemma-27b',         label: msg('UI_CLOUDAIDEMO_GEMMA_27B_CLOUD_VLM') },
  { value: 'qwen2vl-sig',       label: msg('UI_CLOUDAIDEMO_QWEN2_VL_SIG_EXTRACT_MULTI') },
  { value: 'yolov8-sig',        label: msg('UI_CLOUDAIDEMO_YOLOV8_SIG_DETECTOR_QWEN_32B') },
  { value: 'yolov8-sig-only',   label: msg('UI_CLOUDAIDEMO_YOLOV8_SIG_ONLY_LOCAL_NO') },
  { value: 'indic-devanagari',  label: msg('UI_CLOUDAIDEMO_INDICOCR_DEVANAGARI_YOLO_SIG_LOCAL') },
]

const FIELD_ROWS = [
  ['bank_name',          '🏦 Bank Name'],
  ['cheque_number',      '📄 Cheque Number'],
  ['micr_code',          '🏢 MICR Code'],
  ['ifsc_code',           '🏛 IFSC Code'],
  ['date',               '📅 Date'],
  ['payee_name',         '👤 Payee Name'],
  ['account_number',     '💳 Account Number'],
  ['amount_numeric',     '💰 Amount (Numeric)'],
  ['amount_words',       '📝 Amount (Words)'],
  ['signature_name',     '👨‍💼 Signature Name'],
]

async function extractChequeCloud(file, model) {
  const form = new FormData()
  form.append('file', file)

  const response = await fetch(`/v1/cts/demo/cloud-extract?model=${encodeURIComponent(model)}`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'X-CSRF-Token': sessionStorage.getItem('astra-csrf') || '',
    },
    body: form,
  })

  if (!response.ok) {
    const detail = await response.json().catch(() => ({}))
    throw new Error(detail.detail || `HTTP ${response.status}`)
  }
  return response.json()
}

async function fetchChequePreview(file) {
  const form = new FormData()
  form.append('file', file)

  const response = await fetch('/v1/cts/demo/cloud-extract/preview', {
    method: 'POST',
    credentials: 'include',
    headers: {
      'X-CSRF-Token': sessionStorage.getItem('astra-csrf') || '',
    },
    body: form,
  })

  if (!response.ok) {
    const detail = await response.json().catch(() => ({}))
    throw new Error(detail.detail || `HTTP ${response.status}`)
  }
  const blob = await response.blob()
  return URL.createObjectURL(blob)
}

function downloadJSON(data, filename) {
  const blob = new Blob([JSON.stringify(data, null, 4)], { type: 'application/json' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  URL.revokeObjectURL(url)
}

export default function CTSCloudAIDemo() {
  const { isDark } = useTheme()
  usePageHeader({ subtitle: msg('UI_CLOUDAIDEMO_REAL_VISION_AI_EXTRACTION_CLOUD') })

  const th = {
    page:    isDark ? 'bg-navy-950'        : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'         : 'text-slate-900',
    body:    isDark ? 'text-slate-300'     : 'text-slate-700',
    muted:   isDark ? 'text-slate-400'     : 'text-slate-500',
    faint:   isDark ? 'text-slate-600'     : 'text-slate-400',
    divider: isDark ? 'border-white/8'     : 'border-slate-200',
    infoCard: isDark ? 'bg-white/5 border-white/10' : 'bg-slate-50 border-slate-200',
    select:  isDark ? 'bg-navy-900 border-white/15 text-white' : 'bg-white border-slate-300 text-slate-900',
  }

  const [file, setFile]                 = useState(null)
  const [previewUrl, setPreview]        = useState(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [model, setModel]               = useState('qwen-72b')
  const [loading, setLoading]           = useState(false)
  const [result, setResult]             = useState(null)
  const [error, setError]               = useState(null)

  async function handleFileChange(e) {
    const f = e.target.files?.[0]
    if (!f) return
    if (previewUrl) URL.revokeObjectURL(previewUrl)
    setFile(f)
    setPreview(null)
    setResult(null)
    setError(null)
    setPreviewLoading(true)
    try {
      const url = await fetchChequePreview(f)
      setPreview(url)
    } catch (err) {
      setError(err.message || msg('UI_CLOUDAIDEMO_PREVIEW_GENERATION_FAILED'))
    } finally {
      setPreviewLoading(false)
    }
  }

  async function handleExtract() {
    if (!file) return
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const data = await extractChequeCloud(file, model)
      setResult(data)
    } catch (err) {
      setError(err.message || msg('UI_CLOUDAIDEMO_EXTRACTION_FAILED'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        <div className={`mb-5 rounded-xl border px-4 py-3 ${isDark ? 'bg-amber-900/30 border-amber-700/40 text-amber-200' : 'bg-amber-50 border-amber-300 text-amber-800'}`}>
          <span className="font-semibold">{msg('UI_CLOUDAIDEMO_CLOUD_AI_DEMO_TEMPORARY')}</span>{msg('UI_CLOUDAIDEMO_THIS_PAGE_CALLS_A_CLOUD')}
        </div>

        <h1 className={`text-lg font-semibold mb-4 ${th.heading}`}>{msg('UI_CLOUDAIDEMO_CLOUD_AI_CHEQUE_EXTRACTION')}</h1>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          <div className={`rounded-xl border p-5 ${th.card}`} style={{ alignSelf: 'start' }}>
            <div className="mb-3">
              <label className={`block text-xs font-semibold mb-1 ${th.muted}`}>{msg('UI_CLOUDAIDEMO_VISION_MODEL')}</label>
              <select
                className={`w-full rounded-lg border px-3 py-2 text-sm ${th.select}`}
                value={model}
                onChange={(e) => setModel(e.target.value)}
              >
                {MODEL_OPTIONS.map((m) => (
                  <option key={m.value} value={m.value}>{m.label}</option>
                ))}
              </select>
              {model === 'yolov8-sig' && (
                <p className={`mt-1.5 text-[11px] leading-snug ${th.muted}`}>
                 {msg('UI_CLOUDAIDEMO_SIG_CROP_VIA_LOCAL_YOLOV8')} <code className="font-mono">{msg('UI_CLOUDAIDEMO_CD_APPS_SIG_DETECTOR_PYTHON')}</code>
                </p>
              )}
              {model === 'yolov8-sig-only' && (
                <p className={`mt-1.5 text-[11px] leading-snug ${th.muted}`}>
                 {msg('UI_CLOUDAIDEMO_LOCAL_ONLY_MODE_RUNS_THE')} <strong>{msg('UI_CLOUDAIDEMO_NO_HF_TOKEN_NEEDED_NO')}</strong> {msg('UI_CLOUDAIDEMO_USE_THIS_TO_TEST_SIG')} <code className="font-mono">{msg('UI_CLOUDAIDEMO_CD_APPS_SIG_DETECTOR_PYTHON')}</code>
                </p>
              )}
              {model === 'indic-devanagari' && (
                <p className={`mt-1.5 text-[11px] leading-snug ${th.muted}`}>
                  <strong>{msg('UI_CLOUDAIDEMO_STAGE_1_DEVANAGARI_SCRIPT_ONLY')}</strong> {msg('UI_CLOUDAIDEMO_HINDI_MARATHI_SANSKRIT_PAYEE_NAME')}
                  <strong>{msg('UI_CLOUDAIDEMO_PADDLEOCR_HI')}</strong> {msg('UI_CLOUDAIDEMO_DEFAULT')} <strong>{msg('UI_CLOUDAIDEMO_AI4BHARAT_INDICOCR')}</strong> {msg('UI_CLOUDAIDEMO_MANUAL_SETUP_REQUIRED')} <strong>{msg('UI_CLOUDAIDEMO_EASYOCR_HI_PACK')}</strong> {msg('UI_CLOUDAIDEMO_FALLBACK_SET')} <code className="font-mono">{msg('UI_CLOUDAIDEMO_INDIC_OCR_BACKEND_PADDLE_AI4BHARAT')}</code> {msg('UI_CLOUDAIDEMO_ON_THE_INDICOCR_SERVICE_SIGNATURE')} <strong>{msg('UI_CLOUDAIDEMO_YOLOV8_PIXEL_DETECTOR')}</strong>.{' '}
                  <strong>{msg('UI_CLOUDAIDEMO_NO_HF_TOKEN_NEEDED')}</strong> {msg('UI_CLOUDAIDEMO_START_BOTH_SERVICES_FIRST')}
                  <code className="font-mono">{msg('UI_CLOUDAIDEMO_CD_APPS_SIG_DETECTOR_PYTHON')}</code>
                  {msg('UI_CLOUDAIDEMO_AND')}
                  <code className="font-mono">{msg('UI_CLOUDAIDEMO_CD_APPS_INDIC_OCR_PYTHON')}</code>
                </p>
              )}
            </div>

            <div className="mb-3">
              <label className={`block text-xs font-semibold mb-1 ${th.muted}`}>{msg('UI_CLOUDAIDEMO_UPLOAD_CHEQUE_IMAGE')}</label>
              <input
                type="file"
                accept="image/jpeg,image/png,image/bmp,image/tiff"
                onChange={handleFileChange}
                className={`w-full text-sm ${th.body}`}
              />
            </div>

            <button
              onClick={handleExtract}
              disabled={!file || loading}
              className="w-full h-11 rounded-lg font-semibold text-sm bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white transition"
            >
              {loading ? 'Extracting…' : '🚀 Extract Information'}
            </button>

            {error && (
              <p className="mt-3 text-sm text-red-500">{error}</p>
            )}

            {previewLoading && (
              <div className={`mt-4 rounded-lg border flex items-center justify-center text-sm ${th.faint}`} style={{ minHeight: '8rem' }}>
               {msg('UI_CLOUDAIDEMO_GENERATING_PREVIEW')}
              </div>
            )}

            {previewUrl && !previewLoading && (
              <div className="mt-4">
                <p className={`text-xs mb-1 ${th.muted}`}>{msg('UI_CLOUDAIDEMO_UPLOADED_CHEQUE_COMPARE_AGAINST_EXTR')}</p>
                <img
                  src={previewUrl}
                  alt={msg('UI_CLOUDAIDEMO_CHEQUE_PREVIEW')}
                  className="rounded-lg border w-full max-h-72 object-contain bg-white"
                  style={{ minHeight: '8rem' }}
                  onError={() => setError(msg('UI_CLOUDAIDEMO_PREVIEW_FAILED_TO_RENDER_TRY'))}
                />
              </div>
            )}
          </div>

          <div className={`rounded-xl border p-5 ${th.card}`}>
            <h3 className={`text-sm font-semibold mb-3 ${th.heading}`}>{msg('UI_CLOUDAIDEMO_EXTRACTED_INFORMATION')}</h3>

            {!result && !loading && (
              <p className={`text-sm ${th.faint}`}>{msg('UI_CLOUDAIDEMO_UPLOAD_A_CHEQUE_IMAGE_AND')}</p>
            )}

            {loading && (
              <p className={`text-sm ${th.faint}`}>{msg('UI_CLOUDAIDEMO_EXTRACTING')}</p>
            )}

            {result?.error && !result.error.startsWith('SIG_DETECTOR_OFFLINE') && (
              <div>
                <p className="text-sm text-red-500 mb-2">{result.error}</p>
                {result.raw_response && (
                  <pre className={`text-xs p-2 rounded-lg overflow-x-auto ${th.infoCard}`}>{result.raw_response}</pre>
                )}
              </div>
            )}

            {result && (!result.error || result.error.startsWith('SIG_DETECTOR_OFFLINE')) && (() => {
              const isSigOnly         = result.model_used === 'yolov8-sig-only'
              const isIndicDevanagari = result.model_used === 'indic-devanagari'
              const sigOffline        = result.error?.startsWith('SIG_DETECTOR_OFFLINE')
              return (
                <div>
                  {sigOffline && (
                    <div className={`rounded-lg border px-4 py-3 mb-3 ${isDark ? 'bg-amber-900/30 border-amber-700/40 text-amber-200' : 'bg-amber-50 border-amber-300 text-amber-800'}`}>
                      <p className="text-xs font-semibold mb-0.5">{msg('UI_CLOUDAIDEMO_SIG_DETECTOR_OFFLINE')}</p>
                      <p className="text-[11px] leading-snug">
                       {msg('UI_CLOUDAIDEMO_FIELD_EXTRACTION_SUCCEEDED_SIGNATURE')}<code className="font-mono">{msg('UI_CLOUDAIDEMO_CD_APPS_SIG_DETECTOR_PYTHON')}</code>
                      </p>
                    </div>
                  )}
                  {isSigOnly && sigOffline ? (
                    null  /* sig-only + offline: banner above is the only output */
                  ) : isSigOnly ? (
                    <div className={`rounded-lg border px-4 py-3 mb-3 ${isDark ? 'bg-indigo-900/30 border-indigo-700/40 text-indigo-200' : 'bg-indigo-50 border-indigo-200 text-indigo-800'}`}>
                      <p className="text-xs font-semibold mb-0.5">{msg('UI_CLOUDAIDEMO_SIG_ONLY_MODE')}</p>
                      <p className="text-[11px] leading-snug">
                       {msg('UI_CLOUDAIDEMO_ONLY_THE_SIGNATURE_CROP_IS')}
                      </p>
                    </div>
                  ) : (
                    <>
                      {isIndicDevanagari && (
                        <div className={`rounded-lg border px-4 py-3 mb-3 ${isDark ? 'bg-emerald-900/25 border-emerald-700/40 text-emerald-200' : 'bg-emerald-50 border-emerald-200 text-emerald-800'}`}>
                          <p className="text-xs font-semibold mb-0.5">
                           {msg('UI_CLOUDAIDEMO_INDICOCR_DEVANAGARI_STAGE_1')}
                            {result.indic_backend && (
                              <span className={`ml-2 text-[9px] font-bold px-1.5 py-0.5 rounded border ${isDark ? 'border-emerald-600/50 bg-emerald-800/40' : 'border-emerald-300 bg-emerald-100'}`}>
                                {{ paddle: 'PaddleOCR hi', ai4bharat: 'AI4Bharat IndicOCR', easyocr: 'EasyOCR hi-pack' }[result.indic_backend] ?? result.indic_backend}
                              </span>
                            )}
                          </p>
                          <p className="text-[11px] leading-snug">
                           {msg('UI_CLOUDAIDEMO_PAYEE_AMOUNT_IN_WORDS_DATE', { value: { paddle: 'PaddleOCR Hindi model (default)', ai4bharat: 'AI4Bharat IndicOCR', easyocr: 'EasyOCR Hindi pack' }[result.indic_backend] ?? 'local IndicOCR' })}
                          </p>
                        </div>
                      )}
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-3">
                        {FIELD_ROWS.map(([key, label]) => (
                          <div key={key} className={`rounded-lg border px-3 py-2 ${th.infoCard}`}>
                            <div className={`text-[11px] font-semibold ${th.muted}`}>{label}</div>
                            <div className={`text-sm font-semibold break-words ${th.heading}`}>{result[key] ?? '-'}</div>
                          </div>
                        ))}
                      </div>

                      <div className={`rounded-lg border px-3 py-2 mb-2 ${th.infoCard}`}>
                        <div className={`text-[11px] font-semibold ${th.muted}`}>{msg('UI_CLOUDAIDEMO_SIGNATURE')}</div>
                        <div className={`text-sm font-semibold ${th.heading}`}>
                          {result.signature_present ? 'Present' : 'Not Found'}
                        </div>
                      </div>

                      {result.is_amount_matching === true && (
                        <p className="text-sm text-emerald-500">{msg('UI_CLOUDAIDEMO_AMOUNT_IN_WORDS_MATCHES_AMOUNT')}</p>
                      )}
                      {result.is_amount_matching === false && (
                        <p className="text-sm text-red-500">{msg('UI_CLOUDAIDEMO_AMOUNT_IN_WORDS_DOES_NOT')}</p>
                      )}
                      {result.is_amount_matching == null && (
                        <p className={`text-sm ${th.muted}`}>{msg('UI_CLOUDAIDEMO_UNABLE_TO_VALIDATE_AMOUNT')}</p>
                      )}
                    </>
                  )}

                  <p className={`text-xs mt-3 mb-3 ${th.faint}`}>{msg('UI_CLOUDAIDEMO_MODEL', { model_used: result.model_used })}</p>

                  <button
                    onClick={() => downloadJSON(result, 'cheque_extraction.json')}
                    className={`w-full h-10 rounded-lg font-semibold text-sm border transition ${isDark ? 'border-white/15 text-white hover:bg-white/5' : 'border-slate-300 text-slate-900 hover:bg-slate-50'}`}
                  >
                   {msg('UI_CLOUDAIDEMO_DOWNLOAD_JSON')}
                  </button>
                </div>
              )
            })()}
          </div>
        </div>

        {/* ── Signature Crops — shown below both columns once extraction completes ── */}
        {result && (!result.error || result.error.startsWith('SIG_DETECTOR_OFFLINE')) && (
          <div className={`mt-5 rounded-xl border p-5 ${th.card}`}>
            <div className="flex items-center justify-between mb-3">
              <h3 className={`text-sm font-semibold ${th.heading}`}>
                {(() => {
                  const count = result.signature_count ?? (result.signature_present ? 1 : 0)
                  return (
                    <>
                     {msg('UI_CLOUDAIDEMO_EXTRACTED_SIGNATURE', { value: count !== 1 ? 's' : '' })}&nbsp;
                      <span className={`text-xs font-normal ${th.muted}`}>
                       {msg('UI_CLOUDAIDEMO_SIGNATURE_DETECTED_ON_THIS_CHEQUE', { count, value: count !== 1 ? 's' : '' })}
                      </span>
                    </>
                  )
                })()}
              </h3>
              {result.signature_fraud_flags && result.signature_fraud_flags.length > 0 && (
                <span className="flex items-center gap-1 text-[11px] font-semibold text-red-600 bg-red-50 border border-red-200 rounded-full px-2.5 py-1">
                 {msg('UI_CLOUDAIDEMO_FRAUD_FLAG', { count: result.signature_fraud_flags.length, value: result.signature_fraud_flags.length !== 1 ? 's' : '' })}
                </span>
              )}
            </div>

            {result.signature_crops && result.signature_crops.length > 0 ? (
              <div className="flex flex-col gap-3">
                <div className="flex flex-wrap gap-4">
                  {result.signature_crops.map((crop, i) => (
                    <div
                      key={i}
                      className={`rounded-lg border px-3 py-3 flex flex-col items-center gap-2 ${th.infoCard}`}
                      style={{ minWidth: '10rem' }}
                    >
                      <div className={`text-[10px] font-mono font-semibold ${th.muted}`}>
                       {msg('UI_CLOUDAIDEMO_SIGNATURE_2', { value: i + 1 })}
                      </div>
                      <img
                        src={`data:image/png;base64,${crop}`}
                        alt={msg('UI_CLOUDAIDEMO_DETECTED_SIGNATURE', { value: i + 1 })}
                        className="rounded bg-white max-h-24 max-w-xs object-contain border"
                        style={{ minHeight: '3rem' }}
                      />
                    </div>
                  ))}
                </div>
                {result.signature_crops_estimated && (
                  <p className={`text-[11px] ${th.muted}`}>
                   {msg('UI_CLOUDAIDEMO_REGION_ESTIMATED_VIA_INK_DETECTION')}
                  </p>
                )}
              </div>
            ) : (
              <p className={`text-sm ${th.faint}`}>
                {result.error?.startsWith('SIG_DETECTOR_OFFLINE')
                  ? 'Sig detector offline — start it with: cd apps/sig_detector; python main.py'
                  : result.signature_present
                    ? 'Signature present · region could not be isolated from this scan.'
                    : 'No signature detected on this cheque.'}
              </p>
            )}

            {result.signature_fraud_flags && result.signature_fraud_flags.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {result.signature_fraud_flags.map((flag, i) => (
                  <span
                    key={i}
                    className="text-[11px] font-semibold bg-red-100 text-red-700 border border-red-200 rounded-full px-2.5 py-1"
                  >
                    ⚠ {flag.replace(/_/g, ' ')}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </AppShell>
  )
}

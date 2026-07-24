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

const MODEL_OPTIONS = [
  { value: 'qwen-72b',         label: 'Qwen 72B  (cloud VLM)' },
  { value: 'qwen-32b',         label: 'Qwen 32B  (cloud VLM)' },
  { value: 'gemma-27b',        label: 'Gemma 27B (cloud VLM)' },
  { value: 'qwen2vl-sig',      label: '✍️ Qwen2-VL Sig Extract  (multi-signature, cloud)' },
  { value: 'yolov8-sig',       label: '🔍 YOLOv8 Sig Detector  +  Qwen 32B fields' },
  { value: 'yolov8-sig-only',  label: '🔍 YOLOv8 Sig Only  (local — no HF token needed)' },
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
  usePageHeader({ subtitle: 'Real Vision AI extraction — cloud-backed demo, temporary' })

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
      setError(err.message || 'Preview generation failed')
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
      setError(err.message || 'Extraction failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        <div className={`mb-5 rounded-xl border px-4 py-3 ${isDark ? 'bg-amber-900/30 border-amber-700/40 text-amber-200' : 'bg-amber-50 border-amber-300 text-amber-800'}`}>
          <span className="font-semibold">☁️ Cloud AI Demo — Temporary.</span>{' '}
          This page calls a cloud Vision LLM (Hugging Face) for real, live extraction results.
          Production CTS processing never leaves the bank's own infrastructure — this page exists
          only to demo real AI behaviour ahead of on-prem GPU availability.
        </div>

        <h1 className={`text-lg font-semibold mb-4 ${th.heading}`}>Cloud AI Cheque Extraction</h1>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          <div className={`rounded-xl border p-5 ${th.card}`} style={{ alignSelf: 'start' }}>
            <div className="mb-3">
              <label className={`block text-xs font-semibold mb-1 ${th.muted}`}>Vision Model</label>
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
                  Sig crop via local YOLOv8 pixel detector + connected-component denoising.
                  All text fields extracted via Qwen 32B (HF token required).
                  Start detector first: <code className="font-mono">cd apps/sig_detector; python main.py</code>
                </p>
              )}
              {model === 'yolov8-sig-only' && (
                <p className={`mt-1.5 text-[11px] leading-snug ${th.muted}`}>
                  Local-only mode — runs the pixel sig detector + denoising, returns the clean
                  signature crop. <strong>No HF token needed, no cloud call.</strong> Use this
                  to test sig crop quality without burning HF quota.
                  Start detector first: <code className="font-mono">cd apps/sig_detector; python main.py</code>
                </p>
              )}
            </div>

            <div className="mb-3">
              <label className={`block text-xs font-semibold mb-1 ${th.muted}`}>Upload Cheque Image</label>
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
                Generating preview…
              </div>
            )}

            {previewUrl && !previewLoading && (
              <div className="mt-4">
                <p className={`text-xs mb-1 ${th.muted}`}>Uploaded Cheque — compare against extracted fields</p>
                <img
                  src={previewUrl}
                  alt="Cheque preview"
                  className="rounded-lg border w-full max-h-72 object-contain bg-white"
                  style={{ minHeight: '8rem' }}
                  onError={() => setError('Preview failed to render — try re-selecting the file.')}
                />
              </div>
            )}
          </div>

          <div className={`rounded-xl border p-5 ${th.card}`}>
            <h3 className={`text-sm font-semibold mb-3 ${th.heading}`}>📋 Extracted Information</h3>

            {!result && !loading && (
              <p className={`text-sm ${th.faint}`}>Upload a cheque image and click Extract Information.</p>
            )}

            {loading && (
              <p className={`text-sm ${th.faint}`}>Extracting…</p>
            )}

            {result?.error && (
              <div>
                <p className="text-sm text-red-500 mb-2">{result.error}</p>
                {result.raw_response && (
                  <pre className={`text-xs p-2 rounded-lg overflow-x-auto ${th.infoCard}`}>{result.raw_response}</pre>
                )}
              </div>
            )}

            {result && !result.error && (() => {
              const isSigOnly = result.model_used === 'yolov8-sig-only'
              return (
                <div>
                  {isSigOnly ? (
                    <div className={`rounded-lg border px-4 py-3 mb-3 ${isDark ? 'bg-indigo-900/30 border-indigo-700/40 text-indigo-200' : 'bg-indigo-50 border-indigo-200 text-indigo-800'}`}>
                      <p className="text-xs font-semibold mb-0.5">🔍 Sig-only mode</p>
                      <p className="text-[11px] leading-snug">
                        Only the signature crop is returned — no field extraction was run
                        (no HF call made). See the signature panel below for the denoised crop.
                      </p>
                    </div>
                  ) : (
                    <>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-3">
                        {FIELD_ROWS.map(([key, label]) => (
                          <div key={key} className={`rounded-lg border px-3 py-2 ${th.infoCard}`}>
                            <div className={`text-[11px] font-semibold ${th.muted}`}>{label}</div>
                            <div className={`text-sm font-semibold break-words ${th.heading}`}>{result[key] ?? '-'}</div>
                          </div>
                        ))}
                      </div>

                      <div className={`rounded-lg border px-3 py-2 mb-2 ${th.infoCard}`}>
                        <div className={`text-[11px] font-semibold ${th.muted}`}>✍ Signature</div>
                        <div className={`text-sm font-semibold ${th.heading}`}>
                          {result.signature_present ? 'Present' : 'Not Found'}
                        </div>
                      </div>

                      {result.is_amount_matching === true && (
                        <p className="text-sm text-emerald-500">✅ Amount in Words matches Amount in Figures</p>
                      )}
                      {result.is_amount_matching === false && (
                        <p className="text-sm text-red-500">❌ Amount in Words DOES NOT match Amount in Figures</p>
                      )}
                      {result.is_amount_matching == null && (
                        <p className={`text-sm ${th.muted}`}>⚠ Unable to validate amount</p>
                      )}
                    </>
                  )}

                  <p className={`text-xs mt-3 mb-3 ${th.faint}`}>Model: {result.model_used}</p>

                  <button
                    onClick={() => downloadJSON(result, 'cheque_extraction.json')}
                    className={`w-full h-10 rounded-lg font-semibold text-sm border transition ${isDark ? 'border-white/15 text-white hover:bg-white/5' : 'border-slate-300 text-slate-900 hover:bg-slate-50'}`}
                  >
                    ⬇ Download JSON
                  </button>
                </div>
              )
            })()}
          </div>
        </div>

        {/* ── Signature Crops — shown below both columns once extraction completes ── */}
        {result && !result.error && (
          <div className={`mt-5 rounded-xl border p-5 ${th.card}`}>
            <div className="flex items-center justify-between mb-3">
              <h3 className={`text-sm font-semibold ${th.heading}`}>
                {(() => {
                  const count = result.signature_count ?? (result.signature_present ? 1 : 0)
                  return (
                    <>
                      ✍ Extracted Signature{count !== 1 ? 's' : ''}&nbsp;
                      <span className={`text-xs font-normal ${th.muted}`}>
                        — {count} signature{count !== 1 ? 's' : ''} detected on this cheque
                      </span>
                    </>
                  )
                })()}
              </h3>
              {result.signature_fraud_flags && result.signature_fraud_flags.length > 0 && (
                <span className="flex items-center gap-1 text-[11px] font-semibold text-red-600 bg-red-50 border border-red-200 rounded-full px-2.5 py-1">
                  ⚠ {result.signature_fraud_flags.length} fraud flag{result.signature_fraud_flags.length !== 1 ? 's' : ''}
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
                        Signature #{i + 1}
                      </div>
                      <img
                        src={`data:image/png;base64,${crop}`}
                        alt={`Detected signature ${i + 1}`}
                        className="rounded bg-white max-h-24 max-w-xs object-contain border"
                        style={{ minHeight: '3rem' }}
                      />
                    </div>
                  ))}
                </div>
                {result.signature_crops_estimated && (
                  <p className={`text-[11px] ${th.muted}`}>
                    ⚠ Region estimated via ink-detection — model returned no coordinates. Crop covers the standard CTS-2010 signature zone.
                  </p>
                )}
              </div>
            ) : (
              <p className={`text-sm ${th.faint}`}>
                {result.signature_present
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

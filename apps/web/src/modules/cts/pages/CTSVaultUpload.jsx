import { useState, useRef, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'

// ── Vault type catalogue ───────────────────────────────────────────────────

const VAULT_TYPES = [
  {
    id: 'CHEQUE_BOOK',
    label: 'Cheque Book',
    icon: '📒',
    shortDesc: 'Register issued cheque books',
    desc: 'Register issued cheque books. Each row auto-expands all leaves in the series to ACTIVE.',
    filename: 'cheque_book_upload.csv',
    minRole: 'bank_it_admin',
    accent: '#10b981',
  },
  {
    id: 'LEAF_STATUS',
    label: 'Leaf Status',
    icon: '🚫',
    shortDesc: 'Report STOPPED, LOST, STOLEN, CANCELLED',
    desc: 'Report exception events — STOPPED, LOST, STOLEN, CANCELLED. ASTRA writes clearing events automatically.',
    filename: 'cheque_leaf_status_upload.csv',
    minRole: 'ops_manager',
    accent: '#f59e0b',
  },
  {
    id: 'ACCOUNT_DETAIL',
    label: 'Account Holders',
    icon: '👤',
    shortDesc: 'Holder names for joint / corporate accounts',
    desc: 'Account holder names and roles for joint/corporate accounts. One row per holder per account.',
    filename: 'account_vault_detail_upload.csv',
    minRole: 'bank_it_admin',
    accent: '#6366f1',
  },
  {
    id: 'SIGNATURE',
    label: 'Mandate Rules',
    icon: '✍️',
    shortDesc: 'Signatory mandate rules per account',
    desc: 'Signatory mandate rules (ANY_ONE / ALL_REQUIRED / QUORUM_N) per account. Specimen images uploaded separately.',
    filename: 'signatory_upload.csv',
    minRole: 'bank_it_admin',
    accent: '#8b5cf6',
  },
  {
    id: 'PPS',
    label: 'Positive Pay',
    icon: '✅',
    shortDesc: 'Pre-register cheques for PPS',
    desc: 'Pre-register cheques for Positive Pay System (RBI mandate). One row per cheque: account, cheque number, date, amount, payee.',
    filename: 'pps_upload.csv',
    minRole: 'ops_manager',
    accent: '#0ea5e9',
  },
]

const STATUS_STYLES = {
  COMPLETE:   { dot: 'bg-emerald-400', label: 'Complete'   },
  PARTIAL:    { dot: 'bg-amber-400',   label: 'Partial'    },
  FAILED:     { dot: 'bg-red-400',     label: 'Failed'     },
  PROCESSING: { dot: 'bg-violet-400',  label: 'Processing' },
  PENDING:    { dot: 'bg-slate-400',   label: 'Pending'    },
}

const LEAF_LIFECYCLE = [
  { s: 'ACTIVE',    who: 'ASTRA', note: 'auto-expanded from book upload',  color: 'text-emerald-400' },
  { s: 'PRESENTED', who: 'ASTRA', note: 'workflow start',                  color: 'text-violet-400' },
  { s: 'PAID',      who: 'ASTRA', note: 'ngch_filer → CONFIRM',            color: 'text-emerald-400' },
  { s: 'RETURNED',  who: 'ASTRA', note: 'ngch_filer → RETURN',             color: 'text-amber-400' },
  { s: 'EXPIRED',   who: 'ASTRA', note: 'daily sweep > 3 months',          color: 'text-slate-400' },
  { s: 'STOPPED',   who: 'Bank',  note: 'stop payment instruction',        color: 'text-amber-400' },
  { s: 'LOST',      who: 'Bank',  note: 'customer reports loss',           color: 'text-red-400' },
  { s: 'STOLEN',    who: 'Bank',  note: 'customer/police report',          color: 'text-red-400' },
  { s: 'CANCELLED', who: 'Bank',  note: 'customer cancels unused leaf',    color: 'text-red-400' },
]

// ── API helpers ────────────────────────────────────────────────────────────

async function apiFetch(url, opts = {}) {
  const r = await fetch(url, { credentials: 'include', ...opts })
  if (!r.ok) {
    const body = await r.json().catch(() => ({}))
    throw new Error(body?.detail?.message || `HTTP ${r.status}`)
  }
  return r
}

// ── Page ───────────────────────────────────────────────────────────────────

export default function CTSVaultUpload() {
  const { isDark } = useTheme()
  const qc = useQueryClient()
  const [activeTab, setActiveTab]         = useState('CHEQUE_BOOK')
  const [dragOver, setDragOver]           = useState(false)
  const [selectedFile, setSelectedFile]   = useState(null)
  const [uploadResult, setUploadResult]   = useState(null)
  const [downloadingBatch, setDownloadingBatch] = useState(null)
  const fileInputRef = useRef(null)

  const th = {
    page:    isDark ? 'bg-navy-950'                    : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8'     : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'                     : 'text-slate-900',
    body:    isDark ? 'text-slate-300'                 : 'text-slate-700',
    muted:   isDark ? 'text-slate-400'                 : 'text-slate-500',
    faint:   isDark ? 'text-slate-500'                 : 'text-slate-400',
    divider: isDark ? 'border-white/8'                 : 'border-slate-200',
    row:     isDark ? 'border-white/4 hover:bg-white/2': 'border-slate-100 hover:bg-slate-50',
    input:   isDark ? 'bg-white/8 border-white/10 text-white placeholder-slate-500'
                    : 'bg-white border-slate-200 text-slate-800 placeholder-slate-400',
    badge: {
      COMPLETE:   isDark ? 'bg-emerald-900/60 text-emerald-300 border-emerald-700/50' : 'bg-emerald-50 text-emerald-700 border-emerald-200',
      PARTIAL:    isDark ? 'bg-amber-900/60 text-amber-300 border-amber-700/50'       : 'bg-amber-50 text-amber-700 border-amber-200',
      FAILED:     isDark ? 'bg-red-900/60 text-red-300 border-red-700/50'             : 'bg-red-50 text-red-700 border-red-200',
      PROCESSING: isDark ? 'bg-violet-900/60 text-violet-300 border-violet-700/50'    : 'bg-violet-50 text-violet-700 border-violet-200',
      PENDING:    isDark ? 'bg-slate-800 text-slate-400 border-slate-700'             : 'bg-slate-100 text-slate-500 border-slate-200',
    },
  }

  const vt = VAULT_TYPES.find(v => v.id === activeTab)

  const uploadComplete = uploadResult?.status === 'COMPLETE'
  const steps = [
    { n: 1, label: 'Select type', done: true },
    { n: 2, label: 'Drop file',   done: !!selectedFile },
    { n: 3, label: 'Upload',      done: uploadComplete },
  ]

  const { data: batchData } = useQuery({
    queryKey: ['vault-batches', activeTab],
    queryFn: () =>
      apiFetch(`/v1/cts/vault/upload/batches?vault_type=${activeTab}&limit=20`).then(r => r.json()),
    refetchInterval: 10_000,
  })

  const uploadMut = useMutation({
    mutationFn: async (file) => {
      const form = new FormData()
      form.append('file', file)
      const r = await apiFetch(`/v1/cts/vault/upload/${activeTab}`, { method: 'POST', body: form })
      return r.json()
    },
    onSuccess: (data) => {
      setUploadResult(data)
      setSelectedFile(null)
      qc.invalidateQueries({ queryKey: ['vault-batches', activeTab] })
    },
    onError: (err) => {
      setUploadResult({ status: 'FAILED', message: err.message, errors: [] })
    },
  })

  const handleDrop = useCallback((e) => {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file) { setSelectedFile(file); setUploadResult(null) }
  }, [])

  const handleFileChange = (e) => {
    const file = e.target.files[0]
    if (file) { setSelectedFile(file); setUploadResult(null) }
  }

  const handleDownloadErrors = async (batchId) => {
    setDownloadingBatch(batchId)
    try {
      const r = await apiFetch(`/v1/cts/vault/batches/${batchId}/errors.csv`)
      const blob = await r.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = `vault_errors_${batchId.slice(0, 8)}.csv`; a.click()
      URL.revokeObjectURL(url)
    } catch { /* handled gracefully */ }
    finally { setDownloadingBatch(null) }
  }

  const handleDownloadTemplate = async () => {
    const r = await apiFetch(`/v1/cts/vault/upload/template/${activeTab}`)
    const blob = await r.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = vt.filename; a.click()
    URL.revokeObjectURL(url)
  }

  const batches = batchData?.items || []

  const dropzoneStyle = dragOver
    ? isDark ? 'border-violet-400 bg-violet-900/20' : 'border-violet-400 bg-violet-50'
    : isDark ? 'border-white/20 hover:border-white/40' : 'border-slate-300 hover:border-slate-400'

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>

        {/* ── Page header ── */}
        <div className="mb-5">
          <h1 className={`text-lg font-semibold ${th.heading}`}>Vault Upload</h1>
          <p className={`text-sm mt-0.5 ${th.muted}`}>
            Seed or update vault data via CSV. ASTRA audits every change with history snapshots.
          </p>
        </div>

        {/* ── Vault type card selector ── */}
        <div className="grid grid-cols-5 gap-3 mb-5">
          {VAULT_TYPES.map(vtt => {
            const isActive = activeTab === vtt.id
            return (
              <button
                key={vtt.id}
                onClick={() => { setActiveTab(vtt.id); setSelectedFile(null); setUploadResult(null) }}
                className={`text-left rounded-xl border p-4 transition-all focus:outline-none ${
                  isActive
                    ? isDark
                      ? 'border-[#f5c842] bg-[#f5c842]/5'
                      : 'border-amber-400 bg-amber-50'
                    : isDark
                      ? 'border-white/8 bg-white/3 hover:border-white/18 hover:bg-white/5'
                      : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50'
                }`}
              >
                <div className="text-2xl mb-2.5">{vtt.icon}</div>
                <div className={`text-sm font-semibold mb-1 ${
                  isActive
                    ? isDark ? 'text-[#f5c842]' : 'text-amber-700'
                    : th.heading
                }`}>{vtt.label}</div>
                <div className={`text-[10px] leading-snug ${th.faint}`}>{vtt.shortDesc}</div>
              </button>
            )
          })}
        </div>

        {/* ── Selected type description strip ── */}
        <div className={`rounded-xl border p-4 mb-5 flex items-start gap-4 ${th.card}`}>
          <div className="flex-1">
            <div className={`text-sm font-semibold ${th.heading} mb-1`}>{vt.label}</div>
            <div className={`text-sm ${th.body}`}>{vt.desc}</div>
            <div className={`text-xs mt-2 ${th.faint}`}>
              Min. role: <span className="font-medium">{vt.minRole}</span>
              {' · '}Template: <code className="font-mono">{vt.filename}</code>
            </div>
          </div>
          <button
            onClick={handleDownloadTemplate}
            className={`shrink-0 flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg border transition-colors ${
              isDark
                ? 'border-white/15 text-slate-300 hover:border-white/30 hover:text-white'
                : 'border-slate-200 text-slate-600 hover:border-slate-300 hover:text-slate-900'
            }`}
          >
            <svg viewBox="0 0 16 16" fill="currentColor" className="w-3.5 h-3.5">
              <path d="M8 1a.75.75 0 0 1 .75.75v6.19l1.72-1.72a.75.75 0 1 1 1.06 1.06l-3 3a.75.75 0 0 1-1.06 0l-3-3a.75.75 0 1 1 1.06-1.06l1.72 1.72V1.75A.75.75 0 0 1 8 1zm-4 9a.75.75 0 0 1 .75.75v1.5c0 .138.112.25.25.25h6a.25.25 0 0 0 .25-.25v-1.5a.75.75 0 0 1 1.5 0v1.5A1.75 1.75 0 0 1 11 13.5H5A1.75 1.75 0 0 1 3.25 11.75v-1.5A.75.75 0 0 1 4 10z" />
            </svg>
            Download template
          </button>
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">

          {/* ── Left: uploader ── */}
          <div className="flex flex-col gap-4">

            {/* Step progress indicator */}
            <div className="flex items-center gap-2">
              {steps.map((s, i) => (
                <div key={s.n} className="flex items-center flex-1 gap-2">
                  <div className="flex items-center gap-1.5 shrink-0">
                    <div className={`w-5 h-5 rounded-full text-[10px] font-bold flex items-center justify-center shrink-0 transition-colors ${
                      s.done
                        ? 'bg-emerald-500 text-white'
                        : isDark ? 'bg-white/10 text-slate-400' : 'bg-slate-100 text-slate-500'
                    }`}>
                      {s.done ? '✓' : s.n}
                    </div>
                    <span className={`text-xs whitespace-nowrap ${s.done ? 'text-emerald-500 font-medium' : th.muted}`}>
                      {s.label}
                    </span>
                  </div>
                  {i < steps.length - 1 && (
                    <div className={`flex-1 h-px ${isDark ? 'bg-white/10' : 'bg-slate-200'}`} />
                  )}
                </div>
              ))}
            </div>

            {/* Drop zone */}
            <div
              className={`rounded-xl border-2 border-dashed transition-all cursor-pointer ${dropzoneStyle}`}
              style={{ minHeight: 160 }}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
            >
              <div className="flex flex-col items-center justify-center h-full py-10 select-none">
                {selectedFile ? (
                  <>
                    <div className={`w-10 h-10 rounded-full flex items-center justify-center mb-2.5 ${
                      isDark ? 'bg-emerald-900/40' : 'bg-emerald-50'
                    }`}>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                        className="w-5 h-5 text-emerald-500">
                        <path d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    </div>
                    <div className={`text-sm font-semibold ${th.heading}`}>{selectedFile.name}</div>
                    <div className={`text-xs mt-1 ${th.muted}`}>
                      {(selectedFile.size / 1024).toFixed(1)} KB · Click to replace
                    </div>
                  </>
                ) : (
                  <>
                    <div className={`w-10 h-10 rounded-full flex items-center justify-center mb-2.5 ${
                      isDark ? 'bg-white/8' : 'bg-slate-100'
                    }`}>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                        className={`w-5 h-5 ${th.faint}`}>
                        <path d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    </div>
                    <div className={`text-sm font-medium ${th.body}`}>Drop CSV here or click to browse</div>
                    <div className={`text-xs mt-1 ${th.faint}`}>Max 20 MB · UTF-8 CSV only</div>
                  </>
                )}
              </div>
              <input ref={fileInputRef} type="file" accept=".csv,text/csv" className="hidden" onChange={handleFileChange} />
            </div>

            {/* Upload button */}
            <button
              disabled={!selectedFile || uploadMut.isPending}
              onClick={() => selectedFile && uploadMut.mutate(selectedFile)}
              className={`w-full py-2.5 rounded-lg text-sm font-semibold transition-colors ${
                selectedFile && !uploadMut.isPending
                  ? 'bg-[#f5c842] hover:bg-[#f0c235] text-[#03061a]'
                  : isDark ? 'bg-white/5 text-slate-500 cursor-not-allowed' : 'bg-slate-100 text-slate-400 cursor-not-allowed'
              }`}
            >
              {uploadMut.isPending ? 'Uploading…' : 'Upload & Process'}
            </button>

            {/* Result panel */}
            {uploadResult && (
              <div className={`rounded-xl border p-4 ${th.card}`}>
                <div className="flex items-center gap-2 mb-3">
                  <div className={`w-2 h-2 rounded-full ${STATUS_STYLES[uploadResult.status]?.dot || 'bg-slate-400'}`} />
                  <span className={`text-sm font-semibold ${th.heading}`}>
                    {STATUS_STYLES[uploadResult.status]?.label || uploadResult.status}
                  </span>
                </div>
                <p className={`text-sm ${th.body}`}>{uploadResult.message}</p>
                {uploadResult.batch_id && (
                  <p className={`text-xs mt-1 font-mono ${th.faint}`}>Batch: {uploadResult.batch_id}</p>
                )}
                {uploadResult.errors?.length > 0 && (
                  <div className="mt-3">
                    <div className={`text-xs font-medium mb-1.5 ${th.muted}`}>Row errors</div>
                    <div className="space-y-1 max-h-36 overflow-y-auto">
                      {uploadResult.errors.map((e, i) => (
                        <div key={i} className={`text-xs px-2.5 py-1.5 rounded ${
                          isDark ? 'bg-red-900/30 text-red-300' : 'bg-red-50 text-red-700'
                        }`}>
                          Row {e.row}: {e.error}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* ── Right: batch history ── */}
          <div className={`rounded-xl border ${th.card}`}>
            <div className={`px-4 py-3 border-b ${th.divider} flex items-center justify-between`}>
              <span className={`text-sm font-semibold ${th.heading}`}>Upload History</span>
              <span className={`text-xs ${th.faint}`}>{vt.label} · last 20</span>
            </div>
            {batches.length === 0 ? (
              <div className={`px-4 py-10 text-center text-sm ${th.faint}`}>
                No uploads yet for {vt.label}
              </div>
            ) : (
              <div className="divide-y divide-white/4">
                {batches.map(b => (
                  <div key={b.batch_id} className={`px-4 py-3 transition-colors ${th.row}`}>
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <div className={`text-sm truncate font-medium ${th.body}`}>{b.filename || '(no filename)'}</div>
                        <div className={`text-xs mt-0.5 ${th.faint}`}>{b.uploaded_by} · {b.upload_channel}</div>
                      </div>
                      <span className={`text-xs font-semibold px-2 py-0.5 rounded border shrink-0 ${th.badge[b.status] || th.badge.PENDING}`}>
                        {STATUS_STYLES[b.status]?.label || b.status}
                      </span>
                    </div>
                    <div className={`flex flex-wrap gap-4 mt-1.5 text-xs ${th.faint}`}>
                      <span>
                        <span className="text-emerald-400 font-medium">{b.rows_processed ?? 0}</span>
                        {' / '}
                        <span>{b.rows_total ?? '?'}</span>
                        {' rows'}
                      </span>
                      {(b.rows_failed ?? 0) > 0 && (
                        <span className="text-red-400 font-medium">{b.rows_failed} failed</span>
                      )}
                      {b.has_error_file && (
                        <button
                          onClick={() => handleDownloadErrors(b.batch_id)}
                          disabled={downloadingBatch === b.batch_id}
                          className={`text-red-400 underline underline-offset-2 decoration-dashed ${
                            downloadingBatch === b.batch_id ? 'opacity-50 cursor-wait' : 'hover:text-red-300 cursor-pointer'
                          }`}
                        >
                          {downloadingBatch === b.batch_id ? 'downloading…' : '↓ errors.csv'}
                        </button>
                      )}
                      <span>{new Date(b.created_at).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false })}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* ── Leaf lifecycle reference ── */}
        <div className={`mt-5 rounded-xl border p-4 ${th.card}`}>
          <div className={`text-sm font-semibold mb-3 ${th.heading}`}>
            Cheque leaf lifecycle — ASTRA writes these automatically
          </div>
          <div className="flex flex-wrap gap-2">
            {LEAF_LIFECYCLE.map(item => (
              <div key={item.s} className={`rounded border px-3 py-2 text-xs ${
                isDark ? 'border-white/8 bg-white/3' : 'border-slate-200 bg-slate-50'
              }`}>
                <div className={`font-semibold font-mono ${item.color}`}>{item.s}</div>
                <div className={`mt-0.5 ${th.faint}`}>
                  <span className="font-medium">{item.who}</span> · {item.note}
                </div>
              </div>
            ))}
          </div>
        </div>

      </div>
    </AppShell>
  )
}

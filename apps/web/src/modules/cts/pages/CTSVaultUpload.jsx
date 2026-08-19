import { useState, useRef, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'

const VAULT_TYPES = [
  {
    id: 'CHEQUE_BOOK',
    label: 'Cheque Book',
    icon: '📒',
    desc: 'Register issued cheque books. Each row auto-expands all leaves in the series to ACTIVE.',
    filename: 'cheque_book_upload.csv',
    minRole: 'bank_it_admin',
  },
  {
    id: 'LEAF_STATUS',
    label: 'Leaf Status',
    icon: '🚫',
    desc: 'Report exception events — STOPPED, LOST, STOLEN, CANCELLED. ASTRA writes clearing events automatically.',
    filename: 'cheque_leaf_status_upload.csv',
    minRole: 'ops_manager',
  },
  {
    id: 'ACCOUNT_DETAIL',
    label: 'Account Holders',
    icon: '👤',
    desc: 'Account holder names and roles for joint/corporate accounts. One row per holder per account.',
    filename: 'account_vault_detail_upload.csv',
    minRole: 'bank_it_admin',
  },
  {
    id: 'SIGNATURE',
    label: 'Mandate Rules',
    icon: '✍️',
    desc: 'Signatory mandate rules (ANY_ONE / ALL_REQUIRED / QUORUM_N) per account. Specimen images uploaded separately.',
    filename: 'signatory_upload.csv',
    minRole: 'bank_it_admin',
  },
  {
    id: 'PPS',
    label: 'Positive Pay',
    icon: '✅',
    desc: 'Pre-register cheques for Positive Pay System (RBI mandate). One row per cheque: account, cheque number, date, amount, payee.',
    filename: 'pps_upload.csv',
    minRole: 'ops_manager',
  },
]

const STATUS_STYLES = {
  COMPLETE: { dot: 'bg-emerald-400', text: 'text-emerald-400', label: 'Complete' },
  PARTIAL:  { dot: 'bg-amber-400',   text: 'text-amber-400',   label: 'Partial'  },
  FAILED:   { dot: 'bg-red-400',     text: 'text-red-400',     label: 'Failed'   },
  PROCESSING:{ dot: 'bg-violet-400', text: 'text-violet-400',  label: 'Processing'},
  PENDING:  { dot: 'bg-slate-400',   text: 'text-slate-400',   label: 'Pending'  },
}

async function apiFetch(url, opts = {}) {
  const r = await fetch(url, { credentials: 'include', ...opts })
  if (!r.ok) {
    const body = await r.json().catch(() => ({}))
    throw new Error(body?.detail?.message || `HTTP ${r.status}`)
  }
  return r
}

export default function CTSVaultUpload() {
  const { isDark } = useTheme()
  const qc = useQueryClient()
  const [activeTab, setActiveTab] = useState('CHEQUE_BOOK')
  const [dragOver, setDragOver] = useState(false)
  const [selectedFile, setSelectedFile] = useState(null)
  const [uploadResult, setUploadResult] = useState(null)
  const [downloadingBatch, setDownloadingBatch] = useState(null)
  const fileInputRef = useRef(null)

  const th = {
    page:    isDark ? 'bg-navy-950'        : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'         : 'text-slate-900',
    body:    isDark ? 'text-slate-300'     : 'text-slate-700',
    muted:   isDark ? 'text-slate-400'     : 'text-slate-500',
    faint:   isDark ? 'text-slate-500'     : 'text-slate-400',
    divider: isDark ? 'border-white/8'     : 'border-slate-200',
    tab:     isDark ? 'border-white/8 bg-navy-900/50' : 'border-slate-200 bg-slate-100/60',
    tabActive: isDark ? 'bg-navy-900 border-violet-500 text-white' : 'bg-white border-violet-500 text-slate-900',
    tabInactive: isDark ? 'text-slate-400 hover:text-slate-200' : 'text-slate-500 hover:text-slate-700',
    dropzone: dragOver
      ? isDark ? 'border-violet-400 bg-violet-900/20' : 'border-violet-400 bg-violet-50'
      : isDark ? 'border-white/20 hover:border-white/40' : 'border-slate-300 hover:border-slate-400',
    row:     isDark ? 'border-white/4 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
    badge:   {
      COMPLETE:   isDark ? 'bg-emerald-900/60 text-emerald-300 border-emerald-700/50' : 'bg-emerald-50 text-emerald-700 border-emerald-200',
      PARTIAL:    isDark ? 'bg-amber-900/60 text-amber-300 border-amber-700/50'       : 'bg-amber-50 text-amber-700 border-amber-200',
      FAILED:     isDark ? 'bg-red-900/60 text-red-300 border-red-700/50'             : 'bg-red-50 text-red-700 border-red-200',
      PROCESSING: isDark ? 'bg-violet-900/60 text-violet-300 border-violet-700/50'    : 'bg-violet-50 text-violet-700 border-violet-200',
      PENDING:    isDark ? 'bg-slate-800 text-slate-400 border-slate-700'             : 'bg-slate-100 text-slate-500 border-slate-200',
    },
  }

  const vt = VAULT_TYPES.find(v => v.id === activeTab)

  // Batch history
  const { data: batchData } = useQuery({
    queryKey: ['vault-batches', activeTab],
    queryFn: () =>
      apiFetch(`/v1/cts/vault/upload/batches?vault_type=${activeTab}&limit=20`)
        .then(r => r.json()),
    refetchInterval: 10_000,
  })

  // Upload mutation
  const uploadMut = useMutation({
    mutationFn: async (file) => {
      const form = new FormData()
      form.append('file', file)
      const r = await apiFetch(`/v1/cts/vault/upload/${activeTab}`, {
        method: 'POST',
        body: form,
      })
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
      a.href = url
      a.download = `vault_errors_${batchId.slice(0, 8)}.csv`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      console.error('vault error download failed', err)
    } finally {
      setDownloadingBatch(null)
    }
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

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>

        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>Vault Upload</h1>
            <p className={`text-sm mt-0.5 ${th.muted}`}>
              Seed or update vault data via CSV. ASTRA audits every change with history snapshots.
            </p>
          </div>
        </div>

        {/* Vault type tabs */}
        <div className={`flex gap-1 border-b ${th.divider} mb-5`}>
          {VAULT_TYPES.map(vtt => (
            <button
              key={vtt.id}
              onClick={() => { setActiveTab(vtt.id); setSelectedFile(null); setUploadResult(null) }}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px ${
                activeTab === vtt.id
                  ? `border-violet-500 ${isDark ? 'text-white' : 'text-slate-900'}`
                  : `border-transparent ${th.tabInactive}`
              }`}
            >
              {vtt.icon} {vtt.label}
            </button>
          ))}
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">

          {/* Left: uploader */}
          <div className="flex flex-col gap-4">

            {/* Vault type description */}
            <div className={`rounded-lg border p-4 ${th.card}`}>
              <div className="flex items-start gap-3">
                <span className="text-2xl">{vt.icon}</span>
                <div>
                  <div className={`font-medium ${th.heading}`}>{vt.label}</div>
                  <div className={`text-sm mt-1 ${th.body}`}>{vt.desc}</div>
                  <div className={`text-xs mt-2 ${th.faint}`}>
                    Min. role: <span className="font-medium">{vt.minRole}</span>
                    {' · '}Template: <code className="font-mono">{vt.filename}</code>
                  </div>
                </div>
              </div>
              <button
                onClick={handleDownloadTemplate}
                className="mt-3 text-sm text-violet-400 hover:text-violet-300 font-medium flex items-center gap-1"
              >
                <svg viewBox="0 0 16 16" fill="currentColor" className="w-4 h-4">
                  <path d="M8 1a.75.75 0 0 1 .75.75v6.19l1.72-1.72a.75.75 0 1 1 1.06 1.06l-3 3a.75.75 0 0 1-1.06 0l-3-3a.75.75 0 1 1 1.06-1.06l1.72 1.72V1.75A.75.75 0 0 1 8 1zm-4 9a.75.75 0 0 1 .75.75v1.5c0 .138.112.25.25.25h6a.25.25 0 0 0 .25-.25v-1.5a.75.75 0 0 1 1.5 0v1.5A1.75 1.75 0 0 1 11 13.5H5A1.75 1.75 0 0 1 3.25 11.75v-1.5A.75.75 0 0 1 4 10z"/>
                </svg>
                Download CSV template
              </button>
            </div>

            {/* Drop zone */}
            <div
              className={`rounded-lg border-2 border-dashed transition-colors cursor-pointer ${th.dropzone}`}
              style={{ minHeight: 160 }}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
            >
              <div className="flex flex-col items-center justify-center h-full py-10 select-none">
                {selectedFile ? (
                  <>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"
                      className="w-8 h-8 text-violet-400 mb-2">
                      <path d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                    <div className={`text-sm font-medium ${th.heading}`}>{selectedFile.name}</div>
                    <div className={`text-xs mt-1 ${th.muted}`}>
                      {(selectedFile.size / 1024).toFixed(1)} KB · Click to replace
                    </div>
                  </>
                ) : (
                  <>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"
                      className={`w-8 h-8 mb-2 ${th.faint}`}>
                      <path d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                    <div className={`text-sm font-medium ${th.body}`}>Drop CSV here or click to browse</div>
                    <div className={`text-xs mt-1 ${th.faint}`}>Max 20 MB · UTF-8 CSV only</div>
                  </>
                )}
              </div>
              <input
                ref={fileInputRef}
                type="file"
                accept=".csv,text/csv"
                className="hidden"
                onChange={handleFileChange}
              />
            </div>

            {/* Upload button */}
            <button
              disabled={!selectedFile || uploadMut.isPending}
              onClick={() => selectedFile && uploadMut.mutate(selectedFile)}
              className={`w-full py-2.5 rounded-lg text-sm font-semibold transition-colors
                ${selectedFile && !uploadMut.isPending
                  ? 'bg-violet-600 hover:bg-violet-500 text-white'
                  : isDark ? 'bg-white/5 text-slate-500 cursor-not-allowed' : 'bg-slate-100 text-slate-400 cursor-not-allowed'
                }`}
            >
              {uploadMut.isPending ? 'Uploading…' : 'Upload & Process'}
            </button>

            {/* Result panel */}
            {uploadResult && (
              <div className={`rounded-lg border p-4 ${th.card}`}>
                <div className="flex items-center gap-2 mb-3">
                  <div className={`w-2 h-2 rounded-full ${STATUS_STYLES[uploadResult.status]?.dot || 'bg-slate-400'}`} />
                  <span className={`text-sm font-medium ${th.heading}`}>
                    {STATUS_STYLES[uploadResult.status]?.label || uploadResult.status}
                  </span>
                </div>
                <p className={`text-sm ${th.body}`}>{uploadResult.message}</p>
                {uploadResult.batch_id && (
                  <p className={`text-xs mt-1 font-mono ${th.faint}`}>
                    Batch: {uploadResult.batch_id}
                  </p>
                )}
                {uploadResult.errors?.length > 0 && (
                  <div className="mt-3">
                    <div className={`text-xs font-medium mb-1 ${th.muted}`}>Row errors</div>
                    <div className="space-y-1 max-h-36 overflow-y-auto">
                      {uploadResult.errors.map((e, i) => (
                        <div key={i} className={`text-xs px-2 py-1 rounded ${
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

          {/* Right: batch history */}
          <div className={`rounded-lg border ${th.card}`}>
            <div className={`px-4 py-3 border-b ${th.divider} flex items-center justify-between`}>
              <span className={`text-sm font-medium ${th.heading}`}>Upload History</span>
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
                        <div className={`text-sm truncate ${th.body}`}>
                          {b.filename || '(no filename)'}
                        </div>
                        <div className={`text-xs mt-0.5 ${th.faint}`}>
                          {b.uploaded_by} · {b.upload_channel}
                        </div>
                      </div>
                      <span className={`text-xs font-medium px-2 py-0.5 rounded border shrink-0 ${th.badge[b.status] || th.badge.PENDING}`}>
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
                            downloadingBatch === b.batch_id
                              ? 'opacity-50 cursor-wait'
                              : 'hover:text-red-300 cursor-pointer'
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

        {/* Lifecycle reference */}
        <div className={`mt-6 rounded-lg border p-4 ${th.card}`}>
          <div className={`text-sm font-medium mb-3 ${th.heading}`}>
            Cheque leaf lifecycle — ASTRA writes these automatically
          </div>
          <div className="flex flex-wrap gap-2">
            {[
              { s: 'ACTIVE',     who: 'ASTRA', note: 'auto-expanded from book upload', color: 'text-emerald-400' },
              { s: 'PRESENTED',  who: 'ASTRA', note: 'workflow start',                  color: 'text-violet-400' },
              { s: 'PAID',       who: 'ASTRA', note: 'ngch_filer → CONFIRM',            color: 'text-emerald-400' },
              { s: 'RETURNED',   who: 'ASTRA', note: 'ngch_filer → RETURN',             color: 'text-amber-400' },
              { s: 'EXPIRED',    who: 'ASTRA', note: 'daily sweep > 3 months',          color: 'text-slate-400' },
              { s: 'STOPPED',    who: 'Bank',  note: 'stop payment instruction',        color: 'text-amber-400' },
              { s: 'LOST',       who: 'Bank',  note: 'customer reports loss',           color: 'text-red-400' },
              { s: 'STOLEN',     who: 'Bank',  note: 'customer/police report',          color: 'text-red-400' },
              { s: 'CANCELLED',  who: 'Bank',  note: 'customer cancels unused leaf',    color: 'text-red-400' },
            ].map(item => (
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

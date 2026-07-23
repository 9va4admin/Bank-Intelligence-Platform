import { useEffect, useRef, useState } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'

const MAX = 5

async function fetchPreview(file) {
  const fd = new FormData()
  fd.append('file', file)
  const r = await fetch('/v1/cts/demo/cloud-extract/preview', {
    method: 'POST',
    credentials: 'include',
    headers: { 'X-CSRF-Token': sessionStorage.getItem('astra-csrf') || '' },
    body: fd,
  })
  if (!r.ok) throw new Error(`preview HTTP ${r.status}`)
  const blob = await r.blob()
  return URL.createObjectURL(blob)
}

async function extractSig(file) {
  const fd = new FormData()
  fd.append('file', file)
  const r = await fetch('/v1/cts/demo/cloud-extract?model=yolov8-sig-only', {
    method: 'POST',
    credentials: 'include',
    headers: { 'X-CSRF-Token': sessionStorage.getItem('astra-csrf') || '' },
    body: fd,
  })
  if (!r.ok) {
    const d = await r.json().catch(() => ({}))
    throw new Error(d.detail || `HTTP ${r.status}`)
  }
  return r.json()
}

function ResultCard({ file, isDark }) {
  const th = {
    card:    isDark ? 'bg-navy-900 border border-white/8'   : 'bg-white border border-slate-200',
    fname:   isDark ? 'text-slate-300 font-medium'          : 'text-slate-700 font-medium',
    label:   isDark ? 'text-slate-500 text-[10px] uppercase tracking-widest' : 'text-slate-400 text-[10px] uppercase tracking-widest',
    divider: isDark ? 'border-white/8' : 'border-slate-100',
    nosig:   'text-red-400 font-bold text-sm text-center py-8',
    spin:    isDark ? 'text-slate-500 text-xs text-center py-8' : 'text-slate-400 text-xs text-center py-8',
    err:     'text-red-400 text-xs text-center py-6',
  }

  // Original image — fetched via /preview so TIFF/BMP etc. are converted to PNG
  const [origUrl, setOrigUrl] = useState(null)
  useEffect(() => {
    let objectUrl = null
    fetchPreview(file)
      .then(url => { objectUrl = url; setOrigUrl(url) })
      .catch(() => {})
    return () => { if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [file])

  // Extraction result
  const [state, setState] = useState('loading')
  const [b64,   setB64]   = useState(null)
  const [errMsg, setErr]  = useState('')
  const ran = useRef(false)

  if (!ran.current) {
    ran.current = true
    extractSig(file)
      .then(d => {
        if (d.signature_present && d.signature_crops?.length) {
          setB64(d.signature_crops[0]); setState('sig')
        } else {
          setState('nosig')
        }
      })
      .catch(e => { setErr(e.message); setState('error') })
  }

  return (
    <div className={`rounded-xl p-3 flex-shrink-0 w-80 ${th.card}`}>

      {/* Filename */}
      <p className={`text-xs truncate mb-3 ${th.fname}`} title={file.name}>{file.name}</p>

      {/* Original cheque — reduced size */}
      <p className={`mb-1 ${th.label}`}>Original</p>
      {origUrl
        ? <img src={origUrl} alt="original" className="w-full rounded object-contain bg-white" style={{ maxHeight: 90 }} />
        : <div className="w-full h-16 rounded bg-slate-700/20 animate-pulse" />
      }

      {/* Divider */}
      <div className={`my-3 border-t ${th.divider}`} />

      {/* Extracted signature */}
      <p className={`mb-1 ${th.label}`}>Extracted Signature</p>
      {state === 'loading' && <p className={th.spin}>processing…</p>}
      {state === 'sig'     && (
        <img
          src={`data:image/png;base64,${b64}`}
          alt="signature"
          className="w-full rounded border border-slate-300 bg-white object-contain"
          style={{ maxHeight: 100 }}
        />
      )}
      {state === 'nosig'   && <p className={th.nosig}>No-Sign-Present</p>}
      {state === 'error'   && <p className={th.err}>{errMsg}</p>}

    </div>
  )
}

export default function CTSSigBatchTest() {
  const { isDark } = useTheme()
  usePageHeader({
    title: 'Signature Batch Test',
    subtitle: 'Upload up to 5 cheques — compares original with extracted signature',
  })

  const [files, setFiles] = useState([])
  const [run,   setRun]   = useState(false)
  const inputRef = useRef()

  const th = {
    page:  isDark ? 'bg-navy-950' : 'bg-slate-50',
    body:  isDark ? 'text-slate-300' : 'text-slate-700',
    drop:  isDark
      ? 'border-white/10 hover:border-violet-500 bg-white/2'
      : 'border-slate-300 hover:border-violet-500 bg-slate-50',
    fname: isDark ? 'text-emerald-400' : 'text-emerald-600',
  }

  function pick(incoming) {
    const imgs = Array.from(incoming).filter(f => f.type.startsWith('image/')).slice(0, MAX)
    setFiles(imgs)
    setRun(false)
  }

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>

        {/* Drop zone */}
        <div
          className={`border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-colors ${th.drop}`}
          onClick={() => inputRef.current?.click()}
          onDragOver={e => e.preventDefault()}
          onDrop={e => { e.preventDefault(); pick(e.dataTransfer.files) }}
        >
          <p className={`text-sm ${th.body}`}>
            Click or drag &amp; drop up to {MAX} cheque images (jpg / png / tif)
          </p>
          {files.length > 0 && (
            <ul className="mt-3 space-y-0.5">
              {files.map(f => (
                <li key={f.name} className={`text-xs ${th.fname}`}>✓ {f.name}</li>
              ))}
            </ul>
          )}
          <input ref={inputRef} type="file" accept="image/*" multiple className="hidden"
            onChange={e => pick(e.target.files)} />
        </div>

        {/* Run button */}
        <button
          disabled={files.length === 0}
          onClick={() => setRun(true)}
          className="mt-4 px-6 py-2 bg-violet-600 hover:bg-violet-500 disabled:bg-slate-700 disabled:text-slate-500 text-white text-sm rounded-lg transition-colors"
        >
          ▶ Extract Signatures
        </button>

        {/* Results — one card per cheque */}
        {run && files.length > 0 && (
          <div className="flex flex-wrap gap-5 mt-6">
            {files.map(f => (
              <ResultCard key={f.name + f.size} file={f} isDark={isDark} />
            ))}
          </div>
        )}

      </div>
    </AppShell>
  )
}

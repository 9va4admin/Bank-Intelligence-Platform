import { useRef, useState } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'

const MAX = 5

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
    card:   isDark ? 'bg-navy-900 border border-white/8' : 'bg-white border border-slate-200',
    fname:  isDark ? 'text-slate-400' : 'text-slate-500',
    nosig:  'text-red-400 font-bold text-sm text-center py-10',
    spin:   isDark ? 'text-slate-500 text-xs text-center py-10' : 'text-slate-400 text-xs text-center py-10',
    err:    'text-red-400 text-xs text-center py-6',
  }

  const [state, setState] = useState('idle') // idle | loading | sig | nosig | error
  const [b64, setB64]     = useState(null)
  const [errMsg, setErr]  = useState('')
  const ran = useRef(false)

  if (!ran.current) {
    ran.current = true
    setState('loading')
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
    <div className={`rounded-lg p-3 w-52 flex-shrink-0 ${th.card}`}>
      <p className={`text-[10px] truncate mb-2 ${th.fname}`} title={file.name}>{file.name}</p>
      {state === 'loading' && <p className={th.spin}>processing…</p>}
      {state === 'sig'     && <img src={`data:image/png;base64,${b64}`} className="w-full rounded border border-slate-300 bg-white" alt="sig" />}
      {state === 'nosig'   && <p className={th.nosig}>No-Sign-Present</p>}
      {state === 'error'   && <p className={th.err}>{errMsg}</p>}
    </div>
  )
}

export default function CTSSigBatchTest() {
  const { isDark } = useTheme()
  usePageHeader({ title: 'Signature Batch Test', subtitle: 'Upload up to 5 cheques — shows denoised signature crop or No-Sign-Present' })

  const [files, setFiles]   = useState([])
  const [run,   setRun]     = useState(false)
  const inputRef = useRef()

  const th = {
    page:    isDark ? 'bg-navy-950' : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'     : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    drop:    isDark
      ? 'border-white/10 hover:border-violet-500 bg-white/2'
      : 'border-slate-300 hover:border-violet-500 bg-slate-50',
    fname:   isDark ? 'text-emerald-400' : 'text-emerald-600',
  }

  function pick(incoming) {
    const imgs = Array.from(incoming).filter(f => f.type.startsWith('image/')).slice(0, MAX)
    setFiles(imgs)
    setRun(false)
  }

  function onDrop(e) {
    e.preventDefault()
    pick(e.dataTransfer.files)
  }

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>

        {/* Drop zone */}
        <div
          className={`border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-colors ${th.drop}`}
          onClick={() => inputRef.current?.click()}
          onDragOver={e => e.preventDefault()}
          onDrop={onDrop}
        >
          <p className={`text-sm ${th.body}`}>Click or drag &amp; drop up to {MAX} cheque images (jpg / png / tif)</p>
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

        {/* Results grid */}
        {run && files.length > 0 && (
          <div className="flex flex-wrap gap-4 mt-6">
            {files.map(f => (
              <ResultCard key={f.name + f.size} file={f} isDark={isDark} />
            ))}
          </div>
        )}

      </div>
    </AppShell>
  )
}

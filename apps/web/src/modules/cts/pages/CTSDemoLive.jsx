/**
 * CTSDemoLive — Live 5-Bank Docker Demo
 *
 * Connects to local Docker containers (ports 8001-8005).
 * Falls back to embedded simulation data when Docker is not running.
 *
 * Key feature: Side-by-side OCR vs Vision LLM panel for Cat C/D/E cheques
 * — the centrepiece demo showing WHY Vision LLM adds value beyond OCR.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'

// ── Bank configuration ────────────────────────────────────────────────────────

const BANKS = [
  { id: 'srcb', name: 'Saraswat Co-op Bank', short: 'SRCB', type: 'SB',
    port: 8001, primary: '#1a3a5c', accent: '#c9a84c' },
  { id: 'vvsb', name: 'Vasai Vikas Sahakari Bank', short: 'VVSB', type: 'SMB',
    port: 8002, primary: '#1e3a1e', accent: '#6db33f' },
  { id: 'kjsb', name: 'Kalyan Janata Sahakari Bank', short: 'KJSB', type: 'SMB',
    port: 8003, primary: '#2a1a3a', accent: '#9b59b6' },
  { id: 'bcbk', name: 'Bharat Co-operative Bank', short: 'BCBK', type: 'SMB',
    port: 8004, primary: '#3a1a1a', accent: '#e74c3c' },
  { id: 'ducb', name: 'Deccan Urban Co-op Bank', short: 'DUCB', type: 'SMB',
    port: 8005, primary: '#1a2a3a', accent: '#3498db' },
]

// ── Category metadata ─────────────────────────────────────────────────────────

const CAT_META = {
  A: { label: 'Clean STP',          color: 'emerald', outcome: 'STP_CONFIRM',                    icon: '✓' },
  B: { label: 'Amount Mismatch',    color: 'amber',   outcome: 'STP_RETURN (OCR)',                icon: '≠' },
  C: { label: 'Overwrite Fraud',    color: 'red',     outcome: 'STP_RETURN (Vision LLM)',         icon: '!' },
  D: { label: 'Date Tamper',        color: 'red',     outcome: 'STP_RETURN (Vision LLM)',         icon: '!' },
  E: { label: 'CANCELLED Stamp',    color: 'red',     outcome: 'STP_RETURN (Vision LLM)',         icon: '!' },
  F: { label: 'Stale Cheque',       color: 'orange',  outcome: 'STP_RETURN (Rule)',               icon: '⌛' },
  G: { label: 'Duplicate',          color: 'orange',  outcome: 'STP_RETURN (Registry)',           icon: '⊕' },
  H: { label: 'Image Quality',      color: 'yellow',  outcome: 'STP_RETURN (CTS)',                icon: '⚠' },
  I: { label: 'Sig Mismatch',       color: 'amber',   outcome: 'HUMAN_REVIEW',                    icon: '✍' },
  J: { label: 'Stop Payment',       color: 'red',     outcome: 'STP_RETURN (CBS)',                icon: '⊘' },
  K: { label: 'Insuff Funds',       color: 'orange',  outcome: 'STP_RETURN (CBS)',                icon: '$' },
  L: { label: 'PPS Mismatch',       color: 'amber',   outcome: 'STP_RETURN (PPS)',                icon: '≠' },
  M: { label: 'Acct Frozen',        color: 'red',     outcome: 'STP_RETURN (CBS)',                icon: '🔒' },
}

// ── Vision LLM demo value labels ─────────────────────────────────────────────

const VISION_CATCHES = new Set(['C', 'D', 'E'])

// ── Embedded fallback demo data (50 cheques) ──────────────────────────────────

function buildFallbackCheques() {
  const banks = BANKS.map(b => b.id)
  const draweeRing = { srcb: 'vvsb', vvsb: 'kjsb', kjsb: 'bcbk', bcbk: 'ducb', ducb: 'srcb' }
  const cats = ['A','A','B','C','D','E','I','J','L','K']
  const names = [
    ['Ramesh Kumar Sharma','Priya Subramaniam','Mohammed Irfan Shaikh','Anita Devi Rathore',
     'Cyrus Eruch Irani','Sunita Ramesh Patil','Gurpreet Singh Bhatia','Fatima Bi Hussain Ansari',
     'Thomas Varghese Mathew','Meena Jayshree Patel'],
    ['Arvind Kulkarni','Sujata Deshpande','Rashid Ahmed Khan','Lakshmi Iyer',
     'Jaya Shankar Hegde','Bipasha Mukherjee','Manjit Kaur Grewal','Abdul Razzak Qureshi',
     'Maria DSouza','Hemant Desai'],
    ['Vikram Yadav','Pushpa Gowda','Salim Siddiqui','Kamala Pillai',
     'Boman Mistry','Deepa Naik','Harinder Sandhu','Shabana Ansari',
     'George Fernandes','Savita Joshi'],
    ['Suresh Jadhav','Radha Menon','Imran Sheikh','Padmavathi Subramaniam',
     'Noshir Contractor','Rita Banerjee','Kulwant Dhillon','Nasreen Mirza',
     'Lino Rodrigues','Geeta Shekhawat'],
    ['Mahesh Kale','Sumitra Krishnan','Wasim Patel','Champa Mishra',
     'Pervez Wadia','Aparajita Das','Navdeep Randhawa','Zainab Shaikh',
     'Mathew Thomas','Rajendra Mehta'],
  ]
  const amounts = [120000,85000,250000,180000,320000,55000,420000,95000,150000,67000]
  const payees = ['M/s Sunrise Trading Co.','Global Tech Solutions Pvt Ltd',
    'Shree Ram General Stores','Aditya Enterprises','National Import Export Co.']

  const cheques = []
  for (let bi = 0; bi < banks.length; bi++) {
    const bankId = banks[bi]
    const draweeId = draweeRing[bankId]
    for (let ci = 0; ci < 10; ci++) {
      const cat = cats[ci]
      const amount = amounts[ci]
      const fraudAmt = Math.round(amount * 4.2)
      cheques.push({
        cheque_id: `CHQ-${bankId.toUpperCase()}-C${String(ci+1).padStart(3,'0')}-${String(bi*10+ci+1).padStart(3,'0')}`,
        customer_id: `${bankId.toUpperCase()}-C${String(ci+1).padStart(3,'0')}`,
        customer_name: names[bi][ci],
        serial_number: String(100000 + bi * 10 + ci),
        cheque_date: ci === 5 ? '12-01-2026' : '12-05-2026',
        payee_name: payees[(bi + ci) % payees.length],
        amount_figures: cat === 'C' ? fraudAmt : amount,
        amount_words: 'One Lakh Twenty Thousand Only',
        presentee_bank_id: bankId,
        drawee_bank_id: draweeId,
        category: cat,
        category_description: CAT_META[cat]?.label || cat,
        ocr_vs_vision: cat === 'C' ? {
          ocr_reads_fraud_amount: fraudAmt,
          original_amount_display: `Rs. ${amount.toLocaleString('en-IN')}`,
          fraud_amount_display: `Rs. ${fraudAmt.toLocaleString('en-IN')}`,
        } : cat === 'D' ? {
          original_year: '2024', new_year: '2026',
          orig_date: '12-01-2024',
        } : {},
      })
    }
  }
  return cheques
}

const FALLBACK_CHEQUES = buildFallbackCheques()

// ── API helpers ───────────────────────────────────────────────────────────────

async function fetchWithTimeout(url, opts = {}, timeoutMs = 3000) {
  const ctrl = new AbortController()
  const tid = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const r = await fetch(url, { ...opts, signal: ctrl.signal })
    clearTimeout(tid)
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    return await r.json()
  } catch (e) {
    clearTimeout(tid)
    throw e
  }
}

async function processChequeLive(bankPort, chequeId) {
  return fetchWithTimeout(`http://localhost:${bankPort}/v1/pipeline/process`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ cheque_id: chequeId, simulate_speed_ms: 400 }),
  }, 8000)
}

// ── Stage chip ────────────────────────────────────────────────────────────────

function StageChip({ stage, isDark }) {
  const statusColors = {
    OK: isDark ? 'bg-emerald-900/60 text-emerald-300 border-emerald-700/50'
               : 'bg-emerald-50 text-emerald-700 border-emerald-300',
    FAIL: isDark ? 'bg-red-900/60 text-red-300 border-red-700/50'
                 : 'bg-red-50 text-red-700 border-red-300',
    RUNNING: isDark ? 'bg-blue-900/60 text-blue-300 border-blue-700/50 animate-pulse'
                    : 'bg-blue-50 text-blue-700 border-blue-300 animate-pulse',
  }
  const cls = statusColors[stage.status] || (isDark
    ? 'bg-white/5 text-slate-400 border-white/10'
    : 'bg-slate-100 text-slate-400 border-slate-200')

  return (
    <div className={`flex items-center gap-1.5 rounded px-2 py-1 border text-xs ${cls}`}>
      <span className="font-mono">{stage.status === 'OK' ? '✓' : stage.status === 'FAIL' ? '✗' : '⟳'}</span>
      <span className="font-medium">{stage.stage?.replace(/_/g, ' ')}</span>
      {stage.ms ? <span className="opacity-60">{stage.ms}ms</span> : null}
    </div>
  )
}

// ── OCR vs Vision LLM panel ───────────────────────────────────────────────────

function OcrVsVisionPanel({ result, cheque, isDark }) {
  if (!result) return null
  const cat = cheque?.category
  const isVisionCatch = VISION_CATCHES.has(cat) && result.vision_catches_ocr_miss

  const ocr = result.ocr_result || {}
  const vision = result.vision_result || {}

  const card = isDark
    ? 'bg-navy-900 border-white/8'
    : 'bg-white border-slate-200'
  const heading = isDark ? 'text-white' : 'text-slate-900'
  const muted = isDark ? 'text-slate-400' : 'text-slate-500'
  const body = isDark ? 'text-slate-300' : 'text-slate-700'

  return (
    <div className="space-y-4">
      {/* Banner — Vision LLM catches what OCR misses */}
      {isVisionCatch && (
        <div className="rounded-lg border-2 border-red-500 bg-red-950/40 p-4">
          <div className="flex items-center gap-3 mb-2">
            <span className="text-2xl">🧠</span>
            <span className="text-red-300 font-bold text-base">
              Vision LLM Prevented Fraud — OCR Missed It
            </span>
          </div>
          <p className="text-red-200 text-sm leading-relaxed">
            {cat === 'C' && 'OCR reads character pixels — it sees the overwritten amount as valid text. '
              + 'Vision LLM analyses ink layers and texture, detecting the original amount beneath the correction fluid.'}
            {cat === 'D' && 'OCR reads each digit as a character — it sees "2026" and considers the date valid. '
              + 'Vision LLM detects correction-fluid residue and ink inconsistency on the year digits, revealing the original stale date.'}
            {cat === 'E' && 'OCR extracts text from beneath the stamp successfully. '
              + 'Vision LLM detects the diagonal red ink overlay as a CANCELLED stamp — a spatial understanding impossible for character-level OCR.'}
          </p>
          <div className="mt-3 grid grid-cols-2 gap-3">
            <div className="bg-emerald-900/40 border border-emerald-700/50 rounded p-2 text-center">
              <div className="text-emerald-300 font-bold text-sm">OCR Result</div>
              <div className="text-emerald-200 text-xs mt-1">PASS — no issues found</div>
            </div>
            <div className="bg-red-900/40 border border-red-700/50 rounded p-2 text-center">
              <div className="text-red-300 font-bold text-sm">Vision LLM Result</div>
              <div className="text-red-200 text-xs mt-1">FAIL — fraud detected</div>
            </div>
          </div>
        </div>
      )}

      {/* Side by side */}
      <div className="grid grid-cols-2 gap-3">
        {/* OCR panel */}
        <div className={`rounded-lg border ${card} p-4`}>
          <div className="flex items-center gap-2 mb-3">
            <span className="text-lg">🔤</span>
            <span className={`font-semibold text-sm ${heading}`}>GOT-OCR2.0</span>
            {isVisionCatch
              ? <span className="ml-auto text-xs bg-emerald-900/60 text-emerald-300 border border-emerald-700 rounded px-2 py-0.5">PASSED</span>
              : null}
          </div>
          <div className="space-y-2 text-xs">
            <div className="flex justify-between">
              <span className={muted}>Confidence</span>
              <span className={body}>{((ocr.confidence || 0.96) * 100).toFixed(0)}%</span>
            </div>
            <div className="flex justify-between">
              <span className={muted}>Amount</span>
              <span className={`font-mono ${isVisionCatch && cat === 'C' ? 'text-red-400 line-through' : body}`}>
                Rs. {(ocr.amount_figures || cheque?.amount_figures || 0).toLocaleString('en-IN')}
              </span>
            </div>
            <div className="flex justify-between">
              <span className={muted}>Date</span>
              <span className={`font-mono ${isVisionCatch && cat === 'D' ? 'text-red-400' : body}`}>
                {ocr.cheque_date || cheque?.cheque_date}
              </span>
            </div>
            <div className="flex justify-between">
              <span className={muted}>Payee</span>
              <span className={body}>{ocr.payee_name || cheque?.payee_name}</span>
            </div>
            <div className="flex justify-between">
              <span className={muted}>Flags</span>
              <span className={body}>{(ocr.flags || []).join(', ') || 'None'}</span>
            </div>
            <div className={`mt-2 rounded p-2 text-xs font-medium ${
              isVisionCatch
                ? 'bg-emerald-900/40 text-emerald-300'
                : 'bg-white/5 text-slate-300'
            }`}>
              Verdict: {ocr.ocr_verdict || 'PASS'}
            </div>
          </div>
        </div>

        {/* Vision LLM panel */}
        <div className={`rounded-lg border ${card} p-4`}>
          <div className="flex items-center gap-2 mb-3">
            <span className="text-lg">🧠</span>
            <span className={`font-semibold text-sm ${heading}`}>Qwen2-VL-72B</span>
            {isVisionCatch
              ? <span className="ml-auto text-xs bg-red-900/60 text-red-300 border border-red-700 rounded px-2 py-0.5">CAUGHT</span>
              : null}
          </div>
          <div className="space-y-2 text-xs">
            <div className="flex justify-between">
              <span className={muted}>Inference</span>
              <span className={body}>{vision.inference_ms || 450}ms (L2 queue)</span>
            </div>
            <div className="flex justify-between">
              <span className={muted}>Tamper Risk</span>
              <span className={`font-mono font-bold ${
                (vision.overall_tamper_risk || 0) > 0.7
                  ? 'text-red-400'
                  : (vision.overall_tamper_risk || 0) > 0.3
                  ? 'text-amber-400'
                  : 'text-emerald-400'
              }`}>
                {((vision.overall_tamper_risk || 0.02) * 100).toFixed(0)}%
              </span>
            </div>

            {(vision.findings || []).length > 0 ? (
              <div className="mt-2 space-y-2">
                {(vision.findings || []).map((f, i) => (
                  <div key={i}
                    className={`rounded p-2 border text-xs ${
                      f.severity === 'CRITICAL'
                        ? 'bg-red-950/60 border-red-700/60 text-red-200'
                        : 'bg-amber-950/40 border-amber-700/50 text-amber-200'
                    }`}>
                    <div className="font-bold uppercase mb-1">
                      {f.finding} ({f.field})
                    </div>
                    <div className="leading-relaxed opacity-90">{f.detail}</div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="mt-1 text-xs text-slate-500">No anomalies detected</div>
            )}

            <div className={`mt-2 rounded p-2 text-xs font-medium ${
              isVisionCatch
                ? 'bg-red-900/40 text-red-300'
                : 'bg-white/5 text-slate-300'
            }`}>
              Verdict: {vision.vision_verdict || vision.verdict || 'PASS'}
            </div>
          </div>
        </div>
      </div>

      {/* Cheque image */}
      {result.images?.cheque_front && (
        <div className={`rounded-lg border ${card} p-3`}>
          <div className={`text-xs font-semibold mb-2 ${muted}`}>Cheque Scan</div>
          <img
            src={result.images.cheque_front}
            alt="Cheque scan"
            className="w-full rounded border border-white/10"
            style={{ imageRendering: 'crisp-edges' }}
            onError={(e) => { e.target.style.display = 'none' }}
          />
          {cat === 'E' && (
            <p className="text-xs text-red-400 mt-2">
              The CANCELLED stamp is visible to the human eye and to Vision LLM.
              OCR reads through the stamp and extracts all fields as valid.
            </p>
          )}
          {cat === 'C' && (
            <p className="text-xs text-red-400 mt-2">
              Look at the Rs. field: faint original amount under Tipp-Ex, overwritten with fraud amount.
              OCR reads only the top ink layer. Vision LLM detects both layers.
            </p>
          )}
          {cat === 'D' && (
            <p className="text-xs text-red-400 mt-2">
              Year digits show correction fluid residue. OCR reads "2026" as valid.
              Vision LLM detects the Tipp-Ex + re-inking and recovers the original year.
            </p>
          )}
        </div>
      )}
    </div>
  )
}

// ── Cheque row ────────────────────────────────────────────────────────────────

function ChequeRow({ cheque, result, isSelected, onSelect, isDark }) {
  const cat = cheque.category
  const meta = CAT_META[cat] || {}
  const isVisionCatch = VISION_CATCHES.has(cat)

  const colorMap = {
    emerald: isDark ? 'bg-emerald-900/40 text-emerald-300 border-emerald-700/50'
                    : 'bg-emerald-50 text-emerald-700 border-emerald-200',
    red:     isDark ? 'bg-red-900/40 text-red-300 border-red-700/50'
                    : 'bg-red-50 text-red-700 border-red-200',
    amber:   isDark ? 'bg-amber-900/40 text-amber-300 border-amber-700/50'
                    : 'bg-amber-50 text-amber-700 border-amber-200',
    orange:  isDark ? 'bg-orange-900/40 text-orange-300 border-orange-700/50'
                    : 'bg-orange-50 text-orange-700 border-orange-200',
    yellow:  isDark ? 'bg-yellow-900/40 text-yellow-300 border-yellow-700/50'
                    : 'bg-yellow-50 text-yellow-700 border-yellow-200',
  }
  const catCls = colorMap[meta.color] || (isDark ? 'bg-white/5 text-slate-400 border-white/10' : 'bg-slate-100 text-slate-500 border-slate-200')

  const rowCls = isSelected
    ? (isDark ? 'bg-blue-900/30 border-blue-600/50' : 'bg-blue-50 border-blue-300')
    : (isDark ? 'hover:bg-white/3 border-white/4' : 'hover:bg-slate-50 border-slate-100')

  const outcome = result?.outcome
  const outcomeColor = outcome === 'STP_CONFIRM'
    ? 'text-emerald-400'
    : outcome === 'HUMAN_REVIEW'
    ? 'text-amber-400'
    : outcome === 'STP_RETURN'
    ? 'text-red-400'
    : (isDark ? 'text-slate-500' : 'text-slate-400')

  return (
    <div
      className={`flex items-center gap-3 px-3 py-2.5 border-b cursor-pointer transition-colors ${rowCls}`}
      onClick={() => onSelect(cheque)}
    >
      {/* Cat badge */}
      <span className={`text-xs font-bold rounded px-1.5 py-0.5 border font-mono min-w-[28px] text-center ${catCls}`}>
        {cat}
      </span>

      {/* Vision LLM tag */}
      {isVisionCatch && (
        <span className="text-xs bg-purple-900/50 text-purple-300 border border-purple-700/50 rounded px-1.5 py-0.5">
          Vision
        </span>
      )}

      {/* Name */}
      <span className={`text-xs flex-1 truncate ${isDark ? 'text-slate-300' : 'text-slate-700'}`}>
        {cheque.customer_name}
      </span>

      {/* Amount */}
      <span className={`text-xs font-mono ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>
        {(cheque.amount_figures / 100000).toFixed(1)}L
      </span>

      {/* Outcome */}
      {result && (
        <span className={`text-xs font-medium ${outcomeColor}`}>
          {outcome === 'STP_CONFIRM' ? '✓ STP' : outcome === 'STP_RETURN' ? '✗ RTN' : outcome === 'HUMAN_REVIEW' ? '👁 HRV' : '...'}
        </span>
      )}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function CTSDemoLive() {
  const { isDark } = useTheme()
  usePageHeader({ subtitle: 'Live 5-Bank Docker Demo — Vision LLM vs OCR' })

  const [activeBankIdx, setActiveBankIdx] = useState(0)
  const [cheques, setCheques] = useState(FALLBACK_CHEQUES)
  const [results, setResults] = useState({})         // cheque_id -> pipeline result
  const [selected, setSelected] = useState(null)     // selected cheque object
  const [running, setRunning] = useState(false)
  const [dockerOnline, setDockerOnline] = useState({})  // bankId -> bool
  const [filterCat, setFilterCat] = useState('ALL')
  const [mode, setMode] = useState('all')            // 'all' | 'vision' (show only C/D/E)
  const abortRef = useRef(false)

  const activeBank = BANKS[activeBankIdx]

  const th = {
    page:    isDark ? 'bg-navy-950'        : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'         : 'text-slate-900',
    body:    isDark ? 'text-slate-300'     : 'text-slate-700',
    muted:   isDark ? 'text-slate-400'     : 'text-slate-500',
    divider: isDark ? 'border-white/8'     : 'border-slate-200',
    tab:     isDark ? 'bg-white/5 text-slate-300 hover:bg-white/10'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200',
    tabActive: isDark ? 'bg-blue-600 text-white' : 'bg-blue-600 text-white',
  }

  // ── Check Docker health on mount ─────────────────────────────────────── #

  useEffect(() => {
    const check = async () => {
      const online = {}
      for (const b of BANKS) {
        try {
          await fetchWithTimeout(`http://localhost:${b.port}/health/live`, {}, 1500)
          online[b.id] = true
        } catch {
          online[b.id] = false
        }
      }
      setDockerOnline(online)

      // If any bank is online, load its cheques
      const firstOnline = BANKS.find(b => online[b.id])
      if (firstOnline) {
        try {
          const data = await fetchWithTimeout(
            `http://localhost:${firstOnline.port}/v1/cheques?role=presentee&bank_id=`,
            {}, 3000
          )
          if (data?.length) setCheques(data)
        } catch { /* use fallback */ }
      }
    }
    check()
  }, [])

  // ── Filtered cheque list ─────────────────────────────────────────────── #

  const filteredCheques = cheques.filter(c => {
    const bankMatch = activeBankIdx === 0
      ? true  // SB sees all
      : c.presentee_bank_id === activeBank.id
    const catMatch = filterCat === 'ALL' || c.category === filterCat
    const modeMatch = mode === 'all' || VISION_CATCHES.has(c.category)
    return bankMatch && catMatch && modeMatch
  })

  // ── Process all filtered cheques ─────────────────────────────────────── #

  const processAll = useCallback(async () => {
    setRunning(true)
    abortRef.current = false

    for (const chq of filteredCheques) {
      if (abortRef.current) break
      const bank = BANKS.find(b => b.id === chq.presentee_bank_id) || BANKS[0]
      const isOnline = dockerOnline[bank.id]

      try {
        let res
        if (isOnline) {
          res = await processChequeLive(bank.port, chq.cheque_id)
        } else {
          // Simulate locally
          await new Promise(r => setTimeout(r, 200 + Math.random() * 300))
          res = buildLocalResult(chq)
        }
        setResults(prev => ({ ...prev, [chq.cheque_id]: res }))

        // Auto-select Cat C/D/E for the side panel
        if (VISION_CATCHES.has(chq.category) && !selected) {
          setSelected(chq)
        }
      } catch (e) {
        const fallback = buildLocalResult(chq)
        setResults(prev => ({ ...prev, [chq.cheque_id]: fallback }))
      }
    }
    setRunning(false)
  }, [filteredCheques, dockerOnline, selected])

  function buildLocalResult(chq) {
    const cat = chq.category
    const isVision = VISION_CATCHES.has(cat)
    const stages = buildSimStages(cat)
    const outcome = cat === 'A' ? 'STP_CONFIRM'
      : cat === 'I' ? 'HUMAN_REVIEW'
      : 'STP_RETURN'
    return {
      cheque_id: chq.cheque_id,
      outcome,
      return_reason: getReturnReason(cat),
      stages,
      decision_ms: stages.reduce((s, x) => s + (x.ms || 0), 0),
      vision_catches_ocr_miss: isVision,
      ocr_result: buildOcrResult(chq),
      vision_result: buildVisionResult(chq),
      cheque: chq,
    }
  }

  function buildSimStages(cat) {
    const all = [
      { stage: 'cts_image_validate', status: 'OK', ms: 11 },
      { stage: 'ocr_extract', status: cat === 'B' ? 'FAIL' : 'OK', ms: 62 },
      { stage: 'stale_check', status: cat === 'F' ? 'FAIL' : 'OK', ms: 3 },
      { stage: 'duplicate_check', status: cat === 'G' ? 'FAIL' : 'OK', ms: 5 },
      { stage: 'vision_llm', status: VISION_CATCHES.has(cat) ? 'FAIL' : 'OK', ms: 470 },
      { stage: 'stop_payment', status: cat === 'J' ? 'FAIL' : 'OK', ms: 8 },
      { stage: 'cbs_account_check', status: cat === 'M' ? 'FAIL' : 'OK', ms: 18 },
      { stage: 'balance_check', status: cat === 'K' ? 'FAIL' : 'OK', ms: 12 },
      { stage: 'signature_verify', status: cat === 'I' ? 'FAIL' : 'OK', ms: 95 },
      { stage: 'pps_check', status: cat === 'L' ? 'FAIL' : 'OK', ms: 6 },
      { stage: 'fraud_score', status: 'OK', ms: 25 },
      { stage: 'stp_confirm', status: 'OK', ms: 5 },
    ]
    // Truncate at first failure
    const failIdx = all.findIndex(s => s.status === 'FAIL')
    return failIdx >= 0 ? all.slice(0, failIdx + 1) : all
  }

  function getReturnReason(cat) {
    const map = {
      B: 'AMOUNT_MISMATCH', C: 'AMOUNT_OVERWRITE_FRAUD', D: 'DATE_TAMPER_FRAUD',
      E: 'CANCELLED_INSTRUMENT', F: 'STALE_CHEQUE', G: 'DUPLICATE_INSTRUMENT',
      H: 'CTS_IMAGE_QUALITY', I: 'SIGNATURE_MISMATCH', J: 'STOP_PAYMENT_ACTIVE',
      K: 'INSUFFICIENT_FUNDS', L: 'PPS_AMOUNT_MISMATCH', M: 'ACCOUNT_FROZEN',
    }
    return map[cat] || null
  }

  function buildOcrResult(chq) {
    const cat = chq.category
    const isC = cat === 'C'
    return {
      engine: 'GOT-OCR2.0',
      amount_figures: chq.amount_figures,
      cheque_date: chq.cheque_date,
      payee_name: chq.payee_name,
      confidence: isC ? 0.96 : cat === 'E' ? 0.88 : 0.97,
      flags: cat === 'B' ? ['AMOUNT_MISMATCH'] : [],
      ocr_verdict: ['C','D','E'].includes(cat)
        ? 'PASS - all fields extracted cleanly (fraud NOT detected)'
        : cat === 'B' ? 'FAIL - amount mismatch'
        : 'PASS',
    }
  }

  function buildVisionResult(chq) {
    const cat = chq.category
    const ov = chq.ocr_vs_vision || {}
    if (cat === 'C') return {
      model: 'Qwen2-VL-72B', inference_ms: 480,
      overall_tamper_risk: 0.94, verdict: 'FRAUD_DETECTED',
      catches_ocr_miss: true,
      vision_verdict: `FAIL - amount overwrite detected. Original: ${ov.original_amount_display || 'Rs. 1,20,000'} | Fraud: ${ov.fraud_amount_display || 'Rs. 5,04,000'}`,
      findings: [{
        field: 'amount_figures', finding: 'INK_LAYER_ANOMALY', severity: 'CRITICAL',
        detail: 'Two distinct ink layers detected. Correction fluid (Tipp-Ex) residue band present. Secondary overwrite layer detected with 93% confidence. OCR reads only the top ink layer.',
      }],
    }
    if (cat === 'D') return {
      model: 'Qwen2-VL-72B', inference_ms: 495,
      overall_tamper_risk: 0.89, verdict: 'FRAUD_DETECTED',
      catches_ocr_miss: true,
      vision_verdict: `FAIL - date tamper. Year ${ov.original_year||'2024'} changed to ${ov.new_year||'2026'}. True date: ${ov.orig_date||'12-01-2024'} (STALE)`,
      findings: [{
        field: 'cheque_date', finding: 'DATE_YEAR_TAMPER', severity: 'CRITICAL',
        detail: `Correction fluid residue detected beneath year digits. UV-fluorescence anomaly. Original year ${ov.original_year||'2024'} overwritten with ${ov.new_year||'2026'}. Instrument would be stale at original date.`,
      }],
    }
    if (cat === 'E') return {
      model: 'Qwen2-VL-72B', inference_ms: 460,
      overall_tamper_risk: 0.97, verdict: 'VOID_INSTRUMENT',
      catches_ocr_miss: true,
      vision_verdict: 'FAIL - CANCELLED stamp detected across instrument face. Void instrument.',
      findings: [{
        field: 'instrument_face', finding: 'CANCELLED_STAMP', severity: 'CRITICAL',
        detail: 'Diagonal red rubber-stamp overlay detected spanning full instrument face. Text: CANCELLED. Stamp ink is a separate layer above cheque text. Instrument is void.',
      }],
    }
    return {
      model: 'Qwen2-VL-7B', inference_ms: 95,
      overall_tamper_risk: 0.03, verdict: 'CLEAN', vision_verdict: 'PASS',
      findings: [],
    }
  }

  // ── Stats bar ─────────────────────────────────────────────────────────── #

  const totalProcessed = Object.keys(results).length
  const totalSTPConfirm = Object.values(results).filter(r => r.outcome === 'STP_CONFIRM').length
  const totalReturn = Object.values(results).filter(r => r.outcome === 'STP_RETURN').length
  const totalHR = Object.values(results).filter(r => r.outcome === 'HUMAN_REVIEW').length
  const visionCaught = Object.values(results).filter(r => r.vision_catches_ocr_miss).length

  const currentResult = selected ? results[selected.cheque_id] : null

  return (
    <AppShell>
      <div className={`flex h-full ${th.page}`}>

        {/* ── LEFT: Cheque list ───────────────────────────────────────────── */}
        <div className={`w-72 flex-shrink-0 border-r ${th.divider} flex flex-col`}>

          {/* Bank tabs */}
          <div className={`border-b ${th.divider} p-2`}>
            <div className="text-xs font-semibold mb-2 px-1 text-purple-400">
              SELECT BANK VIEW
            </div>
            <div className="space-y-1">
              {BANKS.map((b, i) => (
                <button
                  key={b.id}
                  onClick={() => setActiveBankIdx(i)}
                  className={`w-full text-left px-2.5 py-1.5 rounded text-xs flex items-center gap-2 transition-colors ${
                    activeBankIdx === i ? th.tabActive : th.tab
                  }`}
                >
                  <span className={`text-xs font-bold rounded px-1 ${b.type === 'SB' ? 'bg-purple-700 text-purple-100' : 'bg-slate-700 text-slate-300'}`}>
                    {b.type}
                  </span>
                  <span className="font-medium truncate">{b.short}</span>
                  <span className={`ml-auto w-2 h-2 rounded-full ${
                    dockerOnline[b.id] === true ? 'bg-emerald-400' :
                    dockerOnline[b.id] === false ? 'bg-red-500' : 'bg-slate-500'
                  }`} title={dockerOnline[b.id] ? 'Docker online' : 'Using simulation'} />
                </button>
              ))}
            </div>
          </div>

          {/* Filter bar */}
          <div className={`border-b ${th.divider} p-2 flex gap-2`}>
            <button
              onClick={() => setMode(mode === 'vision' ? 'all' : 'vision')}
              className={`flex-1 text-xs rounded px-2 py-1.5 font-medium transition-colors ${
                mode === 'vision'
                  ? 'bg-purple-600 text-white'
                  : (isDark ? 'bg-white/5 text-slate-400 hover:bg-white/10' : 'bg-slate-100 text-slate-600 hover:bg-slate-200')
              }`}
            >
              {mode === 'vision' ? '🧠 Vision Only' : '🧠 Vision Focus'}
            </button>
            <select
              value={filterCat}
              onChange={e => setFilterCat(e.target.value)}
              className={`text-xs rounded px-2 py-1.5 border ${th.card}`}
            >
              <option value="ALL">All Cats</option>
              {Object.keys(CAT_META).map(c => (
                <option key={c} value={c}>Cat {c} — {CAT_META[c].label}</option>
              ))}
            </select>
          </div>

          {/* Process button */}
          <div className={`border-b ${th.divider} p-2`}>
            <button
              onClick={running ? () => { abortRef.current = true } : processAll}
              className={`w-full text-xs font-semibold rounded px-3 py-2 transition-colors ${
                running
                  ? 'bg-amber-600 hover:bg-amber-700 text-white'
                  : 'bg-blue-600 hover:bg-blue-700 text-white'
              }`}
            >
              {running
                ? `⏹ Stop (${totalProcessed}/${filteredCheques.length})`
                : `▶ Process ${filteredCheques.length} Cheque${filteredCheques.length !== 1 ? 's' : ''}`}
            </button>
          </div>

          {/* Cheque list */}
          <div className="flex-1 overflow-y-auto">
            {filteredCheques.length === 0 ? (
              <div className={`p-4 text-center text-xs ${th.muted}`}>No cheques match filter</div>
            ) : filteredCheques.map(chq => (
              <ChequeRow
                key={chq.cheque_id}
                cheque={chq}
                result={results[chq.cheque_id]}
                isSelected={selected?.cheque_id === chq.cheque_id}
                onSelect={setSelected}
                isDark={isDark}
              />
            ))}
          </div>
        </div>

        {/* ── CENTER + RIGHT: Detail panel ────────────────────────────────── */}
        <div className="flex-1 flex flex-col overflow-hidden">

          {/* Stats bar */}
          <div className={`border-b ${th.divider} px-4 py-2 flex items-center gap-6`}>
            <div className="flex items-center gap-2">
              <span className={`text-xs ${th.muted}`}>Processed</span>
              <span className={`text-sm font-bold ${th.heading}`}>{totalProcessed}/{filteredCheques.length}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-400" />
              <span className={`text-xs ${th.muted}`}>STP</span>
              <span className={`text-sm font-bold text-emerald-400`}>{totalSTPConfirm}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-red-400" />
              <span className={`text-xs ${th.muted}`}>Return</span>
              <span className={`text-sm font-bold text-red-400`}>{totalReturn}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-amber-400" />
              <span className={`text-xs ${th.muted}`}>Human</span>
              <span className={`text-sm font-bold text-amber-400`}>{totalHR}</span>
            </div>
            {visionCaught > 0 && (
              <div className="flex items-center gap-2 ml-2 bg-purple-900/40 border border-purple-700/50 rounded px-3 py-1">
                <span className="text-sm">🧠</span>
                <span className={`text-xs font-bold text-purple-300`}>
                  Vision LLM caught {visionCaught} fraud{visionCaught !== 1 ? 's' : ''} OCR missed
                </span>
              </div>
            )}
            <div className="ml-auto flex items-center gap-2">
              {Object.entries(dockerOnline).map(([bid, up]) => (
                <span key={bid} className={`text-xs rounded px-2 py-0.5 ${
                  up ? 'bg-emerald-900/40 text-emerald-300' : 'bg-white/5 text-slate-500'
                }`}>
                  {bid.toUpperCase()} {up ? '●' : '○'}
                </span>
              ))}
              <span className={`text-xs ${th.muted}`}>
                {Object.values(dockerOnline).some(Boolean) ? 'Docker' : 'Simulation'}
              </span>
            </div>
          </div>

          {/* Main content area */}
          <div className="flex-1 overflow-y-auto p-4">
            {!selected ? (
              <div className="h-full flex flex-col items-center justify-center">
                <div className="text-5xl mb-4">🏦</div>
                <div className={`text-lg font-semibold mb-2 ${th.heading}`}>
                  ASTRA — Vision LLM Demo
                </div>
                <div className={`text-sm text-center max-w-md ${th.muted}`}>
                  Click "Process Cheques" to run the pipeline.
                  Select any cheque on the left to see OCR vs Vision LLM comparison.
                  Cat C, D, E cheques show the key differentiator.
                </div>
                <div className="mt-6 grid grid-cols-3 gap-4 w-full max-w-lg">
                  {['C','D','E'].map(cat => (
                    <div key={cat}
                      className="rounded-lg border border-red-700/50 bg-red-950/30 p-4 text-center cursor-pointer hover:bg-red-950/50"
                      onClick={() => {
                        const c = filteredCheques.find(x => x.category === cat)
                        if (c) setSelected(c)
                      }}>
                      <div className="text-xl mb-1 font-bold text-red-300">Cat {cat}</div>
                      <div className="text-xs text-red-200">{CAT_META[cat].label}</div>
                      <div className="text-xs text-slate-500 mt-1">OCR misses → Vision catches</div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                {/* Cheque header */}
                <div className={`rounded-lg border ${th.card} p-4`}>
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="flex items-center gap-3 mb-1">
                        <span className={`text-lg font-bold ${th.heading}`}>
                          {selected.customer_name}
                        </span>
                        <span className={`text-xs rounded px-2 py-0.5 border font-bold font-mono ${
                          CAT_META[selected.category]?.color === 'red'
                            ? 'bg-red-900/40 text-red-300 border-red-700/50'
                            : 'bg-white/5 text-slate-300 border-white/10'
                        }`}>
                          Cat {selected.category} — {CAT_META[selected.category]?.label}
                        </span>
                        {VISION_CATCHES.has(selected.category) && (
                          <span className="text-xs bg-purple-900/50 text-purple-300 border border-purple-700/50 rounded px-2 py-0.5">
                            🧠 Vision LLM Required
                          </span>
                        )}
                      </div>
                      <div className={`text-xs ${th.muted}`}>
                        {selected.cheque_id} &nbsp;·&nbsp;
                        Rs. {(selected.amount_figures || 0).toLocaleString('en-IN')} &nbsp;·&nbsp;
                        Payee: {selected.payee_name} &nbsp;·&nbsp;
                        Date: {selected.cheque_date}
                      </div>
                    </div>
                    {currentResult && (
                      <div className={`text-sm font-bold rounded px-3 py-1.5 ${
                        currentResult.outcome === 'STP_CONFIRM'
                          ? 'bg-emerald-900/50 text-emerald-300'
                          : currentResult.outcome === 'HUMAN_REVIEW'
                          ? 'bg-amber-900/50 text-amber-300'
                          : 'bg-red-900/50 text-red-300'
                      }`}>
                        {currentResult.outcome}
                        {currentResult.return_reason ? ` — ${currentResult.return_reason}` : ''}
                      </div>
                    )}
                  </div>
                </div>

                {/* Pipeline stages */}
                {currentResult?.stages && (
                  <div className={`rounded-lg border ${th.card} p-4`}>
                    <div className={`text-xs font-semibold mb-3 ${th.muted}`}>
                      PIPELINE STAGES &nbsp;·&nbsp; {currentResult.decision_ms}ms total
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {currentResult.stages.map((s, i) => (
                        <StageChip key={i} stage={s} isDark={isDark} />
                      ))}
                    </div>
                  </div>
                )}

                {/* OCR vs Vision panel */}
                <OcrVsVisionPanel
                  result={currentResult}
                  cheque={selected}
                  isDark={isDark}
                />

                {/* If not yet processed */}
                {!currentResult && (
                  <div className={`rounded-lg border ${th.card} p-8 text-center`}>
                    <div className={`text-sm ${th.muted}`}>
                      Click "Process Cheques" above to run the pipeline for this cheque.
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  )
}

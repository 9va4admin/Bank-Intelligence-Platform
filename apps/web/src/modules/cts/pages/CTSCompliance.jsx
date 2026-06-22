import { useState } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'

// ── CTS-2010 Standard reference (mirrors Python CTS2010Standard) ─────────────
const CTS2010 = {
  MIN_DPI:           200,
  MIN_COLOUR_DEPTH:  24,
  MAX_FILE_SIZE_KB:  50.0,
  MIN_IQA_SCORE:     0.70,
  MICR_BAND_MIN:     0.80,
}

// ── Mock batch data ──────────────────────────────────────────────────────────
function evalRecord(r) {
  const reasons = []
  if (r.front_dpi          < CTS2010.MIN_DPI)          reasons.push('front_dpi')
  if (r.rear_dpi           < CTS2010.MIN_DPI)          reasons.push('rear_dpi')
  if (r.front_colour_depth < CTS2010.MIN_COLOUR_DEPTH) reasons.push('front_colour_depth')
  if (r.front_file_size_kb > CTS2010.MAX_FILE_SIZE_KB) reasons.push('front_file_size_kb')
  if (r.rear_file_size_kb  > CTS2010.MAX_FILE_SIZE_KB) reasons.push('rear_file_size_kb')
  if (r.front_iqa_score    < CTS2010.MIN_IQA_SCORE)    reasons.push('front_iqa_score')
  if (r.rear_iqa_score     < CTS2010.MIN_IQA_SCORE)    reasons.push('rear_iqa_score')
  if (r.micr_band_score    < CTS2010.MICR_BAND_MIN)    reasons.push('micr_band_score')
  return { ...r, result: reasons.length === 0 ? 'PASS' : 'FAIL', reasons }
}

const RAW_INSTRUMENTS = [
  { id:'CHQ-OUT-00001', cheque:'100001', lot:'LOT_SVCB0000001_20260619_SES-0619-001_01', front_dpi:300, front_colour_depth:24, front_file_size_kb:38.2, front_iqa_score:0.94, rear_dpi:300, rear_colour_depth:24, rear_file_size_kb:22.5, rear_iqa_score:0.91, micr_band_score:0.96 },
  { id:'CHQ-OUT-00002', cheque:'100002', lot:'LOT_SVCB0000001_20260619_SES-0619-001_01', front_dpi:300, front_colour_depth:24, front_file_size_kb:41.7, front_iqa_score:0.92, rear_dpi:300, rear_colour_depth:24, rear_file_size_kb:19.8, rear_iqa_score:0.88, micr_band_score:0.93 },
  { id:'CHQ-OUT-00003', cheque:'100003', lot:'LOT_SVCB0000001_20260619_SES-0619-001_01', front_dpi:300, front_colour_depth:24, front_file_size_kb:35.1, front_iqa_score:0.97, rear_dpi:300, rear_colour_depth:24, rear_file_size_kb:18.2, rear_iqa_score:0.95, micr_band_score:0.98 },
  { id:'CHQ-OUT-00004', cheque:'100004', lot:'LOT_SVCB0000001_20260619_SES-0619-001_01', front_dpi:150, front_colour_depth:24, front_file_size_kb:38.2, front_iqa_score:0.94, rear_dpi:300, rear_colour_depth:24, rear_file_size_kb:22.5, rear_iqa_score:0.91, micr_band_score:0.96 }, // low DPI
  { id:'CHQ-OUT-00005', cheque:'100005', lot:'LOT_SVCB0000001_20260619_SES-0619-001_01', front_dpi:300, front_colour_depth:24, front_file_size_kb:38.2, front_iqa_score:0.94, rear_dpi:300, rear_colour_depth:24, rear_file_size_kb:22.5, rear_iqa_score:0.91, micr_band_score:0.62 }, // low MICR
  { id:'CHQ-OUT-00006', cheque:'100006', lot:'LOT_SVCB0000001_20260619_SES-0619-001_01', front_dpi:300, front_colour_depth:24, front_file_size_kb:53.0, front_iqa_score:0.94, rear_dpi:300, rear_colour_depth:24, rear_file_size_kb:22.5, rear_iqa_score:0.91, micr_band_score:0.96 }, // large file
  { id:'CHQ-OUT-00007', cheque:'100007', lot:'LOT_SVCB0000001_20260619_SES-0619-001_01', front_dpi:300, front_colour_depth:24, front_file_size_kb:39.8, front_iqa_score:0.91, rear_dpi:300, rear_colour_depth:24, rear_file_size_kb:21.3, rear_iqa_score:0.89, micr_band_score:0.94 },
  { id:'CHQ-OUT-00008', cheque:'100008', lot:'LOT_SVCB0000001_20260619_SES-0619-001_02', front_dpi:300, front_colour_depth:24, front_file_size_kb:37.5, front_iqa_score:0.96, rear_dpi:300, rear_colour_depth:24, rear_file_size_kb:20.1, rear_iqa_score:0.93, micr_band_score:0.97 },
  { id:'CHQ-OUT-00009', cheque:'100009', lot:'LOT_SVCB0000001_20260619_SES-0619-001_02', front_dpi:300, front_colour_depth:24, front_file_size_kb:40.2, front_iqa_score:0.93, rear_dpi:300, rear_colour_depth:24, rear_file_size_kb:23.4, rear_iqa_score:0.90, micr_band_score:0.95 },
  { id:'CHQ-OUT-00010', cheque:'100010', lot:'LOT_SVCB0000001_20260619_SES-0619-001_02', front_dpi:300, front_colour_depth:24, front_file_size_kb:36.8, front_iqa_score:0.95, rear_dpi:300, rear_colour_depth:24, rear_file_size_kb:19.5, rear_iqa_score:0.92, micr_band_score:0.96 },
]

const INSTRUMENTS = RAW_INSTRUMENTS.map(evalRecord)

const LOTS = [...new Set(INSTRUMENTS.map(i => i.lot))]

function buildXml(instruments, lotId, sessionId, ifsc) {
  const date = new Date().toISOString()
  const passed = instruments.filter(i => i.result === 'PASS').length
  const failed = instruments.length - passed
  const passRate = instruments.length ? ((passed / instruments.length) * 100).toFixed(2) : '0.00'
  const overall = failed === 0 ? 'PASS' : 'FAIL'

  const rows = instruments.map(i => `    <Instrument>
      <InstrumentID>${i.id}</InstrumentID>
      <ChequeNumber>${i.cheque}</ChequeNumber>
      <LotNumber>${i.lot}</LotNumber>
      <Result>${i.result}</Result>
      <FrontImage>
        <DPI>${i.front_dpi}</DPI>
        <ColourDepth>${i.front_colour_depth}</ColourDepth>
        <FileSizeKB>${i.front_file_size_kb.toFixed(2)}</FileSizeKB>
        <IQAScore>${i.front_iqa_score.toFixed(4)}</IQAScore>
      </FrontImage>
      <RearImage>
        <DPI>${i.rear_dpi}</DPI>
        <ColourDepth>${i.rear_colour_depth}</ColourDepth>
        <FileSizeKB>${i.rear_file_size_kb.toFixed(2)}</FileSizeKB>
        <IQAScore>${i.rear_iqa_score.toFixed(4)}</IQAScore>
      </RearImage>
      <MICRBandScore>${i.micr_band_score.toFixed(4)}</MICRBandScore>${
        i.reasons.length ? `\n      <FailureReasons>${i.reasons.map(r => `\n        <Reason>${r}</Reason>`).join('')}\n      </FailureReasons>` : ''
      }
    </Instrument>`).join('\n')

  return `<?xml version="1.0" encoding="UTF-8"?>
<CTS2010ComplianceCertificate xmlns="urn:in:rbi:cts:2010:compliance" version="1.0">
  <Header>
    <BankIFSC>${ifsc}</BankIFSC>
    <SessionID>${sessionId}</SessionID>
    <BatchID>${lotId}</BatchID>
    <IssuedAt>${date}</IssuedAt>
    <OverallResult>${overall}</OverallResult>
    <TotalInstruments>${instruments.length}</TotalInstruments>
    <PassedCount>${passed}</PassedCount>
    <FailedCount>${failed}</FailedCount>
    <PassRate>${passRate}</PassRate>
  </Header>
  <CTS2010StandardReference>
    <MinDPI>${CTS2010.MIN_DPI}</MinDPI>
    <MinColourDepth>${CTS2010.MIN_COLOUR_DEPTH}</MinColourDepth>
    <MaxFileSizeKB>${CTS2010.MAX_FILE_SIZE_KB}</MaxFileSizeKB>
    <MinIQAScore>${CTS2010.MIN_IQA_SCORE}</MinIQAScore>
    <MICRBandMinScore>${CTS2010.MICR_BAND_MIN}</MICRBandMinScore>
  </CTS2010StandardReference>
  <Instruments>
${rows}
  </Instruments>
</CTS2010ComplianceCertificate>`
}

function downloadXml(xml, filename) {
  const blob = new Blob([xml], { type: 'application/xml' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href     = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

// ── Component ────────────────────────────────────────────────────────────────
export default function CTSCompliance() {
  const [selectedLot, setSelectedLot] = useState(LOTS[0])
  const [filterResult, setFilterResult] = useState('ALL')

  const lotItems = INSTRUMENTS.filter(i => i.lot === selectedLot)
  const passed   = lotItems.filter(i => i.result === 'PASS').length
  const failed   = lotItems.filter(i => i.result === 'FAIL').length
  const passRate = lotItems.length ? ((passed / lotItems.length) * 100).toFixed(1) : '0.0'
  const overall  = failed === 0 ? 'PASS' : 'FAIL'

  const visible = filterResult === 'ALL' ? lotItems : lotItems.filter(i => i.result === filterResult)

  const lotSeqMatch  = selectedLot.match(/_(\d{2})$/)
  const lotSeq       = lotSeqMatch ? lotSeqMatch[1] : '01'
  const certFilename = `CTS2010_CERT_SVCB0000001_20260619_SES-0619-001_LOT${lotSeq}.xml`

  const th = {
    page:    'bg-slate-50 dark:bg-transparent',
    card:    'bg-white border-slate-200 dark:bg-white/10 dark:border-white/10',
    heading: 'text-slate-900 dark:text-white',
    body:    'text-slate-700 dark:text-slate-300',
    muted:   'text-slate-500 dark:text-slate-400',
    faint:   'text-slate-400 dark:text-slate-500',
    divider: 'border-slate-200 dark:border-white/10',
    row:     'border-slate-100 hover:bg-slate-50 dark:border-white/5 dark:hover:bg-white/5',
    select:  'bg-white border-slate-300 text-slate-900 dark:bg-navy-900 dark:border-white/10 dark:text-white',
    mono:    'text-slate-600 font-mono text-xs dark:text-slate-300 dark:font-mono dark:text-xs',
    bar:     'bg-slate-100 dark:bg-white/5',
  }

  const overallColor = overall === 'PASS'
    ? ('text-emerald-600 dark:text-emerald-400')
    : ('text-red-600 dark:text-red-400')

  function ScoreBar({ value, min, label }) {
    const pct   = Math.min((value / 1.0) * 100, 100)
    const pass  = value >= min
    const color = pass
      ? ('bg-emerald-500 dark:bg-emerald-500')
      : ('bg-red-500 dark:bg-red-500')
    return (
      <div className="flex items-center gap-2">
        <span className={`text-[10px] w-24 shrink-0 ${th.muted}`}>{label}</span>
        <div className={`flex-1 ${th.bar} rounded-full h-1.5`}>
          <div className={`h-1.5 rounded-full ${color}`} style={{ width: `${pct}%` }} />
        </div>
        <span className={`text-[10px] w-10 text-right ${pass ? ('text-emerald-600 dark:text-emerald-400') : ('text-red-600 dark:text-red-400')}`}>
          {typeof value === 'number' && value < 10 ? `${value}` : value}
        </span>
      </div>
    )
  }

  usePageHeader({
    subtitle: 'Per-lot image quality attestation · RBI CTS-2010 Standard',
    actions: (
      <div className="flex items-center gap-3">
        <select
          value={selectedLot}
          onChange={e => { setSelectedLot(e.target.value); setFilterResult('ALL') }}
          className={`text-xs border rounded-lg px-3 py-1.5 max-w-xs truncate ${th.select}`}
        >
          {LOTS.map(l => (
            <option key={l} value={l}>{l.split('_').slice(-1)[0] === '01' ? 'Lot 01' : `Lot ${l.split('_').slice(-1)[0]}`} — {l}</option>
          ))}
        </select>
        <button
          onClick={() => downloadXml(buildXml(lotItems, selectedLot, 'SES-0619-001', 'SVCB0000001'), certFilename)}
          className="flex items-center gap-2 text-xs bg-violet-600 hover:bg-violet-500 text-white rounded-lg px-3 py-1.5"
        >
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
          </svg>
          Download Certificate
        </button>
      </div>
    ),
  })

  return (
    <AppShell>
      <div className={`${th.page} px-6 py-5`}>

        {/* KPI strip */}
        <div className="grid grid-cols-5 gap-3 mb-6">
          {[
            { label: 'Instruments',   value: lotItems.length, color: th.heading },
            { label: 'Passed',        value: passed,          color: 'text-emerald-600 dark:text-emerald-400' },
            { label: 'Failed',        value: failed,          color: failed > 0 ? ('text-red-600 dark:text-red-400') : ('text-emerald-600 dark:text-emerald-400') },
            { label: 'Pass Rate',     value: `${passRate}%`,  color: parseFloat(passRate) === 100 ? ('text-emerald-600 dark:text-emerald-400') : ('text-amber-600 dark:text-amber-400') },
            { label: 'Overall',       value: overall,         color: overallColor },
          ].map(k => (
            <div key={k.label} className={`border rounded-xl px-4 py-3 ${th.card}`}>
              <div className={`text-[10px] ${th.faint} mb-1`}>{k.label}</div>
              <div className={`text-2xl font-bold ${k.color}`}>{k.value}</div>
            </div>
          ))}
        </div>

        {/* CTS-2010 Standard thresholds reference */}
        <div className={`border rounded-xl p-4 mb-4 ${th.card}`}>
          <div className={`text-xs font-medium ${th.heading} mb-3`}>CTS-2010 Standard Thresholds (RBI Mandate)</div>
          <div className="grid grid-cols-5 gap-4">
            {[
              { label: 'Min DPI',         value: `${CTS2010.MIN_DPI} dpi` },
              { label: 'Colour Depth',    value: `${CTS2010.MIN_COLOUR_DEPTH}-bit RGB` },
              { label: 'Max File Size',   value: `${CTS2010.MAX_FILE_SIZE_KB} KB` },
              { label: 'Min IQA Score',   value: `≥ ${CTS2010.MIN_IQA_SCORE}` },
              { label: 'MICR Band Min',   value: `≥ ${CTS2010.MICR_BAND_MIN}` },
            ].map(t => (
              <div key={t.label}>
                <div className={`text-[10px] ${th.faint}`}>{t.label}</div>
                <div className={`text-sm font-semibold ${th.heading} mt-0.5`}>{t.value}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Filter bar */}
        <div className="flex items-center gap-2 mb-4">
          <span className={`text-xs ${th.muted}`}>Filter:</span>
          {['ALL', 'PASS', 'FAIL'].map(f => (
            <button
              key={f}
              onClick={() => setFilterResult(f)}
              className={`text-xs px-3 py-1 rounded-full border transition-colors ${
                filterResult === f
                  ? 'bg-violet-600 text-white border-violet-600'
                  : 'border-slate-200 text-slate-500 hover:text-slate-900 dark:border-white/10 dark:text-slate-400 dark:hover:text-white'
              }`}
            >
              {f === 'ALL' ? 'All' : f}
            </button>
          ))}
          <span className={`ml-auto text-[10px] ${th.faint}`}>{visible.length} of {lotItems.length} instruments</span>
        </div>

        {/* Instruments table */}
        <div className={`border rounded-xl overflow-hidden ${th.card}`}>
          <div className={`grid grid-cols-12 gap-2 px-4 py-2 border-b ${th.divider} text-[10px] ${th.faint} font-medium uppercase tracking-wider`}>
            <div className="col-span-3">Instrument ID</div>
            <div className="col-span-1">Cheque</div>
            <div className="col-span-1 text-center">DPI</div>
            <div className="col-span-2">Front IQA</div>
            <div className="col-span-2">Rear IQA</div>
            <div className="col-span-2">MICR Score</div>
            <div className="col-span-1 text-center">Result</div>
          </div>

          {visible.map(item => (
            <div key={item.id} className={`grid grid-cols-12 gap-2 px-4 py-3 border-b ${th.row} transition-colors`}>
              <div className={`col-span-3 ${th.mono}`}>{item.id}</div>
              <div className={`col-span-1 text-xs ${th.body}`}>{item.cheque}</div>

              {/* DPI */}
              <div className="col-span-1 text-center">
                <span className={`text-xs font-medium ${item.front_dpi >= CTS2010.MIN_DPI ? ('text-emerald-600 dark:text-emerald-400') : ('text-red-600 dark:text-red-400')}`}>
                  {item.front_dpi}
                </span>
              </div>

              {/* Front IQA bar */}
              <div className="col-span-2">
                <ScoreBar value={item.front_iqa_score} min={CTS2010.MIN_IQA_SCORE} label="" />
              </div>

              {/* Rear IQA bar */}
              <div className="col-span-2">
                <ScoreBar value={item.rear_iqa_score} min={CTS2010.MIN_IQA_SCORE} label="" />
              </div>

              {/* MICR bar */}
              <div className="col-span-2">
                <ScoreBar value={item.micr_band_score} min={CTS2010.MICR_BAND_MIN} label="" />
              </div>

              {/* Result */}
              <div className="col-span-1 text-center">
                <span className={`text-xs font-bold ${item.result === 'PASS' ? ('text-emerald-600 dark:text-emerald-400') : ('text-red-600 dark:text-red-400')}`}>
                  {item.result === 'PASS' ? '✓' : '✗'} {item.result}
                </span>
              </div>
            </div>
          ))}
        </div>

        {/* Filename preview */}
        <div className={`mt-3 text-[10px] ${th.faint}`}>
          Certificate file: <span className={th.mono}>{certFilename}</span>
        </div>
      </div>
    </AppShell>
  )
}

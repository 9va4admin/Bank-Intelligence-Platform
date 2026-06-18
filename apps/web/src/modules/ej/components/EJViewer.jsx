const RAW_EJ_SAMPLES = {
  'ATM-MUM-004': `JRN0001 STA 09:31:44 IDLE
JRN0002 CDE 09:31:52 CARD INSERT 4XXX XXXX XXXX 4521
JRN0003 AUT 09:31:55 PIN VERIFY OK TRYS=1
JRN0004 TXN 09:32:01 WITHDRAWAL REQ AMT=000010000
JRN0005 DSP 09:32:07 DISPENSE CAS1=04 CAS2=06 TOTAL=000010000
JRN0006 RET 09:32:11 CARD RETURNED
JRN0007 END 09:32:13 SESSION COMPLETE
JRN0008 STA 09:32:13 IDLE
JRN0009 CDE 09:35:44 CARD INSERT 4XXX XXXX XXXX 7832
JRN0010 AUT 09:35:47 PIN VERIFY FAIL TRYS=1
JRN0011 AUT 09:35:54 PIN VERIFY FAIL TRYS=2
JRN0012 AUT 09:36:02 PIN VERIFY FAIL TRYS=3
JRN0013 RET 09:36:03 CARD RETAINED REASON=PIN_EXCEEDED
JRN0014 ERR 09:36:04 CASSETTE1 JAM CLEARED
JRN0015 CDE 09:38:11 CARD INSERT 4XXX XXXX XXXX 9901
JRN0016 AUT 09:38:14 PIN VERIFY OK TRYS=1
JRN0017 TXN 09:38:20 WITHDRAWAL REQ AMT=000085000
JRN0018 DSP 09:38:26 DISPENSE FAIL CAS1 JAM
JRN0019 ERR 09:38:27 CND LOGGED AMT=000085000
JRN0020 RET 09:38:29 CARD RETURNED`,

  DEFAULT: `JRN0001 STA 10:01:22 IDLE
JRN0002 CDE 10:01:35 CARD INSERT 4XXX XXXX XXXX 3312
JRN0003 AUT 10:01:38 PIN VERIFY OK TRYS=1
JRN0004 TXN 10:01:44 WITHDRAWAL REQ AMT=000005000
JRN0005 DSP 10:01:49 DISPENSE CAS1=02 CAS2=00 TOTAL=000005000
JRN0006 RET 10:01:52 CARD RETURNED
JRN0007 END 10:01:54 SESSION COMPLETE`,
}

const OPTIMIZED_EJ_SAMPLES = {
  'ATM-MUM-004': [
    { seq:'JRN0001-0007', type:'WITHDRAWAL',     status:'SUCCESS',  card_last4:'4521', amount:10000, dispense_confirmed:true,  timestamp:'2026-06-18T09:32:13', cassette_events:[], ai_confidence:0.99 },
    { seq:'JRN0009-0013', type:'PIN_LOCKOUT',    status:'CARD_RETAINED', card_last4:'7832', amount:0, dispense_confirmed:false, timestamp:'2026-06-18T09:36:03', cassette_events:[], ai_confidence:0.98, alert:'BRE-005: Card retention logged' },
    { seq:'JRN0015-0019', type:'CASH_NOT_DISPENSED', status:'CND_LOGGED', card_last4:'9901', amount:85000, dispense_confirmed:false, timestamp:'2026-06-18T09:38:29', cassette_events:['CAS1_JAM'], ai_confidence:0.97, alert:'BRE-001: CND + BRE-002: Dispense mismatch CRITICAL' },
  ],
  DEFAULT: [
    { seq:'JRN0001-0007', type:'WITHDRAWAL', status:'SUCCESS', card_last4:'3312', amount:5000, dispense_confirmed:true, timestamp:'2026-06-18T10:01:54', cassette_events:[], ai_confidence:0.99 },
  ],
}

export default function EJViewer({ atm, onClose }) {
  const rawLog = RAW_EJ_SAMPLES[atm?.atm_id] || RAW_EJ_SAMPLES.DEFAULT
  const optimized = OPTIMIZED_EJ_SAMPLES[atm?.atm_id] || OPTIMIZED_EJ_SAMPLES.DEFAULT

  return (
    <div className="border border-cyan-800/40 rounded-xl bg-slate-900/60 p-4 backdrop-blur">
      <div className="flex items-center justify-between mb-3">
        <div>
          <span className="text-xs font-semibold text-cyan-400 uppercase tracking-wider">EJ Analysis</span>
          {atm && <span className="text-xs text-slate-500 ml-2">· {atm.atm_id} · {atm.branch} · {atm.oem}</span>}
        </div>
        <button onClick={onClose} className="text-slate-500 hover:text-slate-300 text-lg leading-none">×</button>
      </div>

      <div className="grid grid-cols-2 gap-4">
        {/* Raw EJ */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <div className="w-1.5 h-1.5 rounded-full bg-amber-500" />
            <span className="text-xs font-semibold text-amber-400 uppercase tracking-wider">Raw EJ · OEM Proprietary</span>
            <span className="text-[10px] text-slate-600">(NCR_SELFSERV format)</span>
          </div>
          <pre className="bg-black/40 border border-slate-800 rounded-lg p-3 text-[10px] font-mono text-amber-200/70 overflow-auto leading-relaxed" style={{maxHeight:'200px'}}>
            {rawLog}
          </pre>
          <div className="mt-1 text-[10px] text-slate-600">Unstructured · OEM-specific · Not queryable · Cannot be compared cross-fleet</div>
        </div>

        {/* Optimized EJ */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <div className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
            <span className="text-xs font-semibold text-emerald-400 uppercase tracking-wider">Optimized EJ · AI-Canonical</span>
            <span className="text-[10px] text-slate-600">(Llama 3.3 70B parsed)</span>
          </div>
          <div className="bg-black/40 border border-slate-800 rounded-lg p-3 space-y-2 overflow-auto" style={{maxHeight:'200px'}}>
            {optimized.map((rec, i) => (
              <div key={i} className={`border rounded p-2 text-[10px] font-mono ${rec.alert ? 'border-red-700/50 bg-red-950/20' : 'border-slate-700 bg-slate-900/40'}`}>
                <div className="flex items-center justify-between mb-1">
                  <span className={`font-bold ${rec.status === 'SUCCESS' ? 'text-emerald-400' : 'text-red-400'}`}>{rec.type}</span>
                  <span className="text-slate-500">{rec.seq}</span>
                </div>
                <div className="grid grid-cols-2 gap-x-4 text-slate-400">
                  <span>card: ****{rec.card_last4}</span>
                  <span>amt: ₹{rec.amount.toLocaleString('en-IN')}</span>
                  <span>dispense: {rec.dispense_confirmed ? '✓ confirmed' : '✗ not confirmed'}</span>
                  <span>confidence: {(rec.ai_confidence * 100).toFixed(0)}%</span>
                </div>
                {rec.cassette_events.length > 0 && (
                  <div className="text-amber-400 mt-1">⚠ {rec.cassette_events.join(', ')}</div>
                )}
                {rec.alert && (
                  <div className="text-red-400 mt-1 font-bold">🚨 {rec.alert}</div>
                )}
              </div>
            ))}
          </div>
          <div className="mt-1 text-[10px] text-slate-600">Structured JSON · Cross-OEM · Queryable · BRE-matched · Dispute-ready</div>
        </div>
      </div>
    </div>
  )
}

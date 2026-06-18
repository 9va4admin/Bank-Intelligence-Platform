import { useState, useEffect, useCallback } from 'react'

// 15 ATMs across India
const INITIAL_ATMS = [
  { atm_id:'ATM-MUM-001', branch:'Andheri West', city:'Mumbai', state:'Maharashtra', oem:'NCR_SELFSERV',    risk:'HEALTHY',  cash_pct:78, txn_today:312, txn_velocity:14, last_ej_upload:'2026-06-18 10:47', pending_alarms:0,  status:'ONLINE'  },
  { atm_id:'ATM-MUM-002', branch:'Bandra East',  city:'Mumbai', state:'Maharashtra', oem:'DIEBOLD_NIXDORF', risk:'HIGH',     cash_pct:21, txn_today:487, txn_velocity:31, last_ej_upload:'2026-06-18 10:42', pending_alarms:3,  status:'ONLINE'  },
  { atm_id:'ATM-MUM-003', branch:'Dadar',        city:'Mumbai', state:'Maharashtra', oem:'HYOSUNG',         risk:'HEALTHY',  cash_pct:65, txn_today:201, txn_velocity:8,  last_ej_upload:'2026-06-18 10:48', pending_alarms:0,  status:'ONLINE'  },
  { atm_id:'ATM-MUM-004', branch:'Kurla',        city:'Mumbai', state:'Maharashtra', oem:'GRG_BANKING',     risk:'CRITICAL', cash_pct:8,  txn_today:612, txn_velocity:47, last_ej_upload:'2026-06-18 09:12', pending_alarms:11, status:'ONLINE'  },
  { atm_id:'ATM-MUM-005', branch:'Malad',        city:'Mumbai', state:'Maharashtra', oem:'NCR_SELFSERV',    risk:'HEALTHY',  cash_pct:91, txn_today:178, txn_velocity:6,  last_ej_upload:'2026-06-18 10:49', pending_alarms:0,  status:'ONLINE'  },
  { atm_id:'ATM-PUN-001', branch:'FC Road',      city:'Pune',   state:'Maharashtra', oem:'DIEBOLD_NIXDORF', risk:'DEGRADED', cash_pct:44, txn_today:289, txn_velocity:19, last_ej_upload:'2026-06-18 10:31', pending_alarms:2,  status:'ONLINE'  },
  { atm_id:'ATM-DEL-001', branch:'Connaught Pl', city:'Delhi',  state:'Delhi',       oem:'DIEBOLD_NIXDORF', risk:'HIGH',     cash_pct:33, txn_today:521, txn_velocity:28, last_ej_upload:'2026-06-18 10:38', pending_alarms:4,  status:'ONLINE'  },
  { atm_id:'ATM-DEL-002', branch:'Karol Bagh',   city:'Delhi',  state:'Delhi',       oem:'NCR_SELFSERV',    risk:'HEALTHY',  cash_pct:82, txn_today:341, txn_velocity:11, last_ej_upload:'2026-06-18 10:50', pending_alarms:0,  status:'ONLINE'  },
  { atm_id:'ATM-DEL-003', branch:'Lajpat Nagar', city:'Delhi',  state:'Delhi',       oem:'HYOSUNG',         risk:'HEALTHY',  cash_pct:57, txn_today:267, txn_velocity:9,  last_ej_upload:'2026-06-18 10:46', pending_alarms:1,  status:'ONLINE'  },
  { atm_id:'ATM-DEL-004', branch:'Rohini',       city:'Delhi',  state:'Delhi',       oem:'WINCOR_NIXDORF',  risk:'OFFLINE',  cash_pct:0,  txn_today:0,   txn_velocity:0,  last_ej_upload:'2026-06-18 07:03', pending_alarms:1,  status:'OFFLINE' },
  { atm_id:'ATM-BLR-001', branch:'Koramangala',  city:'Bangalore', state:'Karnataka', oem:'GRG_BANKING',   risk:'HIGH',     cash_pct:29, txn_today:448, txn_velocity:24, last_ej_upload:'2026-06-18 10:40', pending_alarms:5,  status:'ONLINE'  },
  { atm_id:'ATM-BLR-002', branch:'Whitefield',   city:'Bangalore', state:'Karnataka', oem:'NCR_SELFSERV',  risk:'HEALTHY',  cash_pct:74, txn_today:193, txn_velocity:7,  last_ej_upload:'2026-06-18 10:51', pending_alarms:0,  status:'ONLINE'  },
  { atm_id:'ATM-BLR-003', branch:'Indiranagar',  city:'Bangalore', state:'Karnataka', oem:'HYOSUNG',       risk:'DEGRADED', cash_pct:38, txn_today:334, txn_velocity:16, last_ej_upload:'2026-06-18 10:29', pending_alarms:2,  status:'ONLINE'  },
  { atm_id:'ATM-CHE-001', branch:'T Nagar',      city:'Chennai', state:'Tamil Nadu', oem:'DIEBOLD_NIXDORF', risk:'HEALTHY',  cash_pct:88, txn_today:241, txn_velocity:10, last_ej_upload:'2026-06-18 10:48', pending_alarms:0,  status:'ONLINE'  },
  { atm_id:'ATM-CHE-002', branch:'Anna Nagar',   city:'Chennai', state:'Tamil Nadu', oem:'NCR_SELFSERV',    risk:'CRITICAL', cash_pct:5,  txn_today:589, txn_velocity:38, last_ej_upload:'2026-06-18 08:44', pending_alarms:9,  status:'ONLINE'  },
]

// BRE alarm templates
const BRE_RULES = [
  { rule_id:'BRE-001', severity:'CRITICAL', name:'Cash-Not-Dispensed Spike',      message: (id) => `${id}: CND rate 4/hr — exceeds threshold 3/hr. Possible cash trap.` },
  { rule_id:'BRE-002', severity:'CRITICAL', name:'Dispense-Balance Mismatch',      message: (id) => `${id}: EJ dispense ₹8,500 vs ledger debit ₹0. Investigate immediately.` },
  { rule_id:'BRE-003', severity:'HIGH',     name:'Journal Sequence Gap Detected',  message: (id) => `${id}: EJ seq gap 4712→4718. Missing 5 records. Possible tampering.` },
  { rule_id:'BRE-004', severity:'HIGH',     name:'Excessive PIN Failures',         message: (id) => `${id}: 7 PIN fails / 30 min from 3 different cards. Skimming indicator.` },
  { rule_id:'BRE-005', severity:'HIGH',     name:'Card Retention Spike',           message: (id) => `${id}: 3 cards retained in 1 hr. Possible card-trap device installed.` },
  { rule_id:'BRE-006', severity:'HIGH',     name:'Transaction Velocity Spike',     message: (id) => `${id}: Velocity 47 TXN/hr vs 18 baseline (261% spike).` },
  { rule_id:'BRE-007', severity:'MEDIUM',   name:'Off-Hours Large Dispense',       message: (id) => `${id}: ₹49,500 dispensed at 02:17 AM. Off-hours anomaly.` },
  { rule_id:'BRE-008', severity:'MEDIUM',   name:'EJ Upload Timeout',              message: (id) => `${id}: No EJ upload for 97 min. Central sync failed.` },
  { rule_id:'BRE-009', severity:'MEDIUM',   name:'Cassette Jam Pattern',           message: (id) => `${id}: 3 cassette jams in 4 hrs. Predictive maintenance required.` },
  { rule_id:'BRE-010', severity:'LOW',      name:'Low Cash Warning',               message: (id) => `${id}: Cash at 8%. Replenishment needed within 2 hrs.` },
]

// Txn velocity history for chart (last 12 hours, per ATM group)
function genVelocityHistory() {
  const hours = Array.from({length:13}, (_,i) => {
    const h = new Date(); h.setHours(h.getHours() - (12 - i), 0, 0, 0)
    return h.toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit',hour12:false})
  })
  return hours.map(time => ({
    time,
    Mumbai: Math.floor(Math.random()*60 + 40),
    Delhi: Math.floor(Math.random()*50 + 30),
    Bangalore: Math.floor(Math.random()*45 + 25),
    Chennai: Math.floor(Math.random()*30 + 15),
  }))
}

const INITIAL_ALARMS = [
  { id:1, atm_id:'ATM-MUM-004', city:'Mumbai', rule_id:'BRE-002', severity:'CRITICAL', name:'Dispense-Balance Mismatch',    message:'ATM-MUM-004: EJ dispense ₹8,500 vs ledger debit ₹0. Investigate immediately.', ts:'10:31:07', ack:false },
  { id:2, atm_id:'ATM-CHE-002', city:'Chennai', rule_id:'BRE-001', severity:'CRITICAL', name:'Cash-Not-Dispensed Spike',   message:'ATM-CHE-002: CND rate 5/hr — exceeds threshold 3/hr. Possible cash trap.',      ts:'10:38:14', ack:false },
  { id:3, atm_id:'ATM-DEL-001', city:'Delhi',   rule_id:'BRE-004', severity:'HIGH',     name:'Excessive PIN Failures',      message:'ATM-DEL-001: 7 PIN fails / 30 min from 3 different cards. Skimming indicator.', ts:'10:41:52', ack:false },
  { id:4, atm_id:'ATM-BLR-001', city:'Bangalore', rule_id:'BRE-003', severity:'HIGH',   name:'Journal Sequence Gap',        message:'ATM-BLR-001: EJ seq gap 4712→4718. Missing 5 records. Possible tampering.',    ts:'10:44:03', ack:true  },
  { id:5, atm_id:'ATM-MUM-002', city:'Mumbai', rule_id:'BRE-006', severity:'HIGH',     name:'Transaction Velocity Spike',  message:'ATM-MUM-002: Velocity 31 TXN/hr vs 12 baseline (158% spike).',                  ts:'10:46:19', ack:false },
  { id:6, atm_id:'ATM-PUN-001', city:'Pune',   rule_id:'BRE-008', severity:'MEDIUM',   name:'EJ Upload Timeout',           message:'ATM-PUN-001: No EJ upload for 97 min. Central sync failed.',                    ts:'10:47:33', ack:false },
  { id:7, atm_id:'ATM-DEL-004', city:'Delhi',  rule_id:'BRE-008', severity:'MEDIUM',   name:'ATM Offline',                 message:'ATM-DEL-004: Offline since 07:03. No heartbeat for 3h 47m.',                   ts:'07:03:00', ack:false },
]

export function useEJCommandCenter() {
  const [atms, setAtms] = useState(INITIAL_ATMS)
  const [alarms, setAlarms] = useState(INITIAL_ALARMS)
  const [velocityData] = useState(genVelocityHistory)
  const [tick, setTick] = useState(0)
  const [selectedAtm, setSelectedAtm] = useState(null)
  const [filters, setFilters] = useState({ state:'', city:'', branch:'', search:'' })

  // Simulate live data — tick every 4 seconds
  useEffect(() => {
    const interval = setInterval(() => {
      setTick(t => t + 1)
      // Randomly update a few ATM velocities
      setAtms(prev => prev.map(atm => {
        if (atm.status === 'OFFLINE') return atm
        const delta = Math.floor(Math.random() * 5) - 2
        const newVelocity = Math.max(0, atm.txn_velocity + delta)
        const newTxnToday = atm.txn_today + (Math.random() > 0.5 ? 1 : 0)
        const newCash = atm.risk === 'CRITICAL' ? Math.max(0, atm.cash_pct - 0.3) : atm.cash_pct
        return { ...atm, txn_velocity: newVelocity, txn_today: newTxnToday, cash_pct: parseFloat(newCash.toFixed(1)) }
      }))
    }, 4000)
    return () => clearInterval(interval)
  }, [])

  // Randomly generate a new alarm every 12–20 seconds
  useEffect(() => {
    const interval = setInterval(() => {
      const atm = INITIAL_ATMS[Math.floor(Math.random() * INITIAL_ATMS.length)]
      const rule = BRE_RULES[Math.floor(Math.random() * BRE_RULES.length)]
      const now = new Date()
      const ts = now.toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false})
      setAlarms(prev => [{
        id: Date.now(),
        atm_id: atm.atm_id,
        city: atm.city,
        rule_id: rule.rule_id,
        severity: rule.severity,
        name: rule.name,
        message: rule.message(atm.atm_id),
        ts,
        ack: false,
      }, ...prev.slice(0, 49)])
    }, 14000)
    return () => clearInterval(interval)
  }, [])

  const ackAlarm = useCallback((id) => {
    setAlarms(prev => prev.map(a => a.id === id ? { ...a, ack: true } : a))
  }, [])

  const filteredAtms = atms.filter(a => {
    if (filters.state  && a.state  !== filters.state)  return false
    if (filters.city   && a.city   !== filters.city)   return false
    if (filters.branch && !a.branch.toLowerCase().includes(filters.branch.toLowerCase())) return false
    if (filters.search && !a.atm_id.toLowerCase().includes(filters.search.toLowerCase())) return false
    return true
  })

  const kpis = {
    total: atms.length,
    online: atms.filter(a => a.status === 'ONLINE').length,
    critical: atms.filter(a => a.risk === 'CRITICAL').length,
    high: atms.filter(a => a.risk === 'HIGH').length,
    degraded: atms.filter(a => a.risk === 'DEGRADED').length,
    offline: atms.filter(a => a.status === 'OFFLINE').length,
    totalTxnToday: atms.reduce((s,a) => s + a.txn_today, 0),
    unackedAlarms: alarms.filter(a => !a.ack).length,
    avgCash: Math.round(atms.filter(a=>a.status==='ONLINE').reduce((s,a)=>s+a.cash_pct,0) / atms.filter(a=>a.status==='ONLINE').length),
  }

  const states = [...new Set(atms.map(a => a.state))]
  const cities = [...new Set(atms.filter(a => !filters.state || a.state === filters.state).map(a => a.city))]

  return { atms, filteredAtms, alarms, velocityData, kpis, selectedAtm, setSelectedAtm, filters, setFilters, ackAlarm, tick, states, cities }
}

import { useState } from 'react'

const BRE_RULES = [
  {
    id: 'CASH_NOT_DISPENSED', name: 'Cash Not Dispensed', severity: 'CRITICAL',
    category: 'Transaction Integrity',
    description: 'EJ shows withdrawal debit but no cash dispensed event within 30s',
    rego_conditions: ['input.txn_type == "WITHDRAWAL"', 'input.dispense_event == null', 'input.window_seconds <= 30'],
    notify_roles: ['branch_manager','zonal_manager','regional_head','ops_reviewer'],
    channels: {
      branch_manager:  { onscreen:true, whatsapp:true,  email:true,  mandatory:['onscreen','whatsapp'] },
      zonal_manager:   { onscreen:true, whatsapp:true,  email:true,  mandatory:['onscreen'] },
      regional_head:   { onscreen:true, whatsapp:false, email:true,  mandatory:['onscreen'] },
      ops_reviewer:    { onscreen:true, whatsapp:true,  email:true,  mandatory:['onscreen','whatsapp'] },
    },
    escalation: { unacked_minutes:10, then_notify:'national_head', then_channels:['whatsapp','email'] },
    status:'ACTIVE', version:3, last_edited_by:'compliance@bank.in', last_approved_by:'itadmin@bank.in', last_changed:'2026-06-10', pending_change:null,
  },
  {
    id: 'CASH_NEAR_EMPTY', name: 'Cash Near Empty', severity: 'HIGH',
    category: 'Cash Management',
    description: 'ATM cash level drops below configured threshold (default 15%)',
    rego_conditions: ['input.cash_pct < data.config.cash_alert_threshold'],
    notify_roles: ['branch_manager','zonal_manager','ops_reviewer'],
    channels: {
      branch_manager:  { onscreen:true, whatsapp:true,  email:true,  mandatory:['onscreen','whatsapp'] },
      zonal_manager:   { onscreen:true, whatsapp:false, email:true,  mandatory:['onscreen'] },
      ops_reviewer:    { onscreen:true, whatsapp:false, email:true,  mandatory:['onscreen'] },
    },
    escalation: { unacked_minutes:30, then_notify:'zonal_manager', then_channels:['email'] },
    status:'ACTIVE', version:5, last_edited_by:'compliance@bank.in', last_approved_by:'itadmin@bank.in', last_changed:'2026-06-01', pending_change:null,
  },
  {
    id: 'CARD_RETENTION', name: 'Card Retention', severity: 'HIGH',
    category: 'Customer Impact',
    description: 'ATM retained customer card without authorization or after timeout',
    rego_conditions: ['input.card_retained == true', 'input.authorized_retention == false'],
    notify_roles: ['branch_manager','zonal_manager','ops_reviewer'],
    channels: {
      branch_manager:  { onscreen:true, whatsapp:true,  email:true,  mandatory:['onscreen','whatsapp'] },
      zonal_manager:   { onscreen:true, whatsapp:false, email:true,  mandatory:['onscreen'] },
      ops_reviewer:    { onscreen:true, whatsapp:true,  email:true,  mandatory:['onscreen'] },
    },
    escalation: { unacked_minutes:20, then_notify:'regional_head', then_channels:['email'] },
    status:'ACTIVE', version:2, last_edited_by:'compliance@bank.in', last_approved_by:'itadmin@bank.in', last_changed:'2026-05-20', pending_change:null,
  },
  {
    id: 'DISPENSE_MISMATCH', name: 'Dispense Amount Mismatch', severity: 'CRITICAL',
    category: 'Transaction Integrity',
    description: 'EJ dispensed amount differs from requested amount by more than ₹100',
    rego_conditions: ['abs(input.dispensed_amount - input.requested_amount) > 100'],
    notify_roles: ['branch_manager','zonal_manager','regional_head','ops_reviewer'],
    channels: {
      branch_manager:  { onscreen:true, whatsapp:true,  email:true,  mandatory:['onscreen','whatsapp'] },
      zonal_manager:   { onscreen:true, whatsapp:true,  email:true,  mandatory:['onscreen','whatsapp'] },
      regional_head:   { onscreen:true, whatsapp:false, email:true,  mandatory:['onscreen'] },
      ops_reviewer:    { onscreen:true, whatsapp:true,  email:true,  mandatory:['onscreen','whatsapp'] },
    },
    escalation: { unacked_minutes:15, then_notify:'national_head', then_channels:['whatsapp'] },
    status:'ACTIVE', version:1, last_edited_by:'compliance@bank.in', last_approved_by:'itadmin@bank.in', last_changed:'2026-06-05', pending_change:null,
  },
  {
    id: 'HIGH_TXN_VELOCITY', name: 'High Transaction Velocity', severity: 'HIGH',
    category: 'Fraud Signal',
    description: 'ATM processes more than 50 transactions in any 15-minute window',
    rego_conditions: ['input.txn_count_15m > data.config.velocity_threshold'],
    notify_roles: ['zonal_manager','ops_reviewer','fraud_analyst'],
    channels: {
      zonal_manager:  { onscreen:true, whatsapp:false, email:true, mandatory:['onscreen'] },
      ops_reviewer:   { onscreen:true, whatsapp:false, email:true, mandatory:['onscreen'] },
      fraud_analyst:  { onscreen:true, whatsapp:false, email:true, mandatory:['onscreen'] },
    },
    escalation: { unacked_minutes:45, then_notify:'regional_head', then_channels:['email'] },
    status:'ACTIVE', version:4, last_edited_by:'compliance@bank.in', last_approved_by:'itadmin@bank.in', last_changed:'2026-05-28', pending_change:null,
  },
  {
    id: 'COMM_FAILURE', name: 'Communication Failure >15m', severity: 'MEDIUM',
    category: 'Availability',
    description: 'ATM has not sent EJ heartbeat for more than 15 minutes',
    rego_conditions: ['input.last_heartbeat_minutes > 15'],
    notify_roles: ['branch_manager','ops_reviewer'],
    channels: {
      branch_manager:  { onscreen:true, whatsapp:false, email:true, mandatory:['onscreen'] },
      ops_reviewer:    { onscreen:true, whatsapp:false, email:true, mandatory:['onscreen'] },
    },
    escalation: { unacked_minutes:60, then_notify:'zonal_manager', then_channels:['email'] },
    status:'ACTIVE', version:2, last_edited_by:'compliance@bank.in', last_approved_by:'itadmin@bank.in', last_changed:'2026-05-15', pending_change:null,
  },
  {
    id: 'DUPLICATE_TXN', name: 'Duplicate Transaction Detected', severity: 'CRITICAL',
    category: 'Transaction Integrity',
    description: 'Same card + amount + ATM within 90 seconds — possible double-charge',
    rego_conditions: ['input.same_card_txn_90s == true', 'input.amount_match == true'],
    notify_roles: ['branch_manager','zonal_manager','ops_reviewer'],
    channels: {
      branch_manager:  { onscreen:true, whatsapp:true,  email:true, mandatory:['onscreen','whatsapp'] },
      zonal_manager:   { onscreen:true, whatsapp:true,  email:true, mandatory:['onscreen'] },
      ops_reviewer:    { onscreen:true, whatsapp:true,  email:true, mandatory:['onscreen','whatsapp'] },
    },
    escalation: { unacked_minutes:10, then_notify:'regional_head', then_channels:['whatsapp','email'] },
    status:'ACTIVE', version:2, last_edited_by:'compliance@bank.in', last_approved_by:'itadmin@bank.in', last_changed:'2026-06-12', pending_change:null,
  },
  {
    id: 'LOW_PAPER', name: 'Receipt Paper Near Empty', severity: 'LOW',
    category: 'Maintenance',
    description: 'ATM receipt paper roll below 10%',
    rego_conditions: ['input.paper_pct < 10'],
    notify_roles: ['branch_manager'],
    channels: {
      branch_manager:  { onscreen:true, whatsapp:false, email:true, mandatory:['onscreen'] },
    },
    escalation: null,
    status:'ACTIVE', version:1, last_edited_by:'compliance@bank.in', last_approved_by:'itadmin@bank.in', last_changed:'2026-04-10', pending_change:null,
  },
  {
    id: 'AFTER_HOURS_CRIT', name: 'After-Hours CRITICAL Activity', severity: 'HIGH',
    category: 'Security',
    description: 'CRITICAL transaction event between 23:00-06:00 IST — elevated fraud risk',
    rego_conditions: ['input.hour >= 23', 'input.severity == "CRITICAL"'],
    notify_roles: ['ops_reviewer','fraud_analyst','zonal_manager'],
    channels: {
      ops_reviewer:   { onscreen:true, whatsapp:true,  email:true,  mandatory:['onscreen','whatsapp'] },
      fraud_analyst:  { onscreen:true, whatsapp:false, email:true,  mandatory:['onscreen'] },
      zonal_manager:  { onscreen:true, whatsapp:true,  email:false, mandatory:['onscreen'] },
    },
    escalation: { unacked_minutes:20, then_notify:'regional_head', then_channels:['whatsapp'] },
    status:'PENDING', version:0, last_edited_by:'compliance@bank.in', last_approved_by:null, last_changed:'2026-06-17',
    pending_change: { submitted_by:'compliance@bank.in', submitted_at:'2026-06-17T14:32:00Z', description:'New rule for overnight security monitoring at high-risk ATMs', awaiting:'bank_it_admin' },
  },
  {
    id: 'EJ_PARSE_FAIL', name: 'EJ Parse Failure', severity: 'MEDIUM',
    category: 'Data Quality',
    description: 'LLM confidence below threshold for more than 3 fields in one EJ file',
    rego_conditions: ['input.low_confidence_fields > data.config.max_weak_fields'],
    notify_roles: ['ops_reviewer','ml_engineer'],
    channels: {
      ops_reviewer:  { onscreen:true, whatsapp:false, email:true, mandatory:['onscreen'] },
      ml_engineer:   { onscreen:true, whatsapp:false, email:true, mandatory:['onscreen'] },
    },
    escalation: null,
    status:'ACTIVE', version:3, last_edited_by:'compliance@bank.in', last_approved_by:'itadmin@bank.in', last_changed:'2026-06-08', pending_change:null,
  },
]

export { BRE_RULES }

export function useBRERules() {
  const [rules, setRules] = useState(BRE_RULES.map(r => ({ ...r })))
  const [selectedRule, setSelectedRule] = useState(null)

  const approveChange = (ruleId) => {
    setRules(prev => prev.map(r => r.id === ruleId ? {
      ...r,
      status: 'ACTIVE',
      version: r.version + 1,
      last_approved_by: 'itadmin@bank.in',
      last_changed: new Date().toISOString().split('T')[0],
      pending_change: null,
    } : r))
    setSelectedRule(prev => prev?.id === ruleId ? {
      ...prev,
      status: 'ACTIVE',
      version: prev.version + 1,
      last_approved_by: 'itadmin@bank.in',
      last_changed: new Date().toISOString().split('T')[0],
      pending_change: null,
    } : prev)
  }

  const rejectChange = (ruleId) => {
    setRules(prev => prev.map(r => r.id === ruleId ? {
      ...r,
      status: r.version > 0 ? 'ACTIVE' : 'DRAFT',
      pending_change: null,
    } : r))
    setSelectedRule(prev => prev?.id === ruleId ? {
      ...prev,
      status: prev.version > 0 ? 'ACTIVE' : 'DRAFT',
      pending_change: null,
    } : prev)
  }

  return { rules, selectedRule, setSelectedRule, approveChange, rejectChange }
}

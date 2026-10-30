import { useState, useMemo } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'
import { useBankContext } from '../../../shared/context/BankContext'
import useDecisions from '../hooks/useDecisions'
import { msg } from '../../../shared/messages'

// RBI return reason code mapping — mirrors modules/cts/rrf/models.py RBIReturnCode
const RBI_CODE_MAP = {
  'Signature mismatch confirmed':       { code: '06', desc: msg('UI_DECISIONSLOG_DRAWER_SIGNATURE_DIFFERS') },
  'Amount alteration detected':         { code: '07', desc: msg('UI_DECISIONSLOG_ALTERATIONS_REQUIRE_AUTHENTICATION') },
  'Insufficient funds':                 { code: '01', desc: msg('UI_DECISIONSLOG_FUNDS_INSUFFICIENT') },
  'Account dormant / frozen':           { code: '13', desc: msg('UI_DECISIONSLOG_ACCOUNT_CLOSED_TRANSFERRED_NOT_TRACE') },
  'Post-dated cheque':                  { code: '14', desc: msg('UI_DECISIONSLOG_CHEQUE_POST_DATED') },
  'Mutilated / damaged cheque':         { code: '15', desc: msg('UI_DECISIONSLOG_CHEQUE_STALE_MUTILATED_TORN') },
  'Words and figures differ':           { code: '16', desc: msg('UI_DECISIONSLOG_AMOUNT_IN_WORDS_AND_FIGURES') },
  'No specimen on file — cannot verify':{ code: '04', desc: msg('UI_DECISIONSLOG_REFER_TO_DRAWER') },
  'Payee name discrepancy':             { code: '09', desc: msg('UI_DECISIONSLOG_PAYEE_S_ENDORSEMENT_REQUIRED') },
  'SIG_MISMATCH':                       { code: '06', desc: msg('UI_DECISIONSLOG_DRAWER_SIGNATURE_DIFFERS') },
  'FRAUD_RISK':                         { code: '04', desc: msg('UI_DECISIONSLOG_REFER_TO_DRAWER') },
  'ALTERATION':                         { code: '07', desc: msg('UI_DECISIONSLOG_ALTERATIONS_REQUIRE_AUTHENTICATION') },
  'DEFAULT':                            { code: '04', desc: msg('UI_DECISIONSLOG_REFER_TO_DRAWER') },
}
function getRbiCode(reason) { return RBI_CODE_MAP[reason] || RBI_CODE_MAP['DEFAULT'] }

// SESSION_ID built dynamically inside component using bankIfsc

// SHAP feature contributions — positive = raises fraud score, negative = lowers it
// Values in [-1, +1] range — XGBoost TreeExplainer output
const DECISIONS = [
  {
    id: 'CHQ-2026-001901', micr: '400160001901', account: '****4521', amount: '₹[1L-5L]', payee: 'R***',
    reason: 'FRAUD_RISK', outcome: 'STP_RETURN', agent_ms: 412, fraud: 0.91,
    ngch: 'ACK-7821', filed: '11:02:14', reviewer: null,
    return_reason: 'FRAUD_RISK',
    iet_deadline: '2026-06-19T13:30:00Z', returned_at: '2026-06-19T11:02:14Z',
    presenting_ifsc: 'HDFC0001234',
    audit_hash: 'a3f8c1d2e9b54670f1a2c3d4e5f67890a1b2c3d4e5f678901234567890abcdef',
    immudb_seq: 18901,
    ocr_engines_used: ['got-ocr2.0:cascade-1', 'indic_ocr:paddle/devanagari'],
    indic_ocr_kill_switch_active: false,
    shap: {
      score: 0.91,
      features: [
        { name: 'sig_mismatch_delta',  value: +0.38, label: msg('UI_DECISIONSLOG_SIGNATURE_DEVIATION_VS_SPECIMEN') },
        { name: 'ink_anomaly_score',   value: +0.21, label: msg('UI_DECISIONSLOG_INK_PHYSICS_ANOMALY_DETECTED') },
        { name: 'prev_returns_90d',    value: +0.14, label: msg('UI_DECISIONSLOG_ACCOUNT_2_RETURNS_IN_90') },
        { name: 'amount_risk_tier',    value: +0.11, label: msg('UI_DECISIONSLOG_AMOUNT_IN_ELEVATED_RISK_BRACKET') },
        { name: 'micr_check_digit',    value: +0.07, label: msg('UI_DECISIONSLOG_MICR_CHECK_DIGIT_INCONSISTENCY') },
        { name: 'account_age_days',    value: -0.04, label: msg('UI_DECISIONSLOG_ACCOUNT_AGE_MATURE_LOWER_RISK') },
        { name: 'payee_match_score',   value: -0.02, label: msg('UI_DECISIONSLOG_PAYEE_NAME_LOW_RISK_PATTERN') },
        { name: 'vault_hit',           value: -0.03, label: msg('UI_DECISIONSLOG_SIGNATURE_VAULT_HIT_SPECIMEN_PRESENT') },
      ],
    },
  },
  {
    id: 'CHQ-2026-001900', micr: '400160001900', account: '****7103', amount: '₹[<1L]', payee: 'S***',
    reason: 'CLEAR', outcome: 'STP_CONFIRM', agent_ms: 388, fraud: 0.08,
    ngch: 'ACK-7820', filed: '11:01:52', reviewer: null,
    return_reason: null, iet_deadline: null, returned_at: null,
    presenting_ifsc: 'ICIC0001234',
    audit_hash: 'b4e9d2c3f0a1578690b2c3d4e5f67891b2c3d4e5f67890234567890abcdef12',
    immudb_seq: 18900,
    ocr_engines_used: ['got-ocr2.0:cascade-1'],
    indic_ocr_kill_switch_active: false,
    shap: {
      score: 0.08,
      features: [
        { name: 'sig_mismatch_delta',  value: -0.31, label: msg('UI_DECISIONSLOG_SIGNATURE_CLOSELY_MATCHES_SPECIMEN') },
        { name: 'vault_hit',           value: -0.22, label: msg('UI_DECISIONSLOG_VAULT_HIT_SPECIMEN_RETRIEVED') },
        { name: 'account_age_days',    value: -0.15, label: msg('UI_DECISIONSLOG_MATURE_ACCOUNT_9_YEARS') },
        { name: 'payee_match_score',   value: -0.10, label: msg('UI_DECISIONSLOG_PAYEE_PATTERN_CONSISTENT') },
        { name: 'ocr_confidence',      value: -0.09, label: msg('UI_DECISIONSLOG_OCR_CONFIDENCE_HIGH_0_97') },
        { name: 'prev_returns_90d',    value: +0.01, label: msg('UI_DECISIONSLOG_NO_PRIOR_RETURNS') },
        { name: 'amount_risk_tier',    value: +0.04, label: msg('UI_DECISIONSLOG_LOW_VALUE_BRACKET') },
        { name: 'ink_anomaly_score',   value: +0.02, label: msg('UI_DECISIONSLOG_NO_INK_ANOMALY_DETECTED') },
      ],
    },
  },
  {
    id: 'CHQ-2026-001899', micr: '400160001899', account: '****2290', amount: '₹[5L-10L]', payee: 'M***',
    reason: 'VAULT_MISS', outcome: 'HUMAN_REVIEW', agent_ms: 201, fraud: null,
    ngch: 'ACK-7819', filed: '10:58:31', reviewer: 'Rahul S.',
    return_reason: null, iet_deadline: null, returned_at: null,
    presenting_ifsc: 'SBIN0001234',
    audit_hash: 'c5f0e3d4a1b2689701c3d4e5f67892c3d4e5f67890345678901abcdef123456',
    immudb_seq: 18899,
    ocr_engines_used: ['got-ocr2.0:cascade-1'],
    indic_ocr_kill_switch_active: true,
    shap: null, // vault miss — no fraud score computed, routed to human review
  },
  {
    id: 'CHQ-2026-001898', micr: '400160001898', account: '****8812', amount: '₹[<1L]', payee: 'A***',
    reason: 'ALTERATION', outcome: 'STP_RETURN', agent_ms: 544, fraud: 0.87,
    ngch: 'ACK-7818', filed: '10:55:09', reviewer: null,
    return_reason: 'Amount alteration detected',
    iet_deadline: '2026-06-19T13:30:00Z', returned_at: '2026-06-19T10:55:09Z',
    presenting_ifsc: 'AXIS0001234',
    audit_hash: 'd6a1f4e5b2c3790812d4e5f67893d4e5f67890456789012bcdef1234567890ab',
    immudb_seq: 18898,
    ocr_engines_used: ['got-ocr2.0:cascade-2', 'indic_ocr:ai4bharat/devanagari'],
    indic_ocr_kill_switch_active: false,
    shap: {
      score: 0.87,
      features: [
        { name: 'ink_anomaly_score',   value: +0.44, label: msg('UI_DECISIONSLOG_INK_PHYSICS_ANOMALY_CORRECTION_FLUID') },
        { name: 'paper_fibre_dist',    value: +0.22, label: msg('UI_DECISIONSLOG_PAPER_FIBRE_DISTORTION_AT_AMOUNT') },
        { name: 'amount_risk_tier',    value: +0.09, label: msg('UI_DECISIONSLOG_AMOUNT_RANGE_INCONSISTENCY') },
        { name: 'ocr_confidence',      value: +0.07, label: msg('UI_DECISIONSLOG_OCR_CONFIDENCE_DROP_AT_ALTERED') },
        { name: 'sig_mismatch_delta',  value: +0.05, label: msg('UI_DECISIONSLOG_MINOR_SIGNATURE_DEVIATION') },
        { name: 'vault_hit',           value: -0.05, label: msg('UI_DECISIONSLOG_VAULT_HIT_SPECIMEN_PRESENT') },
        { name: 'account_age_days',    value: -0.03, label: msg('UI_DECISIONSLOG_ACCOUNT_AGE_MODERATE') },
        { name: 'payee_match_score',   value: -0.02, label: msg('UI_DECISIONSLOG_PAYEE_NAME_CONSISTENT') },
      ],
    },
  },
  {
    id: 'CHQ-2026-001897', micr: '400160001897', account: '****3301', amount: '₹[1L-5L]', payee: 'P***',
    reason: 'CLEAR', outcome: 'STP_CONFIRM', agent_ms: 361, fraud: 0.12,
    ngch: 'ACK-7817', filed: '10:52:43', reviewer: null,
    return_reason: null, iet_deadline: null, returned_at: null,
    presenting_ifsc: 'HDFC0001234',
    audit_hash: 'e7b2a5f6c3d4801923e5f67894e5f67890567890123cdef2345678901abcdef3',
    immudb_seq: 18897,
    ocr_engines_used: ['got-ocr2.0:cascade-1'],
    indic_ocr_kill_switch_active: false,
    shap: {
      score: 0.12,
      features: [
        { name: 'sig_mismatch_delta',  value: -0.28, label: msg('UI_DECISIONSLOG_SIGNATURE_WELL_WITHIN_TOLERANCE') },
        { name: 'vault_hit',           value: -0.20, label: msg('UI_DECISIONSLOG_VAULT_HIT_SPECIMEN_RETRIEVED') },
        { name: 'ocr_confidence',      value: -0.14, label: msg('UI_DECISIONSLOG_OCR_CONFIDENCE_0_99') },
        { name: 'ink_anomaly_score',   value: -0.08, label: msg('UI_DECISIONSLOG_NO_INK_ANOMALY') },
        { name: 'account_age_days',    value: -0.06, label: msg('UI_DECISIONSLOG_LONG_STANDING_ACCOUNT') },
        { name: 'amount_risk_tier',    value: +0.08, label: msg('UI_DECISIONSLOG_AMOUNT_BRACKET_MINOR_FLAG') },
        { name: 'prev_returns_90d',    value: +0.04, label: msg('UI_DECISIONSLOG_ONE_RETURN_IN_90_DAYS') },
        { name: 'payee_match_score',   value: -0.03, label: msg('UI_DECISIONSLOG_PAYEE_CONSISTENT') },
      ],
    },
  },
  {
    id: 'CHQ-2026-001896', micr: '400160001896', account: '****5509', amount: '₹[>1Cr]', payee: 'N***',
    reason: 'HIGH_VALUE', outcome: 'HUMAN_REVIEW', agent_ms: 298, fraud: 0.44,
    ngch: 'ACK-7816', filed: '10:49:17', reviewer: 'Priya K.',
    return_reason: null, iet_deadline: null, returned_at: null,
    presenting_ifsc: 'ICIC0001234',
    audit_hash: 'f8c3b6a7d4e5912034f6a78905f67890678901234def3456789012bcdef456789',
    immudb_seq: 18896,
    ocr_engines_used: ['got-ocr2.0:cascade-1', 'indic_ocr:paddle/devanagari+gujarati'],
    indic_ocr_kill_switch_active: false,
    shap: {
      score: 0.44,
      features: [
        { name: 'amount_risk_tier',    value: +0.29, label: msg('UI_DECISIONSLOG_VERY_HIGH_VALUE_MANDATORY_REVIEW') },
        { name: 'sig_mismatch_delta',  value: +0.08, label: msg('UI_DECISIONSLOG_MILD_SIGNATURE_DEVIATION') },
        { name: 'prev_returns_90d',    value: +0.05, label: msg('UI_DECISIONSLOG_ONE_PRIOR_RETURN') },
        { name: 'micr_check_digit',    value: +0.02, label: msg('UI_DECISIONSLOG_MICR_NOMINAL') },
        { name: 'vault_hit',           value: -0.09, label: msg('UI_DECISIONSLOG_VAULT_HIT') },
        { name: 'ocr_confidence',      value: -0.08, label: msg('UI_DECISIONSLOG_OCR_HIGH_CONFIDENCE') },
        { name: 'ink_anomaly_score',   value: -0.05, label: msg('UI_DECISIONSLOG_NO_INK_ANOMALY') },
        { name: 'account_age_days',    value: -0.04, label: msg('UI_DECISIONSLOG_ESTABLISHED_ACCOUNT') },
      ],
    },
  },
  {
    id: 'CHQ-2026-001895', micr: '400160001895', account: '****1122', amount: '₹[<1L]', payee: 'V***',
    reason: 'CLEAR', outcome: 'STP_CONFIRM', agent_ms: 402, fraud: 0.05,
    ngch: 'ACK-7815', filed: '10:47:01', reviewer: null,
    return_reason: null, iet_deadline: null, returned_at: null,
    presenting_ifsc: 'SBIN0001234',
    audit_hash: 'a9d4c7b8e5f6023145a7b89016a78901789012345ef04567890123cdef567890',
    immudb_seq: 18895,
    ocr_engines_used: ['got-ocr2.0:cascade-1'],
    indic_ocr_kill_switch_active: false,
    shap: {
      score: 0.05,
      features: [
        { name: 'sig_mismatch_delta',  value: -0.35, label: msg('UI_DECISIONSLOG_SIGNATURE_EXACT_MATCH') },
        { name: 'vault_hit',           value: -0.25, label: msg('UI_DECISIONSLOG_VAULT_HIT') },
        { name: 'ink_anomaly_score',   value: -0.12, label: msg('UI_DECISIONSLOG_CLEAN_INK_PATTERNS') },
        { name: 'ocr_confidence',      value: -0.10, label: msg('UI_DECISIONSLOG_OCR_CONFIDENCE_0_98') },
        { name: 'account_age_days',    value: -0.07, label: msg('UI_DECISIONSLOG_LONG_STANDING_ACCOUNT') },
        { name: 'amount_risk_tier',    value: +0.02, label: msg('UI_DECISIONSLOG_LOW_VALUE_BRACKET') },
        { name: 'prev_returns_90d',    value: +0.01, label: msg('UI_DECISIONSLOG_NO_PRIOR_RETURNS') },
        { name: 'payee_match_score',   value: -0.01, label: msg('UI_DECISIONSLOG_PAYEE_CONSISTENT') },
      ],
    },
  },
  {
    id: 'CHQ-2026-001894', micr: '400160001894', account: '****6634', amount: '₹[1L-5L]', payee: 'D***',
    reason: 'SIG_MISMATCH', outcome: 'STP_RETURN', agent_ms: 478, fraud: 0.79,
    ngch: 'ACK-7814', filed: '10:44:22', reviewer: null,
    return_reason: 'Signature mismatch confirmed',
    iet_deadline: '2026-06-19T13:30:00Z', returned_at: '2026-06-19T10:44:22Z',
    presenting_ifsc: 'HDFC0001234',
    audit_hash: 'b0e5d8c9f6a7134256b8c90127b89012890123456f015678901234def678901a',
    immudb_seq: 18894,
    ocr_engines_used: ['got-ocr2.0:cascade-1'],
    indic_ocr_kill_switch_active: false,
    shap: {
      score: 0.79,
      features: [
        { name: 'sig_mismatch_delta',  value: +0.48, label: msg('UI_DECISIONSLOG_HIGH_SIGNATURE_DEVIATION_0_61') },
        { name: 'prev_returns_90d',    value: +0.12, label: msg('UI_DECISIONSLOG_1_PRIOR_SIGNATURE_RELATED_RETURN') },
        { name: 'ink_anomaly_score',   value: +0.08, label: msg('UI_DECISIONSLOG_MINOR_PEN_PRESSURE_INCONSISTENCY') },
        { name: 'amount_risk_tier',    value: +0.06, label: msg('UI_DECISIONSLOG_MID_VALUE_BRACKET') },
        { name: 'vault_hit',           value: -0.04, label: msg('UI_DECISIONSLOG_VAULT_HIT_SPECIMEN_USED_FOR') },
        { name: 'ocr_confidence',      value: -0.03, label: msg('UI_DECISIONSLOG_OCR_HIGH_CONFIDENCE') },
        { name: 'account_age_days',    value: -0.02, label: msg('UI_DECISIONSLOG_ESTABLISHED_ACCOUNT') },
        { name: 'payee_match_score',   value: -0.01, label: msg('UI_DECISIONSLOG_PAYEE_CONSISTENT') },
      ],
    },
  },
]

const FILTERS = ['All', 'STP_CONFIRM', 'STP_RETURN', 'HUMAN_REVIEW']
const SORT_COLS = ['fraud', 'agent_ms', 'filed', 'immudb_seq']

// ── CSV export ─────────────────────────────────────────────────────────────────
function buildCsv(rows) {
  const header = [msg('UI_COMMON_INSTRUMENT_ID'),msg('CTS_WF_BUCKETCFG_COL_ACCOUNT'),msg('CTS_OUT_CUSTODY_COL_AMOUNT'),msg('UI_COMMON_REASON'),msg('UI_COMMON_OUTCOME'),msg('UI_DECISIONSLOG_AGENT_MS'),msg('UI_COMMON_FRAUD_SCORE'),msg('UI_DECISIONSLOG_NGCH_REF'),msg('UI_COMMON_FILED'),msg('UI_ALLOCATIONADMIN_REVIEWER'),msg('UI_DECISIONSLOG_IMMUDB_SEQ'),msg('UI_DECISIONSLOG_AUDIT_HASH')]
  const lines = rows.map(d => [
    d.id, d.account, d.amount, d.reason, d.outcome,
    d.agent_ms, d.fraud ?? '', d.ngch, d.filed,
    d.reviewer ?? 'STP_AGENT', d.immudb_seq, d.audit_hash,
  ].map(v => `"${v}"`).join(','))
  return [header.join(','), ...lines].join('\n')
}

function downloadText(content, filename, mime) {
  const blob = new Blob([content], { type: mime })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  URL.revokeObjectURL(url)
}

// ── RRF XML ────────────────────────────────────────────────────────────────────
function buildRrfXml(returns, sessionMeta) {
  const now = new Date().toISOString().replace(/\.\d+Z$/, 'Z')
  const filedCount = returns.filter(r => r.returned_at && r.iet_deadline && r.returned_at <= r.iet_deadline).length
  const items = returns.map(r => {
    const rbi = getRbiCode(r.return_reason || r.reason)
    const withinIet = r.returned_at && r.iet_deadline
      ? new Date(r.returned_at) <= new Date(r.iet_deadline) : true
    return `    <ReturnItem>
      <InstrumentID>${r.id}</InstrumentID>
      <MICRCode>${r.micr}</MICRCode>
      <ReturnReasonCode>${rbi.code}</ReturnReasonCode>
      <ReturnReasonDescription>${rbi.desc}</ReturnReasonDescription>
      <DraweeIFSC>${sessionMeta.bank_ifsc}</DraweeIFSC>
      <PresentingIFSC>${r.presenting_ifsc}</PresentingIFSC>
      <IETDeadline>${r.iet_deadline || ''}</IETDeadline>
      <ReturnedAt>${r.returned_at || now}</ReturnedAt>
      <FiledWithinIET>${withinIet ? 'true' : 'false'}</FiledWithinIET>
      <DecidedBy>${r.reviewer || 'STP_AGENT'}</DecidedBy>
      <AmountRange>${r.amount}</AmountRange>
      <ImmudbSeq>${r.immudb_seq}</ImmudbSeq>
      <AuditHash>${r.audit_hash}</AuditHash>
    </ReturnItem>`
  }).join('\n')
  return `<?xml version="1.0" encoding="UTF-8"?>
<ReturnReasonFile xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="2.0">
  <Header>
    <BankIFSC>${sessionMeta.bank_ifsc}</BankIFSC>
    <SessionID>${sessionMeta.session_id}</SessionID>
    <GeneratedAt>${now}</GeneratedAt>
    <TotalReturns>${returns.length}</TotalReturns>
    <FiledWithinIETCount>${filedCount}</FiledWithinIETCount>
  </Header>
  <Returns>
${items}
  </Returns>
</ReturnReasonFile>`
}

// ── SHAP Feature Bar ──────────────────────────────────────────────────────────
function ShapBar({ value, isDark }) {
  const pct  = Math.round(Math.abs(value) * 100)
  const pos  = value >= 0
  const fill = pos
    ? (isDark ? 'bg-red-500' : 'bg-red-500')
    : (isDark ? 'bg-emerald-500' : 'bg-emerald-500')
  return (
    <div className="flex items-center gap-2">
      {/* negative side */}
      <div className="w-24 flex justify-end">
        {!pos && (
          <div className={`h-2.5 rounded-full ${fill}`} style={{ width: `${pct * 2}%`, maxWidth: '96px' }} />
        )}
      </div>
      <span className={`w-10 text-[10px] font-mono text-center font-semibold ${pos ? (isDark ? 'text-red-400' : 'text-red-600') : (isDark ? 'text-emerald-400' : 'text-emerald-600')}`}>
        {pos ? '+' : ''}{value.toFixed(2)}
      </span>
      {/* positive side */}
      <div className="w-24">
        {pos && (
          <div className={`h-2.5 rounded-full ${fill}`} style={{ width: `${pct * 2}%`, maxWidth: '96px' }} />
        )}
      </div>
    </div>
  )
}

// ── SHAP Detail Panel ─────────────────────────────────────────────────────────
function ShapPanel({ decision, onClose, isDark }) {
  const th = {
    overlay: 'fixed inset-0 bg-black/60 z-50 flex items-start justify-end p-4',
    panel:   isDark ? 'bg-navy-900 border-white/10 text-white' : 'bg-white border-slate-200 text-slate-900',
    head:    isDark ? 'border-white/10' : 'border-slate-200',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    label:   isDark ? 'text-slate-300' : 'text-slate-700',
    mono:    isDark ? 'bg-navy-950 text-emerald-400 border-white/10' : 'bg-slate-50 text-emerald-700 border-slate-200',
    hash:    isDark ? 'text-slate-500' : 'text-slate-400',
    badge:   (c) => c === 'red'
      ? (isDark ? 'bg-red-500/15 text-red-400 border-red-500/30' : 'bg-red-50 text-red-600 border-red-200')
      : (isDark ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30' : 'bg-emerald-50 text-emerald-700 border-emerald-200'),
    closeBtn: isDark ? 'hover:bg-white/8 text-slate-400' : 'hover:bg-slate-100 text-slate-500',
  }

  const { shap, audit_hash, immudb_seq, ocr_engines_used = [], indic_ocr_kill_switch_active = false } = decision
  const fraudPct = shap ? Math.round(shap.score * 100) : null
  const fraudColor = fraudPct > 70 ? 'red' : fraudPct > 40 ? 'amber' : 'green'

  return (
    <div className={th.overlay} onClick={onClose}>
      <div className={`w-full max-w-lg h-full max-h-[calc(100vh-2rem)] rounded-2xl border shadow-2xl flex flex-col overflow-hidden ${th.panel}`}
        onClick={e => e.stopPropagation()}>

        {/* Header */}
        <div className={`flex items-center justify-between px-5 py-3.5 border-b ${th.head}`}>
          <div>
            <div className="text-sm font-semibold">{msg('UI_DECISIONSLOG_AI_EXPLAINABILITY_SHAP_BREAKDOWN')}</div>
            <div className={`text-[11px] font-mono ${th.muted}`}>{decision.id}</div>
          </div>
          <button onClick={onClose}
            className={`w-7 h-7 rounded-lg flex items-center justify-center text-sm ${th.closeBtn}`}>✕</button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">

          {/* Fraud score */}
          {shap ? (
            <div>
              <div className={`text-[10px] uppercase tracking-wider ${th.muted} mb-2`}>{msg('UI_DECISIONSLOG_XGBOOST_FRAUD_SCORE')}</div>
              <div className="flex items-center gap-3">
                <span className={`text-3xl font-bold font-mono ${
                  fraudPct > 70 ? (isDark ? 'text-red-400' : 'text-red-600')
                  : fraudPct > 40 ? (isDark ? 'text-amber-400' : 'text-amber-600')
                  : (isDark ? 'text-emerald-400' : 'text-emerald-600')
                }`}>{fraudPct}%</span>
                <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${th.badge(fraudColor)}`}>
                  {fraudPct > 70 ? 'HIGH RISK' : fraudPct > 40 ? 'MEDIUM RISK' : 'LOW RISK'}
                </span>
              </div>
            </div>
          ) : (
            <div className={`text-sm ${th.muted}`}>
             {msg('UI_DECISIONSLOG_VAULT_MISS_FRAUD_SCORING_NOT')}
            </div>
          )}

          {/* SHAP feature table */}
          {shap && (
            <div>
              <div className={`text-[10px] uppercase tracking-wider ${th.muted} mb-3`}>
               {msg('UI_DECISIONSLOG_SHAP_FEATURE_CONTRIBUTIONS')}
                <span className={`ml-2 normal-case ${th.muted}`}>{msg('UI_DECISIONSLOG_RED_RAISES_SCORE_GREEN_LOWERS')}</span>
              </div>
              <div className="space-y-2">
                {[...shap.features].sort((a, b) => Math.abs(b.value) - Math.abs(a.value)).map(f => (
                  <div key={f.name} className="flex items-center gap-3">
                    <ShapBar value={f.value} isDark={isDark} />
                    <span className={`text-[11px] flex-1 ${th.label}`}>{f.label}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Alteration detail — special callout if ink/fibre anomaly drove the decision */}
          {shap && shap.features.find(f => f.name === 'ink_anomaly_score' && f.value > 0.15) && (
            <div className={`rounded-xl border px-4 py-3 ${isDark ? 'bg-orange-500/8 border-orange-500/25' : 'bg-orange-50 border-orange-200'}`}>
              <div className={`text-[10px] font-semibold uppercase tracking-wider mb-1 ${isDark ? 'text-orange-400' : 'text-orange-700'}`}>
               {msg('UI_DECISIONSLOG_PHYSICAL_ANOMALY_DETECTED')}
              </div>
              <p className={`text-[11px] ${isDark ? 'text-orange-300' : 'text-orange-800'}`}>
               {msg('UI_DECISIONSLOG_INK_PHYSICS_ANALYSIS_QWEN2_VL')}
              </p>
            </div>
          )}

          {/* OCR Engines Used */}
          <div>
            <div className={`text-[10px] uppercase tracking-wider ${th.muted} mb-2`}>
             {msg('UI_DECISIONSLOG_OCR_ENGINES_USED')}
              {indic_ocr_kill_switch_active && (
                <span className={`ml-2 normal-case px-1.5 py-0.5 rounded border text-[9px] font-semibold ${
                  isDark ? 'bg-amber-500/15 border-amber-500/30 text-amber-400' : 'bg-amber-50 border-amber-300 text-amber-700'
                }`}>{msg('UI_DECISIONSLOG_INDICOCR_KILL_SWITCH_KC')}</span>
              )}
            </div>
            {ocr_engines_used.length === 0 ? (
              <span className={`text-xs ${th.muted}`}>{msg('UI_DECISIONSLOG_NOT_RECORDED_INWARD_PATH_NGCH')}</span>
            ) : (
              <div className="space-y-1.5">
                {ocr_engines_used.map((eng, i) => {
                  const [model, detail] = eng.split(':')
                  const isIndic = model === 'indic_ocr'
                  const isCascade2 = eng.includes('cascade-2')
                  return (
                    <div key={i} className="flex items-center gap-2">
                      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                        isIndic ? (isDark ? 'bg-violet-400' : 'bg-violet-500') : (isDark ? 'bg-sky-400' : 'bg-sky-500')
                      }`} />
                      <span className={`font-mono text-[11px] ${th.label}`}>{model}</span>
                      {detail && (
                        <span className={`text-[10px] px-1.5 py-0.5 rounded border ${
                          isIndic
                            ? (isDark ? 'border-violet-500/30 bg-violet-500/10 text-violet-300' : 'border-violet-300 bg-violet-50 text-violet-700')
                            : (isDark ? 'border-sky-500/30 bg-sky-500/10 text-sky-300' : 'border-sky-300 bg-sky-50 text-sky-700')
                        }`}>{detail}</span>
                      )}
                      {isCascade2 && (
                        <span className={`text-[9px] ${th.muted}`}>{msg('UI_DECISIONSLOG_FALLBACK_TIER')}</span>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          {/* Decision outcome */}
          <div>
            <div className={`text-[10px] uppercase tracking-wider ${th.muted} mb-2`}>{msg('UI_COMMON_DECISION')}</div>
            <div className="flex items-center gap-2">
              <span className={`px-2.5 py-1 rounded-full text-xs font-semibold ${
                decision.outcome === 'STP_CONFIRM' ? (isDark ? 'bg-emerald-500/15 text-emerald-400' : 'bg-emerald-50 text-emerald-700')
                : decision.outcome === 'STP_RETURN' ? (isDark ? 'bg-red-500/15 text-red-400' : 'bg-red-50 text-red-700')
                : (isDark ? 'bg-amber-500/15 text-amber-400' : 'bg-amber-50 text-amber-700')
              }`}>{decision.outcome.replace(/_/g, ' ')}</span>
              <span className={`text-xs ${th.muted}`}>{decision.reason.replace(/_/g, ' ')}</span>
              {decision.reviewer && (
                <span className={`text-xs ${th.muted}`}>{msg('UI_DECISIONSLOG_REVIEWED_BY')} <strong>{decision.reviewer}</strong></span>
              )}
            </div>
          </div>

          {/* Immutable audit record */}
          <div>
            <div className={`text-[10px] uppercase tracking-wider ${th.muted} mb-2`}>
             {msg('UI_DECISIONSLOG_IMMUTABLE_AUDIT_RECORD_IMMUDB')}
            </div>
            <div className={`rounded-lg border p-3 text-[10px] font-mono space-y-1 ${th.mono}`}>
              <div><span className={th.muted}>{msg('UI_DECISIONSLOG_SEQ')}</span> {immudb_seq}</div>
              <div className="break-all"><span className={th.muted}>{msg('UI_DECISIONSLOG_HASH')}</span> {audit_hash}</div>
              <div className={`mt-1 text-[9px] ${th.hash}`}>
               {msg('UI_DECISIONSLOG_HSM_SIGNED_MERKLE_VERIFIED_TAMPER')}
              </div>
            </div>
          </div>

          {/* NGCH filing */}
          <div>
            <div className={`text-[10px] uppercase tracking-wider ${th.muted} mb-2`}>{msg('UI_DECISIONSLOG_NGCH_FILING')}</div>
            <div className="flex items-center gap-3 text-xs">
              <span className={`font-mono ${th.label}`}>{decision.ngch}</span>
              <span className={th.muted}>{msg('UI_DECISIONSLOG_FILED_AT', { filed: decision.filed })}</span>
              <span className={`text-[10px] px-1.5 py-0.5 rounded border ${isDark ? 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10' : 'text-emerald-700 border-emerald-300 bg-emerald-50'}`}>
               {msg('UI_DECISIONSLOG_ACK')}
              </span>
            </div>
          </div>

        </div>
      </div>
    </div>
  )
}

// ── RRF Modal ─────────────────────────────────────────────────────────────────
function RrfModal({ returns, sessionMeta, onClose, isDark }) {
  const xml = buildRrfXml(returns, sessionMeta)
  const date = new Date().toISOString().slice(0, 10).replace(/-/g, '')
  const filename = `RRF_${sessionMeta.bank_ifsc}_${date}_${sessionMeta.session_id}.xml`
  const th = {
    overlay:  'fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-6',
    modal:    isDark ? 'bg-navy-900 border-white/10 text-white' : 'bg-white border-slate-200 text-slate-900',
    code:     isDark ? 'bg-navy-950/80 text-emerald-400 border-white/10' : 'bg-slate-50 text-emerald-700 border-slate-200',
    muted:    isDark ? 'text-slate-400' : 'text-slate-500',
    btn:      isDark ? 'bg-gold-400/10 border-gold-400/30 text-gold-400 hover:bg-gold-400/20' : 'bg-amber-50 border-amber-300 text-amber-700 hover:bg-amber-100',
    divider:  isDark ? 'border-white/10' : 'border-slate-200',
    badge:    isDark ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400' : 'border-emerald-300 bg-emerald-50 text-emerald-700',
    closeBtn: isDark ? 'hover:bg-white/8 text-slate-400' : 'hover:bg-slate-100 text-slate-500',
    ngchReady: isDark ? 'text-emerald-400' : 'text-emerald-600',
  }
  return (
    <div className={th.overlay} onClick={onClose}>
      <div className={`w-full max-w-3xl max-h-[80vh] rounded-2xl border shadow-2xl flex flex-col ${th.modal}`}
        onClick={e => e.stopPropagation()}>
        <div className={`flex items-center justify-between px-5 py-3 border-b ${th.divider}`}>
          <div>
            <div className="text-sm font-semibold">{msg('UI_DECISIONSLOG_RETURN_REASON_FILE_RRF')}</div>
            <div className={`text-[10px] font-mono ${th.muted}`}>{filename}</div>
          </div>
          <div className="flex items-center gap-2">
            <div className={`text-[10px] px-2 py-0.5 rounded border ${th.badge}`}>{msg('UI_DECISIONSLOG_RETURNS_CTS_2010_XML', { count: returns.length })}</div>
            <button onClick={() => downloadText(xml, filename, 'application/xml')}
              className={`px-3 py-1.5 rounded-lg border text-xs font-semibold transition-all ${th.btn}`}>{msg('UI_DECISIONSLOG_DOWNLOAD_XML')}</button>
            <button onClick={onClose}
              className={`w-7 h-7 rounded-lg flex items-center justify-center text-sm ${th.closeBtn}`}>✕</button>
          </div>
        </div>
        <div className={`shrink-0 px-5 py-2 border-b ${th.divider} flex gap-6 text-[11px] ${th.muted}`}>
          <span>{msg('UI_DECISIONSLOG_BANK')} <span className="font-mono font-semibold">{sessionMeta.bank_ifsc}</span></span>
          <span>{msg('UI_DECISIONSLOG_SESSION')} <span className="font-mono">{sessionMeta.session_id}</span></span>
          <span className={th.ngchReady}>{msg('UI_DECISIONSLOG_NGCH_READY_HSM_SIGN_PENDING')}</span>
        </div>
        <pre className={`flex-1 overflow-auto text-[10px] font-mono p-4 rounded-b-2xl border-t ${th.code} leading-relaxed`}>{xml}</pre>
      </div>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────
export default function CTSDecisionsLog() {
  const { bankIfsc, bankName, isSB, isSMB, isDemo } = useBankContext()
  const { isDark } = useTheme()
  const _td = new Date(); const _tdStr = `${_td.getFullYear()}${String(_td.getMonth()+1).padStart(2,'0')}${String(_td.getDate()).padStart(2,'0')}`
  const sessionId = `SES-${bankIfsc || 'BANK'}-${_tdStr}-001`
  const sessionMeta = {
    bank_ifsc:     bankIfsc,
    bank_name:     bankName,
    session_id:    sessionId,
    generated_at:  new Date().toISOString(),
  }
  const [filter,   setFilter]   = useState('All')
  const [search,   setSearch]   = useState('')
  const [sortCol,  setSortCol]  = useState('immudb_seq')
  const [sortDir,  setSortDir]  = useState('desc')
  const [shapRow,  setShapRow]  = useState(null)   // decision object
  const [rrfModal, setRrfModal] = useState(null)   // null | 'session' | rowId
  const {
    items: liveDecisions,
    loading: decisionsLoading,
    error:   decisionsError,
  } = useDecisions({ limit: 50 })

  // DEMO mode: show mock data. POC/PROD: use live API data.
  // When live data is loading, keep previous mock/empty state to avoid flash.
  const ALL_DECISIONS = isDemo ? DECISIONS : liveDecisions
  const returned = ALL_DECISIONS.filter(d => d.outcome === 'STP_RETURN')

  const rows = useMemo(() => {
    let r = filter === 'All' ? ALL_DECISIONS : ALL_DECISIONS.filter(d => d.outcome === filter)
    if (search.trim()) {
      const q = search.trim().toLowerCase()
      r = r.filter(d =>
        d.id.toLowerCase().includes(q)     ||
        d.account.toLowerCase().includes(q)||
        d.ngch.toLowerCase().includes(q)   ||
        d.reason.toLowerCase().includes(q)
      )
    }
    r = [...r].sort((a, b) => {
      let av = a[sortCol], bv = b[sortCol]
      if (av === null || av === undefined) av = sortDir === 'asc' ? Infinity : -Infinity
      if (bv === null || bv === undefined) bv = sortDir === 'asc' ? Infinity : -Infinity
      return sortDir === 'asc' ? (av > bv ? 1 : -1) : (av < bv ? 1 : -1)
    })
    return r
  }, [isDemo, filter, search, sortCol, sortDir])

  function toggleSort(col) {
    if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortCol(col); setSortDir('desc') }
  }
  function sortIcon(col) { return sortCol === col ? (sortDir === 'desc' ? ' ↓' : ' ↑') : '' }

  const th = {
    page:    isDark ? 'bg-navy-950' : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    faint:   isDark ? 'text-slate-600' : 'text-slate-400',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    row:     isDark ? 'border-white/4 hover:bg-white/2 cursor-pointer' : 'border-slate-100 hover:bg-slate-50 cursor-pointer',
    thead:   isDark ? 'bg-white/5 border-white/10 text-slate-500' : 'bg-slate-50 border-slate-200 text-slate-400',
    input:   isDark ? 'bg-navy-800 border-white/10 text-white placeholder-slate-600 focus:border-[#f5c842]' : 'bg-white border-slate-300 text-slate-900 placeholder-slate-400 focus:border-[#f5c842]',
    filterActive: isDark ? 'bg-gold-400/15 text-gold-400' : 'bg-amber-100 text-amber-700',
    filterIdle:   isDark ? 'text-slate-500 hover:text-slate-300' : 'text-slate-400 hover:text-slate-700',
    rrfBtn:     isDark ? 'border-red-500/25 text-red-400 hover:bg-red-500/10' : 'border-red-300 text-red-600 hover:bg-red-50',
    sessionRrf: isDark ? 'border-amber-500/30 bg-amber-500/10 text-amber-400 hover:bg-amber-500/20' : 'border-amber-400 bg-amber-50 text-amber-700 hover:bg-amber-100',
    csvBtn:     isDark ? 'border-indigo-500/30 text-indigo-400 hover:bg-indigo-500/10' : 'border-indigo-400 text-indigo-600 hover:bg-indigo-50',
    sortTh:     isDark ? 'cursor-pointer hover:text-slate-300 select-none' : 'cursor-pointer hover:text-slate-700 select-none',
  }

  const OUTCOME_STYLE = isDark
    ? { STP_CONFIRM: 'text-emerald-400 bg-emerald-400/10', STP_RETURN: 'text-red-400 bg-red-400/10', HUMAN_REVIEW: 'text-amber-400 bg-amber-400/10' }
    : { STP_CONFIRM: 'text-emerald-700 bg-emerald-50',     STP_RETURN: 'text-red-700 bg-red-50',     HUMAN_REVIEW: 'text-amber-700 bg-amber-50'     }

  const modalReturns = rrfModal === 'session' ? returned : returned.filter(d => d.id === rrfModal)

  const date = new Date().toISOString().slice(0, 10).replace(/-/g, '')

  usePageHeader({
    subtitle: msg('UI_DECISIONSLOG_SESSION_2', { session_id: sessionMeta.session_id, bank_name: sessionMeta.bank_name }),
    actions: (
      <div className="flex items-center gap-2">
        {returned.length > 0 && (
          <button onClick={() => setRrfModal('session')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-semibold transition-all ${th.sessionRrf}`}>
            <span>📄</span><span>{msg('UI_DECISIONSLOG_RRF_RETURNS', { count: returned.length })}</span>
          </button>
        )}
        <button onClick={() => downloadText(buildCsv(rows), `decisions_${sessionMeta.session_id}_${date}.csv`, 'text/csv')}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-semibold transition-all ${th.csvBtn}`}>
         {msg('UI_DECISIONSLOG_CSV')}
        </button>
      </div>
    ),
  })

  return (
    <AppShell>
      <div className={`${th.page} px-6 py-5`}>

        {/* Page heading — visible for tests + accessibility */}
        <h1 className={`text-lg font-semibold ${th.heading} mb-4`}>{msg('UI_DECISIONSLOG_DECISIONS_LOG')}</h1>

        {/* Live data status — shown only in non-demo mode */}
        {!isDemo && decisionsLoading && (
          <div className={`mb-3 px-3 py-2 rounded-lg text-xs ${isDark ? 'bg-white/5 text-slate-400' : 'bg-slate-100 text-slate-500'}`}>
           {msg('UI_DECISIONSLOG_LOADING_DECISIONS')}
          </div>
        )}
        {!isDemo && decisionsError && !decisionsLoading && (
          <div className={`mb-3 px-3 py-2 rounded-lg text-xs ${isDark ? 'bg-red-500/10 text-red-400 border border-red-500/20' : 'bg-red-50 text-red-600 border border-red-200'}`}>
           {msg('UI_DECISIONSLOG_UNABLE_TO_LOAD_LIVE_DECISIONS', { decisionsError })}
          </div>
        )}

        {/* Filter buttons */}
        <div className="flex gap-1 mb-4">
          {FILTERS.map(f => (
            <button key={f} onClick={() => setFilter(f)}
              className={`px-3 py-1 rounded-lg text-xs font-medium transition-all ${filter === f ? th.filterActive : th.filterIdle}`}>
              {f.replace(/_/g, ' ')}
            </button>
          ))}
        </div>

        {/* Summary strip */}
        <div className="grid grid-cols-5 gap-3 mb-4">
          {[
            { label: msg('UI_DECISIONSLOG_TOTAL_FILED'),   value: ALL_DECISIONS.length,                                          color: th.heading },
            { label: msg('UI_COMMON_STP_CONFIRMED'), value: ALL_DECISIONS.filter(d => d.outcome === 'STP_CONFIRM').length, color: isDark ? 'text-emerald-400' : 'text-emerald-600' },
            { label: msg('UI_COMMON_STP_RETURNED'),  value: returned.length,                                               color: isDark ? 'text-red-400' : 'text-red-600' },
            { label: msg('UI_COMMON_HUMAN_REVIEW'),  value: ALL_DECISIONS.filter(d => d.outcome === 'HUMAN_REVIEW').length,color: isDark ? 'text-amber-400' : 'text-amber-600' },
            { label: msg('UI_DECISIONSLOG_RRF_GENERATED'), value: returned.length > 0 ? '✓' : '—',                          color: returned.length > 0 ? (isDark ? 'text-emerald-400' : 'text-emerald-600') : th.faint },
          ].map(s => (
            <div key={s.label} className={`border rounded-xl px-4 py-3 ${th.card}`}>
              <div className={`text-[10px] ${th.faint} mb-1`}>{s.label}</div>
              <div className={`text-2xl font-bold ${s.color}`}>{s.value}</div>
            </div>
          ))}
        </div>

        {/* Search bar */}
        <div className="mb-3">
          <input
            type="text"
            placeholder={msg('UI_DECISIONSLOG_SEARCH_BY_INSTRUMENT_ID_ACCOUNT')}
            value={search}
            onChange={e => setSearch(e.target.value)}
            className={`w-full rounded-xl border px-4 py-2 text-xs outline-none transition-colors ${th.input}`}
          />
        </div>

        {/* Table */}
        <div className={`border rounded-xl overflow-x-auto ${th.card}`}>
          <table className="w-full text-xs">
            <thead>
              <tr className={`${th.thead} border-b`}>
                <th className="text-left px-4 py-3 font-normal">{msg('CTS_OUT_CUSTODY_COL_INSTRUMENT')}</th>
                <th className="text-left px-4 py-3 font-normal">{msg('CTS_WF_BUCKETCFG_COL_ACCOUNT')}</th>
                <th className="text-left px-4 py-3 font-normal">{msg('CTS_OUT_CUSTODY_COL_AMOUNT')}</th>
                <th className="text-left px-4 py-3 font-normal">{msg('UI_COMMON_REASON')}</th>
                <th className="text-left px-4 py-3 font-normal">{msg('UI_COMMON_OUTCOME')}</th>
                <th className={`px-4 py-3 font-normal text-right ${th.sortTh}`} onClick={() => toggleSort('agent_ms')}>
                 {msg('UI_DECISIONSLOG_AGENT_MS_2', { sortIcon: sortIcon('agent_ms') })}
                </th>
                <th className={`px-4 py-3 font-normal text-right ${th.sortTh}`} onClick={() => toggleSort('fraud')}>
                 {msg('UI_DECISIONSLOG_FRAUD', { sortIcon: sortIcon('fraud') })}
                </th>
                <th className="text-left px-4 py-3 font-normal">{msg('UI_DECISIONSLOG_NGCH_REF')}</th>
                <th className={`px-4 py-3 font-normal text-left ${th.sortTh}`} onClick={() => toggleSort('filed')}>
                 {msg('UI_DECISIONSLOG_FILED', { sortIcon: sortIcon('filed') })}
                </th>
                <th className="text-left px-4 py-3 font-normal">{msg('UI_ALLOCATIONADMIN_REVIEWER')}</th>
                <th className="text-left px-4 py-3 font-normal">{msg('UI_DECISIONSLOG_RRF')}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((d, i) => {
                const isReturn = d.outcome === 'STP_RETURN'
                const rbi = isReturn ? getRbiCode(d.return_reason || d.reason) : null
                return (
                  <tr key={i} className={`border-b ${th.row} transition-colors`}
                    onClick={() => setShapRow(d)}>
                    <td className={`px-4 py-2.5 ${th.body} font-mono text-[11px]`}>{d.id}</td>
                    <td className={`px-4 py-2.5 ${th.muted} font-mono`}>{d.account}</td>
                    <td className={`px-4 py-2.5 ${th.muted}`}>{d.amount}</td>
                    <td className={`px-4 py-2.5 ${th.muted}`}>{d.reason.replace(/_/g, ' ')}</td>
                    <td className="px-4 py-2.5">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${OUTCOME_STYLE[d.outcome]}`}>
                        {d.outcome.replace(/_/g, ' ')}
                      </span>
                    </td>
                    <td className={`px-4 py-2.5 text-right ${th.body} font-mono`}>{d.agent_ms}</td>
                    <td className="px-4 py-2.5 text-right">
                      {d.fraud !== null && d.fraud !== undefined
                        ? <span className={d.fraud > 0.7 ? (isDark ? 'text-red-400' : 'text-red-600') : (isDark ? 'text-emerald-400' : 'text-emerald-600')}>
                            {(d.fraud * 100).toFixed(0)}%
                          </span>
                        : <span className={th.faint}>—</span>}
                    </td>
                    <td className={`px-4 py-2.5 ${th.muted} font-mono text-[10px]`}>{d.ngch}</td>
                    <td className={`px-4 py-2.5 ${th.muted} font-mono`}>{d.filed}</td>
                    <td className={`px-4 py-2.5 ${th.faint}`}>{d.reviewer ?? '—'}</td>
                    <td className="px-4 py-2.5" onClick={e => e.stopPropagation()}>
                      {isReturn ? (
                        <button onClick={() => setRrfModal(d.id)}
                          className={`flex items-center gap-1 px-2 py-1 rounded-lg border text-[10px] font-medium transition-all ${th.rrfBtn}`}>
                          <span>📄</span>
                          <span className="font-mono">{rbi.code}</span>
                        </button>
                      ) : <span className={th.faint}>—</span>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {/* Hint */}
        <p className={`mt-2 text-[10px] ${th.faint}`}>
         {msg('UI_DECISIONSLOG_CLICK_ANY_ROW_TO_VIEW')}
        </p>

        {/* RBI code legend */}
        {returned.length > 0 && (
          <div className={`mt-4 border rounded-xl px-5 py-3 ${th.card}`}>
            <div className={`text-[10px] uppercase tracking-widest ${th.faint} mb-2`}>{msg('UI_DECISIONSLOG_RBI_RETURN_REASON_CODES_THIS')}</div>
            <div className="flex flex-wrap gap-3">
              {[...new Set(returned.map(r => {
                const rbi = getRbiCode(r.return_reason || r.reason)
                return `${rbi.code} — ${rbi.desc}`
              }))].map(entry => (
                <span key={entry} className={`text-[10px] font-mono ${th.muted}`}>{entry}</span>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* SHAP panel */}
      {shapRow && <ShapPanel decision={shapRow} onClose={() => setShapRow(null)} isDark={isDark} />}

      {/* RRF Modal */}
      {rrfModal && (
        <RrfModal returns={modalReturns} sessionMeta={sessionMeta}
          onClose={() => setRrfModal(null)} isDark={isDark} />
      )}
    </AppShell>
  )
}

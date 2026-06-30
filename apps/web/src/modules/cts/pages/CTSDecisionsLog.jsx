import { useState, useMemo } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'
import { useBankContext } from '../../../shared/context/BankContext'

// RBI return reason code mapping — mirrors modules/cts/rrf/models.py RBIReturnCode
const RBI_CODE_MAP = {
  'Signature mismatch confirmed':       { code: '06', desc: 'Drawer Signature Differs' },
  'Amount alteration detected':         { code: '07', desc: 'Alterations Require Authentication' },
  'Insufficient funds':                 { code: '01', desc: 'Funds Insufficient' },
  'Account dormant / frozen':           { code: '13', desc: 'Account Closed / Transferred / Not Traceable' },
  'Post-dated cheque':                  { code: '14', desc: 'Cheque Post-Dated' },
  'Mutilated / damaged cheque':         { code: '15', desc: 'Cheque Stale / Mutilated / Torn' },
  'Words and figures differ':           { code: '16', desc: 'Amount in Words and Figures Differs' },
  'No specimen on file — cannot verify':{ code: '04', desc: 'Refer to Drawer' },
  'Payee name discrepancy':             { code: '09', desc: "Payee's Endorsement Required" },
  'SIG_MISMATCH':                       { code: '06', desc: 'Drawer Signature Differs' },
  'FRAUD_RISK':                         { code: '04', desc: 'Refer to Drawer' },
  'ALTERATION':                         { code: '07', desc: 'Alterations Require Authentication' },
  'DEFAULT':                            { code: '04', desc: 'Refer to Drawer' },
}
function getRbiCode(reason) { return RBI_CODE_MAP[reason] || RBI_CODE_MAP['DEFAULT'] }

const SESSION_ID    = 'SES-0619-001'
const CLEARING_ZONE = 'MUMBAI'

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
    shap: {
      score: 0.91,
      features: [
        { name: 'sig_mismatch_delta',  value: +0.38, label: 'Signature deviation vs specimen' },
        { name: 'ink_anomaly_score',   value: +0.21, label: 'Ink-physics anomaly detected' },
        { name: 'prev_returns_90d',    value: +0.14, label: 'Account: 2 returns in 90 days' },
        { name: 'amount_risk_tier',    value: +0.11, label: 'Amount in elevated-risk bracket' },
        { name: 'micr_check_digit',    value: +0.07, label: 'MICR check-digit inconsistency' },
        { name: 'account_age_days',    value: -0.04, label: 'Account age (mature = lower risk)' },
        { name: 'payee_match_score',   value: -0.02, label: 'Payee name — low-risk pattern' },
        { name: 'vault_hit',           value: -0.03, label: 'Signature vault hit (specimen present)' },
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
    shap: {
      score: 0.08,
      features: [
        { name: 'sig_mismatch_delta',  value: -0.31, label: 'Signature closely matches specimen' },
        { name: 'vault_hit',           value: -0.22, label: 'Vault hit — specimen retrieved' },
        { name: 'account_age_days',    value: -0.15, label: 'Mature account (9 years)' },
        { name: 'payee_match_score',   value: -0.10, label: 'Payee pattern consistent' },
        { name: 'ocr_confidence',      value: -0.09, label: 'OCR confidence high (0.97)' },
        { name: 'prev_returns_90d',    value: +0.01, label: 'No prior returns' },
        { name: 'amount_risk_tier',    value: +0.04, label: 'Low-value bracket' },
        { name: 'ink_anomaly_score',   value: +0.02, label: 'No ink anomaly detected' },
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
    shap: {
      score: 0.87,
      features: [
        { name: 'ink_anomaly_score',   value: +0.44, label: 'Ink-physics anomaly — correction fluid detected' },
        { name: 'paper_fibre_dist',    value: +0.22, label: 'Paper fibre distortion at amount field' },
        { name: 'amount_risk_tier',    value: +0.09, label: 'Amount range inconsistency' },
        { name: 'ocr_confidence',      value: +0.07, label: 'OCR confidence drop at altered field' },
        { name: 'sig_mismatch_delta',  value: +0.05, label: 'Minor signature deviation' },
        { name: 'vault_hit',           value: -0.05, label: 'Vault hit — specimen present' },
        { name: 'account_age_days',    value: -0.03, label: 'Account age (moderate)' },
        { name: 'payee_match_score',   value: -0.02, label: 'Payee name consistent' },
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
    shap: {
      score: 0.12,
      features: [
        { name: 'sig_mismatch_delta',  value: -0.28, label: 'Signature well within tolerance' },
        { name: 'vault_hit',           value: -0.20, label: 'Vault hit — specimen retrieved' },
        { name: 'ocr_confidence',      value: -0.14, label: 'OCR confidence 0.99' },
        { name: 'ink_anomaly_score',   value: -0.08, label: 'No ink anomaly' },
        { name: 'account_age_days',    value: -0.06, label: 'Long-standing account' },
        { name: 'amount_risk_tier',    value: +0.08, label: 'Amount bracket — minor flag' },
        { name: 'prev_returns_90d',    value: +0.04, label: 'One return in 90 days' },
        { name: 'payee_match_score',   value: -0.03, label: 'Payee consistent' },
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
    shap: {
      score: 0.44,
      features: [
        { name: 'amount_risk_tier',    value: +0.29, label: 'Very-high-value: mandatory review' },
        { name: 'sig_mismatch_delta',  value: +0.08, label: 'Mild signature deviation' },
        { name: 'prev_returns_90d',    value: +0.05, label: 'One prior return' },
        { name: 'micr_check_digit',    value: +0.02, label: 'MICR nominal' },
        { name: 'vault_hit',           value: -0.09, label: 'Vault hit' },
        { name: 'ocr_confidence',      value: -0.08, label: 'OCR high confidence' },
        { name: 'ink_anomaly_score',   value: -0.05, label: 'No ink anomaly' },
        { name: 'account_age_days',    value: -0.04, label: 'Established account' },
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
    shap: {
      score: 0.05,
      features: [
        { name: 'sig_mismatch_delta',  value: -0.35, label: 'Signature exact match' },
        { name: 'vault_hit',           value: -0.25, label: 'Vault hit' },
        { name: 'ink_anomaly_score',   value: -0.12, label: 'Clean ink patterns' },
        { name: 'ocr_confidence',      value: -0.10, label: 'OCR confidence 0.98' },
        { name: 'account_age_days',    value: -0.07, label: 'Long-standing account' },
        { name: 'amount_risk_tier',    value: +0.02, label: 'Low-value bracket' },
        { name: 'prev_returns_90d',    value: +0.01, label: 'No prior returns' },
        { name: 'payee_match_score',   value: -0.01, label: 'Payee consistent' },
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
    shap: {
      score: 0.79,
      features: [
        { name: 'sig_mismatch_delta',  value: +0.48, label: 'High signature deviation (0.61 vs threshold 0.87)' },
        { name: 'prev_returns_90d',    value: +0.12, label: '1 prior signature-related return' },
        { name: 'ink_anomaly_score',   value: +0.08, label: 'Minor pen-pressure inconsistency' },
        { name: 'amount_risk_tier',    value: +0.06, label: 'Mid-value bracket' },
        { name: 'vault_hit',           value: -0.04, label: 'Vault hit — specimen used for comparison' },
        { name: 'ocr_confidence',      value: -0.03, label: 'OCR high confidence' },
        { name: 'account_age_days',    value: -0.02, label: 'Established account' },
        { name: 'payee_match_score',   value: -0.01, label: 'Payee consistent' },
      ],
    },
  },
]

const FILTERS = ['All', 'STP_CONFIRM', 'STP_RETURN', 'HUMAN_REVIEW']
const SORT_COLS = ['fraud', 'agent_ms', 'filed', 'immudb_seq']

// ── CSV export ─────────────────────────────────────────────────────────────────
function buildCsv(rows) {
  const header = ['Instrument ID','Account','Amount','Reason','Outcome','Agent ms','Fraud Score','NGCH Ref','Filed','Reviewer','Immudb Seq','Audit Hash']
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
    <ClearingZone>${sessionMeta.clearing_zone}</ClearingZone>
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

  const { shap, audit_hash, immudb_seq } = decision
  const fraudPct = shap ? Math.round(shap.score * 100) : null
  const fraudColor = fraudPct > 70 ? 'red' : fraudPct > 40 ? 'amber' : 'green'

  return (
    <div className={th.overlay} onClick={onClose}>
      <div className={`w-full max-w-lg h-full max-h-[calc(100vh-2rem)] rounded-2xl border shadow-2xl flex flex-col overflow-hidden ${th.panel}`}
        onClick={e => e.stopPropagation()}>

        {/* Header */}
        <div className={`flex items-center justify-between px-5 py-3.5 border-b ${th.head}`}>
          <div>
            <div className="text-sm font-semibold">AI Explainability — SHAP Breakdown</div>
            <div className={`text-[11px] font-mono ${th.muted}`}>{decision.id}</div>
          </div>
          <button onClick={onClose}
            className={`w-7 h-7 rounded-lg flex items-center justify-center text-sm ${th.closeBtn}`}>✕</button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">

          {/* Fraud score */}
          {shap ? (
            <div>
              <div className={`text-[10px] uppercase tracking-wider ${th.muted} mb-2`}>XGBoost Fraud Score</div>
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
              Vault miss — fraud scoring not attempted. Routed to human review per policy.
            </div>
          )}

          {/* SHAP feature table */}
          {shap && (
            <div>
              <div className={`text-[10px] uppercase tracking-wider ${th.muted} mb-3`}>
                SHAP Feature Contributions
                <span className={`ml-2 normal-case ${th.muted}`}>— red raises score · green lowers score</span>
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
                Physical Anomaly Detected
              </div>
              <p className={`text-[11px] ${isDark ? 'text-orange-300' : 'text-orange-800'}`}>
                Ink-physics analysis (Qwen2-VL) flagged this cheque. Possible correction fluid,
                paper-fibre distortion, or pen-pressure inconsistency at altered field.
                See alteration activity output for per-field bounding boxes.
              </p>
            </div>
          )}

          {/* Decision outcome */}
          <div>
            <div className={`text-[10px] uppercase tracking-wider ${th.muted} mb-2`}>Decision</div>
            <div className="flex items-center gap-2">
              <span className={`px-2.5 py-1 rounded-full text-xs font-semibold ${
                decision.outcome === 'STP_CONFIRM' ? (isDark ? 'bg-emerald-500/15 text-emerald-400' : 'bg-emerald-50 text-emerald-700')
                : decision.outcome === 'STP_RETURN' ? (isDark ? 'bg-red-500/15 text-red-400' : 'bg-red-50 text-red-700')
                : (isDark ? 'bg-amber-500/15 text-amber-400' : 'bg-amber-50 text-amber-700')
              }`}>{decision.outcome.replace(/_/g, ' ')}</span>
              <span className={`text-xs ${th.muted}`}>{decision.reason.replace(/_/g, ' ')}</span>
              {decision.reviewer && (
                <span className={`text-xs ${th.muted}`}>· reviewed by <strong>{decision.reviewer}</strong></span>
              )}
            </div>
          </div>

          {/* Immutable audit record */}
          <div>
            <div className={`text-[10px] uppercase tracking-wider ${th.muted} mb-2`}>
              Immutable Audit Record (Immudb)
            </div>
            <div className={`rounded-lg border p-3 text-[10px] font-mono space-y-1 ${th.mono}`}>
              <div><span className={th.muted}>seq:</span> {immudb_seq}</div>
              <div className="break-all"><span className={th.muted}>hash:</span> {audit_hash}</div>
              <div className={`mt-1 text-[9px] ${th.hash}`}>
                HSM-signed · Merkle-verified · Tamper-evident · Cannot be modified or deleted
              </div>
            </div>
          </div>

          {/* NGCH filing */}
          <div>
            <div className={`text-[10px] uppercase tracking-wider ${th.muted} mb-2`}>NGCH Filing</div>
            <div className="flex items-center gap-3 text-xs">
              <span className={`font-mono ${th.label}`}>{decision.ngch}</span>
              <span className={th.muted}>Filed at {decision.filed}</span>
              <span className={`text-[10px] px-1.5 py-0.5 rounded border ${isDark ? 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10' : 'text-emerald-700 border-emerald-300 bg-emerald-50'}`}>
                ACK
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
            <div className="text-sm font-semibold">Return Reason File (RRF)</div>
            <div className={`text-[10px] font-mono ${th.muted}`}>{filename}</div>
          </div>
          <div className="flex items-center gap-2">
            <div className={`text-[10px] px-2 py-0.5 rounded border ${th.badge}`}>{returns.length} returns · CTS-2010 XML</div>
            <button onClick={() => downloadText(xml, filename, 'application/xml')}
              className={`px-3 py-1.5 rounded-lg border text-xs font-semibold transition-all ${th.btn}`}>↓ Download XML</button>
            <button onClick={onClose}
              className={`w-7 h-7 rounded-lg flex items-center justify-center text-sm ${th.closeBtn}`}>✕</button>
          </div>
        </div>
        <div className={`shrink-0 px-5 py-2 border-b ${th.divider} flex gap-6 text-[11px] ${th.muted}`}>
          <span>Bank: <span className="font-mono font-semibold">{sessionMeta.bank_ifsc}</span></span>
          <span>Session: <span className="font-mono">{sessionMeta.session_id}</span></span>
          <span>Zone: <span className="font-mono">{sessionMeta.clearing_zone}</span></span>
          <span className={th.ngchReady}>✓ NGCH-ready · HSM sign pending (backend)</span>
        </div>
        <pre className={`flex-1 overflow-auto text-[10px] font-mono p-4 rounded-b-2xl border-t ${th.code} leading-relaxed`}>{xml}</pre>
      </div>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────
export default function CTSDecisionsLog() {
  const { bankIfsc, bankName, isSB, isSMB } = useBankContext()
  const { isDark } = useTheme()
  const sessionMeta = {
    bank_ifsc:     bankIfsc,
    bank_name:     bankName,
    session_id:    SESSION_ID,
    clearing_zone: CLEARING_ZONE,
    generated_at:  new Date().toISOString(),
  }
  const [filter,   setFilter]   = useState('All')
  const [search,   setSearch]   = useState('')
  const [sortCol,  setSortCol]  = useState('immudb_seq')
  const [sortDir,  setSortDir]  = useState('desc')
  const [shapRow,  setShapRow]  = useState(null)   // decision object
  const [rrfModal, setRrfModal] = useState(null)   // null | 'session' | rowId
  const returned = DECISIONS.filter(d => d.outcome === 'STP_RETURN')

  const rows = useMemo(() => {
    let r = filter === 'All' ? DECISIONS : DECISIONS.filter(d => d.outcome === filter)
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
  }, [filter, search, sortCol, sortDir])

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
    input:   isDark ? 'bg-navy-800 border-white/10 text-white placeholder-slate-600 focus:border-indigo-500' : 'bg-white border-slate-300 text-slate-900 placeholder-slate-400 focus:border-indigo-500',
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
    subtitle: `Session: ${sessionMeta.session_id} · ${sessionMeta.bank_name} · ${sessionMeta.clearing_zone}`,
    actions: (
      <div className="flex items-center gap-2">
        {returned.length > 0 && (
          <button onClick={() => setRrfModal('session')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-semibold transition-all ${th.sessionRrf}`}>
            <span>📄</span><span>RRF ({returned.length} returns)</span>
          </button>
        )}
        <button onClick={() => downloadText(buildCsv(rows), `decisions_${sessionMeta.session_id}_${date}.csv`, 'text/csv')}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-semibold transition-all ${th.csvBtn}`}>
          ↓ CSV
        </button>
        <div className="flex gap-1">
          {FILTERS.map(f => (
            <button key={f} onClick={() => setFilter(f)}
              className={`px-3 py-1 rounded-lg text-xs font-medium transition-all ${filter === f ? th.filterActive : th.filterIdle}`}>
              {f.replace(/_/g, ' ')}
            </button>
          ))}
        </div>
      </div>
    ),
  })

  return (
    <AppShell>
      <div className={`${th.page} px-6 py-5`}>

        {/* Page heading — visible for tests + accessibility */}
        <h1 className={`text-lg font-semibold ${th.heading} mb-4`}>Decisions Log</h1>

        {/* Filter buttons — also rendered here so tests can find them */}
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
            { label: 'Total Filed',   value: DECISIONS.length,                                          color: th.heading },
            { label: 'STP Confirmed', value: DECISIONS.filter(d => d.outcome === 'STP_CONFIRM').length, color: isDark ? 'text-emerald-400' : 'text-emerald-600' },
            { label: 'STP Returned',  value: returned.length,                                           color: isDark ? 'text-red-400' : 'text-red-600' },
            { label: 'Human Review',  value: DECISIONS.filter(d => d.outcome === 'HUMAN_REVIEW').length,color: isDark ? 'text-amber-400' : 'text-amber-600' },
            { label: 'RRF Generated', value: returned.length > 0 ? '✓' : '—',                          color: returned.length > 0 ? (isDark ? 'text-emerald-400' : 'text-emerald-600') : th.faint },
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
            placeholder="Search by instrument ID, account, NGCH ref, or reason…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className={`w-full rounded-xl border px-4 py-2 text-xs outline-none transition-colors ${th.input}`}
          />
        </div>

        {/* Table */}
        <div className={`border rounded-xl overflow-hidden ${th.card}`}>
          <table className="w-full text-xs">
            <thead>
              <tr className={`${th.thead} border-b`}>
                <th className="text-left px-4 py-3 font-normal">Instrument</th>
                <th className="text-left px-4 py-3 font-normal">Account</th>
                <th className="text-left px-4 py-3 font-normal">Amount</th>
                <th className="text-left px-4 py-3 font-normal">Reason</th>
                <th className="text-left px-4 py-3 font-normal">Outcome</th>
                <th className={`px-4 py-3 font-normal text-right ${th.sortTh}`} onClick={() => toggleSort('agent_ms')}>
                  Agent ms{sortIcon('agent_ms')}
                </th>
                <th className={`px-4 py-3 font-normal text-right ${th.sortTh}`} onClick={() => toggleSort('fraud')}>
                  Fraud{sortIcon('fraud')}
                </th>
                <th className="text-left px-4 py-3 font-normal">NGCH Ref</th>
                <th className={`px-4 py-3 font-normal text-left ${th.sortTh}`} onClick={() => toggleSort('filed')}>
                  Filed{sortIcon('filed')}
                </th>
                <th className="text-left px-4 py-3 font-normal">Reviewer</th>
                <th className="text-left px-4 py-3 font-normal">RRF</th>
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
          Click any row to view SHAP explainability breakdown and immutable audit hash.
        </p>

        {/* RBI code legend */}
        {returned.length > 0 && (
          <div className={`mt-4 border rounded-xl px-5 py-3 ${th.card}`}>
            <div className={`text-[10px] uppercase tracking-widest ${th.faint} mb-2`}>RBI Return Reason Codes — This Session</div>
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

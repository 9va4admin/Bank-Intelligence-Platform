import { describe, it, expect } from 'vitest'
import { MOCK_QUEUE, BATCH_STATS, getStpStream } from './mockQueue'

describe('MOCK_QUEUE', () => {
  it('contains 6 items', () => {
    expect(MOCK_QUEUE).toHaveLength(6)
  })

  it('every item has required fields', () => {
    for (const item of MOCK_QUEUE) {
      expect(item).toHaveProperty('instrument_id')
      expect(item).toHaveProperty('iet_deadline')
      expect(item).toHaveProperty('fraud_score')
      expect(item).toHaveProperty('ocr_confidence')
      expect(item).toHaveProperty('shap_values')
      expect(item).toHaveProperty('ocr_fields')
      expect(item).toHaveProperty('sig_specimen_available')
      expect(item).toHaveProperty('status', 'PENDING')
    }
  })

  it('includes a VAULT_MISS item with sig_specimen_available false', () => {
    const vaultMiss = MOCK_QUEUE.find((i) => i.reason === 'VAULT_MISS')
    expect(vaultMiss).toBeDefined()
    expect(vaultMiss.sig_specimen_available).toBe(false)
    expect(vaultMiss.sig_match_score).toBeNull()
  })

  it('includes a HIGH_VALUE_DUAL_APPROVAL item with opa_rule set', () => {
    const dual = MOCK_QUEUE.find((i) => i.reason === 'HIGH_VALUE_DUAL_APPROVAL')
    expect(dual).toBeDefined()
    expect(dual.opa_rule).toBeTruthy()
  })

  it('all fraud_score values are between 0 and 1', () => {
    for (const item of MOCK_QUEUE) {
      expect(item.fraud_score).toBeGreaterThan(0)
      expect(item.fraud_score).toBeLessThanOrEqual(1)
    }
  })

  it('covers all 5 reason types', () => {
    const reasons = new Set(MOCK_QUEUE.map((i) => i.reason))
    expect(reasons).toContain('SIGNATURE_LOW_CONFIDENCE')
    expect(reasons).toContain('FRAUD_SCORE_HIGH')
    expect(reasons).toContain('OCR_LOW_CONFIDENCE')
    expect(reasons).toContain('VAULT_MISS')
    expect(reasons).toContain('HIGH_VALUE_DUAL_APPROVAL')
  })

  it('alterations flag is true for OCR_LOW_CONFIDENCE item', () => {
    const ocrItem = MOCK_QUEUE.find((i) => i.reason === 'OCR_LOW_CONFIDENCE')
    expect(ocrItem.ocr_fields.alterations).toBe(true)
  })
})

describe('BATCH_STATS', () => {
  it('has required summary fields', () => {
    expect(BATCH_STATS).toHaveProperty('total_inward')
    expect(BATCH_STATS).toHaveProperty('stp_rate')
    expect(BATCH_STATS).toHaveProperty('human_review')
    expect(BATCH_STATS.stp_rate).toBeGreaterThan(0)
  })
})

describe('getStpStream', () => {
  it('returns 10 STP instruments', () => {
    expect(getStpStream()).toHaveLength(10)
  })

  it('every STP item has id, outcome, ms, acct, amt fields', () => {
    for (const item of getStpStream()) {
      expect(item).toHaveProperty('id')
      expect(item).toHaveProperty('outcome')
      expect(item).toHaveProperty('ms')
      expect(item).toHaveProperty('acct')
      expect(item).toHaveProperty('amt')
    }
  })

  it('outcome is always CONFIRM or RETURN', () => {
    for (const item of getStpStream()) {
      expect(['CONFIRM', 'RETURN']).toContain(item.outcome)
    }
  })

  it('ms values are realistic sub-second timings', () => {
    for (const item of getStpStream()) {
      expect(item.ms).toBeGreaterThan(300)
      expect(item.ms).toBeLessThan(600)
    }
  })
})

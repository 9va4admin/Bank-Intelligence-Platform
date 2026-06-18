import { useQuery, useMutation } from '@tanstack/react-query'

const BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

// --- Mock Data ---

const MOCK_ATM_FLEET = [
  { atm_id: 'ATM-MUM-001', branch: 'Andheri West', oem: 'NCR_SELFSERV', status: 'HEALTHY', last_ej_date: '2026-06-17', pending_uploads: 0 },
  { atm_id: 'ATM-MUM-002', branch: 'Bandra East', oem: 'DIEBOLD_NIXDORF', status: 'DEGRADED', last_ej_date: '2026-06-16', pending_uploads: 3 },
  { atm_id: 'ATM-MUM-003', branch: 'Dadar', oem: 'HYOSUNG', status: 'HEALTHY', last_ej_date: '2026-06-17', pending_uploads: 0 },
  { atm_id: 'ATM-MUM-004', branch: 'Kurla', oem: 'GRG_BANKING', status: 'CRITICAL', last_ej_date: '2026-06-14', pending_uploads: 11 },
  { atm_id: 'ATM-MUM-005', branch: 'Malad', oem: 'NCR_SELFSERV', status: 'HEALTHY', last_ej_date: '2026-06-17', pending_uploads: 0 },
  { atm_id: 'ATM-DEL-001', branch: 'Connaught Place', oem: 'DIEBOLD_NIXDORF', status: 'DEGRADED', last_ej_date: '2026-06-16', pending_uploads: 2 },
  { atm_id: 'ATM-DEL-002', branch: 'Karol Bagh', oem: 'NCR_SELFSERV', status: 'HEALTHY', last_ej_date: '2026-06-17', pending_uploads: 0 },
  { atm_id: 'ATM-DEL-003', branch: 'Lajpat Nagar', oem: 'HYOSUNG', status: 'HEALTHY', last_ej_date: '2026-06-17', pending_uploads: 1 },
  { atm_id: 'ATM-BLR-001', branch: 'Koramangala', oem: 'GRG_BANKING', status: 'DEGRADED', last_ej_date: '2026-06-15', pending_uploads: 5 },
  { atm_id: 'ATM-BLR-002', branch: 'Whitefield', oem: 'NCR_SELFSERV', status: 'HEALTHY', last_ej_date: '2026-06-17', pending_uploads: 0 },
]

const MOCK_EJ_LOGS = [
  { log_id: 'LOG-001', atm_id: 'ATM-MUM-001', date: '2026-06-17', oem_fingerprint: 'NCR_SELFSERV', workflow_status: 'NORMALISED', canonical_hash: 'a3f8c2e1d9b047f6a3f8c2e1d9b047f6a3f8c2e1d9b047f6a3f8c2e1d9b047f6' },
  { log_id: 'LOG-002', atm_id: 'ATM-MUM-002', date: '2026-06-16', oem_fingerprint: 'DIEBOLD_NIXDORF', workflow_status: 'NORMALISED', canonical_hash: 'b4a9d3f2e0c158g7b4a9d3f2e0c158g7b4a9d3f2e0c158g7b4a9d3f2e0c158g7' },
  { log_id: 'LOG-003', atm_id: 'ATM-MUM-003', date: '2026-06-17', oem_fingerprint: 'HYOSUNG', workflow_status: 'RUNNING', canonical_hash: 'c5b0e4a3f1d269h8c5b0e4a3f1d269h8c5b0e4a3f1d269h8c5b0e4a3f1d269h8' },
  { log_id: 'LOG-004', atm_id: 'ATM-MUM-004', date: '2026-06-14', oem_fingerprint: 'GRG_BANKING', workflow_status: 'PARSE_FAILED', canonical_hash: 'd6c1f5b4a2e37ai9d6c1f5b4a2e37ai9d6c1f5b4a2e37ai9d6c1f5b4a2e37ai9' },
  { log_id: 'LOG-005', atm_id: 'ATM-DEL-001', date: '2026-06-16', oem_fingerprint: 'DIEBOLD_NIXDORF', workflow_status: 'NORMALISED', canonical_hash: 'e7d2a6c5b3f48bj0e7d2a6c5b3f48bj0e7d2a6c5b3f48bj0e7d2a6c5b3f48bj0' },
  { log_id: 'LOG-006', atm_id: 'ATM-DEL-002', date: '2026-06-17', oem_fingerprint: 'NCR_SELFSERV', workflow_status: 'NORMALISED', canonical_hash: 'f8e3b7d6c4a59ck1f8e3b7d6c4a59ck1f8e3b7d6c4a59ck1f8e3b7d6c4a59ck1' },
  { log_id: 'LOG-007', atm_id: 'ATM-BLR-001', date: '2026-06-15', oem_fingerprint: 'GRG_BANKING', workflow_status: 'RUNNING', canonical_hash: 'a1b2c3d4e5f6a7b8a1b2c3d4e5f6a7b8a1b2c3d4e5f6a7b8a1b2c3d4e5f6a7b8' },
  { log_id: 'LOG-008', atm_id: 'ATM-BLR-002', date: '2026-06-17', oem_fingerprint: 'NCR_SELFSERV', workflow_status: 'NORMALISED', canonical_hash: 'b2c3d4e5f6a7b8c9b2c3d4e5f6a7b8c9b2c3d4e5f6a7b8c9b2c3d4e5f6a7b8c9' },
]

const MOCK_DISPUTES = [
  { npci_claim_id: 'NPCI-2026-00041', atm_id: 'ATM-MUM-002', amount: 5000, claim_type: 'CASH_NOT_DISPENSED', status: 'AUTO_RESOLVED' },
  { npci_claim_id: 'NPCI-2026-00042', atm_id: 'ATM-MUM-004', amount: 12500, claim_type: 'PARTIAL_DISPENSE', status: 'ESCALATED_TO_HUMAN' },
  { npci_claim_id: 'NPCI-2026-00043', atm_id: 'ATM-DEL-001', amount: 3000, claim_type: 'WRONG_AMOUNT', status: 'PENDING' },
  { npci_claim_id: 'NPCI-2026-00044', atm_id: 'ATM-BLR-001', amount: 20000, claim_type: 'EXCESS_DISPENSE', status: 'ESCALATED_TO_HUMAN' },
  { npci_claim_id: 'NPCI-2026-00045', atm_id: 'ATM-DEL-003', amount: 8000, claim_type: 'CASH_NOT_DISPENSED', status: 'AUTO_RESOLVED' },
]

// --- Hooks ---

export function useATMFleet(bankId) {
  return useQuery({
    queryKey: ['ej', 'atm-fleet', bankId],
    queryFn: async () => {
      try {
        const res = await fetch(`${BASE_URL}/v1/ej/atm/fleet?bank_id=${bankId}`)
        if (res.status === 404) return MOCK_ATM_FLEET
        if (!res.ok) throw new Error(`Fleet fetch failed: ${res.status}`)
        return res.json()
      } catch {
        return MOCK_ATM_FLEET
      }
    },
    staleTime: 30_000,
  })
}

export function useEJLogs(bankId) {
  // TODO: wire to real endpoint
  return useQuery({
    queryKey: ['ej', 'logs', bankId],
    queryFn: async () => MOCK_EJ_LOGS,
    staleTime: 30_000,
  })
}

export function useDisputes(bankId) {
  // TODO: wire to real endpoint
  return useQuery({
    queryKey: ['ej', 'disputes', bankId],
    queryFn: async () => MOCK_DISPUTES,
    staleTime: 30_000,
  })
}

export function useSubmitLog() {
  return useMutation({
    mutationFn: async ({ atm_id, oem_fingerprint, source, raw_log }) => {
      const res = await fetch(`${BASE_URL}/v1/ej/inward/${atm_id}/log`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ oem_fingerprint, source, raw_log }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.message || `Submit failed: ${res.status}`)
      }
      return res.json()
    },
  })
}

export function useRaiseDispute() {
  return useMutation({
    mutationFn: async ({ npci_claim_id, atm_id, claim_amount, claim_timestamp, claim_type }) => {
      const res = await fetch(`${BASE_URL}/v1/ej/disputes/${npci_claim_id}/resolve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ atm_id, claim_amount, claim_timestamp, claim_type }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.message || `Dispute raise failed: ${res.status}`)
      }
      return res.json()
    },
  })
}

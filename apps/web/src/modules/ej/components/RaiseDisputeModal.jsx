import { useState, useEffect } from 'react'
import { useRaiseDispute } from '../hooks/useEJData'

const CLAIM_TYPES = [
  'CASH_NOT_DISPENSED',
  'PARTIAL_DISPENSE',
  'EXCESS_DISPENSE',
  'WRONG_AMOUNT',
]

export default function RaiseDisputeModal({ isOpen, onClose }) {
  const [npciClaimId, setNpciClaimId] = useState('')
  const [atmId, setAtmId] = useState('')
  const [claimAmount, setClaimAmount] = useState('')
  const [claimTimestamp, setClaimTimestamp] = useState('')
  const [claimType, setClaimType] = useState('CASH_NOT_DISPENSED')
  const [successId, setSuccessId] = useState(null)

  const mutation = useRaiseDispute()

  useEffect(() => {
    if (!isOpen) {
      setNpciClaimId('')
      setAtmId('')
      setClaimAmount('')
      setClaimTimestamp('')
      setClaimType('CASH_NOT_DISPENSED')
      setSuccessId(null)
      mutation.reset()
    }
  }, [isOpen])

  useEffect(() => {
    if (successId) {
      const timer = setTimeout(() => onClose(), 2000)
      return () => clearTimeout(timer)
    }
  }, [successId, onClose])

  function handleSubmit(e) {
    e.preventDefault()
    mutation.mutate(
      {
        npci_claim_id: npciClaimId,
        atm_id: atmId,
        claim_amount: parseFloat(claimAmount),
        claim_timestamp: claimTimestamp,
        claim_type: claimType,
      },
      {
        onSuccess: data => setSuccessId(data.workflow_id || 'submitted'),
      },
    )
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-lg w-full mx-4 p-6">
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-lg font-semibold text-gray-900">Raise Dispute</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">
            &times;
          </button>
        </div>

        {successId && (
          <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-md text-sm text-green-800">
            Dispute raised. Workflow ID: <span className="font-mono">{successId}</span>
          </div>
        )}

        {mutation.isError && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-md text-sm text-red-800">
            {mutation.error?.message || 'Failed to raise dispute. Please try again.'}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              NPCI Claim ID <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              required
              value={npciClaimId}
              onChange={e => setNpciClaimId(e.target.value)}
              placeholder="e.g. NPCI-2026-00046"
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              ATM ID <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              required
              value={atmId}
              onChange={e => setAtmId(e.target.value)}
              placeholder="e.g. ATM-MUM-001"
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Claim Amount (₹) <span className="text-red-500">*</span>
            </label>
            <input
              type="number"
              required
              step="0.01"
              min="0"
              value={claimAmount}
              onChange={e => setClaimAmount(e.target.value)}
              placeholder="e.g. 5000"
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Claim Timestamp <span className="text-red-500">*</span>
            </label>
            <input
              type="datetime-local"
              required
              value={claimTimestamp}
              onChange={e => setClaimTimestamp(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Claim Type</label>
            <select
              value={claimType}
              onChange={e => setClaimType(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {CLAIM_TYPES.map(t => (
                <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>
              ))}
            </select>
          </div>

          <div className="flex items-center justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-gray-600 border border-gray-300 rounded-md hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={mutation.isPending}
              className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {mutation.isPending ? 'Raising...' : 'Raise Dispute'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

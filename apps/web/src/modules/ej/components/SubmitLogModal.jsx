import { useState, useEffect } from 'react'
import { useSubmitLog } from '../hooks/useEJData'

const OEM_OPTIONS = [
  'NCR_SELFSERV',
  'DIEBOLD_NIXDORF',
  'WINCOR_NIXDORF',
  'HYOSUNG',
  'GRG_BANKING',
  'OTHER',
]

export default function SubmitLogModal({ isOpen, onClose }) {
  const [atmId, setAtmId] = useState('')
  const [oem, setOem] = useState('NCR_SELFSERV')
  const [source, setSource] = useState('branch-mcp')
  const [rawLog, setRawLog] = useState('')
  const [successId, setSuccessId] = useState(null)

  const mutation = useSubmitLog()

  useEffect(() => {
    if (!isOpen) {
      setAtmId('')
      setOem('NCR_SELFSERV')
      setSource('branch-mcp')
      setRawLog('')
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
      { atm_id: atmId, oem_fingerprint: oem, source, raw_log: rawLog },
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
          <h2 className="text-lg font-semibold text-gray-900">Submit EJ Log</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">
            &times;
          </button>
        </div>

        {successId && (
          <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-md text-sm text-green-800">
            Log submitted. Workflow ID: <span className="font-mono">{successId}</span>
          </div>
        )}

        {mutation.isError && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-md text-sm text-red-800">
            {mutation.error?.message || 'Submission failed. Please try again.'}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
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
            <label className="block text-sm font-medium text-gray-700 mb-1">OEM Fingerprint</label>
            <select
              value={oem}
              onChange={e => setOem(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {OEM_OPTIONS.map(o => (
                <option key={o} value={o}>{o}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Source</label>
            <input
              type="text"
              value={source}
              onChange={e => setSource(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Raw Log <span className="text-red-500">*</span>
            </label>
            <textarea
              required
              rows={6}
              minLength={10}
              value={rawLog}
              onChange={e => setRawLog(e.target.value)}
              placeholder="Paste raw EJ log content here..."
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
            />
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
              {mutation.isPending ? 'Submitting...' : 'Submit Log'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

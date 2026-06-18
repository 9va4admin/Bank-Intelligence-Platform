import { useState } from 'react'

const WORKFLOW_STATUS_STYLES = {
  NORMALISED: 'bg-green-100 text-green-800',
  RUNNING: 'bg-amber-100 text-amber-800',
  PARSE_FAILED: 'bg-red-100 text-red-800',
}

function SkeletonRow() {
  return (
    <tr>
      {[...Array(5)].map((_, i) => (
        <td key={i} className="px-4 py-3">
          <div className="animate-pulse bg-gray-200 rounded h-4 w-full" />
        </td>
      ))}
    </tr>
  )
}

export default function EJLogTable({ logs = [], isLoading }) {
  const [search, setSearch] = useState('')

  const filtered = search.trim()
    ? logs.filter(
        l =>
          l.atm_id.toLowerCase().includes(search.toLowerCase()) ||
          l.oem_fingerprint.toLowerCase().includes(search.toLowerCase()),
      )
    : logs

  return (
    <div className="space-y-3">
      <input
        type="text"
        value={search}
        onChange={e => setSearch(e.target.value)}
        placeholder="Search by ATM ID or OEM Fingerprint..."
        className="w-full max-w-sm px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
      />
      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="min-w-full bg-white">
          <thead className="bg-gray-50">
            <tr>
              {['ATM ID', 'Date', 'OEM Fingerprint', 'Workflow Status', 'Canonical Hash'].map(col => (
                <th key={col} className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {isLoading
              ? [...Array(5)].map((_, i) => <SkeletonRow key={i} />)
              : filtered.length === 0
              ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-sm text-gray-400">
                    No logs match your search.
                  </td>
                </tr>
              )
              : filtered.map(log => (
                <tr key={log.log_id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm font-mono text-gray-900">{log.atm_id}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{log.date}</td>
                  <td className="px-4 py-3 text-sm font-mono text-gray-600">{log.oem_fingerprint}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${WORKFLOW_STATUS_STYLES[log.workflow_status] || 'bg-gray-100 text-gray-700'}`}>
                      {log.workflow_status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm font-mono text-gray-500" title={log.canonical_hash}>
                    {log.canonical_hash.slice(0, 12)}...
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

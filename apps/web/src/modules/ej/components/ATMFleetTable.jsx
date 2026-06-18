import { useState } from 'react'

const STATUS_STYLES = {
  HEALTHY: 'bg-green-100 text-green-800',
  DEGRADED: 'bg-amber-100 text-amber-800',
  CRITICAL: 'bg-red-100 text-red-800',
}

function SkeletonRow() {
  return (
    <tr>
      {[...Array(6)].map((_, i) => (
        <td key={i} className="px-4 py-3">
          <div className="animate-pulse bg-gray-200 rounded h-4 w-full" />
        </td>
      ))}
    </tr>
  )
}

export default function ATMFleetTable({ atms = [], isLoading }) {
  const [expandedId, setExpandedId] = useState(null)

  function toggleRow(atmId) {
    setExpandedId(prev => (prev === atmId ? null : atmId))
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200">
      <table className="min-w-full bg-white">
        <thead className="bg-gray-50">
          <tr>
            {['ATM ID', 'Branch', 'OEM', 'Status', 'Last EJ Date', 'Pending Uploads'].map(col => (
              <th key={col} className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200">
          {isLoading
            ? [...Array(5)].map((_, i) => <SkeletonRow key={i} />)
            : atms.map(atm => (
                <>
                  <tr
                    key={atm.atm_id}
                    onClick={() => toggleRow(atm.atm_id)}
                    className="hover:bg-gray-50 cursor-pointer"
                  >
                    <td className="px-4 py-3 text-sm font-mono text-gray-900">{atm.atm_id}</td>
                    <td className="px-4 py-3 text-sm text-gray-700">{atm.branch}</td>
                    <td className="px-4 py-3 text-sm font-mono text-gray-600">{atm.oem}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_STYLES[atm.status] || 'bg-gray-100 text-gray-700'}`}>
                        {atm.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">{atm.last_ej_date}</td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      {atm.pending_uploads > 0 ? (
                        <span className="text-amber-700 font-semibold">{atm.pending_uploads}</span>
                      ) : (
                        <span className="text-gray-400">0</span>
                      )}
                    </td>
                  </tr>
                  {expandedId === atm.atm_id && (
                    <tr key={`${atm.atm_id}-detail`} className="bg-blue-50">
                      <td colSpan={6} className="px-6 py-4">
                        <div className="grid grid-cols-3 gap-4 text-sm">
                          <div>
                            <span className="text-gray-500 text-xs uppercase font-semibold">ATM ID</span>
                            <p className="font-mono text-gray-900 mt-0.5">{atm.atm_id}</p>
                          </div>
                          <div>
                            <span className="text-gray-500 text-xs uppercase font-semibold">Branch</span>
                            <p className="text-gray-900 mt-0.5">{atm.branch}</p>
                          </div>
                          <div>
                            <span className="text-gray-500 text-xs uppercase font-semibold">OEM</span>
                            <p className="font-mono text-gray-900 mt-0.5">{atm.oem}</p>
                          </div>
                          <div>
                            <span className="text-gray-500 text-xs uppercase font-semibold">Status</span>
                            <p className="mt-0.5">
                              <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_STYLES[atm.status] || 'bg-gray-100 text-gray-700'}`}>
                                {atm.status}
                              </span>
                            </p>
                          </div>
                          <div>
                            <span className="text-gray-500 text-xs uppercase font-semibold">Last EJ Date</span>
                            <p className="text-gray-900 mt-0.5">{atm.last_ej_date}</p>
                          </div>
                          <div>
                            <span className="text-gray-500 text-xs uppercase font-semibold">Pending Uploads</span>
                            <p className="text-gray-900 mt-0.5">{atm.pending_uploads}</p>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              ))}
        </tbody>
      </table>
    </div>
  )
}

const STATUS_STYLES = {
  AUTO_RESOLVED: 'bg-green-100 text-green-800',
  ESCALATED_TO_HUMAN: 'bg-red-100 text-red-800',
  PENDING: 'bg-amber-100 text-amber-800',
}

const inrFormat = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 0,
})

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

export default function DisputeTable({ disputes = [], isLoading }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200">
      <table className="min-w-full bg-white">
        <thead className="bg-gray-50">
          <tr>
            {['NPCI Claim ID', 'ATM ID', 'Amount', 'Claim Type', 'Status'].map(col => (
              <th key={col} className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200">
          {isLoading
            ? [...Array(5)].map((_, i) => <SkeletonRow key={i} />)
            : disputes.map(d => (
              <tr key={d.npci_claim_id} className="hover:bg-gray-50">
                <td className="px-4 py-3 text-sm font-mono text-gray-900">{d.npci_claim_id}</td>
                <td className="px-4 py-3 text-sm font-mono text-gray-600">{d.atm_id}</td>
                <td className="px-4 py-3 text-sm font-semibold text-gray-900">
                  {inrFormat.format(d.amount)}
                </td>
                <td className="px-4 py-3 text-sm text-gray-600">{d.claim_type}</td>
                <td className="px-4 py-3">
                  <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_STYLES[d.status] || 'bg-gray-100 text-gray-700'}`}>
                    {d.status.replace(/_/g, ' ')}
                  </span>
                </td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  )
}

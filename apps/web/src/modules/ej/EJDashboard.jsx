import { useState } from 'react'
import ATMFleetTable from './components/ATMFleetTable'
import EJLogTable from './components/EJLogTable'
import DisputeTable from './components/DisputeTable'
import SubmitLogModal from './components/SubmitLogModal'
import RaiseDisputeModal from './components/RaiseDisputeModal'
import { useATMFleet, useEJLogs, useDisputes } from './hooks/useEJData'

const TABS = [
  { id: 'fleet', label: 'ATM Fleet Map' },
  { id: 'logs', label: 'EJ Logs' },
  { id: 'disputes', label: 'Disputes' },
]

const bankId = 'demo-bank' // TODO: get from auth context

export default function EJDashboard() {
  const [activeTab, setActiveTab] = useState('fleet')
  const [submitLogOpen, setSubmitLogOpen] = useState(false)
  const [raiseDisputeOpen, setRaiseDisputeOpen] = useState(false)

  const { data: atms, isLoading: atmsLoading } = useATMFleet(bankId)
  const { data: logs, isLoading: logsLoading } = useEJLogs(bankId)
  const { data: disputes, isLoading: disputesLoading } = useDisputes(bankId)

  return (
    <div className="min-h-screen bg-gray-100">
      <div className="max-w-7xl mx-auto px-4 py-6">
        {/* Header */}
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-gray-900">EJ Intelligence</h1>
          <p className="text-sm text-gray-500 mt-1">ATM Electronic Journal Processing</p>
        </div>

        {/* Tab bar */}
        <div className="border-b border-gray-200 mb-6">
          <nav className="flex gap-6">
            {TABS.map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`pb-3 text-sm font-medium transition-colors ${
                  activeTab === tab.id
                    ? 'border-b-2 border-blue-600 text-blue-600'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </nav>
        </div>

        {/* Tab content */}
        {activeTab === 'fleet' && (
          <section>
            <div className="mb-4">
              <h2 className="text-base font-semibold text-gray-800">ATM Fleet Map</h2>
              <p className="text-xs text-gray-500 mt-0.5">Click a row to expand ATM details.</p>
            </div>
            <ATMFleetTable atms={atms} isLoading={atmsLoading} />
          </section>
        )}

        {activeTab === 'logs' && (
          <section>
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-base font-semibold text-gray-800">EJ Logs</h2>
                <p className="text-xs text-gray-500 mt-0.5">Normalised Electronic Journal records.</p>
              </div>
              <button
                onClick={() => setSubmitLogOpen(true)}
                className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700"
              >
                Submit Log
              </button>
            </div>
            <EJLogTable logs={logs} isLoading={logsLoading} />
          </section>
        )}

        {activeTab === 'disputes' && (
          <section>
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-base font-semibold text-gray-800">Disputes</h2>
                <p className="text-xs text-gray-500 mt-0.5">NPCI dispute cases and resolution status.</p>
              </div>
              <button
                onClick={() => setRaiseDisputeOpen(true)}
                className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700"
              >
                Raise Dispute
              </button>
            </div>
            <DisputeTable disputes={disputes} isLoading={disputesLoading} />
          </section>
        )}
      </div>

      <SubmitLogModal isOpen={submitLogOpen} onClose={() => setSubmitLogOpen(false)} />
      <RaiseDisputeModal isOpen={raiseDisputeOpen} onClose={() => setRaiseDisputeOpen(false)} />
    </div>
  )
}

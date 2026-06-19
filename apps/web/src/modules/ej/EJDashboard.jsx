import { useState } from 'react'
import ATMFleetTable from './components/ATMFleetTable'
import EJLogTable from './components/EJLogTable'
import DisputeTable from './components/DisputeTable'
import SubmitLogModal from './components/SubmitLogModal'
import RaiseDisputeModal from './components/RaiseDisputeModal'
import { useATMFleet, useEJLogs, useDisputes } from './hooks/useEJData'
import EJShell from './layout/EJShell'
import { useTheme } from '../../shared/theme/ThemeContext'

const TABS = [
  { id: 'fleet', label: 'ATM Fleet Map' },
  { id: 'logs', label: 'EJ Logs' },
  { id: 'disputes', label: 'Disputes' },
]

const bankId = 'demo-bank'

export default function EJDashboard({ defaultTab = 'fleet' }) {
  const [activeTab, setActiveTab] = useState(defaultTab)
  const [submitLogOpen, setSubmitLogOpen] = useState(false)
  const [raiseDisputeOpen, setRaiseDisputeOpen] = useState(false)
  const { isDark } = useTheme()

  const { data: atms, isLoading: atmsLoading } = useATMFleet(bankId)
  const { data: logs, isLoading: logsLoading } = useEJLogs(bankId)
  const { data: disputes, isLoading: disputesLoading } = useDisputes(bankId)

  const heading   = isDark ? 'text-gray-100' : 'text-gray-900'
  const subtext   = isDark ? 'text-gray-400' : 'text-gray-500'
  const tabBorder = isDark ? 'border-gray-700' : 'border-gray-200'
  const tabActive = isDark ? 'border-blue-400 text-blue-400' : 'border-blue-600 text-blue-600'
  const tabIdle   = isDark ? 'text-gray-500 hover:text-gray-300' : 'text-gray-500 hover:text-gray-700'
  const sectionH  = isDark ? 'text-gray-200' : 'text-gray-800'

  return (
    <EJShell>
      <div className="max-w-7xl mx-auto px-4 py-6">
        {/* Header */}
        <div className="mb-6">
          <h1 className={`text-2xl font-bold ${heading}`}>EJ Intelligence</h1>
          <p className={`text-sm mt-1 ${subtext}`}>ATM Electronic Journal Processing</p>
        </div>

        {/* Tab bar */}
        <div className={`border-b ${tabBorder} mb-6`}>
          <nav className="flex gap-6">
            {TABS.map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`pb-3 text-sm font-medium transition-colors ${
                  activeTab === tab.id
                    ? `border-b-2 ${tabActive}`
                    : tabIdle
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
              <h2 className={`text-base font-semibold ${sectionH}`}>ATM Fleet Map</h2>
              <p className={`text-xs mt-0.5 ${subtext}`}>Click a row to expand ATM details.</p>
            </div>
            <ATMFleetTable atms={atms} isLoading={atmsLoading} />
          </section>
        )}

        {activeTab === 'logs' && (
          <section>
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className={`text-base font-semibold ${sectionH}`}>EJ Logs</h2>
                <p className={`text-xs mt-0.5 ${subtext}`}>Normalised Electronic Journal records.</p>
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
                <h2 className={`text-base font-semibold ${sectionH}`}>Disputes</h2>
                <p className={`text-xs mt-0.5 ${subtext}`}>NPCI dispute cases and resolution status.</p>
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
    </EJShell>
  )
}

import { useState, useEffect } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import QueueCard from '../components/QueueCard'
import ReviewPanel from '../components/ReviewPanel'
import useReviewQueue from '../hooks/useReviewQueue'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'
import { useBankContext } from '../../../shared/context/BankContext'

const SESSION_START = new Date(new Date().setHours(10, 0, 0, 0))
const IET_WINDOW_MINS = 180

// SMB-scoped mock instruments — drawn on this SMB's customers, routed through sponsor bank
const SMB_MOCK_ITEMS = [
  {
    instrument_id: 'CHQ-SMB-001847',
    workflow_id: 'wf-smb-001847',
    bank_id: 'saraswat-coop',
    smb_id: 'cosmos-coop',
    account_display: '****7812',
    payee_display: 'K***',
    amount_range: '₹[1L-5L]',
    clearing_zone: 'MUMBAI',
    received_at: Math.floor(Date.now() / 1000) - 480,
    iet_deadline: Math.floor(Date.now() / 1000) + 8220,
    reason: 'SIGNATURE_LOW_CONFIDENCE',
    fraud_score: 0.43,
    vision_confidence: 0.97,
    sig_match_score: 0.61,
    status: 'PENDING',
  },
  {
    instrument_id: 'CHQ-SMB-001901',
    workflow_id: 'wf-smb-001901',
    bank_id: 'saraswat-coop',
    smb_id: 'cosmos-coop',
    account_display: '****3341',
    payee_display: 'P***',
    amount_range: '₹[5L-10L]',
    clearing_zone: 'MUMBAI',
    received_at: Math.floor(Date.now() / 1000) - 1200,
    iet_deadline: Math.floor(Date.now() / 1000) + 7500,
    reason: 'FRAUD_SCORE_HIGH',
    fraud_score: 0.78,
    vision_confidence: 0.95,
    sig_match_score: 0.88,
    status: 'PENDING',
  },
  {
    instrument_id: 'CHQ-SMB-001733',
    workflow_id: 'wf-smb-001733',
    bank_id: 'saraswat-coop',
    smb_id: 'cosmos-coop',
    account_display: '****5509',
    payee_display: 'M***',
    amount_range: '₹[>1Cr]',
    clearing_zone: 'MUMBAI',
    received_at: Math.floor(Date.now() / 1000) - 2700,
    iet_deadline: Math.floor(Date.now() / 1000) + 6000,
    reason: 'HIGH_VALUE_DUAL_APPROVAL',
    fraud_score: 0.31,
    vision_confidence: 0.98,
    sig_match_score: 0.94,
    status: 'PENDING',
  },
]

function formatSponsorLabel(sponsorBankId) {
  if (!sponsorBankId) return 'Sponsor Bank'
  return sponsorBankId
    .replace(/-/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase())
}

export default function CTSSMBReviewQueue() {
  const { bankId, bankName, isSMB, sponsorBankId } = useBankContext()
  const { isDark } = useTheme()
  const { items: liveItems, loading: queueLoading } = useReviewQueue({ pollEnabled: true })
  const [queue, setQueue] = useState([])
  const [selected, setSelected] = useState(null)
  const [decisions, setDecisions] = useState([])
  const [now, setNow] = useState(new Date())

  const sponsorLabel = formatSponsorLabel(sponsorBankId)

  // In production: API pre-filters by smb_id from JWT claim
  // In demo: liveItems are SB mock data — fall through to SMB_MOCK_ITEMS
  useEffect(() => {
    if (!queueLoading) {
      const smbFiltered = liveItems.filter(i => !i.smb_id || i.smb_id === bankId)
      const items = smbFiltered.length > 0 ? smbFiltered : SMB_MOCK_ITEMS

      setQueue(prev => {
        const localState = new Map(prev.map(i => [i.instrument_id, i.status]))
        const merged = items.map(i => ({
          ...i,
          status: localState.get(i.instrument_id) ?? (i.status || 'PENDING'),
        }))
        if (prev.length === 0 && merged.length > 0) {
          const first = merged.find(i => i.status === 'PENDING')
          if (first) setSelected(first)
        }
        return merged
      })
    }
  }, [liveItems, queueLoading, bankId])

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])

  const pending = queue.filter(q => q.status === 'PENDING')
  const decided = queue.filter(q => q.status !== 'PENDING')

  const handleDecision = (id, action, reason) => {
    setQueue(prev =>
      prev.map(item =>
        item.instrument_id === id
          ? { ...item, status: action === 'CONFIRM' ? 'CONFIRMED' : 'RETURNED' }
          : item
      )
    )
    setDecisions(prev => [{ id, action, reason, ts: new Date().toLocaleTimeString() }, ...prev])
    const next = pending.find(p => p.instrument_id !== id)
    setSelected(next || null)
  }

  const elapsed = Math.max(0, Math.floor((now - SESSION_START) / 1000))
  const elapsedStr = [
    String(Math.floor(elapsed / 3600)).padStart(2, '0'),
    String(Math.floor((elapsed % 3600) / 60)).padStart(2, '0'),
    String(elapsed % 60).padStart(2, '0'),
  ].join(':')

  usePageHeader({
    subtitle: `${bankName || bankId} · Routed via ${sponsorLabel} · IET ${IET_WINDOW_MINS}min`,
    actions: (
      <div className="flex items-center gap-3">
        <div className={`text-[10px] font-mono px-3 py-1.5 rounded-lg border ${
          isDark ? 'border-white/10 text-slate-300 bg-white/4' : 'border-slate-200 text-slate-600 bg-white'
        }`}>
          Session {elapsedStr}
        </div>
        <div className={`flex items-center gap-1.5 text-[10px] px-3 py-1.5 rounded-lg border ${
          pending.length > 0
            ? isDark ? 'border-amber-700/40 bg-amber-900/20 text-amber-300' : 'border-amber-200 bg-amber-50 text-amber-700'
            : isDark ? 'border-emerald-700/40 bg-emerald-900/20 text-emerald-300' : 'border-emerald-200 bg-emerald-50 text-emerald-700'
        }`}>
          <span className={`w-1.5 h-1.5 rounded-full ${pending.length > 0 ? 'bg-amber-400 animate-pulse' : 'bg-emerald-400'}`} />
          {pending.length > 0 ? `${pending.length} awaiting review` : 'Queue clear'}
        </div>
      </div>
    ),
  })

  const th = {
    divider:   isDark ? 'border-white/8'  : 'border-slate-200',
    dividerSm: isDark ? 'border-white/5'  : 'border-slate-100',
    heading:   isDark ? 'text-white'      : 'text-slate-900',
    muted:     isDark ? 'text-slate-400'  : 'text-slate-500',
    faint:     isDark ? 'text-slate-500'  : 'text-slate-400',
    decided:   isDark ? 'border-white/5 bg-white/5' : 'border-slate-100 bg-slate-50',
    footer:    isDark ? 'border-white/5'  : 'border-slate-100',
    empty:     isDark ? 'text-slate-500'  : 'text-slate-400',
    smbBadge:  isDark ? 'bg-violet-900/30 text-violet-300 border-violet-700/30'
                      : 'bg-violet-50 text-violet-700 border-violet-200',
    infoBand:  isDark ? 'bg-sky-900/20 border-sky-700/20 text-sky-300'
                      : 'bg-sky-50 border-sky-200 text-sky-700',
  }

  return (
    <AppShell>
      <div className="flex flex-col h-full">
        {/* SMB context banner */}
        <div className={`px-6 py-2.5 border-b ${th.divider} flex items-center gap-3`}>
          <div className={`text-[11px] px-2.5 py-1 rounded-md border font-semibold ${th.smbBadge}`}>
            SMB · {bankName || bankId}
          </div>
          <div className={`text-[11px] px-2.5 py-1 rounded-md border ${th.infoBand}`}>
            Routed via {sponsorLabel} · You see only your own instruments
          </div>
          <div className="ml-auto flex items-center gap-4">
            <div className="flex items-center gap-2 text-[11px]">
              <span className={th.faint}>Pending</span>
              <span className={`font-black text-lg tabular-nums ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>
                {pending.length}
              </span>
            </div>
            <div className={`w-px h-4 ${isDark ? 'bg-white/10' : 'bg-slate-200'}`} />
            <div className="flex items-center gap-2 text-[11px]">
              <span className={th.faint}>Decided</span>
              <span className={`font-black text-lg tabular-nums ${isDark ? 'text-slate-300' : 'text-slate-700'}`}>
                {decided.length}
              </span>
            </div>
          </div>
        </div>

        <div className="flex flex-1 min-h-0">
          {/* Queue column */}
          <div className={`w-72 shrink-0 border-r ${th.divider} flex flex-col`}>
            <div className={`px-4 py-3 border-b ${th.dividerSm} flex items-center justify-between`}>
              <div className={`text-xs font-semibold ${th.heading}`}>Your Review Queue</div>
              <span className={`text-[10px] font-mono px-2 py-0.5 rounded-full border ${
                pending.length > 0
                  ? 'text-amber-500 border-amber-500/30 bg-amber-500/10'
                  : 'text-emerald-500 border-emerald-500/30 bg-emerald-500/10'
              }`}>
                {pending.length} pending
              </span>
            </div>

            <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2">
              {pending.length === 0 && (
                <div className={`text-center ${th.empty} text-sm py-12`}>
                  <div className="text-3xl mb-2">✓</div>
                  <div>Queue clear</div>
                </div>
              )}
              {pending.map(item => (
                <QueueCard
                  key={item.instrument_id}
                  item={item}
                  selected={selected?.instrument_id === item.instrument_id}
                  onClick={() => setSelected(item)}
                  isDark={isDark}
                />
              ))}

              {decided.length > 0 && (
                <>
                  <div className={`text-[10px] ${th.faint} uppercase tracking-widest pt-3 pb-1 px-1`}>
                    Decided this session
                  </div>
                  {decided.map(item => (
                    <div key={item.instrument_id} className={`rounded-xl border ${th.decided} px-4 py-3 opacity-50`}>
                      <div className="flex items-center justify-between">
                        <div className={`text-[11px] font-mono ${th.muted}`}>{item.instrument_id}</div>
                        <span className={`text-[10px] font-semibold ${
                          item.status === 'CONFIRMED' ? 'text-emerald-500' : 'text-red-500'
                        }`}>
                          {item.status === 'CONFIRMED' ? '✓ Confirmed' : '✕ Returned'}
                        </span>
                      </div>
                    </div>
                  ))}
                </>
              )}
            </div>
          </div>

          {/* Review panel — reuses the same SB component; smb_id on item is informational only */}
          <ReviewPanel item={selected} onDecision={handleDecision} />

          {/* Session summary — right rail (SMB has no STP stream, just decision log) */}
          <div className={`w-60 shrink-0 border-l ${th.divider} flex flex-col`}>
            <div className={`px-4 py-3 border-b ${th.dividerSm}`}>
              <div className={`text-xs font-semibold ${th.heading}`}>This Session</div>
            </div>

            <div className="flex-1 overflow-y-auto px-4 py-4">
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className={`text-[11px] font-medium ${th.muted}`}>Confirmed</span>
                  <span className={`text-3xl font-black leading-none tabular-nums ${isDark ? 'text-emerald-400' : 'text-emerald-600'}`}>
                    {decisions.filter(d => d.action === 'CONFIRM').length}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className={`text-[11px] font-medium ${th.muted}`}>Returned</span>
                  <span className={`text-3xl font-black leading-none tabular-nums ${isDark ? 'text-red-400' : 'text-red-600'}`}>
                    {decisions.filter(d => d.action === 'RETURN').length}
                  </span>
                </div>
                <div className={`flex items-center justify-between pt-3 border-t ${th.divider}`}>
                  <span className={`text-[11px] font-medium ${th.muted}`}>Pending</span>
                  <span className={`text-3xl font-black leading-none tabular-nums ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>
                    {pending.length}
                  </span>
                </div>
                <div className={`flex items-center justify-between pt-3 border-t ${th.divider}`}>
                  <span className={`text-[11px] font-medium ${th.muted}`}>Immudb writes</span>
                  <span className={`text-3xl font-black leading-none tabular-nums ${isDark ? 'text-slate-300' : 'text-slate-600'}`}>
                    {decisions.length}
                  </span>
                </div>
              </div>

              {/* Recent decisions */}
              {decisions.length > 0 && (
                <div className={`mt-5 pt-5 border-t ${th.divider}`}>
                  <div className={`text-[10px] uppercase tracking-widest mb-2 ${th.faint}`}>
                    Recent decisions
                  </div>
                  <div className="space-y-2">
                    {decisions.slice(0, 6).map((d, i) => (
                      <div
                        key={i}
                        className={`rounded-lg px-3 py-2 border ${
                          d.action === 'CONFIRM'
                            ? isDark ? 'border-emerald-700/30 bg-emerald-900/10' : 'border-emerald-200 bg-emerald-50'
                            : isDark ? 'border-red-700/30 bg-red-900/10' : 'border-red-200 bg-red-50'
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <span className={`text-[10px] font-semibold ${d.action === 'CONFIRM' ? 'text-emerald-500' : 'text-red-500'}`}>
                            {d.action === 'CONFIRM' ? '✓ Confirmed' : '✕ Returned'}
                          </span>
                          <span className={`text-[9px] font-mono ${th.faint}`}>{d.ts}</span>
                        </div>
                        <div className={`text-[10px] font-mono truncate mt-0.5 ${th.muted}`}>{d.id}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* SMB identity footer */}
            <div className={`px-4 py-4 border-t ${th.footer}`}>
              <div className={`text-[10px] ${th.faint} mb-1`}>Your bank</div>
              <div className={`text-[11px] font-semibold ${th.heading}`}>{bankName || bankId}</div>
              <div className={`text-[10px] mt-0.5 ${th.faint}`}>via {sponsorLabel}</div>
              <div className={`text-[10px] mt-3 px-2 py-1.5 rounded-lg border text-center ${th.infoBand}`}>
                Every decision → Immudb audit
              </div>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  )
}

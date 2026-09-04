import { X, Bot, Cpu, ShieldCheck, User } from 'lucide-react'

const actorConfig = {
  rules_engine: { label: 'Rules Engine', icon: Cpu, color: 'text-blue-400 bg-blue-500/10 border-blue-500/20' },
  llm_agent:    { label: 'LLM Agent',    icon: Bot, color: 'text-purple-400 bg-purple-500/10 border-purple-500/20' },
  guardrail:    { label: 'Guardrail',     icon: ShieldCheck, color: 'text-amber-400 bg-amber-500/10 border-amber-500/20' },
  human:        { label: 'Human',         icon: User, color: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20' },
}

const eventStyles = {
  diagnosed:        'border-blue-500',
  action_proposed:  'border-purple-500',
  action_validated: 'border-emerald-500',
  action_rejected:  'border-red-500',
  action_executed:  'border-emerald-500',
  escalated:        'border-amber-500',
  recovered:        'border-emerald-500',
}

function formatTimestamp(ts) {
  if (!ts) return '—'
  try {
    return new Date(ts).toLocaleString('en-IN', {
      dateStyle: 'medium',
      timeStyle: 'medium'
    })
  } catch {
    return ts
  }
}

function formatINR(amount) {
  if (amount == null) return null
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0,
  }).format(amount)
}

export default function AuditDrawer({ transaction, onClose }) {
  const audits = transaction.audit_history || []

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/60 z-50"
        onClick={onClose}
      />

      {/* Drawer */}
      <div className="fixed top-0 right-0 h-full w-full max-w-lg bg-[#0d0d14] border-l border-zinc-800 z-50 overflow-y-auto shadow-2xl">
        {/* Header */}
        <div className="sticky top-0 bg-[#0d0d14]/95 border-b border-zinc-800 px-6 py-4 flex items-center justify-between z-10">
          <div>
            <h2 className="text-lg font-bold text-white">Audit Trail</h2>
            <p className="text-xs text-zinc-500 font-mono mt-0.5">
              {transaction.id}
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-zinc-800 transition-colors cursor-pointer"
          >
            <X className="w-5 h-5 text-zinc-400" />
          </button>
        </div>

        {/* Transaction Summary */}
        <div className="px-6 py-4 border-b border-zinc-800 space-y-2">
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <span className="text-zinc-500 text-xs">Amount</span>
              <p className="text-white font-semibold font-mono tabular-nums">{formatINR(transaction.amount)}</p>
            </div>
            <div>
              <span className="text-zinc-500 text-xs">Status</span>
              <p className="text-white font-semibold">{transaction.status}</p>
            </div>
            <div>
              <span className="text-zinc-500 text-xs">Failure Code</span>
              <p className="text-zinc-300 font-mono text-xs">{transaction.failure_code}</p>
            </div>
            <div>
              <span className="text-zinc-500 text-xs">Attempts</span>
              <p className="text-zinc-300">{transaction.attempt_count}/{transaction.max_attempts}</p>
            </div>
          </div>
        </div>

        {/* Timeline */}
        <div className="px-6 py-5">
          <h3 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-4">
            Immutable Event Timeline
          </h3>

          {audits.length === 0 ? (
            <p className="text-zinc-500 text-sm">No audit events recorded yet.</p>
          ) : (
            <div className="relative">
              {/* Vertical line */}
              <div className="absolute left-[11px] top-2 bottom-2 w-px bg-zinc-800" />

              <div className="space-y-5">
                {audits.map((audit, idx) => {
                  const actor = actorConfig[audit.actor] || actorConfig.rules_engine
                  const Icon = actor.icon
                  const borderColor = eventStyles[audit.event_type] || 'border-zinc-500'

                  return (
                    <div key={idx} className="relative flex gap-4">
                      {/* Timeline dot */}
                      <div className={`relative z-10 w-[24px] h-[24px] rounded-full border-2 ${borderColor} bg-[#0d0d14] flex items-center justify-center shrink-0`}>
                        <Icon className="w-3 h-3 text-zinc-300" />
                      </div>

                      {/* Content */}
                      <div className="flex-1 min-w-0 pb-1">
                        <div className="flex items-center gap-2 mb-1 flex-wrap">
                          <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold uppercase border ${actor.color}`}>
                            {actor.label}
                          </span>
                          <span className="text-[10px] text-zinc-500 font-mono uppercase">
                            {audit.event_type}
                          </span>
                          {audit.event_type === 'action_rejected' && (
                            <span className="text-[10px] font-bold text-red-500 uppercase tracking-widest">
                              [BLOCKED]
                            </span>
                          )}
                        </div>
                        <p className="text-sm text-zinc-300 leading-relaxed">
                          {audit.justification}
                        </p>
                        
                        {(audit.event_type === 'action_proposed' || audit.event_type === 'action_rejected') && (
                          <details className="mt-2 group">
                            <summary className="text-[10px] text-zinc-500 cursor-pointer hover:text-zinc-400 select-none font-mono tracking-wide">
                              ▶ VIEW PAYLOAD
                            </summary>
                            <pre className="mt-2 p-3 rounded-md bg-zinc-900/50 border border-zinc-800/50 text-[10px] text-zinc-300 font-mono overflow-x-auto">
                              {(() => {
                                try {
                                  return JSON.stringify(JSON.parse(audit.payload_json), null, 2)
                                } catch {
                                  return audit.payload_json
                                }
                              })()}
                            </pre>
                          </details>
                        )}
                        
                        {audit.outcome_amount != null && (
                          <p className="text-xs text-emerald-400 font-mono tabular-nums mt-1">
                            Recovery: {formatINR(audit.outcome_amount)}
                          </p>
                        )}
                        <p className="text-[10px] font-mono text-zinc-600 mt-1">
                          {formatTimestamp(audit.timestamp)}
                        </p>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  )
}

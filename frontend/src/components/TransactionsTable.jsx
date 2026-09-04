import { ChevronRight } from 'lucide-react'

const statusStyles = {
  RECOVERED: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
  ESCALATED: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  FAILED:    'bg-zinc-500/15 text-zinc-400 border-zinc-500/30',
  ABANDONED: 'bg-zinc-500/15 text-zinc-400 border-zinc-500/30',
}

function formatINR(amount) {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0,
  }).format(amount)
}

function getAIAction(tx) {
  const auditHistory = tx.audit_history || []
  const actionEntry = auditHistory.find(a => a.event_type === 'action_proposed')
  if (!actionEntry) return '—'
  try {
    const payload = typeof actionEntry.payload_json === 'string'
      ? JSON.parse(actionEntry.payload_json.replace(/'/g, '"'))
      : actionEntry.payload_json
    return payload.action || '—'
  } catch {
    return '—'
  }
}

export default function TransactionsTable({ transactions, onSelectTx }) {
  if (!transactions.length) {
    return (
      <div className="text-center text-zinc-500 py-12">
        No transactions found. Run seed data or simulate a batch.
      </div>
    )
  }

  return (
    <div className="rounded-md border border-zinc-800 overflow-hidden">
      <div className="px-3 py-1.5 border-b border-zinc-800 bg-[#111118]">
        <h2 className="text-xs font-semibold text-zinc-300 uppercase tracking-wider">
          Transactions ({transactions.length})
        </h2>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-zinc-800 bg-[#0d0d14]">
              <th className="text-left px-3 py-1.5 font-medium text-zinc-500 uppercase tracking-wider">ID</th>
              <th className="text-right px-3 py-1.5 font-medium text-zinc-500 uppercase tracking-wider">Amount</th>
              <th className="text-left px-3 py-1.5 font-medium text-zinc-500 uppercase tracking-wider">Failure Code</th>
              <th className="text-left px-3 py-1.5 font-medium text-zinc-500 uppercase tracking-wider">AI Action</th>
              <th className="text-left px-3 py-1.5 font-medium text-zinc-500 uppercase tracking-wider">Status</th>
              <th className="text-center px-3 py-1.5 font-medium text-zinc-500 uppercase tracking-wider">Attempts</th>
              <th className="px-3 py-1.5"></th>
            </tr>
          </thead>
          <tbody>
            {transactions.map((tx) => (
              <tr
                key={tx.id}
                onClick={() => onSelectTx(tx)}
                className="border-b border-zinc-800/50 hover:bg-zinc-800/30 cursor-pointer transition-colors"
              >
                <td className="px-3 py-1.5 font-mono text-zinc-400">
                  {tx.id?.substring(0, 8)}...
                </td>
                <td className="px-3 py-1.5 text-right font-mono tabular-nums text-zinc-200">
                  {formatINR(tx.amount)}
                </td>
                <td className="px-3 py-1.5">
                  <code className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-300">
                    {tx.failure_code}
                  </code>
                </td>
                <td className="px-3 py-1.5 text-zinc-400">
                  {getAIAction(tx)}
                </td>
                <td className="px-3 py-1.5">
                  <span
                    className={`inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-medium border ${
                      statusStyles[tx.status] || statusStyles.FAILED
                    }`}
                  >
                    {tx.status}
                  </span>
                </td>
                <td className="px-3 py-1.5 text-center text-zinc-400">
                  {tx.attempt_count}/{tx.max_attempts}
                </td>
                <td className="px-3 py-1.5">
                  <ChevronRight className="w-3.5 h-3.5 text-zinc-600" />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

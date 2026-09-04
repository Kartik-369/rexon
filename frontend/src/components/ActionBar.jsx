import { Play, AlertTriangle, CheckCircle, XCircle, Info } from 'lucide-react'

export default function ActionBar({ onBatchRecovery, onDeliberateFailure, feedback }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-3">
        <button
          onClick={onBatchRecovery}
          className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-xs transition-colors cursor-pointer"
        >
          <Play className="w-3.5 h-3.5" />
          Run Batch Recovery
        </button>
        <button
          onClick={onDeliberateFailure}
          className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-red-600/80 hover:bg-red-500 text-white font-medium text-xs transition-colors border border-red-500/30 cursor-pointer"
        >
          <AlertTriangle className="w-3.5 h-3.5" />
          Simulate Rogue Action (Deliberate Failure)
        </button>
      </div>

      {feedback && (
        <div
          className={`flex items-start gap-3 px-4 py-3 rounded-lg border text-sm ${
            feedback.type === 'success'
              ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
              : feedback.type === 'error'
              ? 'bg-red-500/10 border-red-500/30 text-red-300'
              : feedback.type === 'guardrail'
              ? 'bg-amber-500/10 border-amber-500/30 text-amber-300'
              : 'bg-indigo-500/10 border-indigo-500/30 text-indigo-300'
          }`}
        >
          {feedback.type === 'success' && <CheckCircle className="w-5 h-5 mt-0.5 shrink-0" />}
          {feedback.type === 'error' && <XCircle className="w-5 h-5 mt-0.5 shrink-0" />}
          {feedback.type === 'guardrail' && <AlertTriangle className="w-5 h-5 mt-0.5 shrink-0" />}
          {feedback.type === 'info' && <Info className="w-5 h-5 mt-0.5 shrink-0 animate-pulse" />}
          <div>
            <p className="font-medium">{feedback.message}</p>
            {feedback.detail && (
              <p className="text-xs mt-1 opacity-70">
                Guardrail: {feedback.detail.guardrail_status} | Action: {feedback.detail.proposed_action} | Discount: {feedback.detail.discount_pct}%
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

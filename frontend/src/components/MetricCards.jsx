import { IndianRupee, TrendingUp, ShieldAlert, BarChart3 } from 'lucide-react'

function formatINR(amount) {
  if (amount == null) return '₹0'
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0,
  }).format(amount)
}

const cards = [
  {
    key: 'total_revenue_at_risk',
    label: 'Revenue at Risk',
    icon: IndianRupee,
    color: 'text-red-400',
    bgColor: 'bg-red-500/10',
    borderColor: 'border-red-500/20',
    format: formatINR,
  },
  {
    key: 'total_recovered',
    label: 'Recovered Revenue',
    icon: TrendingUp,
    color: 'text-emerald-400',
    bgColor: 'bg-emerald-500/10',
    borderColor: 'border-emerald-500/20',
    format: formatINR,
  },
  {
    key: 'recovery_rate_percentage',
    label: 'Recovery Rate',
    icon: BarChart3,
    color: 'text-indigo-400',
    bgColor: 'bg-indigo-500/10',
    borderColor: 'border-indigo-500/20',
    format: (v) => `${(v ?? 0).toFixed(1)}%`,
  },
  {
    key: 'guardrail_anomalies_caught',
    label: 'Guardrail Anomalies',
    icon: ShieldAlert,
    color: 'text-amber-400',
    bgColor: 'bg-amber-500/10',
    borderColor: 'border-amber-500/20',
    format: (v) => v ?? 0,
  },
]

export default function MetricCards({ metrics }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      {cards.map((card) => {
        const Icon = card.icon
        const value = metrics?.[card.key]
        return (
          <div
            key={card.key}
            className={`rounded-md border-y border-r border-zinc-800 border-l-2 bg-zinc-900 ${card.borderColor.replace('border-', 'border-l-').replace('/20', '')} px-3 py-3`}
          >
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-medium text-zinc-400 uppercase tracking-wider">
                {card.label}
              </span>
              <Icon className={`w-5 h-5 ${card.color}`} />
            </div>
            <div className={`text-2xl font-bold ${card.color} font-mono tabular-nums`}>
              {card.format(value)}
            </div>
          </div>
        )
      })}
    </div>
  )
}

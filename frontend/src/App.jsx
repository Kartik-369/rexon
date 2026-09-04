import { useState, useEffect, useCallback } from 'react'
import Header from './components/Header'
import MetricCards from './components/MetricCards'
import ActionBar from './components/ActionBar'
import TransactionsTable from './components/TransactionsTable'
import AuditDrawer from './components/AuditDrawer'

function App() {
  const [metrics, setMetrics] = useState(null)
  const [transactions, setTransactions] = useState([])
  const [selectedTx, setSelectedTx] = useState(null)
  const [loading, setLoading] = useState(true)
  const [actionFeedback, setActionFeedback] = useState(null)

  const fetchData = useCallback(async () => {
    try {
      const [metricsRes, txRes] = await Promise.all([
        fetch('/api/metrics'),
        fetch('/api/transactions')
      ])
      const metricsData = await metricsRes.json()
      const txData = await txRes.json()
      setMetrics(metricsData)
      setTransactions(txData)
      return txData
    } catch (err) {
      console.error('Failed to fetch data:', err)
      return []
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  const handleBatchRecovery = async () => {
    setActionFeedback({ type: 'info', message: 'Running batch recovery...' })
    try {
      const res = await fetch('/api/recovery/process-batch', { method: 'POST' })
      const data = await res.json()
      setActionFeedback({ type: 'success', message: data.message })
      await fetchData()
    } catch (err) {
      setActionFeedback({ type: 'error', message: 'Batch recovery failed.' })
    }
  }

  const handleDeliberateFailure = async () => {
    // Find a FAILED transaction to use as target
    const failedTx = transactions.find(t => t.status === 'FAILED')
    if (!failedTx) {
      setActionFeedback({ type: 'error', message: 'No FAILED transactions available to simulate.' })
      return
    }
    setActionFeedback({ type: 'info', message: 'Simulating rogue 30% discount on ₹15,000+ transaction...' })
    try {
      const res = await fetch('/api/recovery/trigger-deliberate-failure', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          transaction_id: failedTx.id,
          action: 'apply_discount',
          discount_pct: 30
        })
      })
      const data = await res.json()
      const guardrailStatus = data.state?.guardrail_status || 'UNKNOWN'
      setActionFeedback({
        type: guardrailStatus !== 'PASSED' ? 'guardrail' : 'success',
        message: `Guardrail ${guardrailStatus}: ${data.message}`,
        detail: data.state
      })
      const txData = await fetchData()
      const updatedTx = txData.find(t => t.id === failedTx.id)
      if (updatedTx) setSelectedTx(updatedTx)
    } catch (err) {
      setActionFeedback({ type: 'error', message: 'Simulation failed.' })
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0a0a0f] flex items-center justify-center">
        <div className="text-zinc-400 text-lg animate-pulse">Loading Recon Dashboard...</div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-[#0a0a0f] text-zinc-100">
      <Header />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
        <MetricCards metrics={metrics} />
        <ActionBar
          onBatchRecovery={handleBatchRecovery}
          onDeliberateFailure={handleDeliberateFailure}
          feedback={actionFeedback}
        />
        <TransactionsTable
          transactions={transactions}
          onSelectTx={setSelectedTx}
        />
      </main>
      {selectedTx && (
        <AuditDrawer
          transaction={selectedTx}
          onClose={() => setSelectedTx(null)}
        />
      )}
    </div>
  )
}

export default App

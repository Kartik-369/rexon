import { Shield, Activity } from 'lucide-react'

export default function Header() {
  return (
    <header className="border-b border-zinc-800 bg-[#0a0a0f]/80 backdrop-blur-sm sticky top-0 z-40">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Shield className="w-8 h-8 text-indigo-500" />
          <div>
            <h1 className="text-xl font-bold tracking-tight text-white">
              Recon <span className="text-zinc-500 font-normal">|</span>{' '}
              <span className="text-zinc-300 font-medium text-base">
                Autonomous Bounded Recovery Engine
              </span>
            </h1>
            <p className="text-xs text-zinc-500 mt-0.5">Track 03 — AI Revenue Recovery</p>
          </div>
        </div>
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/20">
          <Activity className="w-3.5 h-3.5 text-emerald-400" />
          <span className="text-xs font-medium text-emerald-400">Agent Status: Guardrails Active</span>
        </div>
      </div>
    </header>
  )
}

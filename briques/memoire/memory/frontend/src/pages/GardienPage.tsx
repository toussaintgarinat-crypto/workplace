import { useEffect, useState } from 'react'
import { Sprout, Play, Check, X, Loader2, History, ScrollText } from 'lucide-react'
import * as api from '../services/api'
import type { GardienConfig, GardienSuggestion, GardienLogEntry } from '../types/api'

export default function GardienPage() {
  const [config, setConfig] = useState<GardienConfig | null>(null)
  const [suggestions, setSuggestions] = useState<GardienSuggestion[]>([])
  const [logs, setLogs] = useState<GardienLogEntry[]>([])
  const [running, setRunning] = useState(false)
  const [loading, setLoading] = useState(true)
  const [showLogs, setShowLogs] = useState(false)

  useEffect(() => {
    Promise.all([api.getGardienConfig(), api.getGardienSuggestions(), api.getGardienLog().catch(() => [])])
      .then(([c, s, l]) => { setConfig(c); setSuggestions(s); setLogs(l) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  async function handleRun() {
    setRunning(true)
    try {
      await api.runGardien()
      const [s, l] = await Promise.all([api.getGardienSuggestions(), api.getGardienLog().catch(() => [])])
      setSuggestions(s)
      setLogs(l)
    } catch {
      // ignore
    }
    setRunning(false)
  }

  async function handleAccept(id: string) {
    await api.acceptSuggestion(id)
    const [s, l] = await Promise.all([api.getGardienSuggestions(), api.getGardienLog().catch(() => [])])
    setSuggestions(s)
    setLogs(l)
  }

  async function handleReject(id: string) {
    await api.rejectSuggestion(id)
    const [s, l] = await Promise.all([api.getGardienSuggestions(), api.getGardienLog().catch(() => [])])
    setSuggestions(s)
    setLogs(l)
  }

  async function updateConfig(updates: Partial<GardienConfig>) {
    if (!config) return
    const next = { ...config, ...updates }
    setConfig(next)
    await api.updateGardienConfig(next)
  }

  function suggestionSummary(s: GardienSuggestion) {
    const d = s.details
    if (s.action === 'suggest_ipcra') {
      const llm = (d.llm_suggestion as string) || ''
      return llm.slice(0, 200)
    }
    if (s.action === 'suggest_archive') {
      const llm = (d.llm_decision as string) || ''
      return llm.slice(0, 200)
    }
    if (s.action === 'summarize_cluster') {
      const llm = (d.llm_summary as string) || ''
      return llm.slice(0, 200)
    }
    if (s.action === 'infer_link') {
      const target = (d.target_title as string) || ''
      return `Analyze link with "${target}"`
    }
    return JSON.stringify(s.details).slice(0, 150)
  }

  if (loading) {
    return <div className="text-text text-sm">Loading...</div>
  }

  return (
    <div className="max-w-3xl space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-text-heading">Gardien</h2>
          <p className="text-sm text-text mt-1">LLM-powered memory organization</p>
        </div>
        <button
          onClick={() => setShowLogs((v) => !v)}
          className="flex items-center gap-2 px-3 py-1.5 text-sm text-text hover:text-text-heading bg-surface-2 border border-border rounded-lg transition-colors"
        >
          <History size={16} />
          {showLogs ? 'Suggestions' : 'History'}
        </button>
      </div>

      {showLogs ? (
        <section className="space-y-3">
          <h3 className="font-medium text-text-heading text-sm">Action History ({logs.length})</h3>
          {logs.length === 0 ? (
            <div className="bg-surface-2 border border-border rounded-xl p-8 text-center">
              <ScrollText size={32} className="mx-auto text-text mb-3" />
              <p className="text-text-heading font-medium">No history yet</p>
              <p className="text-sm text-text mt-1">Run the gardien to see actions here</p>
            </div>
          ) : (
            <div className="space-y-1.5">
              {logs.map((log) => (
                <div key={log.id} className="bg-surface-2 border border-border rounded-lg p-3">
                  <div className="flex items-center justify-between gap-4">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-text-heading capitalize">
                          {log.action.replace(/_/g, ' ')}
                        </span>
                        <span className={`text-xs px-1.5 py-0.5 rounded ${
                          log.status === 'accepted' ? 'bg-emerald-500/10 text-emerald-400' :
                          log.status === 'rejected' ? 'bg-red-500/10 text-red-400' :
                          log.status === 'auto' ? 'bg-blue-500/10 text-blue-400' :
                          'bg-amber-500/10 text-amber-400'
                        }`}>
                          {log.status}
                        </span>
                      </div>
                      <p className="text-xs text-text mt-1 truncate">{suggestionSummary(log)}</p>
                    </div>
                    <span className="text-xs text-text/50 shrink-0">
                      {new Date(log.created_at).toLocaleString()}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      ) : (
        <>
          {config && (
            <section className="bg-surface-2 border border-border rounded-xl p-4 space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="font-medium text-text-heading text-sm">Configuration</h3>
                <button
                  onClick={handleRun}
                  disabled={running}
                  className="flex items-center gap-2 px-3 py-1.5 bg-memory-600 hover:bg-memory-700 disabled:opacity-50 text-white text-sm rounded-lg transition-colors"
                >
                  {running ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
                  {running ? 'Running...' : 'Run Now'}
                </button>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-text block mb-1">Mode</label>
                  <select
                    value={config.mode}
                    onChange={(e) => updateConfig({ mode: e.target.value })}
                    className="w-full px-2 py-1 bg-surface border border-border rounded text-sm text-text-heading focus:outline-none focus:border-memory-500"
                  >
                    <option value="propose">Propose</option>
                    <option value="auto">Auto</option>
                    <option value="off">Off</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs text-text block mb-1">Interval (min)</label>
                  <input
                    value={config.interval_minutes}
                    onChange={(e) => updateConfig({ interval_minutes: Number(e.target.value) })}
                    className="w-full px-2 py-1 bg-surface border border-border rounded text-sm text-text-heading focus:outline-none focus:border-memory-500"
                  />
                </div>
              </div>
              <div className="flex flex-wrap gap-4">
                {([
                  ['Summarize', config.auto_summarize, (v: boolean) => updateConfig({ auto_summarize: v })],
                  ['Merge', config.auto_merge, (v: boolean) => updateConfig({ auto_merge: v })],
                  ['Infer links', config.auto_infer, (v: boolean) => updateConfig({ auto_infer: v })],
                  ['Suggest IPCRa', config.auto_suggest_ipcra, (v: boolean) => updateConfig({ auto_suggest_ipcra: v })],
                  ['Auto-archive', config.auto_archive, (v: boolean) => updateConfig({ auto_archive: v })],
                ] as const).map(([label, value, onChange]) => (
                  <label key={label} className="flex items-center gap-2 text-sm text-text cursor-pointer">
                    <input
                      type="checkbox"
                      checked={value}
                      onChange={(e) => onChange(e.target.checked)}
                      className="rounded border-border bg-surface text-memory-500 focus:ring-memory-500"
                    />
                    {label}
                  </label>
                ))}
              </div>
            </section>
          )}

          <section className="space-y-3">
            <h3 className="font-medium text-text-heading text-sm">Suggestions ({suggestions.length})</h3>
            {suggestions.length === 0 ? (
              <div className="bg-surface-2 border border-border rounded-xl p-8 text-center">
                <Sprout size={32} className="mx-auto text-text mb-3" />
                <p className="text-text-heading font-medium">No pending suggestions</p>
                <p className="text-sm text-text mt-1">Run the gardien to get LLM-powered suggestions</p>
              </div>
            ) : (
              <div className="space-y-2">
                {suggestions.map((s) => (
                  <div key={s.id} className="bg-surface-2 border border-border rounded-xl p-4 flex items-start justify-between gap-4">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-text-heading text-sm capitalize">
                          {s.action.replace(/_/g, ' ')}
                        </span>
                        {s.node_id && (
                          <span className="text-xs text-text/50 font-mono">
                            {s.node_id.slice(0, 8)}
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-text mt-1 leading-relaxed">{suggestionSummary(s)}</p>
                      <p className="text-xs text-text/50 mt-1">{new Date(s.created_at).toLocaleString()}</p>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <button
                        onClick={() => handleAccept(s.id)}
                        className="p-1.5 rounded-lg hover:bg-emerald-500/10 text-emerald-400 transition-colors"
                        title="Accept"
                      >
                        <Check size={16} />
                      </button>
                      <button
                        onClick={() => handleReject(s.id)}
                        className="p-1.5 rounded-lg hover:bg-red-500/10 text-red-400 transition-colors"
                        title="Reject"
                      >
                        <X size={16} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  )
}

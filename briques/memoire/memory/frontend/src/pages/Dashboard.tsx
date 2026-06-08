import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  FileText,
  TrendingUp,
  Archive,
  Snowflake,
  type LucideIcon,
} from 'lucide-react'
import * as api from '../services/api'
import { useAppStore } from '../stores/appStore'
import type { NodeResponse } from '../types/api'

interface StatCard {
  label: string
  value: string | number
  icon: LucideIcon
  color: string
}

export default function Dashboard({ initDone = false }: { initDone?: boolean }) {
  const [recentNodes, setRecentNodes] = useState<NodeResponse[]>([])
  const [stats, setStats] = useState({ total: 0, hot: 0, archive: 0, coldArchive: 0 })
  const [loading, setLoading] = useState(true)
  const spaceId = useAppStore((s) => s.activeSpaceId)

  useEffect(() => {
    if (!spaceId) {
      if (initDone) setLoading(false)
      return
    }
    let cancelled = false
    async function loadData() {
      try {
        const nodes = await api.getNodes({ limit: 20 })
        if (cancelled) return
        const hot = nodes.filter((n) => n.storage_tier === 'hot')
        const archive = nodes.filter((n) => n.storage_tier === 'archive')
        const cold = nodes.filter((n) => n.storage_tier === 'cold_archive')
        setStats({ total: nodes.length, hot: hot.length, archive: archive.length, coldArchive: cold.length })
        setRecentNodes(nodes.slice(0, 10))
      } catch (e) {
        console.error('Dashboard load error:', e)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    loadData()
    return () => { cancelled = true }
  }, [spaceId, initDone])

  const cards: StatCard[] = [
    { label: 'Total Memories', value: stats.total, icon: FileText, color: 'text-memory-400' },
    { label: 'Hot', value: stats.hot, icon: TrendingUp, color: 'text-emerald-400' },
    { label: 'Archive', value: stats.archive, icon: Archive, color: 'text-amber-400' },
    { label: 'Cold Archive', value: stats.coldArchive, icon: Snowflake, color: 'text-sky-400' },
  ]

  function formatDate(d: string | null | undefined) {
    if (!d) return '—'
    return new Date(d).toLocaleDateString()
  }

  function tierBadge(tier: string) {
    const colors: Record<string, string> = {
      hot: 'bg-emerald-500/10 text-emerald-400',
      archive: 'bg-amber-500/10 text-amber-400',
      cold_archive: 'bg-sky-500/10 text-sky-400',
    }
    return colors[tier] || 'bg-surface-3 text-text'
  }

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h2 className="text-2xl font-semibold text-text-heading">Dashboard</h2>
        <p className="text-sm text-text mt-1">Overview of your memory palace</p>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {cards.map(({ label, value, icon: Icon, color }) => (
          <div key={label} className="bg-surface-2 border border-border rounded-xl p-4 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs text-text">{label}</span>
              <Icon size={18} className={color} />
            </div>
            <p className="text-2xl font-semibold text-text-heading">{loading ? '...' : value}</p>
          </div>
        ))}
      </div>

      <section>
        <h3 className="text-lg font-medium text-text-heading mb-3">Recent Memories</h3>
        {loading ? (
          <div className="text-text text-sm">Loading...</div>
        ) : recentNodes.length === 0 ? (
          <div className="bg-surface-2 border border-border rounded-xl p-8 text-center">
            <FileText size={32} className="mx-auto text-text mb-3" />
            <p className="text-text-heading font-medium">No memories yet</p>
            <p className="text-sm text-text mt-1">Create your first memory to get started</p>
            <Link
              to="/memory/note/new"
              className="inline-block mt-4 px-4 py-2 bg-memory-600 hover:bg-memory-700 text-white text-sm rounded-lg transition-colors"
            >
              New Memory
            </Link>
          </div>
        ) : (
          <div className="space-y-2">
            {recentNodes.map((node) => (
              <Link
                key={node.id}
                to={`/memory/note/${node.id}`}
                className="block bg-surface-2 border border-border rounded-lg p-4 hover:border-memory-500/30 transition-colors"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <h4 className="font-medium text-text-heading truncate">{node.title}</h4>
                    <p className="text-xs text-text mt-1 line-clamp-1">{node.content_md}</p>
                    <p className="text-xs text-text/50 mt-1">
                      Created {formatDate(node.created_at)}
                      {node.happened_at && ` · Happened ${formatDate(node.happened_at)}`}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className={`text-xs px-2 py-0.5 rounded-full capitalize ${tierBadge(node.storage_tier)}`}>
                      {node.storage_tier}
                    </span>
                    <span className="text-xs px-2 py-0.5 rounded-full bg-surface-3 text-text capitalize">
                      {node.type}
                    </span>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

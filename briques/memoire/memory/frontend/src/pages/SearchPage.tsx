import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { Search, Loader2 } from 'lucide-react'
import * as api from '../services/api'
import type { SearchResult } from '../types/api'
import { Markdown } from '../components/editor/Markdown'

export default function SearchPage() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [loading, setLoading] = useState(false)

  const doSearch = useCallback(async (q: string) => {
    if (!q.trim()) {
      setResults([])
      return
    }
    setLoading(true)
    try {
      const res = await api.search(q)
      setResults(res)
    } catch {
      setResults([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const timer = setTimeout(() => doSearch(query), 300)
    return () => clearTimeout(timer)
  }, [query, doSearch])

  return (
    <div className="max-w-3xl space-y-4">
      <div>
        <h2 className="text-2xl font-semibold text-text-heading">Search</h2>
        <p className="text-sm text-text mt-1">Full-text and semantic search across your memories</p>
      </div>

      <div className="relative">
        <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-text" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search memories..."
          autoFocus
          className="w-full pl-10 pr-4 py-3 bg-surface-2 border border-border rounded-xl text-text-heading placeholder:text-text/40 focus:outline-none focus:border-memory-500 transition-colors"
        />
      </div>

      {loading && (
        <div className="flex items-center justify-center py-8">
          <Loader2 size={24} className="animate-spin text-text" />
        </div>
      )}

      {!loading && results.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs text-text">{results.length} results</p>
          {results.map((r) => (
            <Link
              key={r.id}
              to={`/memory/note/${r.id}`}
              className="block bg-surface-2 border border-border rounded-xl p-4 hover:border-memory-500/30 transition-colors"
            >
              <div className="flex items-start justify-between gap-3 mb-2">
                <h3 className="font-medium text-text-heading">{r.title}</h3>
                <div className="flex items-center gap-2 shrink-0">
                  {r.storage_tier !== 'hot' && (
                    <span className={`text-xs px-1.5 py-0.5 rounded ${
                      r.storage_tier === 'archive' ? 'bg-amber-500/10 text-amber-400' : 'bg-sky-500/10 text-sky-400'
                    }`}>{r.storage_tier}</span>
                  )}
                  <span className="text-xs px-2 py-0.5 rounded-full bg-surface-3 text-text capitalize">{r.type}</span>
                </div>
              </div>
              <div className="text-sm text-text line-clamp-2 prose prose-invert prose-sm max-w-none">
                <Markdown content={r.content_md} />
              </div>
              <div className="flex items-center gap-3 mt-2">
                <p className="text-xs text-memory-400">Score: {(r.score * 100).toFixed(0)}%</p>
                {r.happened_at && <p className="text-xs text-text/50">{new Date(r.happened_at).toLocaleDateString()}</p>}
              </div>
            </Link>
          ))}
        </div>
      )}

      {!loading && query && results.length === 0 && (
        <div className="text-center py-8 text-text">
          <Search size={32} className="mx-auto mb-2 opacity-50" />
          <p>No results for "{query}"</p>
        </div>
      )}
    </div>
  )
}

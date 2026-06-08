import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Save, Trash2, Layers } from 'lucide-react'
import MarkdownEditor from '../components/editor/MarkdownEditor'
import FrontmatterEditor from '../components/editor/FrontmatterEditor'
import TemplatePicker from '../components/editor/TemplatePicker'
import * as api from '../services/api'
import type { NodeResponse, Template, Collection } from '../types/api'

const NODE_TYPES = ['input', 'projet', 'casquette', 'ressource', 'archive']
const STORAGE_TIERS = ['hot', 'archive', 'cold_archive']

export default function NotePage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const isNew = id === 'new'

  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [type, setType] = useState('input')
  const [frontmatter, setFrontmatter] = useState<Record<string, unknown>>({})
  const [saving, setSaving] = useState(false)
  const [node, setNode] = useState<NodeResponse | null>(null)
  const [happenedAt, setHappenedAt] = useState('')
  const [collections, setCollections] = useState<Collection[]>([])
  const [showColPicker, setShowColPicker] = useState(false)

  useEffect(() => {
    api.getCollections().then(setCollections).catch(() => {})
  }, [])

  useEffect(() => {
    if (!isNew && id) {
      api.getNode(id).then((n) => {
        setNode(n)
        setTitle(n.title)
        setContent(n.content_md)
        setType(n.type)
        setFrontmatter(n.frontmatter)
        setHappenedAt(n.happened_at ? new Date(n.happened_at).toISOString().slice(0, 16) : '')
      }).catch(() => navigate('/memory'))
    }
  }, [id])

  async function handleSave() {
    setSaving(true)
    try {
      if (isNew) {
        const created = await api.createNode({
          title,
          content_md: content,
          type,
          frontmatter,
          happened_at: happenedAt ? new Date(happenedAt).toISOString() : null,
        })
        navigate(`/memory/note/${created.id}`, { replace: true })
      } else if (id) {
        await api.updateNode(id, {
          title,
          content_md: content,
          frontmatter,
          happened_at: happenedAt ? new Date(happenedAt).toISOString() : null,
        })
      }
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    if (!id || isNew) return
    if (!confirm('Archive this memory?')) return
    await api.deleteNode(id)
    navigate('/memory')
  }

  function handleTemplateSelect(tmpl: Template) {
    if (tmpl.title_template) setTitle(tmpl.title_template)
    if (tmpl.content_template) {
      setContent(tmpl.content_template)
    }
    if (tmpl.frontmatter_template) {
      try {
        const parsed = JSON.parse(tmpl.frontmatter_template)
        setFrontmatter(parsed)
      } catch {
        setFrontmatter({})
      }
    }
  }

  async function handleTierChange(tier: string) {
    if (!id) return
    await api.updateNodeTier(id, tier)
    const updated = await api.getNode(id)
    setNode(updated)
  }

  function formatDate(d: string | null | undefined) {
    if (!d) return '—'
    return new Date(d).toLocaleString()
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
    <div className="max-w-4xl space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate('/memory')} className="p-1.5 rounded-lg hover:bg-surface-3 text-text transition-colors">
            <ArrowLeft size={20} />
          </button>
          <h2 className="text-lg font-semibold text-text-heading">
            {isNew ? 'New Memory' : 'Edit Memory'}
          </h2>
        </div>
        <div className="flex items-center gap-2">
          {!isNew && (
            <>
              <div className="relative">
                <button onClick={() => setShowColPicker((v) => !v)} className="p-2 rounded-lg hover:bg-surface-3 text-text hover:text-memory-400 transition-colors" title="Add to collection">
                  <Layers size={18} />
                </button>
                {showColPicker && (
                  <div className="absolute right-0 top-full mt-1 w-56 bg-surface-2 border border-border rounded-xl shadow-xl z-50 p-2 space-y-1">
                    <p className="text-xs text-text px-2 py-1">Add to collection</p>
                    {collections.filter((c) => !c.is_dynamic).map((c) => (
                      <button
                        key={c.id}
                        onClick={async () => {
                          if (id) await api.addNodeToCollection(c.id, id)
                          setShowColPicker(false)
                        }}
                        className="w-full text-left px-2 py-1.5 text-sm text-text-heading hover:bg-surface-3 rounded-lg transition-colors"
                      >
                        {c.name}
                      </button>
                    ))}
                    {collections.filter((c) => !c.is_dynamic).length === 0 && (
                      <p className="text-xs text-text/50 px-2 py-1">No manual collections</p>
                    )}
                  </div>
                )}
              </div>
              <button onClick={handleDelete} className="p-2 rounded-lg hover:bg-surface-3 text-text hover:text-red-400 transition-colors">
                <Trash2 size={18} />
              </button>
            </>
          )}
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-2 px-4 py-2 bg-memory-600 hover:bg-memory-700 disabled:opacity-50 text-white text-sm rounded-lg transition-colors"
          >
            <Save size={16} />
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>

      <div className="flex items-center gap-3 flex-wrap">
        <select
          value={type}
          onChange={(e) => setType(e.target.value)}
          className="px-3 py-1.5 bg-surface-2 border border-border rounded-lg text-sm text-text-heading focus:outline-none focus:border-memory-500 capitalize"
        >
          {NODE_TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        {node && (
          <>
            <span className="text-xs text-text">{node.ipcra_stage}</span>
            <select
              value={node.storage_tier}
              onChange={(e) => handleTierChange(e.target.value)}
              className={`text-xs px-2 py-0.5 rounded-lg border border-border ${tierBadge(node.storage_tier)}`}
            >
              {STORAGE_TIERS.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
            <span className="text-xs text-text">{node.access_count} accesses</span>
          </>
        )}
      </div>

      {!isNew && node && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-text/70">
          <span>Created: {formatDate(node.created_at)}</span>
          <span>Updated: {formatDate(node.updated_at)}</span>
          <span>Last accessed: {formatDate(node.last_accessed)}</span>
          {node.happened_at && <span>Happened: {formatDate(node.happened_at)}</span>}
          {node.stage_changed_at && <span>Stage changed: {formatDate(node.stage_changed_at)}</span>}
        </div>
      )}

      {!isNew && node?.location && (
        <div className="text-xs text-text">
          Located in {node.location.wing} / {node.location.room}{node.location.drawer ? ` / ${node.location.drawer}` : ''}
        </div>
      )}

      {isNew && (
        <>
          <TemplatePicker nodeType={type} onSelect={handleTemplateSelect} />
          <div className="flex items-center gap-2">
            <span className="text-xs text-text">Happened at:</span>
            <input
              type="datetime-local"
              value={happenedAt}
              onChange={(e) => setHappenedAt(e.target.value)}
              className="px-2 py-1 bg-surface-2 border border-border rounded text-sm text-text-heading focus:outline-none focus:border-memory-500"
            />
          </div>
        </>
      )}

      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Memory title..."
        className="w-full text-xl font-semibold bg-transparent text-text-heading border-none focus:outline-none placeholder:text-text/40"
      />

      <MarkdownEditor value={content} onChange={(v) => setContent(v)} placeholder="Write your memory in Markdown..." />

      <FrontmatterEditor frontmatter={frontmatter} onChange={(fm) => setFrontmatter(fm)} />
    </div>
  )
}

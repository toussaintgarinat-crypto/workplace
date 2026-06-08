import { useEffect, useState } from 'react'
import { FileText } from 'lucide-react'
import * as api from '../services/api'
import type { Template } from '../types/api'

export default function TemplatesPage() {
  const [templates, setTemplates] = useState<Template[]>([])
  const [loading, setLoading] = useState(true)
  const [filterType, setFilterType] = useState('')

  useEffect(() => {
    api.getTemplates(filterType || undefined).then(setTemplates).catch(() => setTemplates([])).finally(() => setLoading(false))
  }, [filterType])

  const grouped = templates.reduce<Record<string, Template[]>>((acc, t) => {
    if (!acc[t.node_type]) acc[t.node_type] = []
    acc[t.node_type].push(t)
    return acc
  }, {})

  const nodeTypeLabels: Record<string, string> = {
    input: 'Input',
    projet: 'Project',
    casquette: 'Role',
    ressource: 'Resource',
    archive: 'Archive',
  }

  return (
    <div className="max-w-3xl space-y-4">
      <div>
        <h2 className="text-2xl font-semibold text-text-heading">Templates</h2>
        <p className="text-sm text-text mt-1">Predefined templates for each memory type</p>
      </div>

      <select
        value={filterType}
        onChange={(e) => setFilterType(e.target.value)}
        className="px-3 py-1.5 bg-surface-2 border border-border rounded-lg text-sm text-text-heading focus:outline-none focus:border-memory-500 capitalize"
      >
        <option value="">All types</option>
        {Object.keys(nodeTypeLabels).map((t) => (
          <option key={t} value={t}>{nodeTypeLabels[t]}</option>
        ))}
      </select>

      {loading ? (
        <div className="text-text text-sm">Loading...</div>
      ) : templates.length === 0 ? (
        <div className="bg-surface-2 border border-border rounded-xl p-8 text-center">
          <FileText size={32} className="mx-auto text-text mb-3" />
          <p className="text-text-heading font-medium">No templates</p>
          <p className="text-sm text-text mt-1">Custom templates will appear here</p>
        </div>
      ) : (
        <div className="space-y-4">
          {Object.entries(grouped).map(([type, items]) => (
            <section key={type}>
              <h3 className="text-sm font-medium text-text-heading mb-2 capitalize">{nodeTypeLabels[type] || type}</h3>
              <div className="space-y-1.5">
                {items.map((t) => (
                  <div key={t.id} className="flex items-center justify-between bg-surface-2 border border-border rounded-lg px-4 py-2.5">
                    <div>
                      <p className="text-sm text-text-heading">{t.name}</p>
                      <p className="text-xs text-text mt-0.5 line-clamp-1">{t.content_template.slice(0, 80)}</p>
                    </div>
                    <span className="text-xs text-text/50">{t.is_global ? 'built-in' : 'custom'}</span>
                  </div>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  )
}
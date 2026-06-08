import { useState, useEffect } from 'react'
import { FileText, Plus } from 'lucide-react'
import * as api from '../../services/api'
import type { Template } from '../../types/api'

interface TemplatePickerProps {
  nodeType: string
  onSelect: (template: Template) => void
}

export default function TemplatePicker({ nodeType, onSelect }: TemplatePickerProps) {
  const [templates, setTemplates] = useState<Template[]>([])
  const [loading, setLoading] = useState(true)
  const [showAll, setShowAll] = useState(false)

  useEffect(() => {
    api.getTemplates(nodeType).then(setTemplates).catch(() => setTemplates([])).finally(() => setLoading(false))
  }, [nodeType])

  if (loading || templates.length === 0) return null

  const visible = showAll ? templates : templates.slice(0, 4)

  return (
    <div className="space-y-2">
      <label className="text-xs font-medium text-text uppercase tracking-wider">Templates</label>
      <div className="flex flex-wrap gap-2">
        {visible.map((t) => (
          <button
            key={t.id}
            onClick={() => onSelect(t)}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-surface-2 border border-border rounded-lg text-xs text-text hover:text-text-heading hover:border-memory-500/30 transition-colors"
          >
            <FileText size={14} className="text-memory-400" />
            {t.name}
          </button>
        ))}
        {templates.length > 4 && !showAll && (
          <button
            onClick={() => setShowAll(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-text hover:text-text-heading transition-colors"
          >
            <Plus size={14} /> {templates.length - 4} more
          </button>
        )}
      </div>
    </div>
  )
}
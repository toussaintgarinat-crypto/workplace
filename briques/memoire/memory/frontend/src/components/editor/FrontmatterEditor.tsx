import { useState } from 'react'
import { Plus, X } from 'lucide-react'

interface FrontmatterEditorProps {
  frontmatter: Record<string, unknown>
  onChange: (fm: Record<string, unknown>) => void
}

export default function FrontmatterEditor({ frontmatter, onChange }: FrontmatterEditorProps) {
  const [newKey, setNewKey] = useState('')
  const [newValue, setNewValue] = useState('')

  function addField() {
    if (!newKey.trim()) return
    onChange({ ...frontmatter, [newKey.trim()]: newValue.trim() })
    setNewKey('')
    setNewValue('')
  }

  function removeField(key: string) {
    const rest = { ...frontmatter }
    delete rest[key]
    onChange(rest)
  }

  function updateField(key: string, value: string) {
    onChange({ ...frontmatter, [key]: value })
  }

  const entries = Object.entries(frontmatter)

  return (
    <div className="space-y-2">
      <label className="text-xs font-medium text-text uppercase tracking-wider">Properties</label>
      <div className="space-y-1.5">
        {entries.map(([key, val]) => (
          <div key={key} className="flex items-center gap-2">
            <input
              value={key}
              onChange={(e) => {
                const { [key]: v, ...rest } = frontmatter
                onChange({ ...rest, [e.target.value]: v })
              }}
              className="w-28 px-2 py-1 bg-surface border border-border rounded text-sm text-text-heading font-mono focus:outline-none focus:border-memory-500"
            />
            <input
              value={String(val ?? '')}
              onChange={(e) => updateField(key, e.target.value)}
              className="flex-1 px-2 py-1 bg-surface border border-border rounded text-sm text-text-heading font-mono focus:outline-none focus:border-memory-500"
            />
            <button onClick={() => removeField(key)} className="p-1 text-text hover:text-red-400 transition-colors">
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <input
          value={newKey}
          onChange={(e) => setNewKey(e.target.value)}
          placeholder="key"
          className="w-28 px-2 py-1 bg-surface border border-border rounded text-sm text-text-heading font-mono focus:outline-none focus:border-memory-500 placeholder:text-text/40"
        />
        <input
          value={newValue}
          onChange={(e) => setNewValue(e.target.value)}
          placeholder="value"
          className="flex-1 px-2 py-1 bg-surface border border-border rounded text-sm text-text-heading font-mono focus:outline-none focus:border-memory-500 placeholder:text-text/40"
        />
        <button onClick={addField} className="p-1 text-text hover:text-memory-400 transition-colors">
          <Plus size={16} />
        </button>
      </div>
    </div>
  )
}

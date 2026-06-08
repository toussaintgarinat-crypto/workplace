const types = [
  { key: 'input', label: 'Input', color: '#f59e0b' },
  { key: 'projet', label: 'Project', color: '#3b82f6' },
  { key: 'casquette', label: 'Role', color: '#8b5cf6' },
  { key: 'ressource', label: 'Resource', color: '#10b981' },
  { key: 'archive', label: 'Archive', color: '#64748b' },
]

const edges = [
  { key: 'related', label: 'Related', color: '#64748b' },
  { key: 'cause', label: 'Cause', color: '#ef4444' },
  { key: 'depends', label: 'Depends', color: '#f59e0b' },
  { key: 'references', label: 'References', color: '#3b82f6' },
  { key: 'part_of', label: 'Part of', color: '#10b981' },
]

export default function Legend() {
  return (
    <div className="bg-surface-2 border border-border rounded-lg p-3 text-xs space-y-3">
      <div>
        <p className="text-text-heading font-medium mb-1.5">Node Types</p>
        <div className="space-y-1">
          {types.map((t) => (
            <div key={t.key} className="flex items-center gap-2">
              <span
                className="w-2 h-2 rounded-full shrink-0"
                style={{ backgroundColor: t.color }}
              />
              <span className="text-text capitalize">{t.label}</span>
            </div>
          ))}
        </div>
      </div>
      <div>
        <p className="text-text-heading font-medium mb-1.5">Edge Types</p>
        <div className="space-y-1">
          {edges.map((e) => (
            <div key={e.key} className="flex items-center gap-2">
              <span
                className="w-3 h-0.5 shrink-0"
                style={{ backgroundColor: e.color }}
              />
              <span className="text-text capitalize">{e.label}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

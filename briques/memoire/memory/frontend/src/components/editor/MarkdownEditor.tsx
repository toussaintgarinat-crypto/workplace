import { useState, type KeyboardEvent } from 'react'
import { Markdown } from './Markdown'

interface MarkdownEditorProps {
  value: string
  onChange: (value: string) => void
  placeholder?: string
}

export default function MarkdownEditor({ value, onChange, placeholder }: MarkdownEditorProps) {
  const [tab, setTab] = useState<'write' | 'preview'>('write')

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Tab') {
      e.preventDefault()
      const ta = e.currentTarget
      const start = ta.selectionStart
      const end = ta.selectionEnd
      const next = value.slice(0, start) + '  ' + value.slice(end)
      onChange(next)
      requestAnimationFrame(() => {
        ta.selectionStart = ta.selectionEnd = start + 2
      })
    }
  }

  return (
    <div className="border border-border rounded-lg overflow-hidden bg-surface-2">
      <div className="flex border-b border-border">
        <button
          onClick={() => setTab('write')}
          className={`px-4 py-2 text-sm font-medium transition-colors ${
            tab === 'write' ? 'text-memory-400 border-b-2 border-memory-500' : 'text-text hover:text-text-heading'
          }`}
        >
          Write
        </button>
        <button
          onClick={() => setTab('preview')}
          className={`px-4 py-2 text-sm font-medium transition-colors ${
            tab === 'preview' ? 'text-memory-400 border-b-2 border-memory-500' : 'text-text hover:text-text-heading'
          }`}
        >
          Preview
        </button>
      </div>
      {tab === 'write' ? (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          className="w-full min-h-[300px] p-4 bg-transparent text-text-heading font-mono text-sm resize-y focus:outline-none placeholder:text-text/40"
        />
      ) : (
        <div className="p-4 min-h-[300px] prose prose-invert prose-sm max-w-none">
          {value ? <Markdown content={value} /> : <p className="text-text/40">Nothing to preview</p>}
        </div>
      )}
    </div>
  )
}

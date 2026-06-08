import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export function Markdown({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        a: ({ href, children }) => (
          <a href={href} target="_blank" rel="noopener noreferrer" className="text-memory-400 hover:underline">
            {children}
          </a>
        ),
        code: ({ children, ...props }) => {
          const { className } = props as { className?: string }
          const isInline = !className
          if (isInline) {
            return <code className="bg-surface-3 px-1 py-0.5 rounded text-sm text-memory-300">{children}</code>
          }
          return (
            <pre className="bg-surface-3 p-4 rounded-lg overflow-x-auto text-sm">
              <code>{children}</code>
            </pre>
          )
        },
        table: ({ children }) => (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse border border-border text-sm">{children}</table>
          </div>
        ),
        th: ({ children }) => <th className="border border-border px-3 py-2 bg-surface-3 text-left font-medium text-text-heading">{children}</th>,
        td: ({ children }) => <td className="border border-border px-3 py-2">{children}</td>,
      }}
    >
      {content}
    </ReactMarkdown>
  )
}

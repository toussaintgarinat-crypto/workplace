import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  Search,
  TreePine,
  PenSquare,
  Share2,
  Sprout,
  FileText,
  Layers,
  Settings,
} from 'lucide-react'

const links = [
  { to: '/memory', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/memory/search', icon: Search, label: 'Search' },
  { to: '/memory/palace', icon: TreePine, label: 'Palace' },
  { to: '/memory/graph', icon: Share2, label: 'Graph' },
  { to: '/memory/note/new', icon: PenSquare, label: 'New Note' },
  { to: '/memory/gardien', icon: Sprout, label: 'Gardien' },
  { to: '/memory/templates', icon: FileText, label: 'Templates' },
  { to: '/memory/collections', icon: Layers, label: 'Collections' },
  { to: '/memory/settings', icon: Settings, label: 'Settings' },
]

export default function Sidebar() {
  return (
    <aside className="w-56 border-r border-border bg-surface-2 flex flex-col shrink-0">
      <div className="h-14 flex items-center px-4 border-b border-border">
        <h1 className="text-lg font-semibold text-text-heading tracking-tight">
          Memory
        </h1>
      </div>
      <nav className="flex-1 p-2 space-y-1">
        {links.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/memory'}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                isActive
                  ? 'bg-memory-600/20 text-memory-400 font-medium'
                  : 'text-text hover:bg-surface-3 hover:text-text-heading'
              }`
            }
          >
            <Icon size={18} />
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="p-3 border-t border-border text-xs text-text">
        v0.1 · Memory
      </div>
    </aside>
  )
}

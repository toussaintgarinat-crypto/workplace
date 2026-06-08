import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  Search,
  TreePine,
  PenSquare,
  Share2,
  Sprout,
  Layers,
} from 'lucide-react'

const links = [
  { to: '/memory', icon: LayoutDashboard, label: 'Home' },
  { to: '/memory/search', icon: Search, label: 'Search' },
  { to: '/memory/note/new', icon: PenSquare, label: 'New' },
  { to: '/memory/palace', icon: TreePine, label: 'Palace' },
  { to: '/memory/graph', icon: Share2, label: 'Graph' },
  { to: '/memory/gardien', icon: Sprout, label: 'Gardien' },
  { to: '/memory/collections', icon: Layers, label: 'RAG' },
]

export default function BottomNav() {
  return (
    <nav className="fixed bottom-0 left-0 right-0 bg-surface-2 border-t border-border flex md:hidden z-50">
      {links.map(({ to, icon: Icon, label }) => (
        <NavLink
          key={to}
          to={to}
          end={to === '/memory'}
          className={({ isActive }) =>
            `flex flex-col items-center gap-0.5 flex-1 py-2 text-xs transition-colors ${
              isActive
                ? 'text-memory-400'
                : 'text-text hover:text-text-heading'
            }`
          }
        >
          <Icon size={20} />
          {label}
        </NavLink>
      ))}
    </nav>
  )
}

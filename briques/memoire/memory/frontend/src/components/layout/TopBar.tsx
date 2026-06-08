import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Menu, Search, Settings, LogOut } from 'lucide-react'
import { useAppStore } from '../../stores/appStore'
import * as api from '../../services/api'

interface TopBarProps {
  onSearchFocus?: () => void
}

export default function TopBar({ onSearchFocus }: TopBarProps) {
  const toggleSidebar = useAppStore((s) => s.toggleSidebar)
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)
  const [profile, setProfile] = useState<{ display_name: string | null; email: string } | null>(null)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const token = localStorage.getItem('auth_token')
    if (token) api.getProfile().then(setProfile).catch(() => {})
  }, [])

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  function handleSignOut() {
    localStorage.removeItem('auth_token')
    api.setToken(null)
    navigate(0)
  }

  const initials = (profile?.display_name || profile?.email || '?')[0].toUpperCase()

  return (
    <header className="h-14 border-b border-border bg-surface flex items-center px-4 gap-3 shrink-0">
      <button
        onClick={toggleSidebar}
        className="p-1.5 rounded-lg hover:bg-surface-3 text-text transition-colors lg:hidden"
      >
        <Menu size={20} />
      </button>
      <button
        onClick={onSearchFocus}
        className="flex-1 flex items-center gap-2 px-3 py-1.5 bg-surface-2 border border-border rounded-lg text-sm text-text hover:border-memory-500/30 transition-colors max-w-md"
      >
        <Search size={16} />
        <span>Search memories...</span>
        <kbd className="ml-auto text-xs text-text bg-surface-3 px-1.5 py-0.5 rounded">
          ⌘K
        </kbd>
      </button>

      <div className="relative ml-auto" ref={menuRef}>
        <button
          onClick={() => setMenuOpen(!menuOpen)}
          className="w-8 h-8 rounded-full bg-memory-600/20 flex items-center justify-center text-memory-400 text-sm font-medium hover:bg-memory-600/30 transition-colors"
        >
          {initials}
        </button>

        {menuOpen && (
          <div className="absolute right-0 top-10 w-48 bg-surface-2 border border-border rounded-xl shadow-xl shadow-black/20 py-1 z-50">
            <div className="px-3 py-2 border-b border-border">
              <p className="text-sm text-text-heading truncate">{profile?.display_name || 'User'}</p>
              <p className="text-xs text-text truncate">{profile?.email || ''}</p>
            </div>
            <button
              onClick={() => { setMenuOpen(false); navigate('/memory/settings') }}
              className="w-full flex items-center gap-2 px-3 py-2 text-sm text-text hover:bg-surface-3 hover:text-text-heading transition-colors"
            >
              <Settings size={16} /> Settings
            </button>
            <button
              onClick={handleSignOut}
              className="w-full flex items-center gap-2 px-3 py-2 text-sm text-red-400 hover:bg-red-600/10 transition-colors"
            >
              <LogOut size={16} /> Sign Out
            </button>
          </div>
        )}
      </div>
    </header>
  )
}

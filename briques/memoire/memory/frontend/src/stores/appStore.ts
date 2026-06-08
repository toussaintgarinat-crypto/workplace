import { create } from 'zustand'

interface AppState {
  sidebarOpen: boolean
  activeSpaceId: string
  theme: 'dark' | 'light'
  toggleSidebar: () => void
  setActiveSpace: (id: string) => void
}

export const useAppStore = create<AppState>((set) => ({
  sidebarOpen: true,
  activeSpaceId: localStorage.getItem('active_space_id') || '',
  theme: 'dark',
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
  setActiveSpace: (id) => {
    localStorage.setItem('active_space_id', id)
    set({ activeSpaceId: id })
  },
}))

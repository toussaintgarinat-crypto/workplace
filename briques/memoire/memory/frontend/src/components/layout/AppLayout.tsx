import { Outlet, useNavigate } from 'react-router-dom'
import Sidebar from './Sidebar'
import TopBar from './TopBar'
import BottomNav from './BottomNav'

export default function AppLayout() {
  const navigate = useNavigate()

  return (
    <div className="flex w-full min-h-svh">
      <div className="hidden md:block">
        <Sidebar />
      </div>
      <div className="flex-1 flex flex-col min-w-0 pb-16 md:pb-0">
        <TopBar onSearchFocus={() => navigate('/memory/search')} />
        <main className="flex-1 overflow-auto p-4 lg:p-6">
          <Outlet />
        </main>
      </div>
      <BottomNav />
    </div>
  )
}

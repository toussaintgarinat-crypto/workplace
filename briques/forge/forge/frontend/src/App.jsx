import { Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './hooks/useAuth'
import AppShell from './components/AppShell'
import WorkspaceView from './views/WorkspaceView'
import CommandBridgeView from './views/CommandBridge'
import PoleView from './views/PoleView'
import GitPackView from './views/GitPackView'
import FacturationView from './views/FacturationView'
import KBView from './views/KBView'
import VeilleView from './views/VeilleView'
import AgentFactoryView from './views/AgentFactoryView'
import NetworkView from './views/NetworkView'
import GovernorView from './views/GovernorView'
import SLOView from './views/SLOView'
import AnalyticsView from './views/AnalyticsView'
import DevTeamView from './views/DevTeamView'
import AutomationView from './views/AutomationView'
import MorningBriefView from './views/MorningBriefView'
import VentureView from './views/VentureView'
import VentureDetail from './views/VentureView/VentureDetail'
import SearchView from './views/SearchView'
import TeamView from './views/TeamView'
import StripeView from './views/StripeView'
import MCPView from './views/MCPView'
import SkillsView from './views/SkillsView'
import MemPalaceView from './views/MemPalaceView'

function AppRoutes() {
  const { loading } = useAuth()

  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', color: '#6b6b80' }}>
      Loading...
    </div>
  )

  return (
    <AppShell>
      <Routes>
        <Route path="/"                     element={<Navigate to="/workspace" replace />} />
        <Route path="/workspace"            element={<WorkspaceView />} />
        <Route path="/workspace/:sessionId" element={<WorkspaceView />} />
        <Route path="/command-bridge"       element={<CommandBridgeView />} />
        <Route path="/poles/:poleId"        element={<PoleView />} />
        <Route path="/gitpack"              element={<GitPackView />} />
        <Route path="/facturation"          element={<FacturationView />} />
        <Route path="/kb"                   element={<KBView />} />
        <Route path="/veille"               element={<VeilleView />} />
        <Route path="/agents"               element={<AgentFactoryView />} />
        <Route path="/network"              element={<NetworkView />} />
        <Route path="/governor"             element={<GovernorView />} />
        <Route path="/slo"                  element={<SLOView />} />
        <Route path="/analytics"            element={<AnalyticsView />} />
        <Route path="/dev-team"             element={<DevTeamView />} />
        <Route path="/automation"           element={<AutomationView />} />
        <Route path="/morning-brief"        element={<MorningBriefView />} />
        <Route path="/ventures"                              element={<VentureView />} />
        <Route path="/ventures/:ventureId"               element={<VentureDetail />} />
        <Route path="/ventures/:ventureId/poles/:poleId" element={<PoleView />} />
        <Route path="/search"               element={<SearchView />} />
        <Route path="/team"                 element={<TeamView />} />
        <Route path="/abonnements"          element={<StripeView />} />
        <Route path="/mcp"                  element={<MCPView />} />
        <Route path="/skills"               element={<SkillsView />} />
        <Route path="/mempalace"            element={<MemPalaceView />} />
        <Route path="*"                     element={<Navigate to="/workspace" replace />} />
      </Routes>
    </AppShell>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <AppRoutes />
    </AuthProvider>
  )
}

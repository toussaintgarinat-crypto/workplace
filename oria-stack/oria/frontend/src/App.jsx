import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { AuthProvider, useAuth } from './hooks/useAuth'
import MainLayout from './components/MainLayout.jsx'
import EasySetupWizard from './components/EasySetupWizard.jsx'
import { DegradedBanner } from '@workspace/shared-ui/components'
import { api } from './services/api.js'
import { initMatrixClient, startMatrixClient, stopMatrixClient } from './services/matrixClient.js'

function AppInner() {
  const { t } = useTranslation()
  const { user, loading, logout, matrixCreds, refreshUser } = useAuth()

  useEffect(() => {
    if (!matrixCreds?.userId || !matrixCreds?.accessToken) return
    localStorage.setItem('matrix_user_id', matrixCreds.userId)
    localStorage.setItem('matrix_token',   matrixCreds.accessToken)
    initMatrixClient({ userId: matrixCreds.userId, accessToken: matrixCreds.accessToken })
    startMatrixClient().catch(console.error)
    return () => stopMatrixClient()
  }, [matrixCreds])

  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', color: '#6b6b80' }}>
      {t('app.loading')}
    </div>
  )

  if (!user) return null // Keycloak redirige automatiquement via login-required

  if (!user.setup_completed_at) {
    return <EasySetupWizard user={user} onComplete={refreshUser} />
  }

  return (
    <>
      <DegradedBanner fetcher={() => api.get('/admin/degraded')} />
      <MainLayout moi={user} onMoiUpdate={refreshUser} onDeconnexion={logout} />
    </>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <AppInner />
    </AuthProvider>
  )
}

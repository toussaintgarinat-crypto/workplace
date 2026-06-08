import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { LogIn, User, UserPlus, Save, Eye, EyeOff, Trash2, AlertTriangle, Users } from 'lucide-react'
import * as api from '../services/api'
import { useAppStore } from '../stores/appStore'

type Tab = 'profile' | 'space' | 'account'

export default function SettingsPage() {
  const navigate = useNavigate()
  const setActiveSpace = useAppStore((s) => s.setActiveSpace)
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [error, setError] = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    try {
      if (mode === 'register') {
        await api.register(email, password, displayName || undefined)
      }
      await api.login(email, password)
      // Load or create space
      const spaces = await api.getSpaces()
      if (spaces.length > 0) {
        setActiveSpace(spaces[0].id)
      } else {
        const space = await api.createSpace('My Space', 'My personal memory space')
        setActiveSpace(space.id)
      }
      navigate('/memory')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    }
  }

  const token = localStorage.getItem('auth_token')

  if (!token) {
    return (
      <div className="max-w-sm mx-auto pt-12 space-y-6">
        <div className="text-center">
          <User size={40} className="mx-auto text-memory-400 mb-2" />
          <h2 className="text-xl font-semibold text-text-heading">
            {mode === 'login' ? 'Sign In' : 'Create Account'}
          </h2>
          <p className="text-sm text-text mt-1">
            {mode === 'login' ? 'Access your Memory space' : 'Start building your second brain'}
          </p>
        </div>
        <form onSubmit={handleSubmit} className="space-y-3">
          <input
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            type="email"
            placeholder="Email"
            required
            className="w-full px-3 py-2 bg-surface-2 border border-border rounded-lg text-sm text-text-heading focus:outline-none focus:border-memory-500 placeholder:text-text/40"
          />
          {mode === 'register' && (
            <input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              type="text"
              placeholder="Display name (optional)"
              className="w-full px-3 py-2 bg-surface-2 border border-border rounded-lg text-sm text-text-heading focus:outline-none focus:border-memory-500 placeholder:text-text/40"
            />
          )}
          <input
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            type="password"
            placeholder="Password"
            required
            minLength={4}
            className="w-full px-3 py-2 bg-surface-2 border border-border rounded-lg text-sm text-text-heading focus:outline-none focus:border-memory-500 placeholder:text-text/40"
          />
          {error && <p className="text-xs text-red-400">{error}</p>}
          <button
            type="submit"
            className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-memory-600 hover:bg-memory-700 text-white text-sm rounded-lg transition-colors"
          >
            {mode === 'login' ? <><LogIn size={16} /> Sign In</> : <><UserPlus size={16} /> Create Account</>}
          </button>
        </form>
        <p className="text-center text-xs text-text">
          {mode === 'login' ? (
            <>
              Don't have an account?{' '}
              <button onClick={() => { setMode('register'); setError('') }} className="text-memory-400 hover:underline">
                Sign up
              </button>
            </>
          ) : (
            <>
              Already have an account?{' '}
              <button onClick={() => { setMode('login'); setError('') }} className="text-memory-400 hover:underline">
                Sign in
              </button>
            </>
          )}
        </p>
      </div>
    )
  }

  return <SettingsPageAuthenticated />
}

function SettingsPageAuthenticated() {
  const [tab, setTab] = useState<Tab>('profile')
  const spaceId = api.getSpaceId()

  const tabs: { id: Tab; label: string }[] = [
    { id: 'profile', label: 'Profile' },
    { id: 'space', label: 'Space' },
    { id: 'account', label: 'Account' },
  ]

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h2 className="text-2xl font-semibold text-text-heading">Settings</h2>
        <p className="text-sm text-text mt-1">Manage your account, space, and preferences</p>
      </div>

      <div className="flex gap-1 bg-surface-2 border border-border rounded-lg p-1 w-fit">
        {tabs.map(({ id, label }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`px-4 py-1.5 text-sm rounded-md transition-colors ${
              tab === id
                ? 'bg-memory-600/20 text-memory-400 font-medium'
                : 'text-text hover:text-text-heading'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'profile' && <ProfileTab />}
      {tab === 'space' && <SpaceTab spaceId={spaceId} />}
      {tab === 'account' && <AccountTab />}
    </div>
  )
}

function ProfileTab() {
  const [profile, setProfile] = useState<{ id: string; email: string; display_name: string | null; created_at: string } | null>(null)
  const [displayName, setDisplayName] = useState('')
  const [email, setEmail] = useState('')
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    api.getProfile().then((p) => {
      setProfile(p)
      setDisplayName(p.display_name || '')
      setEmail(p.email)
    }).catch(() => {})
  }, [])

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    setMessage('')
    try {
      const updated = await api.updateProfile({ display_name: displayName || undefined, email: email || undefined })
      setProfile(updated)
      setMessage('Profile updated')
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Failed to update')
    } finally {
      setSaving(false)
    }
  }

  const [showCurrentPw, setShowCurrentPw] = useState(false)
  const [showNewPw, setShowNewPw] = useState(false)
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [pwSaving, setPwSaving] = useState(false)
  const [pwMessage, setPwMessage] = useState('')

  async function handleChangePassword(e: React.FormEvent) {
    e.preventDefault()
    setPwSaving(true)
    setPwMessage('')
    try {
      await api.changePassword(currentPassword, newPassword)
      setPwMessage('Password updated')
      setCurrentPassword('')
      setNewPassword('')
    } catch (err) {
      setPwMessage(err instanceof Error ? err.message : 'Failed to update password')
    } finally {
      setPwSaving(false)
    }
  }

  if (!profile) return <div className="text-text text-sm">Loading...</div>

  return (
    <div className="space-y-6">
      <section className="bg-surface-2 border border-border rounded-xl p-5 space-y-4">
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-full bg-memory-600/20 flex items-center justify-center text-memory-400 font-semibold text-lg">
            {(profile.display_name || profile.email)[0].toUpperCase()}
          </div>
          <div>
            <h3 className="font-medium text-text-heading">{profile.display_name || 'User'}</h3>
            <p className="text-xs text-text">{profile.email}</p>
            <p className="text-xs text-text/50 mt-0.5">Joined {new Date(profile.created_at).toLocaleDateString()}</p>
          </div>
        </div>
      </section>

      <section className="bg-surface-2 border border-border rounded-xl p-5 space-y-4">
        <h3 className="font-medium text-text-heading text-sm">Edit Profile</h3>
        <form onSubmit={handleSave} className="space-y-3">
          <div>
            <label className="text-xs text-text mb-1 block">Display name</label>
            <input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              type="text"
              className="w-full px-3 py-2 bg-surface border border-border rounded-lg text-sm text-text-heading focus:outline-none focus:border-memory-500"
            />
          </div>
          <div>
            <label className="text-xs text-text mb-1 block">Email</label>
            <input
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              type="email"
              className="w-full px-3 py-2 bg-surface border border-border rounded-lg text-sm text-text-heading focus:outline-none focus:border-memory-500"
            />
          </div>
          {message && <p className={`text-xs ${message === 'Profile updated' ? 'text-emerald-400' : 'text-red-400'}`}>{message}</p>}
          <button
            type="submit"
            disabled={saving}
            className="flex items-center gap-2 px-4 py-2 bg-memory-600 hover:bg-memory-700 disabled:opacity-50 text-white text-sm rounded-lg transition-colors"
          >
            <Save size={16} /> {saving ? 'Saving...' : 'Save Changes'}
          </button>
        </form>
      </section>

      <section className="bg-surface-2 border border-border rounded-xl p-5 space-y-4">
        <h3 className="font-medium text-text-heading text-sm">Change Password</h3>
        <form onSubmit={handleChangePassword} className="space-y-3 max-w-sm">
          <div className="relative">
            <label className="text-xs text-text mb-1 block">Current password</label>
            <input
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              type={showCurrentPw ? 'text' : 'password'}
              required
              className="w-full px-3 py-2 bg-surface border border-border rounded-lg text-sm text-text-heading focus:outline-none focus:border-memory-500 pr-9"
            />
            <button type="button" onClick={() => setShowCurrentPw(!showCurrentPw)} className="absolute right-3 top-[30px] text-text hover:text-text-heading">
              {showCurrentPw ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
          <div className="relative">
            <label className="text-xs text-text mb-1 block">New password</label>
            <input
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              type={showNewPw ? 'text' : 'password'}
              required
              minLength={4}
              className="w-full px-3 py-2 bg-surface border border-border rounded-lg text-sm text-text-heading focus:outline-none focus:border-memory-500 pr-9"
            />
            <button type="button" onClick={() => setShowNewPw(!showNewPw)} className="absolute right-3 top-[30px] text-text hover:text-text-heading">
              {showNewPw ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
          {pwMessage && <p className={`text-xs ${pwMessage === 'Password updated' ? 'text-emerald-400' : 'text-red-400'}`}>{pwMessage}</p>}
          <button
            type="submit"
            disabled={pwSaving}
            className="flex items-center gap-2 px-4 py-2 bg-memory-600 hover:bg-memory-700 disabled:opacity-50 text-white text-sm rounded-lg transition-colors"
          >
            <Save size={16} /> {pwSaving ? 'Updating...' : 'Update Password'}
          </button>
        </form>
      </section>
    </div>
  )
}

function SpaceTab({ spaceId }: { spaceId: string }) {
  const [space, setSpace] = useState<{ id: string; name: string; description: string; role: string } | null>(null)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [members, setMembers] = useState<{ id: string; email: string; display_name: string | null; role: string }[]>([])

  useEffect(() => {
    if (!spaceId) return
    api.getSpace(spaceId).then((s) => {
      setSpace(s)
      setName(s.name)
      setDescription(s.description || '')
    }).catch(() => {})
    api.getMembers(spaceId).then(setMembers).catch(() => {})
  }, [spaceId])

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    if (!spaceId) return
    setSaving(true)
    setMessage('')
    try {
      await api.updateSpace(spaceId, { name, description })
      setMessage('Space updated')
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Failed to update space')
    } finally {
      setSaving(false)
    }
  }

  const isOwner = space?.role === 'owner'
  const isAdmin = isOwner || space?.role === 'admin'

  if (!space) return <div className="text-text text-sm">Loading...</div>

  return (
    <div className="space-y-6">
      {isAdmin && (
        <section className="bg-surface-2 border border-border rounded-xl p-5 space-y-4">
          <h3 className="font-medium text-text-heading text-sm">Space Settings</h3>
          <form onSubmit={handleSave} className="space-y-3 max-w-md">
            <div>
              <label className="text-xs text-text mb-1 block">Space name</label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                type="text"
                required
                className="w-full px-3 py-2 bg-surface border border-border rounded-lg text-sm text-text-heading focus:outline-none focus:border-memory-500"
              />
            </div>
            <div>
              <label className="text-xs text-text mb-1 block">Description</label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
                className="w-full px-3 py-2 bg-surface border border-border rounded-lg text-sm text-text-heading focus:outline-none focus:border-memory-500 resize-none"
              />
            </div>
            {message && <p className={`text-xs ${message === 'Space updated' ? 'text-emerald-400' : 'text-red-400'}`}>{message}</p>}
            <button
              type="submit"
              disabled={saving}
              className="flex items-center gap-2 px-4 py-2 bg-memory-600 hover:bg-memory-700 disabled:opacity-50 text-white text-sm rounded-lg transition-colors"
            >
              <Save size={16} /> {saving ? 'Saving...' : 'Save Changes'}
            </button>
          </form>
        </section>
      )}

      <section className="bg-surface-2 border border-border rounded-xl p-5 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="font-medium text-text-heading text-sm">Members</h3>
          <span className="text-xs text-text bg-surface-3 px-2 py-0.5 rounded-full">{members.length}</span>
        </div>
        <div className="space-y-2">
          {members.map((m) => (
            <div key={m.id} className="flex items-center justify-between py-2 px-3 bg-surface rounded-lg">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-full bg-memory-600/10 flex items-center justify-center text-memory-400 text-xs font-medium">
                  {(m.display_name || m.email)[0].toUpperCase()}
                </div>
                <div>
                  <p className="text-sm text-text-heading">{m.display_name || m.email}</p>
                  <p className="text-xs text-text">{m.email}</p>
                </div>
              </div>
              <span className="text-xs capitalize bg-surface-3 text-text px-2 py-0.5 rounded-full">{m.role}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}

function AccountTab() {
  const navigate = useNavigate()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [confirmDeleteSpace, setConfirmDeleteSpace] = useState(false)
  const [deletingSpace, setDeletingSpace] = useState(false)
  const spaceId = api.getSpaceId()

  async function handleDeleteAccount() {
    setDeleting(true)
    try {
      await api.deleteAccount()
      navigate(0)
    } catch {
      setDeleting(false)
    }
  }

  async function handleDeleteSpace() {
    if (!spaceId) return
    setDeletingSpace(true)
    try {
      await api.deleteSpace(spaceId)
      localStorage.removeItem('active_space_id')
      navigate(0)
    } catch {
      setDeletingSpace(false)
    }
  }

  function handleSignOut() {
    localStorage.removeItem('auth_token')
    api.setToken(null)
    navigate(0)
  }

  return (
    <div className="space-y-6">
      <section className="bg-surface-2 border border-red-900/30 rounded-xl p-5 space-y-4">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-red-600/10 flex items-center justify-center">
            <AlertTriangle size={18} className="text-red-400" />
          </div>
          <div>
            <h3 className="font-medium text-text-heading text-sm">Sign Out</h3>
            <p className="text-xs text-text">Sign out of your account on this device</p>
          </div>
        </div>
        <button
          onClick={handleSignOut}
          className="px-4 py-2 bg-surface-3 hover:bg-surface border border-border text-text text-sm rounded-lg transition-colors"
        >
          Sign Out
        </button>
      </section>

      <section className="bg-surface-2 border border-red-900/30 rounded-xl p-5 space-y-4">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-red-600/10 flex items-center justify-center">
            <Trash2 size={18} className="text-red-400" />
          </div>
          <div>
            <h3 className="font-medium text-text-heading text-sm">Delete Space</h3>
            <p className="text-xs text-text">Permanently delete this space and all its memories</p>
          </div>
        </div>
        {!confirmDeleteSpace ? (
          <button
            onClick={() => setConfirmDeleteSpace(true)}
            className="px-4 py-2 bg-red-600/10 hover:bg-red-600/20 text-red-400 text-sm rounded-lg transition-colors"
          >
            Delete Space
          </button>
        ) : (
          <div className="space-y-2">
            <p className="text-xs text-red-400">Are you sure? This action cannot be undone.</p>
            <div className="flex gap-2">
              <button
                onClick={handleDeleteSpace}
                disabled={deletingSpace}
                className="px-4 py-2 bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white text-sm rounded-lg transition-colors"
              >
                {deletingSpace ? 'Deleting...' : 'Yes, delete permanently'}
              </button>
              <button
                onClick={() => setConfirmDeleteSpace(false)}
                className="px-4 py-2 bg-surface-3 hover:bg-surface text-text text-sm rounded-lg transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </section>

      <section className="bg-surface-2 border border-red-900/30 rounded-xl p-5 space-y-4">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-red-600/10 flex items-center justify-center">
            <Users size={18} className="text-red-400" />
          </div>
          <div>
            <h3 className="font-medium text-text-heading text-sm">Delete Account</h3>
            <p className="text-xs text-text">Permanently delete your account and all associated data</p>
          </div>
        </div>
        {!confirmDelete ? (
          <button
            onClick={() => setConfirmDelete(true)}
            className="px-4 py-2 bg-red-600/10 hover:bg-red-600/20 text-red-400 text-sm rounded-lg transition-colors"
          >
            Delete Account
          </button>
        ) : (
          <div className="space-y-2">
            <p className="text-xs text-red-400">This will permanently delete your account and all spaces you own. This cannot be undone.</p>
            <div className="flex gap-2">
              <button
                onClick={handleDeleteAccount}
                disabled={deleting}
                className="px-4 py-2 bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white text-sm rounded-lg transition-colors"
              >
                {deleting ? 'Deleting...' : 'Yes, delete my account'}
              </button>
              <button
                onClick={() => setConfirmDelete(false)}
                className="px-4 py-2 bg-surface-3 hover:bg-surface text-text text-sm rounded-lg transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  )
}

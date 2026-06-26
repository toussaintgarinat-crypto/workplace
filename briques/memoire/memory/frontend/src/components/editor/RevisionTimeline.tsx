import { useEffect, useMemo, useState } from 'react'
import { History, RotateCcw, Clock } from 'lucide-react'
import * as api from '../../services/api'
import type { NodeRevision, NodeResponse } from '../../types/api'
import { Markdown } from './Markdown'

interface Props {
  nodeId: string
  trackHistory: boolean
  /** Bump pour relire l'historique (après une sauvegarde, p.ex.). */
  refreshKey?: number
  onToggleHistory: (on: boolean) => Promise<void>
  onRestore: (restored: NodeResponse) => void
}

function formatStamp(iso: string): string {
  return new Date(iso).toLocaleString()
}

/**
 * Curseur de date par document (S111) — consomme l'historique opt-in de S110.
 *
 * Le curseur balaie les versions archivées (la plus ancienne à gauche) jusqu'à
 * « Actuel » (tout à droite). Glisser vers une version passée l'affiche en
 * lecture seule ; un bouton la restaure (ce qui archive l'état courant au passage,
 * côté backend). L'historique est opt-in : tant qu'il n'est pas activé, on propose
 * simplement de l'activer.
 */
export default function RevisionTimeline({ nodeId, trackHistory, refreshKey, onToggleHistory, onRestore }: Props) {
  // Révisions de la plus ANCIENNE à la plus récente (l'API les rend récentes d'abord).
  const [revisions, setRevisions] = useState<NodeRevision[]>([])
  const [cursor, setCursor] = useState(0)
  const [busy, setBusy] = useState(false)
  const [togglingHistory, setTogglingHistory] = useState(false)

  useEffect(() => {
    if (!trackHistory) {
      setRevisions([])
      return
    }
    let alive = true
    api.getNodeRevisions(nodeId)
      .then((revs) => {
        if (!alive) return
        const chrono = [...revs].reverse()
        setRevisions(chrono)
        setCursor(chrono.length) // position « Actuel » par défaut
      })
      .catch(() => { if (alive) setRevisions([]) })
    return () => { alive = false }
  }, [nodeId, trackHistory, refreshKey])

  const atCurrent = cursor >= revisions.length
  const selected = useMemo<NodeRevision | null>(
    () => (atCurrent ? null : revisions[cursor]),
    [atCurrent, cursor, revisions],
  )

  async function handleToggle() {
    setTogglingHistory(true)
    try {
      await onToggleHistory(!trackHistory)
    } finally {
      setTogglingHistory(false)
    }
  }

  async function handleRestore() {
    if (!selected) return
    if (!confirm('Restaurer cette version ? La version actuelle sera archivée.')) return
    setBusy(true)
    try {
      const restored = await api.restoreNodeRevision(nodeId, selected.id)
      onRestore(restored)
      const revs = await api.getNodeRevisions(nodeId)
      const chrono = [...revs].reverse()
      setRevisions(chrono)
      setCursor(chrono.length)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded-xl border border-border bg-surface-2 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm font-medium text-text-heading">
          <History size={16} className="text-memory-400" />
          Historique
        </div>
        <button
          onClick={handleToggle}
          disabled={togglingHistory}
          className={`text-xs px-2.5 py-1 rounded-lg border border-border transition-colors disabled:opacity-50 ${
            trackHistory
              ? 'bg-memory-600/15 text-memory-300 hover:bg-memory-600/25'
              : 'bg-surface-3 text-text hover:text-text-heading'
          }`}
        >
          {trackHistory ? 'Activé — désactiver' : 'Activer le suivi'}
        </button>
      </div>

      {!trackHistory && (
        <p className="text-xs text-text/70">
          Le suivi est désactivé : aucune version n'est conservée. Activez-le pour pouvoir
          revenir en arrière sur ce document (les modifications suivantes seront archivées).
        </p>
      )}

      {trackHistory && revisions.length === 0 && (
        <p className="text-xs text-text/70">
          Aucune version archivée pour l'instant — l'historique démarrera à la prochaine
          modification enregistrée.
        </p>
      )}

      {trackHistory && revisions.length > 0 && (
        <div className="space-y-3">
          <input
            type="range"
            min={0}
            max={revisions.length}
            step={1}
            value={cursor}
            onChange={(e) => setCursor(Number(e.target.value))}
            className="w-full accent-memory-500"
            aria-label="Curseur de date"
          />
          <div className="flex items-center justify-between text-[11px] text-text/60">
            <span className="flex items-center gap-1">
              <Clock size={11} />
              {formatStamp(revisions[0].captured_at)}
            </span>
            <span>{atCurrent ? 'Actuel' : `version ${cursor + 1}/${revisions.length}`}</span>
            <span>Actuel</span>
          </div>

          {atCurrent ? (
            <p className="text-xs text-text/60 italic">Version actuelle du document.</p>
          ) : selected && (
            <div className="rounded-lg border border-border bg-surface-3/50 p-3 space-y-2">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs text-text/70 flex items-center gap-1">
                  <Clock size={12} />
                  Archivée le {formatStamp(selected.captured_at)}
                </span>
                <button
                  onClick={handleRestore}
                  disabled={busy}
                  className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-lg bg-memory-600 hover:bg-memory-700 disabled:opacity-50 text-white transition-colors"
                >
                  <RotateCcw size={13} />
                  {busy ? 'Restauration…' : 'Restaurer cette version'}
                </button>
              </div>
              <p className="text-sm font-medium text-text-heading">{selected.title}</p>
              <div className="prose prose-invert prose-sm max-w-none text-text max-h-64 overflow-y-auto">
                <Markdown content={selected.content_md || '*(vide)*'} />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

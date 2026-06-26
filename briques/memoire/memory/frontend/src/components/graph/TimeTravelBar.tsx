import { useEffect, useRef, useState } from 'react'
import { History, Play, Pause, RotateCcw, Clock } from 'lucide-react'
import type { TimelineEntry } from '../../types/api'

interface TimeTravelBarProps {
  // L'espace a-t-il le journal temporel activé ? (opt-in S112)
  trackHistory: boolean
  // Crans saillants de l'histoire de l'espace (S112), du plus ancien au plus récent.
  timeline: TimelineEntry[]
  // Instant courant affiché (ISO), ou null = présent / live.
  asOf: string | null
  // Activation en cours (appel réseau).
  activating: boolean
  // Demande d'activation du journal temporel de l'espace.
  onActivate: () => void
  // Glissement du curseur : iso = remonter à cet instant, null = revenir au présent.
  onSeek: (iso: string | null) => void
}

const kindLabels: Record<TimelineEntry['kind'], string> = {
  created: 'Création',
  stage: 'Changement de stade',
  edge_added: 'Lien créé',
  edge_removed: 'Lien supprimé',
}

function formatStamp(iso: string): string {
  try {
    return new Date(iso).toLocaleString('fr-FR', {
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

export default function TimeTravelBar({
  trackHistory,
  timeline,
  asOf,
  activating,
  onActivate,
  onSeek,
}: TimeTravelBarProps) {
  const [playing, setPlaying] = useState(false)

  // Crans du curseur : chaque instant saillant, puis le présent (null) à droite.
  const stops: (string | null)[] = [...timeline.map((e) => e.at), null]
  const lastIndex = stops.length - 1 // = le présent

  // Index courant déduit de asOf (présent si null ou introuvable).
  const currentIndex =
    asOf === null ? lastIndex : Math.max(0, stops.indexOf(asOf))

  // Référence vivante pour la lecture automatique (évite la fermeture périmée).
  const idxRef = useRef(currentIndex)
  idxRef.current = currentIndex

  useEffect(() => {
    if (!playing) return
    const id = setInterval(() => {
      const next = idxRef.current + 1
      if (next > lastIndex) {
        setPlaying(false)
        return
      }
      onSeek(stops[next])
    }, 1200)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, lastIndex])

  // Espace non suivi : proposer d'activer la frise temporelle.
  if (!trackHistory) {
    return (
      <div className="flex items-center justify-between gap-3 bg-surface-2 border border-border rounded-lg px-4 py-3">
        <div className="flex items-center gap-2 text-sm text-text">
          <History size={16} className="text-text/60" />
          <span>
            Remontez le temps du graphe entier (présence des nœuds, stade, liens).
          </span>
        </div>
        <button
          onClick={onActivate}
          disabled={activating}
          className="shrink-0 px-3 py-1.5 text-sm font-medium text-white bg-memory-600 hover:bg-memory-500 disabled:opacity-50 rounded-lg transition-colors"
        >
          {activating ? 'Activation…' : 'Activer la frise temporelle'}
        </button>
      </div>
    )
  }

  const atPresent = currentIndex === lastIndex
  const entry = atPresent ? null : timeline[currentIndex]

  return (
    <div className="bg-surface-2 border border-border rounded-lg px-4 py-3 space-y-2">
      <div className="flex items-center gap-3">
        <button
          onClick={() => setPlaying((p) => !p)}
          disabled={atPresent && !playing}
          title={playing ? 'Pause' : 'Lecture'}
          className="shrink-0 p-1.5 text-text hover:text-text-heading bg-surface-3 border border-border rounded-md disabled:opacity-40 transition-colors"
        >
          {playing ? <Pause size={16} /> : <Play size={16} />}
        </button>

        <input
          type="range"
          min={0}
          max={lastIndex}
          step={1}
          value={currentIndex}
          onChange={(e) => {
            setPlaying(false)
            onSeek(stops[Number(e.target.value)])
          }}
          className="flex-1 accent-memory-500 cursor-pointer"
          aria-label="Curseur temporel du graphe"
        />

        <button
          onClick={() => {
            setPlaying(false)
            onSeek(null)
          }}
          disabled={atPresent}
          title="Revenir au présent"
          className="shrink-0 p-1.5 text-text hover:text-text-heading bg-surface-3 border border-border rounded-md disabled:opacity-40 transition-colors"
        >
          <RotateCcw size={16} />
        </button>
      </div>

      <div className="flex items-center gap-2 text-xs">
        <Clock size={13} className="text-text/60 shrink-0" />
        {atPresent ? (
          <span className="text-emerald-400 font-medium">Présent — graphe en direct</span>
        ) : (
          <span className="text-amber-400">
            Lecture à <span className="font-medium">{entry ? formatStamp(entry.at) : ''}</span>
            {entry && (
              <span className="text-text/60"> · {kindLabels[entry.kind]}{entry.label ? ` : ${entry.label}` : ''}</span>
            )}
            <span className="text-text/40"> · {currentIndex + 1}/{lastIndex}</span>
          </span>
        )}
      </div>
    </div>
  )
}

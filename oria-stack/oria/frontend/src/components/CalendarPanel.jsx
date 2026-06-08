import { useState, useEffect } from 'react'
import { api } from '../services/api.js'

const MOIS_FR = ['Janvier','Février','Mars','Avril','Mai','Juin','Juillet','Août','Septembre','Octobre','Novembre','Décembre']
const JOURS_FR = ['Lun','Mar','Mer','Jeu','Ven','Sam','Dim']

export default function CalendarPanel({ world, moi, onFermer }) {
  const [annee, setAnnee] = useState(new Date().getFullYear())
  const [mois, setMois] = useState(new Date().getMonth())
  const [conseils, setConseils] = useState([])
  const [arretes, setArretes] = useState([])

  useEffect(() => { charger() }, [world?.id])

  async function charger() {
    const [c, a] = await Promise.all([
      api.get(`/conseils/world/${world.id}`),
      api.get(`/arretes/world/${world.id}`),
    ])
    if (c) setConseils(c)
    if (a) setArretes(a)
  }

  function naviguer(delta) {
    let nm = mois + delta, na = annee
    if (nm < 0) { nm = 11; na-- }
    if (nm > 11) { nm = 0; na++ }
    setMois(nm); setAnnee(na)
  }

  // Construire grille calendrier
  const premierJour = new Date(annee, mois, 1)
  const nbJours = new Date(annee, mois + 1, 0).getDate()
  // lundi=0 ... dimanche=6
  const debutOffset = (premierJour.getDay() + 6) % 7

  const cellules = []
  for (let i = 0; i < debutOffset; i++) cellules.push(null)
  for (let j = 1; j <= nbJours; j++) cellules.push(j)

  const moisStr = `${annee}-${String(mois + 1).padStart(2, '0')}`

  function evenementsDuJour(jour) {
    if (!jour) return []
    const dateStr = `${annee}-${String(mois + 1).padStart(2, '0')}-${String(jour).padStart(2, '0')}`
    const evts = []
    conseils.filter(c => c.date_conseil === dateStr).forEach(c =>
      evts.push({ type: 'conseil', label: `🏛 Conseil ${c.heure}`, statut: c.statut })
    )
    arretes.filter(a => a.date_arrete === dateStr).forEach(a =>
      evts.push({ type: 'arrete', label: `📑 ${a.numero}` })
    )
    return evts
  }

  const today = new Date()
  const isToday = (j) => j === today.getDate() && mois === today.getMonth() && annee === today.getFullYear()

  return (
    <div className="mairie-panel">
      <div className="mairie-panel-header">
        <div className="mairie-panel-title"><span>📅</span><h2>Calendrier</h2></div>
        <div className="mairie-panel-actions">
          <button className="mairie-btn-close" onClick={onFermer}>✕</button>
        </div>
      </div>

      <div className="calendar-nav">
        <button className="calendar-nav-btn" onClick={() => naviguer(-1)}>◀</button>
        <span className="calendar-mois-label">{MOIS_FR[mois]} {annee}</span>
        <button className="calendar-nav-btn" onClick={() => naviguer(1)}>▶</button>
        <button className="mairie-filter-btn" onClick={() => { setMois(new Date().getMonth()); setAnnee(new Date().getFullYear()) }}>
          Aujourd'hui
        </button>
      </div>

      <div className="calendar-grid">
        {JOURS_FR.map(j => <div key={j} className="calendar-day-header">{j}</div>)}
        {cellules.map((jour, idx) => {
          const evts = evenementsDuJour(jour)
          return (
            <div key={idx} className={`calendar-cell ${!jour ? 'calendar-cell-vide' : ''} ${isToday(jour) ? 'calendar-cell-today' : ''}`}>
              {jour && <span className="calendar-jour-num">{jour}</span>}
              {evts.map((e, i) => (
                <div key={i} className={`calendar-evt calendar-evt-${e.type}`}>{e.label}</div>
              ))}
            </div>
          )
        })}
      </div>

      <div className="calendar-legende">
        <span className="calendar-evt calendar-evt-conseil">🏛 Conseil</span>
        <span className="calendar-evt calendar-evt-arrete">📑 Arrêté</span>
      </div>
    </div>
  )
}

# world-engine — Génome Cosmique

Prototype : croise 2 profils cosmiques (via la brique `personnages`) pour produire
un enfant dont le thème astral est calculé à une vraie date, avec un récit
d'hérédité en post-traitement (comparaison des 10 corps aux 2 parents).

Voir la spec : `docs/superpowers/specs/2026-08-22-world-engine-genome-cosmique-design.md`.

Stateless : aucune donnée n'est persistée. Dépend de la brique `personnages`
(port 5900) en HTTP — pas de duplication du moteur astro.

Port : 6220.

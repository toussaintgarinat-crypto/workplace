"""Brique externe de démonstration — auto-découverte par le générateur.

Déposer ce fichier dans briques_app/ suffit à ajouter un module « Notes internes »
à TOUTES les applications générées, sans toucher au cœur du générateur.

Contrat d'une brique externe : exposer `construire(ctx) -> list[vue]`.
Une vue = {"id","label","icone","categorie","html"} ; html peut contenir son
propre <script> (les briques externes sont autonomes).
"""


def construire(ctx):
    slug = ctx.get("slug", "app")
    html = """
    <div class="page-header"><h4><i class="bi bi-journal-text me-2 text-wp"></i>Notes internes</h4>
      <p class="text-muted mb-0">Bloc-notes partagé de l'équipe — enregistré dans ce navigateur.</p></div>
    <div class="card"><div class="card-body">
      <textarea id="notesZone" class="form-control mb-2" rows="12" placeholder="Vos notes..."></textarea>
      <button class="btn btn-wp" onclick="sauverNotes()"><i class="bi bi-save me-1"></i>Enregistrer</button>
      <span id="notesEtat" class="text-success ms-2 small"></span>
    </div></div>
    <script>
      (function(){
        var k = 'wp_NOTESLUG_notes';
        function init(){
          var z = document.getElementById('notesZone'); if(!z) return;
          z.value = localStorage.getItem(k) || '';
        }
        window.sauverNotes = function(){
          var z = document.getElementById('notesZone');
          localStorage.setItem(k, z.value);
          var e = document.getElementById('notesEtat'); e.textContent = 'Enregistré ✓';
          setTimeout(function(){ e.textContent=''; }, 2000);
        };
        document.addEventListener('DOMContentLoaded', init);
      })();
    </script>
    """.replace("NOTESLUG", slug)
    return [{
        "id": "notes",
        "label": "Notes internes",
        "icone": "bi-journal-text",
        "categorie": "outils",
        "html": html,
    }]

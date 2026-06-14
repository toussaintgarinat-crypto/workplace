#!/usr/bin/env python3
"""
Service « voix » du studio — tourne sur l'HÔTE macOS (a accès à `say` + ffmpeg,
contrairement aux conteneurs Linux). Mirroir du pont Ollama : les briques le
joignent via host.docker.internal:5810.

POST /rendre   {episode_id, segments:[{voix, texte}]} -> assemble un .mp3 (say + ffmpeg)
GET  /fichiers/{nom}.mp3                               -> sert l'audio (lecture navigateur)
GET  /sante

Stdlib uniquement (http.server) — aucun pip. Démarrage : python3 serveur.py
"""
import json, os, subprocess, tempfile, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.getenv("VOIX_PORT", "5810"))
ICI = os.path.dirname(os.path.abspath(__file__))
FICHIERS = os.path.join(ICI, "fichiers")
os.makedirs(FICHIERS, exist_ok=True)

# Langues du Studio (= les 7 d'Oria) → locales macOS à retenir, par ordre de préférence.
# `say` lit le texte dans la langue de la voix choisie : une voix es_ES lit en espagnol.
LANGUES_LOCALES = {
    "fr": ["fr_FR", "fr_CA"],
    "en": ["en_US", "en_GB"],
    "es": ["es_ES", "es_MX"],
    "ar": ["ar_001", "ar_"],
    "pt": ["pt_BR", "pt_PT"],
    "ja": ["ja_JP"],
    "zh": ["zh_CN", "zh_TW"],
}
# Voix « propres » à remonter en tête du pool quand elles existent (par langue).
PREF = {
    "fr": ["Thomas", "Amélie", "Jacques", "Aurélie", "Marie", "Nicolas"],
    "en": ["Samantha", "Alex", "Ava", "Allison", "Tom", "Fred"],
    "es": ["Mónica", "Paulina", "Juan", "Diego", "Jorge"],
}
# Voix « nouveauté / effets » macOS (1er mot du nom) à NE PAS proposer comme narrateurs.
EXCLURE = {
    "Albert", "Bad", "Bahh", "Bells", "Boing", "Bubbles", "Cellos", "Good", "Jester",
    "Organ", "Superstar", "Trinoids", "Whisper", "Wobble", "Zarvox", "Hysterical",
    "Deranged", "Pipe", "Princess", "Junior", "Ralph",
}


def _voix_par_langue():
    """Parse `say -v ?` une fois → {code_langue: [voix...]}. Repli FR = ['Thomas'].

    On ne garde par langue que les voix MONOLINGUES (une seule locale installée) : ainsi
    `say -v <voix>` prononce bien la langue voulue. Les voix « nouveauté » multilingues
    (Flo, Eddy, Grandma…) sont écartées — elles liraient dans leur langue par défaut."""
    try:
        out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return {"fr": ["Thomas"]}
    import re
    # nom de voix → ensemble des locales où elle apparaît (ordre d'apparition conservé)
    voix_locales, ordre = {}, []
    for ligne in out.splitlines():
        if not ligne.strip():
            continue
        nom = ligne.split()[0]
        m = re.search(r"[a-z]{2}_[A-Za-z0-9]{2,3}", ligne)
        if not m:
            continue
        if nom not in voix_locales:
            voix_locales[nom], _ = set(), ordre.append(nom)
        voix_locales[nom].add(m.group(0))
    par_langue = {}
    for code, locales in LANGUES_LOCALES.items():
        pool = []
        for nom in ordre:                       # ordre stable du catalogue système
            if nom in EXCLURE:                  # écarte les voix « nouveauté / effets »
                continue
            locs = voix_locales[nom]
            if len(locs) != 1:                  # écarte les voix multilingues
                continue
            (loc,) = tuple(locs)
            if any(loc.startswith(p) for p in locales):
                pool.append(nom)
        pref = PREF.get(code, [])               # remonte les voix « propres » connues en tête
        if pref:
            pool = [v for v in pref if v in pool] + [v for v in pool if v not in pref]
        if pool:
            par_langue[code] = pool
    par_langue.setdefault("fr", ["Thomas"])
    return par_langue


VOIX_PAR_LANGUE = _voix_par_langue()
VOIX = VOIX_PAR_LANGUE["fr"]            # rétro-compat (pool FR « historique »)
DEFAUT = VOIX[0]
DEFAUT_PAR_LANGUE = {c: pool[0] for c, pool in VOIX_PAR_LANGUE.items()}


def _rendre(episode_id, segments, langue="fr"):
    """say chaque réplique -> aiff, puis ffmpeg concat -> mp3. Retourne (chemin, duree)."""
    pool = VOIX_PAR_LANGUE.get(langue) or VOIX_PAR_LANGUE["fr"]
    defaut = pool[0]
    with tempfile.TemporaryDirectory() as tmp:
        liste = os.path.join(tmp, "list.txt")
        lignes = []
        for i, seg in enumerate(segments):
            texte = (seg.get("texte") or "").strip()
            if not texte:
                continue
            voix = seg.get("voix") if seg.get("voix") in pool else defaut
            aiff = os.path.join(tmp, f"s{i}.aiff")
            subprocess.run(["say", "-v", voix, "-o", aiff, texte], check=True, timeout=60)
            lignes.append(f"file '{aiff}'")
        if not lignes:
            raise ValueError("aucun segment audible")
        with open(liste, "w") as f:
            f.write("\n".join(lignes) + "\n")
        nom = f"{episode_id or uuid.uuid4().hex}.mp3"
        sortie = os.path.join(FICHIERS, nom)
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", liste,
             "-ar", "44100", "-ac", "2", "-b:a", "128k", sortie],
            check=True, capture_output=True, timeout=120,
        )
        duree = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", sortie],
            capture_output=True, text=True, timeout=15).stdout.strip()
        return nom, float(duree or 0)


class H(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def do_GET(self):
        if self.path == "/sante":
            return self._json(200, {"statut": "ok",
                                    "langues": VOIX_PAR_LANGUE,
                                    "defaut_par_langue": DEFAUT_PAR_LANGUE,
                                    "voix": VOIX, "defaut": DEFAUT})  # voix/defaut = rétro-compat FR
        if self.path.startswith("/fichiers/"):
            nom = os.path.basename(self.path.split("?")[0])
            chemin = os.path.join(FICHIERS, nom)
            if not os.path.isfile(chemin):
                return self._json(404, {"erreur": "introuvable"})
            data = open(chemin, "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Accept-Ranges", "bytes")
            self._cors()
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self._json(404, {"erreur": "route inconnue"})

    def do_POST(self):
        if self.path != "/rendre":
            return self._json(404, {"erreur": "route inconnue"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or "{}")
            nom, duree = _rendre(body.get("episode_id"), body.get("segments") or [],
                                 body.get("langue") or "fr")
            self._json(200, {"fichier": nom, "duree": duree,
                             "url": f"http://localhost:{PORT}/fichiers/{nom}"})
        except Exception as e:  # noqa: BLE001
            self._json(500, {"erreur": str(e)[:300]})

    def log_message(self, *a):  # silencieux
        pass


if __name__ == "__main__":
    print(f"[studio-voix] écoute :{PORT} — langues dispo : "
          + ", ".join(f"{c}({len(v)})" for c, v in VOIX_PAR_LANGUE.items()))
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()

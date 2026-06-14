#!/usr/bin/env bash
# S41 POC openWakeWord — génère des échantillons audio de test (16 kHz mono WAV).
#
# Deux usages :
#  1) Preuve de DÉTECTION : on synthétise « hey jarvis » (positifs, plusieurs voix)
#     et des phrases qui n'ont rien à voir (négatifs) pour mesurer le modèle
#     pré-entraîné hey_jarvis d'openWakeWord.
#  2) Preuve du CHEMIN DE DONNÉES FR : on synthétise un nom inventé en FRANÇAIS
#     avec une voix française locale (`say`). C'est exactement ce que fait le
#     pipeline d'entraînement officiel (Piper TTS) mais en local et reproductible,
#     pour lever le risque « FR » du plan avant d'investir dans l'entraînement GPU.
#
# Le TTS macOS `say` produit de l'AIFF ; `afconvert` le ramène en WAV PCM16 16 kHz mono
# (format d'entrée attendu par openWakeWord).
set -euo pipefail
ICI="$(cd "$(dirname "$0")" && pwd)"
OUT="$ICI/echantillons"
rm -rf "$OUT"; mkdir -p "$OUT"

dire() { # dire <voix> <texte> <fichier_sans_ext>
  local voix="$1" texte="$2" nom="$3"
  say -v "$voix" -o "$OUT/$nom.aiff" "$texte"
  afconvert "$OUT/$nom.aiff" "$OUT/$nom.wav" -d LEI16@16000 -c 1 -f WAVE
  rm -f "$OUT/$nom.aiff"
}

echo "→ Positifs « hey jarvis » (plusieurs voix EN)"
dire "Samantha" "hey jarvis"            "pos_samantha"
dire "Alex"     "hey jarvis"            "pos_alex"
dire "Daniel"   "hey jarvis"            "pos_daniel"
dire "Samantha" "hey jarvis, what's the weather" "pos_phrase"

echo "→ Négatifs (ne doivent PAS déclencher)"
dire "Samantha" "what time is it"       "neg_time"
dire "Samantha" "hello there my friend" "neg_hello"
dire "Alex"     "hey google turn on"    "neg_google"
dire "Eddy (Français (France))" "bonjour comment ça va" "neg_fr"

echo "→ Chemin FR : nom inventé prononcé par une voix française locale"
dire "Eddy (Français (France))"    "dis Oria"   "fr_oria_eddy"
dire "Flo (Français (France))"     "dis Oria"   "fr_oria_flo"
dire "Thomas"                      "Oria, ouvre mon agenda" "fr_oria_thomas"

echo "✓ $(ls "$OUT"/*.wav | wc -l | tr -d ' ') fichiers WAV générés dans $OUT"

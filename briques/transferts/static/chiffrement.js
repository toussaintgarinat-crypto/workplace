// Primitives crypto E2E — AES-256-GCM via WebCrypto, vendorées à la main depuis
// le design de suitenumerique/transfers (docs/ENCRYPTION.md, encryption.ts),
// PAS un import de leur code : Workplace ne fork pas l'appli Django (S196).
//
// Layout par partie chiffrée : [ IV(12) | ciphertext | tag GCM(16) ].
// Une "partie" = un PUT HTTP direct vers notre propre endpoint (pas une URL S3
// présignée : sans S3, chaque partie va directement à notre FastAPI, cf. plan
// S196 § Risques/Décisions). L'AAD `idFichier:numero:nbParties` empêche
// l'échange/réordonnancement de parties entre fichiers ou positions (le tag
// GCM ne s'authentifie que si l'AAD recalculée est identique des deux côtés).
//
// La clé (32 octets aléatoires) ne quitte JAMAIS ce module vers le serveur :
// v1 est TOUJOURS en mode confidentiel/E2E pur (pas de mode "normal" où le
// serveur détiendrait la clé, cf. arbitrage du plan) — le `fragment` base64url
// vit uniquement dans le fragment `#` de l'URL de partage.

export const SURCOUT_PAR_PARTIE = 12 /* IV */ + 16 /* tag GCM */;
const TAILLE_CLE_OCTETS = 32;
const TAILLE_IV_OCTETS = 12;

export async function genererCle() {
  const brut = crypto.getRandomValues(new Uint8Array(TAILLE_CLE_OCTETS));
  const cleCrypto = await crypto.subtle.importKey(
    "raw", brut, { name: "AES-GCM" }, false, ["encrypt", "decrypt"],
  );
  return { cleCrypto, fragment: encoderBase64Url(brut) };
}

export async function importerCle(fragment) {
  const brut = decoderBase64Url(fragment);
  if (brut.length !== TAILLE_CLE_OCTETS) throw new Error("Longueur de clé invalide.");
  return crypto.subtle.importKey("raw", brut, { name: "AES-GCM" }, false, ["encrypt", "decrypt"]);
}

export function aadPourPartie(idFichier, numero, nbParties) {
  return new TextEncoder().encode(`${idFichier}:${numero}:${nbParties}`);
}

export function nbParties(tailleClair, taillePartie) {
  if (tailleClair <= 0) return 1;   // fichier vide : une partie authentifiée (IV+tag) quand même
  return Math.ceil(tailleClair / taillePartie);
}

export function tailleChiffree(tailleClair, taillePartie) {
  return tailleClair + nbParties(tailleClair, taillePartie) * SURCOUT_PAR_PARTIE;
}

export async function chiffrerPartie(cle, clair, aad) {
  const iv = crypto.getRandomValues(new Uint8Array(TAILLE_IV_OCTETS));
  const ct = new Uint8Array(
    await crypto.subtle.encrypt({ name: "AES-GCM", iv, additionalData: aad }, cle, clair),
  );
  const out = new Uint8Array(iv.length + ct.length);
  out.set(iv, 0);
  out.set(ct, iv.length);
  return out;
}

export async function dechiffrerPartie(cle, partieChiffree, aad) {
  if (partieChiffree.length < TAILLE_IV_OCTETS + 16) throw new Error("Partie chiffrée trop courte.");
  const iv = partieChiffree.subarray(0, TAILLE_IV_OCTETS);
  const corps = partieChiffree.subarray(TAILLE_IV_OCTETS);
  const clair = await crypto.subtle.decrypt({ name: "AES-GCM", iv, additionalData: aad }, cle, corps);
  return new Uint8Array(clair);
}

export function encoderBase64Url(octets) {
  let bin = "";
  for (let i = 0; i < octets.length; i++) bin += String.fromCharCode(octets[i]);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function decoderBase64Url(s) {
  const pad = s.length % 4 === 0 ? "" : "=".repeat(4 - (s.length % 4));
  const b64 = s.replace(/-/g, "+").replace(/_/g, "/") + pad;
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

// TransformStream ciphertext → clair, en flux : le réseau livre le ciphertext
// en paquets TCP arbitraires (~64 Ko), pas alignés sur la frontière de partie
// chiffrée (tailleChiffréePartie = taillePartie + SURCOUT_PAR_PARTIE). On
// bufferise jusqu'à avoir une partie complète, on la déchiffre, on pousse le
// clair — jamais tout le fichier en RAM (mirrors sw.js::decryptStream de
// suitenumerique/transfers, docs/ENCRYPTION.md § Stream reassembly).
export function creerFluxDechiffrement(cle, taillePartie, tailleClairTotale, idFichier) {
  const tailleChiffreePartie = taillePartie + SURCOUT_PAR_PARTIE;
  const encoder = new TextEncoder();
  const parties = nbParties(tailleClairTotale, taillePartie);
  let enAttente = new Uint8Array(0);
  let clairRestant = tailleClairTotale;
  let numero = 0;

  function concat(a, b) {
    const bArr = b instanceof Uint8Array ? b : new Uint8Array(b);
    const out = new Uint8Array(a.length + bArr.length);
    out.set(a, 0);
    out.set(bArr, a.length);
    return out;
  }

  return new TransformStream({
    async transform(morceau, controller) {
      enAttente = concat(enAttente, morceau);
      while (clairRestant > taillePartie && enAttente.length >= tailleChiffreePartie) {
        const partieChiffree = enAttente.subarray(0, tailleChiffreePartie);
        enAttente = enAttente.slice(tailleChiffreePartie);
        const aad = encoder.encode(`${idFichier}:${numero}:${parties}`);
        const clair = await dechiffrerPartie(cle, partieChiffree, aad);
        controller.enqueue(clair);
        clairRestant -= clair.length;
        numero += 1;
      }
    },
    async flush(controller) {
      const attendu = clairRestant + SURCOUT_PAR_PARTIE;
      if (enAttente.length !== attendu) {
        controller.error(new Error(
          `Flux ciphertext tronqué (attendu ${attendu} octets restants, reçu ${enAttente.length}).`,
        ));
        return;
      }
      const aad = encoder.encode(`${idFichier}:${numero}:${parties}`);
      const clair = await dechiffrerPartie(cle, enAttente, aad);
      if (clair.length > 0) controller.enqueue(clair);
      clairRestant -= clair.length;
      if (clairRestant !== 0) {
        controller.error(new Error(`Taille de clair incohérente après déchiffrement (résiduel ${clairRestant}).`));
      }
    },
  });
}

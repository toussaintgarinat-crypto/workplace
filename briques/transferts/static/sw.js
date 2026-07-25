// Service Worker de déchiffrement — intercepte /_dl/<jetonPublic>/<idFichier>
// et streame le clair directement vers le gestionnaire de téléchargement du
// navigateur (jamais de Blob, jamais tout le fichier en RAM).
//
// Duplique volontairement l'algorithme de déchiffrement en flux de
// chiffrement.js (déjà testé en Node, cf. static/chiffrement.test.mjs) : un
// Service Worker ne peut pas importer un module ES de façon universellement
// fiable sur tous les navigateurs cibles, donc on l'inline ici — même motif
// que sw.js/encryption.ts dans suitenumerique/transfers (docs/ENCRYPTION.md
// § What's ours vs what WebCrypto handles).
//
// Différence avec l'upstream : un seul hop réseau (pas de S3), on fetch
// directement notre propre endpoint /t/<jeton>/fichiers/<id>/chiffre, même
// origine — pas besoin du détour "backend renvoie une URL présignée S3 en
// JSON, puis fetch anonyme vers S3" qui existe chez eux pour contourner les
// particularités CORS/cookies d'un fetch cross-origin vers S3.

const IV_OCTETS = 12;
const SURCOUT = IV_OCTETS + 16;
const REGISTRE = new Map(); // jetonPublic -> { cle, fichiers: Map<id, meta> }

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("message", (event) => {
  const data = event.data;
  if (!data || typeof data !== "object") return;
  if (data.type === "enregistrer-cle") {
    enregistrerCle(data)
      .then(() => event.source?.postMessage({ type: "enregistrer-cle-ok", jeton: data.jeton }))
      .catch((err) => event.source?.postMessage({
        type: "enregistrer-cle-erreur", jeton: data.jeton, message: String(err?.message || err),
      }));
  } else if (data.type === "oublier-cle") {
    REGISTRE.delete(data.jeton);
  }
});

async function enregistrerCle({ jeton, cleOctets, fichiers }) {
  if (!jeton || !(cleOctets instanceof Uint8Array) || !Array.isArray(fichiers)) {
    throw new Error("Message enregistrer-cle malformé.");
  }
  const cle = await crypto.subtle.importKey("raw", cleOctets, { name: "AES-GCM" }, false, ["decrypt"]);
  const fichierMap = new Map();
  for (const f of fichiers) {
    fichierMap.set(f.id, {
      taillePartie: f.taillePartie, tailleClair: f.tailleClair,
      nom: f.nom, typeMime: f.typeMime || "application/octet-stream",
    });
  }
  REGISTRE.set(jeton, { cle, fichiers: fichierMap });
}

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;
  const m = url.pathname.match(/^\/_dl\/([^/]+)\/([^/]+)/);
  if (!m) return;
  event.respondWith(gererTelechargement(m[1], m[2]));
});

async function gererTelechargement(jeton, idFichier) {
  const entree = REGISTRE.get(jeton);
  if (!entree) {
    return new Response("Clé de déchiffrement non chargée. Rouvre le lien.", { status: 500 });
  }
  const meta = entree.fichiers.get(idFichier);
  if (!meta) return new Response("Fichier inconnu.", { status: 404 });

  const reponse = await fetch(`/t/${jeton}/fichiers/${idFichier}/chiffre`, { credentials: "omit" });
  if (!reponse.ok || !reponse.body) {
    return new Response("Échec de récupération du fichier chiffré.", { status: reponse.status || 502 });
  }

  const flux = reponse.body.pipeThrough(
    creerFluxDechiffrement(entree.cle, meta.taillePartie, meta.tailleClair, idFichier),
  );

  return new Response(flux, {
    headers: {
      "Content-Type": meta.typeMime,
      "Content-Length": String(meta.tailleClair),
      "Content-Disposition": `attachment; filename*=UTF-8''${encodeURIComponent(meta.nom)}`,
      "Cache-Control": "no-store",
    },
  });
}

// Copie de chiffrement.js::creerFluxDechiffrement — voir la note en tête de
// fichier pour pourquoi cette duplication est assumée.
function creerFluxDechiffrement(cle, taillePartie, tailleClairTotale, idFichier) {
  const tailleChiffreePartie = taillePartie + SURCOUT;
  const encoder = new TextEncoder();
  const parties = tailleClairTotale <= 0 ? 1 : Math.ceil(tailleClairTotale / taillePartie);
  let enAttente = new Uint8Array(0);
  let clairRestant = tailleClairTotale;
  let numero = 0;

  function concat(a, b) {
    const bArr = b instanceof Uint8Array ? b : new Uint8Array(b);
    const out = new Uint8Array(a.length + bArr.length);
    out.set(a, 0); out.set(bArr, a.length);
    return out;
  }
  async function dechiffrerUne(ciphertext, aad) {
    const iv = ciphertext.subarray(0, IV_OCTETS);
    const corps = ciphertext.subarray(IV_OCTETS);
    return new Uint8Array(await crypto.subtle.decrypt({ name: "AES-GCM", iv, additionalData: aad }, cle, corps));
  }

  return new TransformStream({
    async transform(morceau, controller) {
      enAttente = concat(enAttente, morceau);
      while (clairRestant > taillePartie && enAttente.length >= tailleChiffreePartie) {
        const ct = enAttente.subarray(0, tailleChiffreePartie);
        enAttente = enAttente.slice(tailleChiffreePartie);
        const aad = encoder.encode(`${idFichier}:${numero}:${parties}`);
        const clair = await dechiffrerUne(ct, aad);
        controller.enqueue(clair);
        clairRestant -= clair.length;
        numero += 1;
      }
    },
    async flush(controller) {
      const attendu = clairRestant + SURCOUT;
      if (enAttente.length !== attendu) {
        controller.error(new Error(`Flux tronqué (attendu ${attendu}, reçu ${enAttente.length}).`));
        return;
      }
      const aad = encoder.encode(`${idFichier}:${numero}:${parties}`);
      const clair = await dechiffrerUne(enAttente, aad);
      if (clair.length > 0) controller.enqueue(clair);
      clairRestant -= clair.length;
      if (clairRestant !== 0) controller.error(new Error(`Taille incohérente (résiduel ${clairRestant}).`));
    },
  });
}

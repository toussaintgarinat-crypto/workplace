// Tests offline du module crypto E2E — Node natif (WebCrypto + TransformStream
// sont globaux depuis Node 16.5/19, aucune dépendance npm). Lancé via
// `node --test`. Vérifie le mécanisme réimplémenté de suitenumerique/transfers
// (encryption.ts) : IV(12)|ciphertext|tag(16) par partie, AAD liant
// fileId:partNumber:parts contre le rejeu/l'échange de parties.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as C from "./chiffrement.js";

test("genererCle produit un fragment base64url de 43 caractères", async () => {
  const { fragment } = await C.genererCle();
  assert.equal(fragment.length, 43);
  assert.doesNotMatch(fragment, /[+/=]/);
});

test("importerCle(fragment) reconstruit la même clé (round-trip chiffrer/déchiffrer)", async () => {
  const { cleCrypto, fragment } = await C.genererCle();
  const cleReimportee = await C.importerCle(fragment);
  const aad = C.aadPourPartie("f1", 0, 1);
  const clair = new TextEncoder().encode("bonjour");
  const chiffre = await C.chiffrerPartie(cleCrypto, clair, aad);
  const dechiffre = await C.dechiffrerPartie(cleReimportee, chiffre, aad);
  assert.equal(new TextDecoder().decode(dechiffre), "bonjour");
});

test("nbParties et tailleChiffree suivent la formule ceil(clair/partie) + surcout", () => {
  assert.equal(C.nbParties(40, 16), 3);
  assert.equal(C.nbParties(0, 16), 1);          // fichier vide : 1 partie authentifiée quand même
  assert.equal(C.tailleChiffree(40, 16), 40 + 3 * C.SURCOUT_PAR_PARTIE);
  assert.equal(C.tailleChiffree(0, 16), C.SURCOUT_PAR_PARTIE);
});

test("chiffrerPartie produit IV(12) + ciphertext + tag(16), taille = clair + surcout", async () => {
  const { cleCrypto } = await C.genererCle();
  const clair = new Uint8Array(100).fill(7);
  const chiffre = await C.chiffrerPartie(cleCrypto, clair, C.aadPourPartie("f", 0, 1));
  assert.equal(chiffre.length, 100 + C.SURCOUT_PAR_PARTIE);
});

test("dechiffrerPartie rejette une AAD différente (partie échangée/réordonnée)", async () => {
  const { cleCrypto } = await C.genererCle();
  const clair = new TextEncoder().encode("secret");
  const chiffre = await C.chiffrerPartie(cleCrypto, clair, C.aadPourPartie("f1", 0, 2));
  await assert.rejects(() => C.dechiffrerPartie(cleCrypto, chiffre, C.aadPourPartie("f1", 1, 2)));
});

test("encoderBase64Url / decoderBase64Url round-trip sur des octets aléatoires", () => {
  const octets = crypto.getRandomValues(new Uint8Array(32));
  const s = C.encoderBase64Url(octets);
  assert.deepEqual(Array.from(C.decoderBase64Url(s)), Array.from(octets));
});

test("creerFluxDechiffrement reconstruit le clair depuis un flux ciphertext TCP-fragmenté", async () => {
  const { cleCrypto } = await C.genererCle();
  const taillePartie = 8;
  const idFichier = "fichier-test";
  // 3 parties de clair : 8 + 8 + 4 = 20 octets
  const clairTotal = new Uint8Array(20).map((_, i) => i);
  const partiesClair = [clairTotal.slice(0, 8), clairTotal.slice(8, 16), clairTotal.slice(16, 20)];
  const parties = C.nbParties(20, taillePartie);
  const morceauxChiffres = [];
  for (let i = 0; i < partiesClair.length; i++) {
    morceauxChiffres.push(
      await C.chiffrerPartie(cleCrypto, partiesClair[i], C.aadPourPartie(idFichier, i, parties)),
    );
  }
  const ciphertextComplet = new Uint8Array(morceauxChiffres.reduce((n, m) => n + m.length, 0));
  let off = 0;
  for (const m of morceauxChiffres) { ciphertextComplet.set(m, off); off += m.length; }

  // Simule un flux réseau TCP : re-fragmente en morceaux arbitraires de 5 octets
  // (indépendants des frontières de partie chiffrée) pour vérifier le buffering interne.
  const source = new ReadableStream({
    start(controller) {
      for (let i = 0; i < ciphertextComplet.length; i += 5) {
        controller.enqueue(ciphertextComplet.slice(i, i + 5));
      }
      controller.close();
    },
  });

  const dechiffre = source.pipeThrough(
    C.creerFluxDechiffrement(cleCrypto, taillePartie, 20, idFichier),
  );
  const lecteur = dechiffre.getReader();
  const recu = [];
  for (;;) {
    const { done, value } = await lecteur.read();
    if (done) break;
    recu.push(...value);
  }
  assert.deepEqual(recu, Array.from(clairTotal));
});

test("creerFluxDechiffrement signale une erreur sur un flux tronqué", async () => {
  const { cleCrypto } = await C.genererCle();
  const idFichier = "f-tronque";
  const chiffre = await C.chiffrerPartie(
    cleCrypto, new Uint8Array(8).fill(1), C.aadPourPartie(idFichier, 0, 1),
  );
  const tronque = chiffre.slice(0, chiffre.length - 5);   // coupe les 5 derniers octets
  const source = new ReadableStream({
    start(controller) { controller.enqueue(tronque); controller.close(); },
  });
  const dechiffre = source.pipeThrough(C.creerFluxDechiffrement(cleCrypto, 8, 8, idFichier));
  const lecteur = dechiffre.getReader();
  await assert.rejects(async () => { while (!(await lecteur.read()).done); });
});

/**
 * Singleton Matrix client pour Oria.
 * Initialisé une fois au login, partagé dans toute l'app.
 * Phase 5 : E2EE Megolm activé via IndexedDBCryptoStore.
 */
import { createClient, IndexedDBCryptoStore } from 'matrix-js-sdk'

const MATRIX_URL = import.meta.env.VITE_MATRIX_URL || 'http://localhost:8008'

let _client = null

/** Génère ou récupère un deviceId stable pour cette session. */
function _getDeviceId(userId) {
  const key = `oria_device_${userId}`
  let id = localStorage.getItem(key)
  if (!id) {
    id = 'ORIA_' + Math.random().toString(36).slice(2, 10).toUpperCase()
    localStorage.setItem(key, id)
  }
  return id
}

/**
 * Initialise le client Matrix avec les credentials du login.
 * À appeler juste après la connexion réussie à l'API Oria.
 */
export function initMatrixClient({ userId, accessToken }) {
  if (_client) {
    _client.stopClient()
    _client = null
  }

  _client = createClient({
    baseUrl: MATRIX_URL,
    userId,
    accessToken,
    deviceId: _getDeviceId(userId),
    cryptoStore: new IndexedDBCryptoStore(
      window.indexedDB,
      'oria:matrix-crypto'
    ),
  })

  return _client
}

/**
 * Démarre la synchro Matrix (à appeler après initMatrixClient).
 * Initialise le module crypto Megolm avant le premier sync.
 * Résout quand l'état initial est prêt (PREPARED/SYNCING).
 */
export async function startMatrixClient() {
  if (!_client) return null

  // Initialiser le chiffrement E2EE (Megolm)
  try {
    await _client.initCrypto()
    _client.setGlobalErrorOnUnknownDevices(false) // évite les erreurs sur devices inconnus
  } catch (e) {
    // Synapse indisponible ou crypto déjà initialisé — mode dégradé
    console.warn('[Matrix] Crypto init échoué, mode sans E2EE :', e.message)
  }

  // Écouter tous les changements d'état de sync pour l'indicateur de connexion
  _client.on('sync', (state) => {
    window.dispatchEvent(new CustomEvent('oria:matrix-status', { detail: state }))
  })

  return new Promise((resolve) => {
    _client.once('sync', (state) => {
      if (state === 'PREPARED' || state === 'SYNCING') {
        resolve(_client)
      }
    })
    _client.startClient({ initialSyncLimit: 30 })
  })
}

/** Retourne le client Matrix actif (ou null). */
export function getMatrixClient() {
  return _client
}

/** Arrête et nettoie le client (à appeler à la déconnexion). */
export function stopMatrixClient() {
  if (_client) {
    _client.stopClient()
    _client = null
  }
}

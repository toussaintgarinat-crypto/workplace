/**
 * Ollama Bridge — relaie les requêtes réseau vers un Ollama local.
 *
 * Permet aux téléphones, tablettes et conteneurs Docker d'appeler le LLM
 * local (Mac / serveur) sans exposer directement le port 11434.
 *
 * Variables d'environnement :
 *   OLLAMA_URL        URL d'Ollama local  (défaut: http://localhost:11434)
 *   BRIDGE_PORT       Port d'écoute       (défaut: 11436)
 *   BRIDGE_API_KEY    Clé API optionnelle (vide = pas d'auth)
 *   ALLOWED_ORIGINS   CORS, séparés par , (défaut: *)
 */

const OLLAMA_URL   = process.env.OLLAMA_URL    || 'http://localhost:11434'
const PORT         = Number(process.env.BRIDGE_PORT)    || 11436
const API_KEY      = process.env.BRIDGE_API_KEY || ''
const ALLOWED_ORIGINS = (process.env.ALLOWED_ORIGINS || '*').split(',').map(s => s.trim())
if (ALLOWED_ORIGINS.includes('*')) {
  console.warn('[WARN] ALLOWED_ORIGINS=* — toutes les origines sont autorisées. Restreindre en production via ALLOWED_ORIGINS=https://votre-domaine.com')
}

function corsHeaders(origin: string | null): Record<string, string> {
  const allow = ALLOWED_ORIGINS.includes('*') ? '*' : (ALLOWED_ORIGINS.includes(origin ?? '') ? origin! : '')
  return {
    'Access-Control-Allow-Origin':  allow || '',
    'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
  }
}

async function handler(req: Request): Promise<Response> {
  const origin = req.headers.get('Origin')

  // Preflight CORS
  if (req.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: corsHeaders(origin) })
  }

  // Auth optionnelle
  if (API_KEY) {
    const auth = req.headers.get('Authorization') ?? ''
    const provided = auth.startsWith('Bearer ') ? auth.slice(7) : auth
    if (provided !== API_KEY) {
      return new Response(JSON.stringify({ error: 'Unauthorized' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json', ...corsHeaders(origin) },
      })
    }
  }

  // Proxy vers Ollama
  const url = new URL(req.url)
  const targetUrl = `${OLLAMA_URL}${url.pathname}${url.search}`

  try {
    const body = req.method !== 'GET' && req.method !== 'HEAD'
      ? await req.arrayBuffer()
      : undefined

    const upstream = await fetch(targetUrl, {
      method: req.method,
      headers: { 'Content-Type': req.headers.get('Content-Type') || 'application/json' },
      body: body,
    })

    const responseHeaders: Record<string, string> = {
      'Content-Type': upstream.headers.get('Content-Type') || 'application/json',
      ...corsHeaders(origin),
    }

    return new Response(upstream.body, {
      status: upstream.status,
      headers: responseHeaders,
    })
  } catch (err: any) {
    const msg = err?.message?.includes('ECONNREFUSED')
      ? `Ollama non disponible sur ${OLLAMA_URL}. Lance "ollama serve" sur la machine hôte.`
      : `Erreur proxy: ${err?.message}`
    return new Response(JSON.stringify({ error: msg }), {
      status: 502,
      headers: { 'Content-Type': 'application/json', ...corsHeaders(origin) },
    })
  }
}

Bun.serve({ fetch: handler, port: PORT, hostname: '0.0.0.0' })

console.log(`[ollama-bridge] Écoute sur http://0.0.0.0:${PORT}`)
console.log(`[ollama-bridge] → Ollama: ${OLLAMA_URL}`)
console.log(`[ollama-bridge] Auth: ${API_KEY ? '🔒 clé API active' : '🔓 ouverte (pas de clé)'}`)
if (ALLOWED_ORIGINS.includes('*') && !API_KEY) {
  console.warn('[ollama-bridge] ⚠  ALLOWED_ORIGINS=* sans BRIDGE_API_KEY — acceptable en LAN/NetBird uniquement, pas en prod publique')
}

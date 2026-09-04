const TOKEN_KEY = 'spritedex.auth'

export function getTokens() {
  try {
    return JSON.parse(localStorage.getItem(TOKEN_KEY) || 'null')
  } catch {
    return null
  }
}

export function setTokens(tokens) {
  if (!tokens) localStorage.removeItem(TOKEN_KEY)
  else localStorage.setItem(TOKEN_KEY, JSON.stringify(tokens))
}

async function parseResponse(response) {
  if (response.status === 204) return null
  const type = response.headers.get('content-type') || ''
  const payload = type.includes('application/json') ? await response.json() : await response.text()
  if (!response.ok) {
    const detail = typeof payload === 'object' && payload?.detail ? payload.detail : payload
    const message = Array.isArray(detail)
      ? detail.map((item) => item.msg || JSON.stringify(item)).join(', ')
      : String(detail || `Request failed (${response.status})`)
    const error = new Error(message)
    error.status = response.status
    throw error
  }
  return payload
}

async function refreshSession() {
  const current = getTokens()
  if (!current?.refresh_token) return null
  try {
    const response = await fetch('/api/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: current.refresh_token }),
    })
    const tokens = await parseResponse(response)
    setTokens(tokens)
    return tokens
  } catch {
    setTokens(null)
    return null
  }
}

export async function apiFetch(path, options = {}, retry = true) {
  const tokens = getTokens()
  const headers = new Headers(options.headers || {})
  if (tokens?.access_token) headers.set('Authorization', `Bearer ${tokens.access_token}`)
  const response = await fetch(path, { ...options, headers })
  if (response.status === 401 && retry && tokens?.refresh_token) {
    const refreshed = await refreshSession()
    if (refreshed) return apiFetch(path, options, false)
  }
  return parseResponse(response)
}

export async function register({ email, password, displayName }) {
  const tokens = await apiFetch('/api/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password, display_name: displayName }),
  }, false)
  setTokens(tokens)
  return tokens
}

export async function login({ email, password }) {
  const body = new URLSearchParams({ username: email, password })
  const tokens = await apiFetch('/api/auth/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  }, false)
  setTokens(tokens)
  return tokens
}

export async function logout() {
  const tokens = getTokens()
  try {
    if (tokens?.refresh_token) {
      await apiFetch('/api/auth/logout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: tokens.refresh_token }),
      }, false)
    }
  } finally {
    setTokens(null)
  }
}

export const getMe = () => apiFetch('/api/me')
export const getRegions = () => apiFetch('/api/regions')
export const getRegionsAt = (latitude, longitude) =>
  apiFetch(`/api/regions/at?latitude=${encodeURIComponent(latitude)}&longitude=${encodeURIComponent(longitude)}`)
export const getMyRegions = () => apiFetch('/api/me/regions')
export const getMyRegionDex = (regionId) => apiFetch(`/api/me/regions/${regionId}/dex`)
export const getRegionDex = (regionId) => apiFetch(`/api/regions/${regionId}/dex`)
export const getSpecies = (speciesId) => apiFetch(`/api/species/${speciesId}`)
export const getEncounters = (limit = 100) => apiFetch(`/api/encounters?limit=${limit}`)
export const searchTaxa = (query) => apiFetch(`/api/taxa/search?q=${encodeURIComponent(query)}`)
export const importTaxon = (inatTaxonId) => apiFetch('/api/taxa/import', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ inat_taxon_id: inatTaxonId }),
})

export async function createFieldEncounter({ speciesId, latitude, longitude, notes, photo, caption, syncInaturalist }) {
  const form = new FormData()
  form.set('metadata', JSON.stringify({
    species_id: speciesId,
    latitude,
    longitude,
    notes: notes || null,
  }))
  if (photo) form.set('photo', photo)
  if (caption) form.set('caption', caption)
  form.set('sync_inaturalist', syncInaturalist ? 'true' : 'false')
  return apiFetch('/api/field/encounters', { method: 'POST', body: form })
}

export const syncEncounter = (encounterId) => apiFetch(`/api/field/encounters/${encounterId}/sync/inaturalist`, {
  method: 'POST',
})

export async function api(path, options = {}) {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 300_000)
  try {
    const response = await fetch(`/api${path}`, {
      ...options,
      signal: controller.signal,
      headers: { 'Content-Type': 'application/json', ...options.headers },
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) {
      const detail = Array.isArray(data.detail) ? 'Bitte überprüfe deine Eingabe.' : data.detail
      const error = new Error(detail || `Die Anfrage konnte nicht ausgeführt werden (${response.status}).`)
      error.status = response.status
      throw error
    }
    return data
  } catch (error) {
    if (error.name === 'AbortError')
      throw new Error('Die Anfrage dauert zu lange. Bitte Verbindung und Serverprotokoll prüfen.')
    if (error instanceof TypeError) throw new Error('Keine Verbindung zu Folio. Läuft der lokale Server?')
    throw error
  } finally {
    clearTimeout(timeout)
  }
}

export const post = (path, body) =>
  api(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
export const imageUrl = (path, full = false) =>
  `/api/${full ? 'preview' : 'thumb'}/${path.split('/').map(encodeURIComponent).join('/')}`

export function formatSize(bytes = 0) {
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let size = bytes / 1024
  let index = 0
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024
    index++
  }
  return `${size.toLocaleString('de-DE', { maximumFractionDigits: index === 0 ? 0 : 1 })} ${units[index]}`
}

export const albumTarget = (path) => (path === 'alben' ? '' : path.replace(/^alben\//, ''))

export function flattenAlbums(nodes, result = []) {
  for (const node of nodes) {
    result.push({ ...node, target: albumTarget(node.path) })
    flattenAlbums(node.children, result)
  }
  return result
}

import { realpath } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { basename, dirname } from 'node:path'

// Filesystem fixtures must NEVER run against the actual configured user library.
export async function requireTestLibrary(request) {
  const status = await (await request.get('/api/status')).json()
  const base = await realpath(status.base_path)
  const temporaryRoot = await realpath(tmpdir())
  if (
    !status.demo ||
    basename(base) !== 'library' ||
    dirname(dirname(base)) !== temporaryRoot ||
    !basename(dirname(base)).startsWith('folio-e2e-')
  ) {
    throw new Error('File-writing browser tests require the disposable scripts/serve_e2e.py library.')
  }
  return base
}

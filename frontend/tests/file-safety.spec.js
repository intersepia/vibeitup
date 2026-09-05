import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { createHash, randomUUID } from 'node:crypto'
import { mkdir, readFile, realpath, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { basename, dirname, join } from 'node:path'

const digest = (bytes) => createHash('sha256').update(bytes).digest('hex')
const urlPath = (path) => path.split('/').map(encodeURIComponent).join('/')

async function collisionFixture(request) {
  const status = await (await request.get('/api/status')).json()
  const base = await realpath(status.base_path)
  const temporaryRoot = await realpath(tmpdir())
  // Never write fixtures into a user's actual workspace, even if the wrong server is running.
  if (
    !status.demo ||
    basename(base) !== 'library' ||
    dirname(dirname(base)) !== temporaryRoot ||
    !basename(dirname(base)).startsWith('folio-e2e-')
  ) {
    throw new Error('File-safety tests require the disposable scripts/serve_e2e.py library.')
  }
  const images = (await (await request.get('/api/images?path=zur_sortieren&recursive=true')).json()).images
  const samples = await Promise.all(
    images.slice(0, 4).map(async (image) => (await request.get(`/api/image/${urlPath(image.path)}`)).body()),
  )
  expect(new Set(samples.map(digest)).size).toBe(4)
  const id = randomUUID().slice(0, 8)
  const sourceRoot = `zur_sortieren/Pruefquelle-${id}`
  const album = `Pruefalbum-${id}`
  const albumRoot = `alben/${album}`
  const sources = [`${sourceRoot}/A/gleich.jpg`, `${sourceRoot}/B/gleich.jpg`]
  const protectedPaths = [`${albumRoot}/gleich.jpg`, `${albumRoot}/gleich_001.jpg`]
  await mkdir(join(base, sourceRoot, 'A'), { recursive: true })
  await mkdir(join(base, sourceRoot, 'B'))
  await mkdir(join(base, albumRoot))
  for (const [index, path] of [...sources, ...protectedPaths].entries()) {
    await writeFile(join(base, path), samples[index], { flag: 'wx' })
  }
  expect((await request.post('/api/index')).ok()).toBeTruthy()

  return {
    base,
    sources,
    protectedPaths,
    album,
    albumRoot,
    samples,
    async cleanup() {
      // Restore any still-completed test transaction before discarding OUR sample folders.
      const latest = (await (await request.get('/api/logs')).json()).find(
        (entry) => entry.status === 'completed',
      )
      if (latest?.files.every((file) => file.source.startsWith(`${sourceRoot}/`))) {
        for (const item of latest.files) await rm(join(base, item.source), { force: true })
        await request.post('/api/action/undo')
      }
      await rm(join(base, sourceRoot), { recursive: true, force: true })
      await rm(join(base, albumRoot), { recursive: true, force: true })
      await request.post('/api/index')
    },
  }
}

async function moveFromBrowser(page, fixture) {
  await page.goto('/')
  await page.getByRole('searchbox').fill('gleich.jpg')
  await expect(page.locator('.image-card')).toHaveCount(2)
  await page.getByRole('checkbox', { name: 'Alle auswählen' }).click()
  const [response] = await Promise.all([
    page.waitForResponse(
      (response) => response.url().endsWith('/api/action/move') && response.request().method() === 'POST',
    ),
    page.locator('.album-target').filter({ hasText: fixture.album }).click(),
  ])
  expect(response.status()).toBe(200)
  await expect(page.locator('.image-card')).toHaveCount(0)
  return response.json()
}

async function assertProtectedFiles(fixture) {
  for (const [index, path] of fixture.protectedPaths.entries()) {
    expect(digest(await readFile(join(fixture.base, path)))).toBe(digest(fixture.samples[index + 2]))
  }
}

test('real equal-name batch in the UI preserves existing photos and undoes exact names after reload', async ({
  page,
  request,
}) => {
  const fixture = await collisionFixture(request)
  try {
    const result = await moveFromBrowser(page, fixture)
    expect(result.files.map((file) => file.destination)).toEqual([
      `${fixture.albumRoot}/gleich_002.jpg`,
      `${fixture.albumRoot}/gleich_003.jpg`,
    ])
    for (const [index, file] of result.files.entries()) {
      expect(file.source).toBe(fixture.sources[index])
      expect(digest(await readFile(join(fixture.base, file.destination)))).toBe(
        digest(fixture.samples[index]),
      )
    }
    await assertProtectedFiles(fixture)
    await page.reload()
    await expect(page.locator('.undo-button')).toBeEnabled()
    const [undoResponse] = await Promise.all([
      page.waitForResponse((response) => response.url().endsWith('/api/action/undo')),
      page.locator('.undo-button').click(),
    ])
    expect(undoResponse.status()).toBe(200)
    expect((await undoResponse.json()).id).toBe(result.id)
    for (const [index, source] of fixture.sources.entries()) {
      expect(digest(await readFile(join(fixture.base, source)))).toBe(digest(fixture.samples[index]))
      await expect(readFile(join(fixture.base, result.files[index].destination))).rejects.toMatchObject({
        code: 'ENOENT',
      })
    }
    await assertProtectedFiles(fixture)
    await page.getByRole('searchbox').fill('gleich.jpg')
    await expect(page.locator('.image-card')).toHaveCount(2)
  } finally {
    await fixture.cleanup()
  }
})

test('undo in the UI refuses an occupied original path without partially restoring a batch', async ({
  page,
  request,
}) => {
  const fixture = await collisionFixture(request)
  try {
    const result = await moveFromBrowser(page, fixture)
    // Simulate a new photo copied to the original location by another program.
    await writeFile(join(fixture.base, fixture.sources[0]), fixture.samples[3], { flag: 'wx' })
    const [failure] = await Promise.all([
      page.waitForResponse((response) => response.url().endsWith('/api/action/undo')),
      page.locator('.undo-button').click(),
    ])
    expect(failure.status()).toBe(409)
    await expect(page.getByRole('alert')).toContainText('Es wird nichts überschrieben')
    expect(digest(await readFile(join(fixture.base, fixture.sources[0])))).toBe(digest(fixture.samples[3]))
    await expect(readFile(join(fixture.base, fixture.sources[1]))).rejects.toMatchObject({ code: 'ENOENT' })
    for (const [index, item] of result.files.entries()) {
      expect(digest(await readFile(join(fixture.base, item.destination)))).toBe(
        digest(fixture.samples[index]),
      )
    }
    await assertProtectedFiles(fixture)
    // Remove only our simulated conflict, then retry the SAME transaction.
    await rm(join(fixture.base, fixture.sources[0]))
    const [success] = await Promise.all([
      page.waitForResponse((response) => response.url().endsWith('/api/action/undo')),
      page.locator('.undo-button').click(),
    ])
    expect(success.status()).toBe(200)
    expect((await success.json()).id).toBe(result.id)
    for (const [index, source] of fixture.sources.entries()) {
      expect(digest(await readFile(join(fixture.base, source)))).toBe(digest(fixture.samples[index]))
    }
  } finally {
    await fixture.cleanup()
  }
})

test('a separate index warning can be rechecked without repeating a move', async ({ page }) => {
  let warningActive = true
  let moves = 0
  page.on('request', (request) => {
    if (request.url().endsWith('/api/action/move')) moves++
  })
  await page.route('**/api/status', async (route) => {
    const response = await route.fetch()
    const data = await response.json()
    await route.fulfill({
      response,
      json: {
        ...data,
        index_warning: warningActive
          ? 'Index konnte nicht gespeichert werden. Abgeschlossene Aktionen bleiben gültig.'
          : null,
      },
    })
  })
  await page.route('**/api/index', async (route) => {
    const response = await route.fetch()
    warningActive = false
    await route.fulfill({ response })
  })
  await page.goto('/')
  await expect(page.locator('.index-warning')).toBeVisible()
  const check = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze()
  expect(check.violations).toEqual([])
  await page.locator('.index-warning').getByRole('button', { name: 'Neu einlesen' }).click()
  await expect(page.locator('.index-warning')).toHaveCount(0)
  expect(moves).toBe(0)
})

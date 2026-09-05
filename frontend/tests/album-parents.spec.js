import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { randomUUID, createHash } from 'node:crypto'
import { rm, stat } from 'node:fs/promises'
import { join } from 'node:path'
import { requireTestLibrary } from './helpers/library'

const parentSelect = (page) => page.getByLabel('Übergeordneter Ordner')
const createButton = (page) => page.getByRole('button', { name: 'Album erstellen', exact: true })
const preview = (page) => page.getByLabel('Relativer Album-Pfad')
const hash = (bytes) => createHash('sha256').update(bytes).digest('hex')
const encodedPath = (path) => path.split('/').map(encodeURIComponent).join('/')
const unique = () => `Dialog-${randomUUID().slice(0, 8)}`

async function open(page) {
  await page.getByRole('button', { name: 'Neues Album erstellen' }).click()
  await expect(parentSelect(page)).toBeEnabled()
}

async function makeParent(request, name, parent = 'Reisen') {
  const response = await request.post('/api/folders/albums', { data: { name, parent } })
  expect(response.status()).toBe(201)
  return parent ? `${parent}/${name}` : name
}

test('nested album creation and immediate move use the full returned path, not an existing root namesake', async ({
  page,
  request,
}) => {
  const base = await requireTestLibrary(request)
  const parent = await makeParent(request, unique())
  const source = (await (await request.get('/api/images?path=zur_sortieren&recursive=true')).json()).images[0]
  const original = hash(await (await request.get(`/api/image/${encodedPath(source.path)}`)).body())
  const rootBefore = (await (await request.get('/api/images?path=alben/Favoriten')).json()).images
  const previous = (await (await request.get('/api/logs')).json()).find(
    (entry) => entry.status === 'completed',
  )?.id
  try {
    await page.goto('/')
    await expect(page.locator('.image-card').first()).toContainText(source.name)
    await page.locator('.image-card').first().click()
    await open(page)
    await expect(parentSelect(page)).toHaveValue('')
    await page.getByLabel('Albumname').fill('Favoriten')
    await createButton(page).click()
    await expect(page.locator('.form-error')).toContainText('Im ausgewählten Ordner')
    await expect(page.getByLabel('Albumname')).toHaveValue('Favoriten')

    await parentSelect(page).selectOption(parent)
    await expect(preview(page)).toHaveText(`${parent}/Favoriten`)
    await expect(page.locator('.form-error')).toHaveCount(0)
    await page.getByRole('checkbox', { name: /direkt hierhin verschieben/ }).check()
    const [move] = await Promise.all([
      page.waitForResponse((response) => response.url().endsWith('/api/action/move')),
      createButton(page).click(),
    ])
    expect(move.status()).toBe(200)
    expect(move.request().postDataJSON().target_album).toBe(`${parent}/Favoriten`)
    const transaction = await move.json()
    const destination = transaction.files[0].destination
    expect(destination).toBe(`alben/${parent}/Favoriten/${source.name}`)
    expect(hash(await (await request.get(`/api/image/${encodedPath(destination)}`)).body())).toBe(original)
    const rootAfter = (await (await request.get('/api/images?path=alben/Favoriten')).json()).images
    expect(rootAfter).toEqual(rootBefore)
    await expect(page.locator('.album-target').filter({ hasText: `${parent}/Favoriten` })).toContainText(
      '1 Bild',
    )
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await page.reload()
    await expect(page.locator('.image-card')).toHaveCount(17)
    await page.locator('.undo-button').click()
    await expect(page.locator('.image-card')).toHaveCount(18)
    expect(hash(await (await request.get(`/api/image/${encodedPath(source.path)}`)).body())).toBe(original)
    expect((await stat(join(base, `alben/${parent}/Favoriten`))).isDirectory()).toBe(true)
  } finally {
    const latest = (await (await request.get('/api/logs')).json()).find(
      (entry) => entry.status === 'completed',
    )
    if (latest && latest.id !== previous && latest.files.every((file) => file.source === source.path)) {
      expect((await request.post('/api/action/undo')).ok()).toBeTruthy()
    }
    await rm(join(base, `alben/${parent}`), { recursive: true, force: true })
    await request.post('/api/index')
  }
})

test('parent list refresh finds externally added folders and creation without selection does not move images', async ({
  page,
  request,
}) => {
  const base = await requireTestLibrary(request)
  const parentName = unique()
  const parent = `Reisen/${parentName}`
  let moves = 0
  page.on('request', (request) => {
    if (request.url().endsWith('/api/action/move')) moves++
  })
  try {
    await page.goto('/')
    await expect(page.locator('.image-card')).toHaveCount(18)
    await open(page)
    await expect(page.getByRole('checkbox', { name: /direkt hierhin verschieben/ })).toHaveCount(0)
    await makeParent(request, parentName)
    await expect(parentSelect(page).locator('option').filter({ hasText: parentName })).toHaveCount(0)
    await page.getByRole('button', { name: 'Ordnerliste aktualisieren' }).click()
    await expect(parentSelect(page)).toBeEnabled()
    await parentSelect(page).selectOption(parent)
    await page.getByLabel('Albumname').fill('Sommer')
    await expect(preview(page)).toHaveText(`${parent}/Sommer`)
    await createButton(page).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(page.locator('.album-target').filter({ hasText: `${parent}/Sommer` })).toContainText(
      '0 Bilder',
    )
    await expect(page.locator('.image-card')).toHaveCount(18)
    expect(moves).toBe(0)
  } finally {
    await rm(join(base, `alben/${parent}`), { recursive: true, force: true })
    await request.post('/api/index')
  }
})

test('a removed parent never silently falls back to the root; choosing the root explicitly works', async ({
  page,
  request,
}) => {
  const base = await requireTestLibrary(request)
  const parent = await makeParent(request, unique())
  const leaf = unique()
  try {
    await page.goto('/')
    await expect(page.locator('.image-card')).toHaveCount(18)
    await open(page)
    await parentSelect(page).selectOption(parent)
    await page.getByLabel('Albumname').fill(leaf)
    await rm(join(base, `alben/${parent}`), { recursive: true })
    await createButton(page).click()
    await expect(page.locator('.form-error')).toBeVisible()
    await expect(parentSelect(page)).toHaveValue(parent)
    await expect(stat(join(base, 'alben', leaf))).rejects.toMatchObject({ code: 'ENOENT' })
    await page.getByRole('button', { name: 'Ordnerliste aktualisieren' }).click()
    await expect(parentSelect(page)).toBeEnabled()
    await expect(page.getByText(/Es wird nicht automatisch im Hauptordner gespeichert/)).toBeVisible()
    await expect(createButton(page)).toBeDisabled()
    await expect(parentSelect(page)).toHaveValue(parent)
    await parentSelect(page).selectOption('')
    await expect(preview(page)).toHaveText(leaf)
    await createButton(page).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    expect((await stat(join(base, 'alben', leaf))).isDirectory()).toBe(true)
  } finally {
    await rm(join(base, `alben/${parent}`), { recursive: true, force: true })
    await rm(join(base, 'alben', leaf), { recursive: true, force: true })
    await request.post('/api/index')
  }
})

test('a failed folder-list request blocks creation and can be retried without losing the name', async ({
  page,
}) => {
  await page.goto('/')
  await expect(page.locator('.image-card')).toHaveCount(18)
  let fail = true
  let creates = 0
  await page.route('**/api/folders/albums', (route) => {
    if (route.request().method() === 'POST') creates++
    if (fail && route.request().method() === 'GET') {
      return route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Test: Ordner momentan nicht verfügbar.' }),
      })
    }
    return route.continue()
  })
  await page.getByRole('button', { name: 'Neues Album erstellen' }).click()
  await page.getByLabel('Albumname').fill('Mein neues Album')
  await expect(page.locator('.form-error')).toContainText('Ordnerliste konnte nicht geladen werden')
  await expect(createButton(page)).toBeDisabled()
  fail = false
  await page.getByRole('button', { name: 'Ordnerliste aktualisieren' }).click()
  await expect(parentSelect(page)).toBeEnabled()
  await expect(page.locator('.form-error')).toHaveCount(0)
  await expect(page.getByLabel('Albumname')).toHaveValue('Mein neues Album')
  await expect(createButton(page)).toBeEnabled()
  await page.getByRole('button', { name: 'Abbrechen', exact: true }).click()
  expect(creates).toBe(0)
})

test('album location controls are keyboard-accessible and fit the phone dialog', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await expect(page.locator('.image-card')).toHaveCount(18)
  await open(page)
  await expect(page.getByLabel('Albumname')).toBeFocused()
  await page.getByLabel('Albumname').fill('Sommer in Portugal')
  await parentSelect(page).selectOption('Reisen')
  await expect(preview(page)).toHaveText('Reisen/Sommer in Portugal')
  await parentSelect(page).focus()
  await page.keyboard.press('Home')
  await expect(parentSelect(page)).toHaveValue('')
  await page.keyboard.press('ArrowDown')
  await expect(parentSelect(page)).toHaveValue('Alltagsmomente')
  await page.getByRole('button', { name: 'Dialog schließen' }).focus()
  await page.keyboard.press('Shift+Tab')
  await expect(createButton(page)).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: 'Dialog schließen' })).toBeFocused()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)
  const result = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze()
  expect(result.violations).toEqual([])
})

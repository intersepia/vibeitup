import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

const cards = (page) => page.locator('.image-card')
const undo = (page) => page.locator('.undo-button')
const closeDialog = (page) => page.getByRole('button', { name: 'Dialog schließen' })

test.beforeEach(async ({ page }) => {
  await page.goto('/')
  await expect(cards(page)).toHaveCount(18)
})

test('four-column gallery, local thumbnails and source tree', async ({ page }) => {
  await expect(page.getByRole('heading', { name: 'Zu sortieren' })).toBeVisible()
  await expect(page.locator('.duplicate-badge')).toHaveCount(2)
  await expect(page.locator('.album-target')).toHaveCount(5)
  const columns = await page
    .locator('.image-grid')
    .evaluate((el) => getComputedStyle(el).gridTemplateColumns.split(' ').length)
  expect(columns).toBe(4)
  expect(
    await page
      .locator('.image-visual img')
      .first()
      .evaluate((img) => img.complete && img.naturalWidth > 0),
  ).toBe(true)
  await page.getByRole('button', { name: /Portugal 2025/ }).click()
  await expect(cards(page)).toHaveCount(7)
  await page
    .getByRole('button', { name: /Herbst/ })
    .last()
    .click()
  await expect(cards(page)).toHaveCount(2)
})

test('click, shift-click, ctrl-click, select all and escape', async ({ page }) => {
  await cards(page).nth(0).click()
  await cards(page)
    .nth(2)
    .click({ modifiers: ['Shift'] })
  await expect(page.locator('.image-card.selected')).toHaveCount(3)
  await cards(page)
    .nth(4)
    .click({ modifiers: ['Control'] })
  await expect(page.locator('.image-card.selected')).toHaveCount(4)
  await page.keyboard.press('Control+a')
  await expect(page.locator('.image-card.selected')).toHaveCount(18)
  await page.keyboard.press('Escape')
  await expect(page.locator('.image-card.selected')).toHaveCount(0)
})

test('move a batch into an album and undo after reload', async ({ page }) => {
  await cards(page).nth(0).click()
  await cards(page)
    .nth(2)
    .click({ modifiers: ['Shift'] })
  await page.locator('.album-target').filter({ hasText: 'Reisen' }).click()
  await expect(cards(page)).toHaveCount(15)
  await expect(undo(page)).toBeEnabled()
  await page.reload()
  await expect(cards(page)).toHaveCount(15)
  await undo(page).click()
  await expect(cards(page)).toHaveCount(18)
  await page.getByRole('button', { name: 'Protokoll öffnen' }).click()
  await expect(page.locator('.history-status').first()).toHaveText('Rückgängig gemacht')
  const latestEntry = page.locator('.history-entry').first()
  await latestEntry.locator('summary').click()
  await expect(latestEntry.locator('.history-file')).toHaveCount(3)
})

test('trash is a reversible move, with confirmation', async ({ page }) => {
  await cards(page).nth(0).click()
  await page.getByRole('button', { name: /In den Papierkorb/ }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.getByRole('dialog').getByRole('button', { name: 'In den Papierkorb' }).click()
  await expect(cards(page)).toHaveCount(17)
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page
    .locator('.filing-navigation')
    .getByRole('button', { name: /Papierkorb/ })
    .click()
  await expect(cards(page)).toHaveCount(1)
  await undo(page).click()
  await expect(cards(page)).toHaveCount(0)
  await page.getByRole('button', { name: 'Zum Eingang', exact: true }).click()
  await expect(cards(page)).toHaveCount(18)
})

test('exact duplicates can be reviewed, filed and restored', async ({ page }) => {
  await page.getByRole('tab', { name: /Duplikate/ }).click()
  await expect(cards(page)).toHaveCount(2)
  await page.getByRole('checkbox', { name: 'Alle auswählen' }).click()
  await page.getByRole('button', { name: 'In Duplikate ablegen' }).click()
  await expect(cards(page)).toHaveCount(0)
  await page
    .locator('.filing-navigation')
    .getByRole('button', { name: /Duplikate/ })
    .click()
  await expect(cards(page)).toHaveCount(2)
  await undo(page).click()
  await expect(cards(page)).toHaveCount(0)
})

test('new album validates input and can receive the selection immediately', async ({ page }) => {
  await cards(page).nth(0).click()
  await page.getByRole('button', { name: 'Neues Album erstellen' }).click()
  await page.getByLabel('Albumname').fill('../outside')
  await page.getByRole('button', { name: 'Album erstellen', exact: true }).click()
  await expect(page.locator('.form-error')).toBeVisible()
  await page.getByLabel('Albumname').fill('Browser-Test')
  await page.getByRole('checkbox', { name: /direkt hierhin verschieben/ }).check()
  await page.getByRole('button', { name: 'Album erstellen', exact: true }).click()
  await expect(cards(page)).toHaveCount(17)
  await expect(page.locator('.album-target').filter({ hasText: 'Browser-Test' })).toContainText('1 Bild')
  await undo(page).click()
  await expect(cards(page)).toHaveCount(18)
})

test('search, list view and full-size preview work', async ({ page }) => {
  await page.getByRole('searchbox').fill('waldspaziergang')
  await expect(cards(page)).toHaveCount(1)
  await page.getByRole('button', { name: 'Listenansicht' }).click()
  await expect(page.locator('.image-grid')).toHaveClass(/list-layout/)
  await page.getByRole('button', { name: /waldspaziergang.jpg vergrößern/ }).click()
  await expect(page.locator('.lightbox img')).toBeVisible()
  await expect(page.getByRole('dialog')).toContainText('SHA-1')
  await closeDialog(page).click()
  await page.getByRole('searchbox').fill('nothing-matches-this-name')
  await expect(page.getByRole('heading', { name: 'Noch kein Treffer.' })).toBeVisible()
  await page.getByRole('button', { name: 'Alle Bilder anzeigen' }).click()
  await expect(cards(page)).toHaveCount(18)
  await page.getByLabel('Bilder sortieren').selectOption('size')
  await page.getByRole('button', { name: 'Absteigend sortieren' }).click()
  await page.getByRole('button', { name: 'Rasteransicht' }).click()
})

test('an API conflict keeps images and selection intact', async ({ page }) => {
  await page.route('**/api/action/move', (route) =>
    route.fulfill({
      status: 409,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Test: Eine Datei wurde geändert.' }),
    }),
  )
  await cards(page).nth(0).click()
  await page.locator('.album-target').filter({ hasText: 'Reisen' }).click()
  await expect(page.getByRole('alert')).toContainText('Eine Datei wurde geändert')
  await expect(cards(page)).toHaveCount(18)
  await expect(page.locator('.image-card.selected')).toHaveCount(1)
})

test('phone layout, navigation and selection have no horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)
  await page.getByRole('button', { name: 'Quell-Navigation öffnen' }).click()
  await page.getByRole('button', { name: /Portugal 2025/ }).click()
  await expect(cards(page)).toHaveCount(7)
  await cards(page).nth(0).click()
  await expect(page.locator('.selection-bar')).toBeVisible()
  await page.locator('.album-target').filter({ hasText: 'Reisen' }).click()
  await expect(cards(page)).toHaveCount(6)
  await undo(page).click()
  await expect(cards(page)).toHaveCount(7)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)
})

test('gallery and dialogs pass automated accessibility checks', async ({ page }) => {
  const scan = async () => {
    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze()
    expect(results.violations).toEqual([])
  }
  await scan()
  await cards(page).first().click()
  await scan()
  await page.getByRole('button', { name: 'Neues Album erstellen' }).click()
  await expect(page.getByLabel('Übergeordneter Ordner')).toBeEnabled()
  await scan()
  await closeDialog(page).click()
  await page.getByRole('button', { name: 'Bibliothek und Einstellungen' }).click()
  await scan()
  await closeDialog(page).click()
  await page.getByRole('button', { name: /Tastenkürzel/ }).click()
  await scan()
})

test('large galleries render in chunks while search covers every image', async ({ page }) => {
  const original = (await (await page.request.get('/api/images')).json()).images[0]
  const photo = await (await page.request.get(`/api/thumb/${original.path}`)).body()
  const generated = Array.from({ length: 110 }, (_, index) => ({
    ...original,
    path: `zur_sortieren/generated/photo_${String(index).padStart(3, '0')}.jpg`,
    name: `photo_${String(index).padStart(3, '0')}.jpg`,
    is_duplicate: false,
    duplicate_of: [],
  }))
  await page.route('**/api/images?**', (route) =>
    route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        path: 'zur_sortieren',
        images: generated,
        total: 110,
        total_size: original.size * 110,
      }),
    }),
  )
  await page.route('**/api/thumb/**', (route) => route.fulfill({ contentType: 'image/jpeg', body: photo }))
  await page.reload()
  await expect(cards(page)).toHaveCount(80)
  await page.getByRole('button', { name: 'Weitere 30 Bilder anzeigen' }).click()
  await expect(cards(page)).toHaveCount(110)
  await page.getByRole('searchbox').fill('photo_109')
  await expect(cards(page)).toHaveCount(1)
  await expect(cards(page).first()).toContainText('photo_109.jpg')
})

import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

const cards = (page) => page.locator('.image-card')
const actions = (page) => page.getByRole('group', { name: 'Bibliotheksaktionen', exact: true })
const navigation = (page) => page.getByRole('dialog', { name: 'Quell-Navigation', exact: true })
const menu = (page) => page.getByRole('button', { name: 'Quell-Navigation öffnen', exact: true })
const settle = (page) =>
  page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))

async function moveFirst(page) {
  await cards(page).first().click()
  const [response] = await Promise.all([
    page.waitForResponse((response) => response.url().endsWith('/api/action/move')),
    page.locator('.album-target').filter({ hasText: 'Reisen' }).click(),
  ])
  expect(response.status()).toBe(200)
  await expect(cards(page)).toHaveCount(17)
  return (await response.json()).id
}
async function restoreIfNeeded(request, id) {
  if (!id) return
  const logs = await (await request.get('/api/logs')).json()
  if (logs.find((entry) => entry.status === 'completed')?.id === id) {
    expect((await request.post('/api/action/undo')).ok()).toBeTruthy()
  }
}

test('no top header, logo above navigation, and working undo/settings above the album targets', async ({
  page,
  request,
}) => {
  let transaction
  try {
    await page.goto('/')
    await expect(cards(page)).toHaveCount(18)
    await expect(page.locator('.app-header')).toHaveCount(0)
    const positions = await page.evaluate(() => ({
      mainTop: document.querySelector('main').getBoundingClientRect().top,
      logoBottom: document.querySelector('.sidebar-brand').getBoundingClientRect().bottom,
      libraryTop: document.querySelector('.source-sidebar .sidebar-section-title').getBoundingClientRect()
        .top,
      actionsBottom: document.querySelector('.album-workspace-actions').getBoundingClientRect().bottom,
      albumsTop: document.querySelector('.action-panel .section-label').getBoundingClientRect().top,
      firstImageTop: document.querySelector('.image-card').getBoundingClientRect().top,
    }))
    expect(positions.mainTop).toBe(0)
    expect(positions.logoBottom).toBeLessThanOrEqual(positions.libraryTop)
    expect(positions.actionsBottom).toBeLessThan(positions.albumsTop)
    expect(positions.firstImageTop).toBeLessThan(110)
    await expect(page.locator('.undo-button')).toHaveCount(1)
    await expect(actions(page).locator('.undo-button')).toBeDisabled()
    await page.getByRole('button', { name: /Alle Alben/ }).click()
    await page.getByRole('button', { name: 'Folio – zurück zum Eingang', exact: true }).click()
    await expect(cards(page)).toHaveCount(18)

    transaction = await moveFirst(page)
    await expect(actions(page).locator('.undo-button')).toBeEnabled()
    const audit = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze()
    expect(audit.violations).toEqual([])
    await actions(page).getByRole('button', { name: 'Bibliothek und Einstellungen' }).click()
    await expect(page.getByRole('dialog', { name: 'Dein Workspace. Auf deinem Gerät.' })).toBeVisible()
    await page.getByRole('button', { name: 'Dialog schließen' }).click()
    await actions(page).locator('.undo-button').click()
    await expect(cards(page)).toHaveCount(18)

    transaction = await moveFirst(page)
    await page.keyboard.press('Control+z')
    await expect(cards(page)).toHaveCount(18)
    await expect(actions(page).locator('.undo-button')).toBeDisabled()
  } finally {
    await restoreIfNeeded(request, transaction)
  }
})

test('phone navigation opens from the toolbar, traps focus, closes with Escape and preserves selection', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await expect(cards(page)).toHaveCount(18)
  await cards(page).first().click()
  await menu(page).click()
  await expect(navigation(page)).toBeVisible()
  expect((await navigation(page).boundingBox()).y).toBe(0)
  await expect(page.getByRole('button', { name: 'Quell-Navigation schließen', exact: true })).toBeFocused()
  expect(await page.locator('.gallery-panel').evaluate((el) => el.inert)).toBe(true)
  expect(await page.evaluate(() => document.body.style.overflow)).toBe('hidden')
  const audit = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze()
  expect(audit.violations).toEqual([])
  await navigation(page).getByRole('button', { name: 'Folio – zurück zum Eingang', exact: true }).focus()
  await page.keyboard.press('Shift+Tab')
  await expect(navigation(page).getByRole('button', { name: 'Speicherort anzeigen' })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(
    navigation(page).getByRole('button', { name: 'Folio – zurück zum Eingang', exact: true }),
  ).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(navigation(page)).toHaveCount(0)
  await expect(menu(page)).toBeFocused()
  await expect(page.locator('.image-card.selected')).toHaveCount(1)
  expect(await page.locator('.gallery-panel').evaluate((el) => el.inert)).toBe(false)
  expect(await page.evaluate(() => document.body.style.overflow)).toBe('')

  await menu(page).click()
  await navigation(page).getByRole('button', { name: 'Speicherort anzeigen' }).click()
  await expect(navigation(page)).toHaveCount(0)
  await expect(page.getByRole('dialog', { name: 'Dein Workspace. Auf deinem Gerät.' })).toBeVisible()
  expect(await page.evaluate(() => document.body.style.overflow)).toBe('hidden')
  await page.getByRole('button', { name: 'Dialog schließen' }).click()
  await expect(menu(page)).toBeFocused()
  expect(await page.evaluate(() => document.body.style.overflow)).toBe('')
})

test('phone album-action shortcut reaches settings and relocated undo without a top bar', async ({
  page,
  request,
}) => {
  let transaction
  try {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto('/')
    await expect(cards(page)).toHaveCount(18)
    const jump = page.getByRole('button', { name: 'Zu Alben und Aktionen', exact: true })
    await expect(jump).toBeInViewport()
    await jump.click()
    const settings = actions(page).getByRole('button', { name: 'Bibliothek und Einstellungen' })
    await expect(settings).toBeInViewport()
    await settings.click()
    await expect(page.getByRole('dialog', { name: 'Dein Workspace. Auf deinem Gerät.' })).toBeVisible()
    await page.getByRole('button', { name: 'Dialog schließen' }).click()
    await expect(settings).toBeFocused()
    await page.getByRole('button', { name: 'Zur Galerie', exact: true }).click()
    await expect(cards(page).first()).toBeInViewport()
    transaction = await moveFirst(page)
    await actions(page).locator('.undo-button').click()
    await expect(cards(page)).toHaveCount(18)
    await page.getByRole('button', { name: 'Zur Galerie', exact: true }).click()
    await expect(cards(page).first()).toBeInViewport()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)
  } finally {
    await restoreIfNeeded(request, transaction)
  }
})

test('resizing an open drawer restores desktop navigation and never leaves the workspace inert', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await expect(cards(page)).toHaveCount(18)
  await menu(page).click()
  await expect(navigation(page)).toBeVisible()
  await page.setViewportSize({ width: 1440, height: 960 })
  await settle(page)
  await expect(navigation(page)).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Folio – zurück zum Eingang', exact: true })).toBeVisible()
  expect(await page.locator('.gallery-panel').evaluate((el) => el.inert)).toBe(false)
  expect(await page.locator('.source-sidebar').evaluate((el) => el.inert)).toBe(false)
  expect(await page.evaluate(() => document.body.style.overflow)).toBe('')
  await page.setViewportSize({ width: 390, height: 844 })
  await settle(page)
  await expect(page.locator('.source-sidebar')).toBeHidden()
  expect(await page.locator('.source-sidebar').evaluate((el) => el.inert)).toBe(true)
  await expect(menu(page)).toHaveAttribute('aria-expanded', 'false')
  await menu(page).click()
  await page.getByRole('button', { name: 'Quell-Navigation schließen', exact: true }).click()
  await expect(menu(page)).toBeFocused()
})

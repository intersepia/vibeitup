import { test, expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { rm } from 'node:fs/promises'
import { join } from 'node:path'
import { requireTestLibrary } from './helpers/library'

test('All Albums counts images, not folders, including nested moves and undo', async ({ page, request }) => {
  const base = await requireTestLibrary(request)
  const name = `Count-${randomUUID().slice(0, 8)}`
  const target = `${name}/Unteralbum`
  let transaction
  try {
    expect((await request.post('/api/folders/albums', { data: { name } })).status()).toBe(201)
    expect(
      (await request.post('/api/folders/albums', { data: { name: 'Unteralbum', parent: name } })).status(),
    ).toBe(201)
    await page.goto('/')
    await expect(page.locator('.image-card')).toHaveCount(18)
    const navigation = page.locator('.main-navigation').getByRole('button', { name: /Alle Alben/ })
    const count = navigation.locator('.plain-count')
    // Seven folders, but only the five original album images: empty folders must not raise the badge.
    await expect(page.locator('.album-target')).toHaveCount(7)
    await expect(count).toHaveText('5')
    await page.locator('.image-card').first().click()
    await page
      .locator('.image-card')
      .nth(2)
      .click({ modifiers: ['Shift'] })
    const [moved] = await Promise.all([
      page.waitForResponse((response) => response.url().endsWith('/api/action/move')),
      page.locator('.album-target').filter({ hasText: target }).click(),
    ])
    expect(moved.status()).toBe(200)
    transaction = (await moved.json()).id
    // Nested images count once, not once for the parent and again for the child.
    await expect(count).toHaveText('8')
    await navigation.click()
    await expect(page.locator('.image-card')).toHaveCount(8)
    await expect(page.getByRole('tab', { name: /Alle Bilder/ })).toContainText('8')
    await page.locator('.undo-button').click()
    await expect(count).toHaveText('5')
    await expect(page.locator('.image-card')).toHaveCount(5)
    await expect(page.locator('.album-target')).toHaveCount(7)
  } finally {
    const latest = (await (await request.get('/api/logs')).json()).find(
      (entry) => entry.status === 'completed',
    )
    if (transaction && latest?.id === transaction) {
      expect((await request.post('/api/action/undo')).ok()).toBeTruthy()
    }
    await rm(join(base, 'alben', name), { recursive: true, force: true })
    await request.post('/api/index')
  }
})

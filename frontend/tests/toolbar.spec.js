import { test, expect } from '@playwright/test'

const toolbar = (page) => page.getByRole('group', { name: 'Galerie-Werkzeugleiste', exact: true })
const settleLayout = (page) =>
  page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))

test('title, filters, search and view controls share one compact toolbar in every collection', async ({
  page,
}) => {
  await page.goto('/')
  await expect(page.locator('.image-card')).toHaveCount(18)
  const bar = toolbar(page)
  const check = async (title) => {
    await expect(bar.getByRole('heading', { name: title, exact: true, level: 1 })).toBeVisible()
    await expect(bar.getByRole('tab', { name: /Alle Bilder/ })).toBeVisible()
    await expect(bar.getByRole('searchbox', { name: 'Bilder suchen' })).toBeVisible()
    await expect(bar.getByRole('button', { name: 'Rasteransicht' })).toBeVisible()
    await expect(bar.getByRole('button', { name: 'Listenansicht' })).toBeVisible()
    await expect(page.locator('.gallery-overline, .gallery-description')).toHaveCount(0)
    await expect(
      page.getByText('Aus vielen Bildern werden gut sortierte Erinnerungen.', { exact: true }),
    ).toHaveCount(0)
    await expect(page.getByText('EIN GUTER PLATZ FÜR JEDES BILD', { exact: true })).toHaveCount(0)
  }
  await check('Zu sortieren')
  await page.getByRole('button', { name: /Alle Alben/ }).click()
  await check('Deine Alben')
  await bar.getByRole('button', { name: 'Listenansicht' }).click()
  await expect(bar.getByRole('button', { name: 'Listenansicht' })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('.image-grid')).toHaveClass(/list-layout/)
  await bar.getByRole('button', { name: 'Rasteransicht' }).click()
  await page
    .locator('.filing-navigation')
    .getByRole('button', { name: /Duplikate/ })
    .click()
  await check('Duplikate')
  await page
    .locator('.filing-navigation')
    .getByRole('button', { name: /Papierkorb/ })
    .click()
  await check('Papierkorb')
})

test('compact toolbar fits desktop, tablet and phone widths without hidden or overlapping controls', async ({
  page,
}) => {
  await page.goto('/')
  await expect(page.locator('.image-card')).toHaveCount(18)
  for (const width of [1920, 1440, 1280, 1100, 1024, 840, 768, 690, 430, 390, 360, 320]) {
    await page.setViewportSize({ width, height: 960 })
    await settleLayout(page)
    const geometry = await page.evaluate(() => {
      const rect = (selector) => {
        const r = document.querySelector(selector).getBoundingClientRect()
        return {
          left: r.left,
          right: r.right,
          top: r.top,
          bottom: r.bottom,
          width: r.width,
          height: r.height,
        }
      }
      return {
        pageWidth: document.documentElement.scrollWidth,
        panel: rect('.gallery-panel'),
        header: rect('.gallery-top'),
        bar: rect('.filter-toolbar'),
        items: ['.gallery-title', '.gallery-tabs', '.search-field', '.gallery-view-switch'].map(rect),
      }
    })
    expect(geometry.pageWidth, `Page overflow at ${width}px`).toBe(width)
    const headerLimit = geometry.panel.width > 650 ? 112 : geometry.panel.width > 380 ? 150 : 186
    expect(geometry.header.height, `Header too tall at ${width}px`).toBeLessThanOrEqual(headerLimit)
    expect(geometry.items[2].width, `Search too narrow at ${width}px`).toBeGreaterThanOrEqual(112)
    for (const item of geometry.items) {
      expect(item.left).toBeGreaterThanOrEqual(geometry.bar.left - 1)
      expect(item.right).toBeLessThanOrEqual(geometry.bar.right + 1)
      expect(item.bottom).toBeLessThanOrEqual(geometry.bar.bottom + 1)
    }
    for (let a = 0; a < geometry.items.length; a++) {
      for (let b = a + 1; b < geometry.items.length; b++) {
        const first = geometry.items[a]
        const second = geometry.items[b]
        const overlapX = Math.min(first.right, second.right) - Math.max(first.left, second.left)
        const overlapY = Math.min(first.bottom, second.bottom) - Math.max(first.top, second.top)
        expect(overlapX > 1 && overlapY > 1, `Controls overlap at ${width}px`).toBe(false)
      }
    }
    if (geometry.panel.width > 650) {
      const centers = geometry.items.map((item) => item.top + item.height / 2)
      expect(Math.max(...centers) - Math.min(...centers)).toBeLessThan(2)
    }
  }
})

test('long folder headings truncate visually without displacing the search or view buttons', async ({
  page,
  request,
}) => {
  const name = 'Erinnerungen an unseren langen Sommerurlaub mit Familie und Freunden '.repeat(2).trim()
  const path = `zur_sortieren/${name}`
  const listing = await (await request.get('/api/images?path=zur_sortieren&recursive=true')).json()
  await page.route('**/api/folders/source', async (route) => {
    const response = await route.fetch()
    const source = await response.json()
    await route.fulfill({
      response,
      json: {
        ...source,
        children: [...source.children, { name, path, count: 18, direct_count: 18, children: [] }],
      },
    })
  })
  await page.route('**/api/images?**', (route) => {
    if (new URL(route.request().url()).searchParams.get('path') === path) {
      return route.fulfill({ json: { ...listing, path } })
    }
    return route.continue()
  })
  await page.goto('/')
  await expect(page.locator('.image-card')).toHaveCount(18)
  await page.locator('.tree-link').filter({ hasText: name }).click()
  await expect(toolbar(page).getByRole('heading', { level: 1 })).toHaveText(name)
  await expect(toolbar(page).getByRole('heading', { level: 1 })).toHaveAttribute('title', name)
  for (const width of [1440, 1024, 390, 320]) {
    await page.setViewportSize({ width, height: 960 })
    await settleLayout(page)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width)
    await expect(toolbar(page).getByRole('searchbox')).toBeVisible()
    await expect(toolbar(page).getByRole('button', { name: 'Listenansicht' })).toBeVisible()
    expect(await page.locator('.gallery-title').evaluate((el) => getComputedStyle(el).textOverflow)).toBe(
      'ellipsis',
    )
  }
})

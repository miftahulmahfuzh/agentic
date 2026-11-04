// Fault injection: the home page with the public CDNs unreachable (run started with `up --offline`;
// a reader behind a firewall that blocks cdnjs / Google Fonts sees the same). Mermaid and the
// webfonts fail to load; everything that does not draw a diagram must keep working: popups open
// AND close (Close button, Escape, backdrop), disclosures toggle, the rail answers hover, and a
// masthead link auto-expands its section. Each check is logged; the drive fails if any is broken.
export default async ({ page, base, shot, log, allow }) => {
  allow(/Failed to load resource/)
  allow(/cdn-offline/)
  allow(/mermaid is not defined/)
  await page.goto(base, { waitUntil: 'load' })
  const results = {}
  const check = async (name, fn) => {
    try { await fn(); results[name] = 'ok' } catch (e) { results[name] = `BROKEN: ${e.message.split('\n')[0]}` }
    log(`${name}: ${results[name]}`)
  }
  results.mermaid = await page.evaluate(() => typeof window.mermaid)
  log(`typeof mermaid: ${results.mermaid}`)

  const modal = page.locator('#popup-modal')
  const open = async () => {
    await page.locator(`button.popup-trigger[onclick="showPopup('cache-fastlane')"]`).click()
    await modal.waitFor({ state: 'visible', timeout: 3000 })
  }
  await check('popup opens', open)
  await shot('popup-open-offline')
  await check('popup closes by Close button', async () => {
    await page.getByRole('button', { name: 'Close' }).click({ timeout: 3000 })
    await modal.waitFor({ state: 'hidden', timeout: 2000 })
  })
  await check('popup closes by Escape', async () => {
    await open()
    await page.keyboard.press('Escape')
    await modal.waitFor({ state: 'hidden', timeout: 2000 })
  })
  await check('popup closes by backdrop click', async () => {
    if (await modal.isVisible()) await page.getByRole('button', { name: 'Close' }).click({ timeout: 3000 })
    await open()
    await page.mouse.click(5, 450)
    await modal.waitFor({ state: 'hidden', timeout: 2000 })
  })
  if (await modal.isVisible()) await page.getByRole('button', { name: 'Close' }).click({ timeout: 3000 })
  await check('disclosure toggles', async () => {
    const head = page.locator('.disclosure__head').first()
    await head.click()
    if ((await head.getAttribute('aria-expanded')) !== 'true') throw new Error('aria-expanded stayed false')
    await head.click()
  })
  await check('rail answers hover', async () => {
    const node = page.locator('.rail__node').first()
    await node.hover()
    if (!(await node.evaluate((n) => n.classList.contains('rail__node--hot')))) throw new Error('node not hot after hover')
  })
  await check('masthead link auto-expands #tools', async () => {
    await page.goto(base, { waitUntil: 'load' })
    await page.getByRole('navigation', { name: 'Primary' }).getByRole('link', { name: 'Tools', exact: true }).click()
    await page.waitForTimeout(800)
    const v = await page.locator('#tools .disclosure__head').getAttribute('aria-expanded')
    if (v !== 'true') throw new Error(`aria-expanded=${v}`)
  })
  const broken = Object.entries(results).filter(([, v]) => String(v).startsWith('BROKEN'))
  if (broken.length) throw new Error(`${broken.length} behaviour(s) broken without the CDN: ${broken.map(([k]) => k).join(', ')}`)
}

// The home page's navigation: masthead anchors (and the auto-expand of a collapsed section they
// land on), every disclosure toggling open and shut, the request-lifecycle rail's hover notes,
// and the masthead's Docs link reaching the docs list.
export default async ({ page, base, shot, log }) => {
  await page.goto(base, { waitUntil: 'networkidle' })
  const nav = page.getByRole('navigation', { name: 'Primary' })

  // Masthead anchors: Tools and API land on a collapsed disclosure, which the click expands.
  for (const [name, id] of [['Architecture', 'architecture'], ['Agents', 'agents'], ['Screener', 'screener'], ['Tools', 'tools'], ['API', 'api']]) {
    await nav.getByRole('link', { name, exact: true }).click()
    await page.waitForFunction((h) => location.hash === h, `#${id}`)
    // style.css sets scroll-behavior: smooth, so wait for the scroll to land, not for the hash.
    await page.waitForFunction((sid) => {
      const t = Math.round(document.getElementById(sid).getBoundingClientRect().top)
      const settled = window.__lastTop === t
      window.__lastTop = t
      return settled && t >= -5 && t < innerHeight / 2
    }, id, { polling: 150, timeout: 5000 }).catch(() => {})
    const st = await page.evaluate((sid) => {
      const s = document.getElementById(sid)
      const r = s.getBoundingClientRect()
      const head = s.querySelector('.disclosure__head')
      return { top: Math.round(r.top), inView: r.top < innerHeight && r.bottom > 0, expanded: head ? head.getAttribute('aria-expanded') : null }
    }, id)
    log(`masthead ${name} -> #${id}: ${JSON.stringify(st)}`)
    if (!st.inView) throw new Error(`#${id} not scrolled into view`)
    if (st.expanded !== null && st.expanded !== 'true') throw new Error(`#${id} disclosure not auto-expanded`)
  }
  await shot('api-expanded')

  // Every disclosure: closed by default on a fresh load, opens on click, shuts on a second click.
  await page.goto(base, { waitUntil: 'networkidle' })
  const heads = page.locator('.disclosure__head')
  const count = await heads.count()
  for (let i = 0; i < count; i++) {
    const head = heads.nth(i)
    const title = (await head.locator('.disclosure__title').textContent()).trim()
    const body = head.locator('xpath=following-sibling::div[contains(@class,"disclosure__body")]')
    if ((await head.getAttribute('aria-expanded')) !== 'false') throw new Error(`"${title}" starts expanded`)
    await head.scrollIntoViewIfNeeded()
    await head.click()
    await page.waitForTimeout(400)
    const open = { aria: await head.getAttribute('aria-expanded'), cls: await body.getAttribute('class'), h: (await body.boundingBox())?.height ?? 0 }
    await head.click()
    await page.waitForTimeout(400)
    const shut = { aria: await head.getAttribute('aria-expanded'), h: (await body.boundingBox())?.height ?? 0 }
    log(`disclosure "${title}": open ${JSON.stringify(open)} shut ${JSON.stringify(shut)}`)
    if (open.aria !== 'true' || !open.cls.includes('expanded') || open.h < 50) throw new Error(`"${title}" did not open`)
    if (shut.aria !== 'false' || shut.h > 5) throw new Error(`"${title}" did not shut`)
  }
  log(`disclosures: ${count} toggled`)

  // Request-lifecycle rail: hovering a node makes it hot and swaps the note to its data-note.
  await page.evaluate(() => scrollTo(0, 0))
  const nodes = page.locator('.rail__node')
  const nn = await nodes.count()
  for (let i = 0; i < nn; i++) {
    await nodes.nth(i).hover()
    const st = await page.evaluate((k) => {
      const n = document.querySelectorAll('.rail__node')[k]
      return { hot: n.classList.contains('rail__node--hot'), match: document.querySelector('.rail__note').innerHTML === n.dataset.note, label: n.textContent.trim().replace(/\s+/g, ' ').slice(0, 40) }
    }, i)
    log(`rail node ${i} "${st.label}": hot=${st.hot} note-matches=${st.match}`)
    if (!st.hot || !st.match) throw new Error(`rail node ${i} did not activate`)
  }

  // Docs link: a relative href, so it must resolve under /agentic/.
  await nav.getByRole('link', { name: /Docs/ }).click()
  await page.waitForURL(/\/agentic\/docs\/$/)
  await page.waitForLoadState('networkidle')
  log(`docs link -> ${new URL(page.url()).pathname} "${await page.title()}"`)
  await shot('docs-list')
}

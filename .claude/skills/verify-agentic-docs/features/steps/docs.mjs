// Read the theme-rendered documentation: every article listed in the run's sitemap (or only the
// paths in args, relative to the site root, e.g. docs/architectures/circuit_breaker/), plus every
// section list page. Each article must render a title and body text, and turn every ```mermaid
// block into an <svg> (head/custom.html swaps them in). On the first article with a diagram,
// flipping the colour scheme must redraw it in the other palette.
// The TOC count is logged, not asserted: params.widgets.page is empty, so Stack renders none.
export default async ({ page, base, shot, log, args }) => {
  let paths = args
  if (!paths.length) {
    const res = await page.request.get(`${base}sitemap.xml`)
    const xml = await res.text()
    paths = [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => new URL(m[1]).pathname.replace('/agentic/', ''))
      .filter((p) => /^docs\//.test(p)).sort()
  }
  log(`pages: ${paths.length}`)
  let flipped = false
  for (const p of paths) {
    await page.goto(base + p, { waitUntil: 'networkidle' })
    const isArticle = (await page.locator('article.main-article').count()) > 0
    if (!isArticle) {
      const items = await page.locator('article').count()
      const title = (await page.locator('.section-term').first().textContent().catch(() => ''))?.trim()
      log(`list ${p}: "${title}" ${items} entries`)
      if (items < 1) throw new Error(`list ${p} has no entries`)
      continue
    }
    const blocks = await page.locator('.mermaid').count()
    if (blocks) {
      await page.waitForFunction(() => [...document.querySelectorAll('.mermaid')].every((m) => m.querySelector('svg')),
        null, { timeout: 20000 })
    }
    const s = await page.evaluate(() => ({
      title: document.querySelector('.article-title')?.textContent.trim() ?? '',
      text: document.querySelector('.article-content')?.textContent.trim().length ?? 0,
      headings: document.querySelectorAll('.article-content h2, .article-content h3').length,
      toc: document.querySelectorAll('#TableOfContents a').length,
      leftover: document.querySelectorAll('code.language-mermaid').length,
      syntaxError: [...document.querySelectorAll('.mermaid')].some((m) => /Syntax error/i.test(m.textContent)),
    }))
    log(`article ${p}: "${s.title}" ${s.text} chars, ${s.headings} headings, toc ${s.toc}, ${blocks} diagram(s)`)
    if (!s.title) throw new Error(`${p}: no article title`)
    if (s.text < 200) throw new Error(`${p}: only ${s.text} chars of body`)
    if (s.leftover) throw new Error(`${p}: ${s.leftover} mermaid block(s) left as code`)
    if (s.syntaxError) throw new Error(`${p}: a mermaid diagram failed to parse`)
    if (blocks && !flipped) {
      const fill = () => page.evaluate(() => getComputedStyle(document.querySelector('.mermaid svg .node rect, .mermaid svg rect')).fill)
      const before = { scheme: await page.evaluate(() => document.documentElement.dataset.scheme), fill: await fill() }
      await page.locator('#dark-mode-toggle').click()
      await page.waitForFunction((f) => {
        const r = document.querySelector('.mermaid svg .node rect, .mermaid svg rect')
        return r && getComputedStyle(r).fill !== f
      }, before.fill, { timeout: 10000 })
      const after = { scheme: await page.evaluate(() => document.documentElement.dataset.scheme), fill: await fill() }
      log(`scheme flip on ${p}: ${JSON.stringify(before)} -> ${JSON.stringify(after)}`)
      await shot('diagram-after-flip')
      await page.locator('#dark-mode-toggle').click()
      flipped = true
    }
  }
}

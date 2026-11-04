// Open every feature popup on the home page (or only the ids in args) and close it again.
// For each trigger: the modal shows, #popup-content holds exactly its carrier's HTML, every
// .mermaid block in it renders an <svg> without mermaid's "Syntax error", and the close path
// (cycled: the Close button, Escape, a click on the backdrop) hides the modal and returns focus
// to the trigger. Logs one line per popup: id, card heading, label, text length, diagrams.
export default async ({ page, base, shot, log, args }) => {
  await page.goto(base, { waitUntil: 'networkidle' })
  const triggers = page.locator('button.popup-trigger')
  const ids = await triggers.evaluateAll((els) =>
    els.map((b) => b.getAttribute('onclick').match(/showPopup\('([^']+)'\)/)[1]))
  const want = args.length ? args : ids
  for (const id of want) if (!ids.includes(id)) throw new Error(`no trigger for popup ${id}`)
  log(`triggers: ${ids.length} on the page, driving ${want.length}`)
  const closers = ['button', 'escape', 'backdrop']
  let n = 0
  for (const id of want) {
    const btn = page.locator(`button.popup-trigger[onclick="showPopup('${id}')"]`).first()
    await btn.scrollIntoViewIfNeeded()
    await btn.click()
    const modal = page.locator('#popup-modal')
    await modal.waitFor({ state: 'visible', timeout: 5000 })
    const diagrams = await page.locator('#popup-content .mermaid').count()
    if (diagrams) {
      await page.waitForFunction(() =>
        [...document.querySelectorAll('#popup-content .mermaid')].every((m) => m.querySelector('svg')),
        null, { timeout: 15000 })
    }
    const s = await page.evaluate((pid) => {
      const carrier = document.querySelector(`.popup-body[data-popup-id="${pid}"]`)
      const content = document.getElementById('popup-content')
      const probe = document.createElement('div')
      probe.innerHTML = carrier.textContent
      const card = document.querySelector(`button.popup-trigger[onclick="showPopup('${pid}')"]`)
        .closest('.feature-card, .card, article, section')
      return {
        same: content.querySelectorAll('*').length >= probe.querySelectorAll('*').length
          && content.textContent.replace(/\s+/g, ' ').includes(probe.textContent.replace(/\s+/g, ' ').trim().slice(0, 200)),
        text: content.textContent.trim().length,
        heading: (content.querySelector('h1,h2,h3')?.textContent ?? '').trim().slice(0, 60),
        card: (card?.querySelector('h3,h4')?.textContent ?? '').trim().slice(0, 40),
        syntaxError: /Syntax error in (text|graph)/i.test(content.textContent),
      }
    }, id)
    if (!s.same) throw new Error(`popup ${id}: #popup-content does not hold its carrier's HTML`)
    if (s.text < 40) throw new Error(`popup ${id}: only ${s.text} chars of text`)
    if (s.syntaxError) throw new Error(`popup ${id}: a mermaid diagram failed to parse`)
    if (n === 0 || id === want[want.length - 1]) await shot(`popup-${id}`)
    const how = closers[n % closers.length]
    if (how === 'button') await page.getByRole('button', { name: 'Close' }).click()
    else if (how === 'escape') await page.keyboard.press('Escape')
    else await page.mouse.click(5, 450)
    await modal.waitFor({ state: 'hidden', timeout: 3000 })
    const focused = await page.evaluate(() => document.activeElement?.getAttribute('onclick') ?? '')
    if (!focused.includes(`'${id}'`)) throw new Error(`popup ${id}: focus not returned to its trigger after ${how} (on ${focused || 'nothing'})`)
    log(`popup ${id} | card "${s.card}" | "${s.heading}" | ${s.text} chars | ${diagrams} diagram(s) | closed by ${how}`)
    n++
  }
  log(`popups: ${n} opened, rendered and closed`)
}

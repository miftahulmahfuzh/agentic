// Open each architecture diagram from the home page into the standalone viewer tab and require a
// drawn SVG. args: diagram ids (default: architecture agents screener).
// End state per id: a new tab on diagram.html?d=<id>, #title = the diagram's title, an <svg> in
// #stage with N g.node elements, the "could not be drawn" state hidden.
export default async ({ page, context, base, shot, log, args }) => {
  const ids = args.length ? args : ['architecture', 'agents', 'screener']
  await page.goto(base, { waitUntil: 'networkidle' })
  for (const id of ids) {
    const btn = page.locator(`button.diagram-open[onclick="openDiagramTab('${id}')"]`)
    if ((await btn.count()) !== 1) throw new Error(`no diagram button for ${id}`)
    const [tab] = await Promise.all([context.waitForEvent('page'), btn.click()])
    await tab.waitForLoadState('networkidle')
    await tab.waitForFunction(
      () => document.querySelector('#stage svg') || !document.getElementById('state-empty').hidden,
      null, { timeout: 20000 })
    const state = await tab.evaluate(() => ({
      url: location.pathname + location.search,
      title: document.getElementById('title').textContent,
      nodes: document.querySelectorAll('#stage svg g.node').length,
      clusters: document.querySelectorAll('#stage svg g.cluster').length,
      empty: document.getElementById('state-empty').hidden ? null
        : document.getElementById('empty-title').textContent + ': ' + document.getElementById('empty-body').textContent,
    }))
    log(`diagram ${id}: ${JSON.stringify(state)}`)
    await shot(`diagram-${id}`, tab)
    if (state.empty) throw new Error(`diagram ${id} not drawn: ${state.empty}`)
    if (state.nodes < 5) throw new Error(`diagram ${id} drew only ${state.nodes} nodes`)
    await tab.close()
  }
  await shot('home-after')
}

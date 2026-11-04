// node ui.mjs <base-url> <steps.mjs> <evidence-dir> <cdn-mode> <cdn-cache-dir> [args...]
// Steps module: `export default async ({ page, context, base, shot, log, args, allow }) => { ... }`.
//   base        the run's site root, http://localhost:PORT/agentic/ (always ends in /)
//   shot(name, p?)  full-page screenshot of `page` (or of another tab p) into evidence
//   log(text)   line into the drive's transcript
//   args        everything after `--` on the verify.sh ui command line
//   allow(re)   console errors / blocked requests matching re are expected, not a failure
// Records a video and a final screenshot, pass or fail. The drive FAILS on any console error,
// page error, or blocked request the steps did not allow().
//
// The fence (every request from every page in the context, popups included):
//   the run's own origin           passes
//   GET to the four public CDNs    served from <cdn-cache-dir> (fetched once, then cached);
//                                  aborted instead when cdn-mode is `offline`
//   anything else                  aborted and logged as `blocked:` (the owner's :1313 included)
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import { createHash } from 'node:crypto'
import { appendFileSync, existsSync, mkdirSync, readdirSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'

const [base, stepsArg, evidence, cdnMode, cdnCache, ...args] = process.argv.slice(2)
if (!base || !stepsArg || !evidence || !cdnMode || !cdnCache) {
  console.error('usage: node ui.mjs <base-url> <steps.mjs> <evidence-dir> <cache|offline> <cdn-cache-dir> [args...]')
  process.exit(2)
}
const stepsPath = path.resolve(stepsArg)

const require = createRequire(path.join(process.env.VERIFY_TOOLS, 'package.json'))
const { chromium } = require('playwright')

const CDN_HOSTS = new Set(['cdnjs.cloudflare.com', 'fonts.googleapis.com', 'fonts.gstatic.com', 'cdn.jsdelivr.net'])
const origin = new URL(base).origin

const n = readdirSync(evidence).filter((f) => /^\d\d-.*\.txt$/.test(f) && !f.startsWith('00-')).length
const tag = `${String(n + 1).padStart(2, '0')}-ui-${path.basename(stepsPath, '.mjs')}`
const transcript = path.join(evidence, `${tag}.txt`)
const log = (text) => {
  appendFileSync(transcript, `${text}\n`)
  console.log(text)
}

const allowed = []
const allow = (re) => allowed.push(re)
const problems = []
const problem = (text) => {
  log(text)
  problems.push(text)
}

async function serveCdn(route, req) {
  const key = createHash('sha256').update(req.url()).digest('hex').slice(0, 32)
  const body = path.join(cdnCache, `${key}.body`)
  const meta = path.join(cdnCache, `${key}.json`)
  if (existsSync(meta)) {
    const m = JSON.parse(readFileSync(meta, 'utf8'))
    return route.fulfill({ status: m.status, headers: m.headers, body: readFileSync(body) })
  }
  const res = await route.fetch()
  const headers = {
    'content-type': res.headers()['content-type'] ?? 'application/octet-stream',
    'access-control-allow-origin': '*',
  }
  const buf = await res.body()
  if (res.status() === 200) {
    mkdirSync(cdnCache, { recursive: true })
    writeFileSync(body, buf)
    writeFileSync(meta, JSON.stringify({ url: req.url(), status: 200, headers }))
    log(`cdn: fetched and cached ${req.url()}`)
  }
  return route.fulfill({ status: res.status(), headers, body: buf })
}

const browser = await chromium.launch()
const context = await browser.newContext({
  viewport: { width: 1400, height: 900 },
  permissions: [],
  serviceWorkers: 'block',
  timezoneId: 'Asia/Jakarta',
  recordVideo: { dir: path.join(evidence, '.video') },
})
await context.route('**/*', async (route) => {
  const req = route.request()
  const url = new URL(req.url())
  if (url.origin === origin) return route.continue()
  if (CDN_HOSTS.has(url.hostname) && req.method() === 'GET') {
    if (cdnMode === 'offline') {
      log(`cdn-offline: refused ${req.url()}`)
      return route.abort('internetdisconnected')
    }
    try {
      return await serveCdn(route, req)
    } catch (err) {
      problem(`cdn: fetch failed ${req.url()}: ${err.message}`)
      return route.abort('failed')
    }
  }
  if (url.protocol === 'data:' || url.protocol === 'blob:') return route.continue()
  const line = `blocked: ${req.method()} ${req.url()}`
  if (allowed.some((re) => re.test(line))) log(`${line} (allowed)`)
  else problem(line)
  return route.abort('blockedbyclient')
})

const watch = (p) => {
  p.on('console', (m) => {
    if (m.type() !== 'error') return
    const line = `console.error: ${m.text()}`
    if (allowed.some((re) => re.test(line))) log(`${line} (allowed)`)
    else problem(line)
  })
  p.on('pageerror', (e) => {
    const line = `pageerror: ${e.message}`
    if (allowed.some((re) => re.test(line))) log(`${line} (allowed)`)
    else problem(line)
  })
  p.on('requestfailed', (r) => log(`requestfailed: ${r.method()} ${r.url()} ${r.failure()?.errorText ?? ''}`))
}
context.on('page', watch)
const page = await context.newPage()

let shots = 0
const shot = async (name, p = page) => {
  const file = path.join(evidence, `${tag}-${++shots}-${name}.png`)
  await p.screenshot({ path: file, fullPage: true, caret: 'initial' })
  log(`screenshot: ${file}`)
}

let failed = null
try {
  log(`steps: ${stepsPath}${args.length ? ` args: ${args.join(' ')}` : ''}`)
  log(`base: ${base}  cdn: ${cdnMode}`)
  const { default: steps } = await import(pathToFileURL(stepsPath).href)
  await steps({ page, context, base, shot, log, args, allow })
  // Late console errors (a mermaid render after the last step) still count.
  await page.waitForTimeout(300)
  if (problems.length) throw new Error(`${problems.length} unexpected console/page error(s) or blocked request(s), see above`)
  log('result: PASS')
} catch (err) {
  failed = err
  log(`result: FAIL ${err?.stack ?? err}`)
} finally {
  await shot(failed ? 'failure' : 'final').catch(() => {})
  const video = page.video()
  await context.close()
  await browser.close()
  if (video) {
    const file = path.join(evidence, `${tag}.webm`)
    renameSync(await video.path(), file)
    rmSync(path.join(evidence, '.video'), { recursive: true, force: true })
    log(`video: ${file}`)
  }
  console.error(`[evidence: ${transcript}]`)
}
process.exit(failed ? 1 : 0)

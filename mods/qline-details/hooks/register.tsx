import type { EngineInterface, On } from 'claude-code'

const PANE = 'qline-details'
let view = { lines: ['No snapshot loaded. Select Refresh.'] }
let generation = 0
let commandRegistered = false

function text(value: unknown) {
  return typeof value === 'string'
    ? value.replace(/[\u0000-\u001f\u007f-\u009f]/g, '').slice(0, 128) : 'unavailable'
}

function number(value: unknown, digits = 0) {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0
    ? value.toFixed(digits) : 'unavailable'
}

function snapshotLines(content: string, sessionId: string, now: number) {
  let skipped = false
  const rows = content.trim().split('\n')
  for (let i = rows.length - 1; i >= 0; i--) {
    let row
    try { row = JSON.parse(rows[i]!) } catch { skipped = true; continue }
    if (!row || row.session_id !== sessionId || typeof row.ts !== 'string'
      || !Number.isFinite(Date.parse(row.ts))) {
      skipped = true
      continue
    }
    const age = Math.floor((now - Date.parse(row.ts)) / 1000)
    const percent = number(row.context_pct, 1)
    const lines = [
      `Model: ${text(row.model_name)} · Project: ${text(row.dir_basename)}`,
      `Cost: ${number(row.cost_usd, 4) === 'unavailable' ? 'unavailable' : '$' + number(row.cost_usd, 4)}`,
      `Context: ${percent === 'unavailable' ? percent : percent + '%'} · ${number(row.context_used)} / ${number(row.context_total)} tokens`,
      `Input: ${number(row.input_tokens)} · Output: ${number(row.output_tokens)} tokens`,
      `Duration: ${number(typeof row.duration_ms === 'number' ? row.duration_ms / 1000 : null)} seconds`,
      `Recorded: ${text(row.ts)} (${age < 0 ? 'clock is ahead; age unavailable' : age + ' seconds ago at refresh'})`,
    ]
    if (skipped) lines.push('Skipped invalid or incomplete trailing records; showing the last valid snapshot.')
    return { lines }
  }
  return { lines: ['No valid qLine snapshot for this session. The existing status line remains available.'] }
}

async function loadSnapshot($: EngineInterface) {
  try {
    const sessionId = await $.session.id()
    if (!/^[A-Za-z0-9_-]+$/.test(sessionId)) throw new Error('Invalid session identifier')
    const configured = await $.env.get('OBS_ROOT')
    const home = await $.env.get('HOME')
    const root = configured || (home ? `${home}/.claude/observability` : '')
    if (!root.startsWith('/')) throw new Error('No absolute observability root')
    const map = JSON.parse(await $.fs.read(`${root}/runtime/${sessionId}.json`))
    if (typeof map?.package_root !== 'string' || !map.package_root.startsWith('/')) {
      throw new Error('Invalid qLine session map')
    }
    const content = await $.fs.read(`${map.package_root}/native/statusline/snapshots.jsonl`)
    return snapshotLines(content, sessionId, await $.clock.now())
  } catch (error) {
    return { lines: [
      'qLine snapshot unavailable. The existing status line remains available.',
      text(error instanceof Error ? error.message : 'Unable to read the snapshot'),
    ] }
  }
}

async function refresh($: EngineInterface) {
  const request = ++generation
  const result = await loadSnapshot($)
  if (request === generation) {
    view = result
    $.ui.invalidate('ui.render')
  }
}

export function register(on: On) {
  on('session.start', async ($, e, next) => {
    commandRegistered = false
    const existing = (await $.command.list()).find(command => command.name === 'qline')
    if (existing && existing.plugin !== $.plugin.name) return next(e)
    await $.command.register({ name: 'qline', description: 'Inspect recorded qLine metrics', immediate: true })
    commandRegistered = true
    return next(e)
  }).catch(($, e, next) => next(e))

  on('command.run', { command: 'qline' }, async ($, e, next) => {
    if (!commandRegistered) return next(e)
    const current = (await $.command.list()).find(command => command.name === 'qline')
    if (current?.plugin !== $.plugin.name) return next(e)
    try {
      await refresh($)
      await $.ui.open({ id: PANE, title: 'qLine details', focus: true, closeOnEscape: true, rows: 12 })
      return {}
    } catch {
      return { text: 'qLine details could not open. The existing status line remains available.' }
    }
  }).catch(($, e, next) => next(e))

  on('session.end', async ($, e, next) => {
    generation++
    view = { lines: ['Session changed. Select Refresh to load its qLine snapshot.'] }
    $.ui.invalidate('ui.render')
    return next(e)
  })

  on('ui.render', { component: 'Pane' }, async ($, e, next) => {
    if (e.requestId !== PANE) return next(e)
    const { Box, Text, Button } = $.ui.resolve(e)
    return <Box flexDirection="column">
      {view.lines.map((line, index) => <Text key={`line-${index}`}>{line}</Text>)}
      <Text dimColor>Refresh reads existing snapshots; it does not run collectors.</Text>
      <Box flexDirection="row" columnGap={2}>
        <Button key="refresh" label="Refresh" hotkey="r" onPress={async () => refresh($)} />
        <Button key="close" label="Close" hotkey="q" onPress={async () => { await $.ui.close({ id: PANE }) }} />
      </Box>
    </Box>
  })
}

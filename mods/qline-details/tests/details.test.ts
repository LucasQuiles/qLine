import { expect, mock, test, type Engine } from 'claude-code/testing'
import type { CommandInfo, On } from 'claude-code'

const COMMAND = { command: 'qline', args: '', origin: { kind: 'composer' },
  presentation: { isFullscreen: false, columns: 100 } } as const

const PANE = {
  plugin: 'qline-details', component: 'Pane', requestId: 'qline-details',
  surface: 'terminal', viewport: { columns: 100, rows: 30 },
  props: { title: 'qLine details', isFocused: true, bodyColumns: 70,
    placement: 'inline', scroll: { offset: 0, bodyRows: 12 }, view: {} },
} as const

const RECORD = {
  ts: '2026-10-18T05:00:00Z', session_id: 'session-1', cost_usd: 1.25,
  duration_ms: 120000, context_pct: 25, context_used: 50000,
  context_total: 200000, input_tokens: 100, output_tokens: 50,
  model_name: 'test-model', dir_basename: 'example',
}

function startup(on: On) {
  let commands: CommandInfo[] = []
  on('session.start', () => ({ cwd: '/work' }))
  on('command.list', () => ({ value: commands }))
  on('command.register', ($, e) => {
    commands = [{ name: e.name, description: e.description, source: 'plugin', plugin: 'qline-details' }]
    return { value: { command: e.name } }
  })
}

async function start($: Engine) {
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
}

function sources(on: On, content: string | (() => string) = JSON.stringify(RECORD) + '\n') {
  startup(on)
  mock.env(on, { HOME: '/home/test', OBS_ROOT: '/observability' })
  mock.clock(on, { now: Date.parse('2026-10-18T05:00:20Z') })
  on('session.id', () => ({ value: 'session-1' }))
  on('fs.read', ($, e) => ({ value: e.path.endsWith('/runtime/session-1.json')
    ? JSON.stringify({ package_root: '/observability/sessions/day/session-1' })
    : typeof content === 'function' ? content() : content }))
}

test('opens a pane with recorded metrics and their age without a model request', async ($, on) => {
  sources(on)
  let opened = 0
  on('ui.open', () => { opened++; return { value: { isPlaced: true } } })
  on('command.run', () => ({}))
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['fallback'] }))
  await start($)
  const result = await $.command.run(COMMAND)
  expect(result).toEqual({})
  expect(opened).toBe(1)
  const ui = await $.ui.mount(PANE)
  expect(await ui.find({ type: 'Text', text: /Cost: \$1\.2500/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /20 seconds ago/ })).toBeDefined()
  await ui.unmount()
})

test('refresh reloads snapshots and close releases the pane', async ($, on) => {
  let cost = 1.25
  sources(on, () => JSON.stringify({ ...RECORD, cost_usd: cost }))
  let closed = 0
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.close', ($, e) => { expect(e.id).toBe('qline-details'); closed++; return { value: undefined } })
  await start($)
  await $.command.run(COMMAND)
  const ui = await $.ui.mount(PANE)
  cost = 2.5
  await ui.press({ key: 'refresh' })
  expect(await ui.find({ type: 'Text', text: /Cost: \$2\.5000/ })).toBeDefined()
  await ui.press({ key: 'close' })
  expect(closed).toBe(1)
  await ui.unmount()
})

test('reports an incomplete tail without presenting it as current data', async ($, on) => {
  sources(on, JSON.stringify(RECORD) + '\n{"ts":')
  on('ui.open', () => ({ value: { isPlaced: true } }))
  await start($)
  await $.command.run(COMMAND)
  const ui = await $.ui.mount(PANE)
  expect(await ui.find({ type: 'Text', text: /last valid snapshot/ })).toBeDefined()
  await ui.unmount()
})

test('does not display another session or invent zero metrics', async ($, on) => {
  sources(on, JSON.stringify({ ...RECORD, session_id: 'other-session' }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  await start($)
  await $.command.run(COMMAND)
  const ui = await $.ui.mount(PANE)
  expect(await ui.find({ type: 'Text', text: /No valid qLine snapshot/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /Cost:/ })).toBeUndefined()
  await ui.unmount()
})

test('file access refusal remains visible and keeps the status-line fallback', async ($, on) => {
  startup(on)
  mock.env(on, { HOME: '/home/test' })
  on('session.id', () => ({ value: 'session-1' }))
  on('fs.read', () => ({ deny: 'read unavailable' }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  await start($)
  await $.command.run(COMMAND)
  const ui = await $.ui.mount(PANE)
  expect(await ui.find({ type: 'Text', text: /snapshot unavailable/ })).toBeDefined()
  await ui.unmount()
})

test('session end clears displayed values and other panes pass through', async ($, on) => {
  sources(on)
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.end', () => ({ sessionId: 'session-1' }))
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['other pane'] }))
  await start($)
  await $.command.run(COMMAND)
  await $.session.end({ reason: 'clear', sessionId: 'session-1', resume: { id: 'session-1' } })
  const ui = await $.ui.mount(PANE)
  expect(await ui.find({ type: 'Text', text: /Session changed/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /Cost:/ })).toBeUndefined()
  await ui.unmount()
  const other = await $.ui.mount({ ...PANE, requestId: 'another-pane' })
  expect(await other.find({ type: 'Text', text: 'other pane' })).toBeDefined()
  await other.unmount()
})

test('startup registers an immediate command without reading files', async ($, on) => {
  let registered
  on('command.list', () => ({ value: [] }))
  on('command.register', ($, e) => { registered = e; return { value: { command: e.name } } })
  on('session.start', () => ({ cwd: '/work' }))
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  expect(registered).toMatchObject({ name: 'qline', immediate: true })
})

test('unknown metrics stay unknown and future timestamps do not claim freshness', async ($, on) => {
  sources(on, JSON.stringify({ ...RECORD, cost_usd: null, context_pct: null,
    ts: '2026-10-18T06:00:00Z', model_name: 'model\u0007name' }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  await start($)
  await $.command.run(COMMAND)
  const ui = await $.ui.mount(PANE)
  expect(await ui.find({ type: 'Text', text: 'Cost: unavailable' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^Context: unavailable ·/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /clock is ahead; age unavailable/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /Model: modelname/ })).toBeDefined()
  await ui.unmount()
})

test('a refused command registration preserves the existing command', async ($, on) => {
  on('command.list', () => ({ value: [] }))
  on('session.start', () => ({ cwd: '/work' }))
  on('command.register', () => ({ deny: 'command already exists' }))
  on('command.run', () => ({ text: 'existing command' }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  const result = await $.command.run(COMMAND)
  expect(result.text).toBe('existing command')
})

test('does not replace a plugin command even when registration would succeed', async ($, on) => {
  let registrations = 0
  on('command.list', () => ({ value: [{ name: 'qline', description: 'existing', source: 'plugin', plugin: 'other' }] }))
  on('command.register', () => { registrations++; return { value: { command: 'qline' } } })
  on('session.start', () => ({ cwd: '/work' }))
  on('command.run', () => ({ text: 'existing command' }))
  await start($)
  expect(registrations).toBe(0)
  expect((await $.command.run(COMMAND)).text).toBe('existing command')
})

test('command discovery failure passes through without opening a pane', async ($, on) => {
  let calls = 0
  let opened = 0
  on('command.list', () => ++calls === 1 ? { value: [] } : { deny: 'discovery unavailable' })
  on('command.register', () => ({ value: { command: 'qline' } }))
  on('session.start', () => ({ cwd: '/work' }))
  on('command.run', () => ({ text: 'existing command' }))
  on('ui.open', () => { opened++; return { value: { isPlaced: true } } })
  await start($)
  expect((await $.command.run(COMMAND)).text).toBe('existing command')
  expect(opened).toBe(0)
})

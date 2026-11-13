import { test, beforeEach, afterEach, mock } from 'node:test'
import assert from 'node:assert/strict'
import {
  createElapsedClock,
  formatDuration,
  parseServerTimestamp,
} from './elapsed.ts'

beforeEach(() => {
  mock.timers.enable({ apis: ['setInterval', 'Date'] })
})

afterEach(() => {
  mock.timers.reset()
})

function clockWithSink() {
  const ticks: number[] = []
  const clock = createElapsedClock((elapsedMs) => ticks.push(elapsedMs))
  return { clock, ticks }
}

test('running time advances normally while queued or running', () => {
  const { clock, ticks } = clockWithSink()
  clock.reset(Date.now())
  assert.equal(clock.value(), 0)
  assert.equal(clock.ticking(), true)

  for (let second = 1; second <= 3; second += 1) {
    mock.timers.tick(1000)
    assert.equal(clock.value(), second * 1000)
  }

  assert.deepEqual(ticks, [0, 1000, 2000, 3000])
  assert.equal(formatDuration(clock.value()), '00:03')
  clock.dispose()
})

test('the timer keeps ticking while the job is still running', () => {
  const { clock } = clockWithSink()
  const now = Date.now()
  clock.reset(now)
  clock.applyServerTimestamps(new Date(now - 500).toISOString(), null)

  mock.timers.tick(3000)
  assert.ok(clock.value() >= 3000)
  assert.equal(clock.ticking(), true)
  clock.dispose()
})

test('COMPLETE freezes the timer and a further minute does not change it', () => {
  const { clock, ticks } = clockWithSink()
  clock.reset(Date.now())
  mock.timers.tick(5000)

  assert.equal(clock.freeze('complete'), 5000)
  const ticksAtFreeze = ticks.length
  assert.equal(clock.ticking(), false)

  mock.timers.tick(60_000)

  assert.equal(clock.value(), 5000)
  assert.equal(ticks.length, ticksAtFreeze)
  assert.equal(formatDuration(clock.value()), '00:05')
  clock.dispose()
})

test('FAILED freezes the timer', () => {
  const { clock } = clockWithSink()
  clock.reset(Date.now())
  mock.timers.tick(7000)

  assert.equal(clock.freeze('failed'), 7000)
  mock.timers.tick(60_000)

  assert.equal(clock.value(), 7000)
  assert.equal(clock.ticking(), false)
  clock.dispose()
})

test('terminal error branches (missing job, invalid payload) freeze the timer', () => {
  for (const branch of ['missing job', 'invalid payload']) {
    const { clock } = clockWithSink()
    clock.reset(Date.now())
    mock.timers.tick(4000)

    clock.freeze('failed')
    mock.timers.tick(60_000)

    assert.equal(clock.value(), 4000, `${branch} should freeze the timer`)
    assert.equal(clock.ticking(), false, `${branch} should stop the interval`)
    clock.dispose()
  }
})

test('valid server timestamps produce the server duration', () => {
  const created = '2026-11-12T08:57:04.502850+00:00'
  const completed = '2026-11-12T08:57:32.795392+00:00'
  const expected = Date.parse(completed) - Date.parse(created)

  const { clock } = clockWithSink()
  clock.reset(Date.now())
  mock.timers.tick(3000) // client only measured 3s
  clock.applyServerTimestamps(created, completed)

  assert.equal(clock.freeze('complete'), expected)
  assert.ok(expected > 3000)
  clock.dispose()
})

test('server duration wins over a much larger client-measured age', () => {
  // Reproduces the "FAILED · 134:40" case: the client attached to an old job.
  const created = '2026-11-12T08:57:04.502850+00:00'
  const completed = '2026-11-12T08:57:32.795392+00:00'
  const expected = Date.parse(completed) - Date.parse(created)

  const { clock } = clockWithSink()
  clock.reset(Date.now())
  mock.timers.tick(10 * 60_000)
  clock.applyServerTimestamps(created, completed)

  assert.equal(clock.freeze('failed'), expected)
  clock.dispose()
})

test('missing completed_at falls back to the frozen client elapsed', () => {
  const { clock } = clockWithSink()
  clock.reset(Date.now())
  mock.timers.tick(7000)

  clock.applyServerTimestamps(null, null)
  assert.equal(clock.freeze('failed'), 7000)
  clock.dispose()
})

test('a server completion without created_at never fabricates a duration', () => {
  const { clock } = clockWithSink()
  const now = Date.now()
  clock.reset(now)
  mock.timers.tick(2000)

  // Only completed_at is available; it must not be compared to the client start.
  clock.applyServerTimestamps(null, new Date(now + 100_000).toISOString())
  assert.equal(clock.freeze('failed'), 2000)
  clock.dispose()
})

test('invalid timestamps use a finite, non-negative fallback', () => {
  const { clock } = clockWithSink()
  clock.reset(Date.now())
  mock.timers.tick(3000)

  clock.applyServerTimestamps('not-a-date', 'also-not-a-date')
  const value = clock.freeze('failed')

  assert.ok(Number.isFinite(value))
  assert.ok(value >= 0)
  assert.equal(value, 3000)
  assert.equal(formatDuration(value), '00:03')
  clock.dispose()
})

test('a completed_at before created_at never yields a negative duration', () => {
  const { clock } = clockWithSink()
  clock.reset(Date.now())
  mock.timers.tick(1000)

  clock.applyServerTimestamps('2026-11-12T10:00:00Z', '2026-11-12T09:00:00Z')
  const value = clock.freeze('failed')

  assert.ok(Number.isFinite(value))
  assert.ok(value >= 0)
  assert.ok(!formatDuration(value).includes('NaN'))
  clock.dispose()
})

test('changing jobId restarts the timer from zero', () => {
  const first = clockWithSink()
  first.clock.reset(Date.now())
  mock.timers.tick(9000)
  assert.equal(first.clock.value(), 9000)
  first.clock.dispose()

  const second = clockWithSink()
  second.clock.reset(Date.now())
  assert.equal(second.clock.value(), 0)
  mock.timers.tick(1000)
  assert.equal(second.clock.value(), 1000)
  assert.equal(second.clock.ticking(), true)
  second.clock.dispose()
})

test('stale responses cannot affect the clock for the current job', () => {
  const stale = clockWithSink()
  stale.clock.reset(Date.now())
  mock.timers.tick(4000)
  stale.clock.dispose()

  const current = clockWithSink()
  current.clock.reset(Date.now())
  mock.timers.tick(1000)

  const staleTicks = stale.ticks.length
  stale.clock.freeze('failed')
  stale.clock.applyServerTimestamps('2020-01-01T00:00:00Z', '2020-01-01T00:00:10Z')
  stale.clock.reset(Date.now())
  mock.timers.tick(60_000)

  assert.equal(stale.ticks.length, staleTicks)
  assert.equal(stale.clock.value(), 0)
  assert.equal(current.clock.value(), 61_000)
  current.clock.dispose()
})

test('unmounting leaves no active interval', () => {
  const { clock, ticks } = clockWithSink()
  clock.reset(Date.now())
  mock.timers.tick(2000)
  assert.equal(clock.ticking(), true)

  clock.dispose()
  assert.equal(clock.ticking(), false)

  const ticksAtDispose = ticks.length
  mock.timers.tick(60_000)
  assert.equal(ticks.length, ticksAtDispose)
})

test('formatDuration clamps NaN and negative input', () => {
  assert.equal(formatDuration(0), '00:00')
  assert.equal(formatDuration(-5000), '00:00')
  assert.equal(formatDuration(Number.NaN), '00:00')
  assert.equal(formatDuration(65_000), '01:05')
  assert.equal(formatDuration(3_600_000), '60:00')
})

test('parseServerTimestamp rejects unusable values', () => {
  assert.equal(parseServerTimestamp(undefined), null)
  assert.equal(parseServerTimestamp(null), null)
  assert.equal(parseServerTimestamp(''), null)
  assert.equal(parseServerTimestamp('   '), null)
  assert.equal(parseServerTimestamp('not-a-date'), null)
  assert.equal(parseServerTimestamp(12345), null)
  assert.equal(
    parseServerTimestamp('2026-11-12T08:57:04Z'),
    Date.parse('2026-11-12T08:57:04Z'),
  )
})

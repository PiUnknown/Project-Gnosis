/**
 * Elapsed-time tracking for the analysis progress screen.
 *
 * The progress screen must stop counting once an analysis reaches a terminal
 * state. Keeping the timing rules outside React makes them testable without a
 * DOM, and leaves the component responsible only for wiring.
 *
 * Duration semantics:
 *  - While queued/running the clock counts against the client clock, starting
 *    from the server's `created_at` when it is usable and otherwise from the
 *    moment the progress screen started. This is the client-measured elapsed
 *    value and always ticks while the run is live.
 *  - On a terminal state the server's own duration
 *    (`completed_at - created_at`) is preferred when both timestamps are valid.
 *  - When the server duration is unavailable the client-measured value is
 *    frozen at the moment termination was detected. A client start time is
 *    never subtracted from a server completion time, so a missing `created_at`
 *    cannot fabricate a long processing time.
 *  - Every value is clamped to a finite, non-negative number of milliseconds.
 */

export const TICK_INTERVAL_MS = 1000

export type TerminalKind = 'complete' | 'failed'

export interface ElapsedClock {
  /** Start (or restart) the clock for a new job, discarding all prior state. */
  reset(clientStartedAtMs?: number): void
  /** Feed the timestamps from a job status response. */
  applyServerTimestamps(createdAt: unknown, completedAt: unknown): void
  /** Freeze the clock permanently for this job. Idempotent. */
  freeze(kind: TerminalKind): number
  /** Current elapsed value in milliseconds (finite and non-negative). */
  value(): number
  /** Whether the one-second interval is currently scheduled. */
  ticking(): boolean
  /** Stop the interval and ignore every later call. Idempotent. */
  dispose(): void
}

/** Parse a server timestamp into epoch milliseconds, or null when unusable. */
export function parseServerTimestamp(value: unknown): number | null {
  if (typeof value !== 'string' || value.trim() === '') return null
  const parsed = Date.parse(value)
  return Number.isFinite(parsed) ? parsed : null
}

/** Format milliseconds as MM:SS, guarding against NaN and negative input. */
export function formatDuration(ms: number): string {
  const safe = Number.isFinite(ms) ? Math.max(0, ms) : 0
  const total = Math.floor(safe / 1000)
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

export function createElapsedClock(onTick: (elapsedMs: number) => void): ElapsedClock {
  let clientStartedAtMs = Date.now()
  let serverStartedAtMs: number | null = null
  let serverCompletedAtMs: number | null = null
  let terminal: TerminalKind | null = null
  let frozenMs: number | null = null
  let interval: ReturnType<typeof setInterval> | null = null
  let disposed = false

  const clientElapsed = (nowMs: number) => {
    const startedAt = serverStartedAtMs ?? clientStartedAtMs
    const elapsed = nowMs - startedAt
    return Number.isFinite(elapsed) && elapsed > 0 ? elapsed : 0
  }

  const emit = (value: number) => {
    if (disposed) return
    onTick(value)
  }

  const tick = () => {
    if (disposed || terminal) return
    emit(clientElapsed(Date.now()))
  }

  const startInterval = () => {
    if (disposed || terminal || interval !== null) return
    interval = setInterval(tick, TICK_INTERVAL_MS)
  }

  const stopInterval = () => {
    if (interval === null) return
    clearInterval(interval)
    interval = null
  }

  return {
    reset(clientStartedAt) {
      if (disposed) return
      stopInterval()
      clientStartedAtMs =
        typeof clientStartedAt === 'number' &&
        Number.isFinite(clientStartedAt) &&
        clientStartedAt >= 0
          ? clientStartedAt
          : Date.now()
      serverStartedAtMs = null
      serverCompletedAtMs = null
      terminal = null
      frozenMs = null
      emit(0)
      startInterval()
    },

    applyServerTimestamps(createdAt, completedAt) {
      if (disposed || terminal) return
      const created = parseServerTimestamp(createdAt)
      const completed = parseServerTimestamp(completedAt)
      if (created !== null) serverStartedAtMs = created
      if (completed !== null) serverCompletedAtMs = completed
      emit(clientElapsed(Date.now()))
    },

    freeze(kind) {
      if (disposed) return frozenMs ?? 0
      if (terminal) return frozenMs ?? 0
      terminal = kind

      let value: number | null = null
      if (serverStartedAtMs !== null && serverCompletedAtMs !== null) {
        const serverDuration = serverCompletedAtMs - serverStartedAtMs
        if (Number.isFinite(serverDuration) && serverDuration >= 0) value = serverDuration
      }
      // Fallback: freeze the client-measured value at detection time. Never
      // combine a client start with a server completion.
      if (value === null) value = clientElapsed(Date.now())

      frozenMs = value
      stopInterval()
      emit(value)
      return value
    },

    value() {
      if (disposed || terminal) return frozenMs ?? 0
      return clientElapsed(Date.now())
    },

    ticking() {
      return interval !== null
    },

    dispose() {
      disposed = true
      stopInterval()
    },
  }
}

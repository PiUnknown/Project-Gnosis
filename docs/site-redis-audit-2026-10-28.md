# Site and Redis audit — 2026-10-28

## Overall assessment

The frontend compiles and its built HTML, JavaScript, and CSS serve locally. TypeScript checking also passes. The backend source contains a Redis-backed job store, RQ dispatch, a separate worker, a local in-memory/thread-pool fallback, and Docker Compose Redis wiring.

This is not a full end-to-end pass. The Python test suite could not start in this environment, no local Redis server is listening, and neither the public site nor its API returned an HTTP response from this environment. Vercel deployment and runtime diagnostics returned 403 for the connected account. Production health, production Redis connectivity, and the active-index sentinel state therefore remain unverified.

The audit was read-only with respect to application code. It reviewed the current working tree, including the existing uncommitted active-index changes and migration script, and left those changes untouched.

## Verification performed

| Check | Result |
|---|---|
| Frontend production build | Passed. Vite emitted config-loader warnings and a chunk-size warning: main JavaScript is 866 KB (272 KB gzip); the lazy graph chunk is 1.23 MB (329 KB gzip). |
| TypeScript | Passed with `npm.cmd exec -- tsc --noEmit`. |
| Local production-preview smoke check | Passed. Preview returned HTTP 200; the built JavaScript and CSS assets also returned HTTP 200. This checks static serving, not browser interaction or API submission. |
| Python syntax compilation | Passed for `src` and `tests` using the available Python 3.14.5 interpreter. This is syntax-only validation. |
| Pytest suite | Not run. The project venv launcher points to a missing uv-managed Python install; the available system Python does not have pytest installed. |
| Local Redis | Not available. TCP port 6379 was closed, so Redis/RQ integration and active-index behavior could not be exercised. |
| Public site and API | No HTTP response was received from this environment (curl status 000 for both). This does not establish that either service is down. |
| Vercel production diagnostics | Project discovery succeeded, but deployment and runtime-error requests returned 403 because the connected account lacks access to the owning team scope. No access grant was requested. |

## Findings

### P1 — Redis store and queue can select different execution modes

The job store chooses Redis or memory once when the process imports it. If that initial Redis ping fails, it stays in memory mode. The queue independently pings Redis each time it dispatches. A request can therefore create its job in the API process’s memory and then enqueue it into Redis/RQ; the worker will not find that job record in Redis, and status polling will continue to see the API’s separate memory copy. A similar split can occur when Redis storage writes fail and `create` falls back to memory while the queue remains reachable. `finish` and `fail` also fall through to the process-local map after Redis write errors, which cannot update a job previously stored only in Redis.

Evidence: `src/api/job_store.py` selects a backend during initialization and falls back in `create`; `src/api/queue.py` establishes its Redis connection independently before choosing RQ or the thread pool; `src/api/worker.py` opens its own Redis connection.

**Recommendation:** Make storage and dispatch mode a single startup decision. Do not acknowledge or RQ-enqueue a job unless its shared durable record was written. On Redis transition errors, surface a failed state or explicit service error instead of silently writing to an unrelated process-local store.

### P1 — Credential-bearing values can be logged or retained in Redis

`JobStore` logs the full REDIS_URL after connecting. The worker logs that URL before connecting and includes it in its connection-failure message. If the URL contains a password or token, those values can enter platform logs.

The API also accepts a GitHub token and serializes it in the job’s options. `Job.to_dict` includes options, so the token is stored in the Redis job record. The job-record TTL defaults to zero (no expiry) unless JOB_TTL_SECONDS is configured.

Evidence: `src/api/job_store.py:91, 148, 345`; `src/api/main.py:88-90, 173-175, 219`; `src/api/worker.py:84, 90`.

**Recommendation:** Redact Redis credentials from all log messages. Avoid persisting GitHub PATs in job records; if a token must be retained, use a separately protected, short-lived secret store and enforce deletion after the GitHub fetch phase.

### P2 — Job records and the global job index can grow without bound

Completed job records use JOB_TTL_SECONDS with a default of zero. The RQ result TTL default of one day applies to RQ’s own result, not automatically to the serialized JobStore record. When a job-record TTL is configured, the global Redis set `gnosis:jobs` is not updated on key expiry, so stale IDs remain in the index. `list_all` reads the full index and fetches all corresponding records; submission deduplication and `/jobs` use that path.

**Impact:** Redis storage and the cost of each full listing/submission check can increase with the lifetime number of jobs, including jobs whose record keys have expired.

**Recommendation:** Define an explicit record-retention policy and remove expired IDs from the index, using expiry notifications or bounded cleanup. Keep active-job lookups separate from full result enumeration.

### P2 — Active-index health optimization only works after an operator migration

The current working tree adds `gnosis:jobs:active` membership updates and a sentinel-based fast path for `active_count`. The fast path is used only when the sentinel is present. Normal creates and health reads do not arm it; `src/api/job_store_migrate.py` is the operator-run reconciliation path and requires writer-version confirmation before arming.

Until the migration is successfully run, `/health` falls back to `list_all` to count active jobs. That reads all job records, including large results, on each health request. The current environment had no Redis connection, and production diagnostics were unavailable, so I could not verify whether the production sentinel is armed.

**Recommendation:** Confirm migration status against the production Redis instance after all API writers and workers are on the compatible revision. Until verified, budget health checks for the legacy full scan. The health response reports `status: ok` even when Redis is disconnected, so monitors must inspect `redis_connected` and `queue_mode`, not just HTTP 200.

### P2 — Terminal job states can be overwritten by overlapping workers

`start` changes any existing indexed record to `running`, including a record already marked `complete` or `failed`. `finish` and `fail` read a job and then write a terminal state without a WATCH/CAS guard. If a duplicate execution or overlapping failure handler occurs, a completed result can be changed back to running or overwritten as failed; the active set can then show a job as active again. Phase updates do guard against terminal records, but these lifecycle transitions do not.

Evidence: `src/api/job_store.py:198-248, 333-398`.

**Recommendation:** Make all transitions conditional on the current status in one Redis transaction or Lua script. Treat completed and failed states as terminal and add retry/overlap cases to the Redis tests.

### P2 — Missing job IDs can leave the progress screen polling forever

`GET /api/jobs/{job_id}` returns HTTP 200 with an error object when the job does not exist. The progress screen treats any 2xx response as job data, immediately calls `data.agents.map`, catches the resulting exception as a transient network blip, and continues polling without showing an error. Expiry, deletion, a backend/store mode mismatch, or a stale browser tab can trigger this path.

Evidence: `src/api/main.py:239-242`; `frontend/src/App.tsx:594-620`.

**Recommendation:** Return HTTP 404 for a missing job and have the progress screen surface terminal HTTP errors instead of retrying them as network blips.

### P2 — Untrusted option shapes can produce server errors; duplicate submissions race

The request model types `options` as an unrestricted dictionary. The handler compares `options.max_explanations` to integers without validating/coercing its type, so a value such as a string can raise TypeError and return a server error instead of a validation response. Also, duplicate detection is a read of all jobs followed later by creation; concurrent submissions for the same repository can both pass the check and enqueue separate analyses.

Evidence: `src/api/main.py:84-90, 164-180, 222-223`.

**Recommendation:** Use a typed options model for overrides, and make per-repository deduplication atomic if duplicate analysis is not intended.

### P3 — Frontend bundle and repository validation have edge-case costs

The successful build reports 866 KB of main JavaScript and a 1.23 MB lazy graph chunk. The graph is lazy-loaded, but the initial bundle still exceeds Vite’s 500 KB warning threshold. This can slow first load on constrained connections.

The API validates that the input contains the substring `github.com`, and the parser extracts path segments without validating the actual hostname. A URL such as `https://github.com.evil.example/owner/repo` can pass the API check and be interpreted as the GitHub repository `owner/repo`. This does not make the GitHub API request use the supplied host, but it accepts a malformed URL and can confuse callers.

**Recommendation:** Measure first-load performance and split heavy initial dependencies if needed. Validate the parsed URL hostname as exactly `github.com` and normalize accepted repository URLs.

## Documentation drift

`README.md:584` remains stale: it describes the in-memory store as the selected approach and Redis as a future upgrade. `Flow.md` had an outdated simulation-only description at the start of the audit; it was relabeled as archived and supplemented with the current API runtime flow during this audit. Treat the source and current deployment configuration as authoritative until README.md is refreshed.

## Suggested order

1. Fix Redis mode consistency and remove credentials from logs/job records.
2. Guard terminal transitions and return correct missing-job responses.
3. Set retention and prune the global index; verify and arm the active index in production.
4. Restore a working Python environment, run pytest and fakeredis coverage, then run an end-to-end check against a disposable Redis instance.
5. Re-run production health/deployment checks when network access and Vercel team authorization are available.

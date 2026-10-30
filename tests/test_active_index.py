"""Tests for the derived active-job index and its operator reconciliation.

These tests are deterministic: interleavings are injected at a pipeline's
EXEC boundary or by calling individual reconciliation steps, never by sleeping
or by racing real threads.
"""
import json

import fakeredis
import pytest

from src.api.job_store import (
    ACTIVE_INDEX_SENTINEL,
    WATCH_MAX_ATTEMPTS,
    ActiveIndexReconcileError,
    JobStore,
)

INDEX = "gnosis:jobs"
ACTIVE = "gnosis:jobs:active"


def _job_key(job_id: str) -> str:
    return f"gnosis:job:{job_id}"


def _new_store():
    fake = fakeredis.FakeRedis(decode_responses=True)
    store = JobStore()
    store.connect_redis(fake)
    return store, fake


def _seed_record(fake, job_id, status, result=None, in_index=True):
    payload = {
        "job_id": job_id,
        "repo_url": f"https://github.com/test/{job_id}",
        "options": {},
        "status": status,
        "current_phase": None,
        "phases_completed": [],
        "progress_pct": 0,
        "created_at": "2026-01-01T00:00:00+00:00",
        "completed_at": None,
        "error": None,
        "result": result,
    }
    fake.set(_job_key(job_id), json.dumps(payload))
    if in_index:
        fake.sadd(INDEX, job_id)


def _assert_fast_matches_legacy(store):
    # active_count() uses the fast set when armed and the legacy path otherwise.
    assert store.active_count() == store._legacy_active_count()


class _InterleavingPipeline:
    def __init__(self, pipe, callback):
        self._pipe = pipe
        self._callback = callback

    def __getattr__(self, name):
        attr = getattr(self._pipe, name)
        if name == "execute":
            def execute(*args, **kwargs):
                if self._callback is not None:
                    self._callback()
                return attr(*args, **kwargs)
            return execute
        return attr


class _InterleavingClient:
    """Proxy that runs a callback immediately before every EXEC."""

    def __init__(self, client, callback):
        self._client = client
        self._callback = callback

    def pipeline(self, *args, **kwargs):
        return _InterleavingPipeline(
            self._client.pipeline(*args, **kwargs), self._callback
        )

    def __getattr__(self, name):
        return getattr(self._client, name)


def _once(callback):
    state = {"done": False}

    def wrapped():
        if not state["done"]:
            state["done"] = True
            callback()

    return wrapped


class TestLifecycleMembership:
    def test_create_start_finish_membership(self):
        store, fake = _new_store()
        job_id = store.create("https://github.com/test/repo", {})

        assert fake.sismember(ACTIVE, job_id)
        assert store.active_count() == 1
        _assert_fast_matches_legacy(store)

        store.start(job_id)
        assert store.get(job_id).status == "running"
        assert fake.sismember(ACTIVE, job_id)
        assert store.active_count() == 1
        _assert_fast_matches_legacy(store)

        store.finish(job_id, {"onboarding_doc": "done"})
        assert store.get(job_id).status == "complete"
        assert not fake.sismember(ACTIVE, job_id)
        assert store.active_count() == 0
        _assert_fast_matches_legacy(store)

    def test_fail_delete_clear_membership(self):
        store, fake = _new_store()
        job1 = store.create("https://github.com/test/1", {})
        job2 = store.create("https://github.com/test/2", {})
        job3 = store.create("https://github.com/test/3", {})

        store.fail(job1, "boom")
        assert not fake.sismember(ACTIVE, job1)
        assert store.active_count() == 2
        _assert_fast_matches_legacy(store)

        assert store.delete(job2) is True
        assert not fake.sismember(ACTIVE, job2)
        assert store.active_count() == 1
        _assert_fast_matches_legacy(store)

        store.rebuild_active_index(arm=True)
        assert fake.sismember(ACTIVE, ACTIVE_INDEX_SENTINEL)
        store.clear()
        # clear deliberately uninitializes the fast path.
        assert not fake.sismember(ACTIVE, ACTIVE_INDEX_SENTINEL)
        assert store.active_count() == 0
        _assert_fast_matches_legacy(store)
        assert job3  # created but cleared

    def test_duplicate_start_and_finish_are_idempotent(self):
        store, fake = _new_store()
        job_id = store.create("https://github.com/test/repo", {})
        store.start(job_id)
        store.start(job_id)
        assert fake.scard(ACTIVE) == 1
        assert store.active_count() == 1

        store.finish(job_id, {"x": 1})
        store.finish(job_id, {"x": 2})
        assert fake.scard(ACTIVE) == 0
        assert store.active_count() == 0
        _assert_fast_matches_legacy(store)

    def test_finish_and_fail_on_missing_record_remove_stale_member(self):
        store, fake = _new_store()
        job1 = store.create("https://github.com/test/1", {})
        job2 = store.create("https://github.com/test/2", {})

        fake.delete(_job_key(job1))
        fake.delete(_job_key(job2))
        store.finish(job1, {"x": 1})
        store.fail(job2, "gone")

        assert not fake.sismember(ACTIVE, job1)
        assert not fake.sismember(ACTIVE, job2)
        assert store.active_count() == 0

    def test_reserved_sentinel_id_is_rejected(self):
        store, _ = _new_store()
        with pytest.raises(ValueError):
            store.create("https://github.com/test/repo", {}, job_id=ACTIVE_INDEX_SENTINEL)


class TestStartContention:
    def test_delete_between_start_read_and_write(self):
        store, fake = _new_store()
        job_id = store.create("https://github.com/test/repo", {})

        store.connect_redis(_InterleavingClient(fake, _once(lambda: store.delete(job_id))))
        store.start(job_id)

        assert not fake.exists(_job_key(job_id))
        assert not fake.sismember(INDEX, job_id)
        assert not fake.sismember(ACTIVE, job_id)
        assert store.get(job_id) is None
        assert store.active_count() == store._legacy_active_count() == 0

    def test_index_removal_between_start_read_and_write(self):
        store, fake = _new_store()
        job_id = store.create("https://github.com/test/repo", {})

        def unindex_and_deactivate():
            fake.srem(INDEX, job_id)
            fake.srem(ACTIVE, job_id)

        store.connect_redis(_InterleavingClient(fake, _once(unindex_and_deactivate)))
        store.start(job_id)

        assert json.loads(fake.get(_job_key(job_id)))["status"] == "queued"
        assert not fake.sismember(ACTIVE, job_id)
        assert store.active_count() == store._legacy_active_count() == 0

    def test_clear_between_start_read_and_write(self):
        store, fake = _new_store()
        job_id = store.create("https://github.com/test/repo", {})

        store.connect_redis(_InterleavingClient(fake, _once(store.clear)))
        store.start(job_id)

        assert not fake.exists(_job_key(job_id))
        assert not fake.sismember(INDEX, job_id)
        assert not fake.sismember(ACTIVE, job_id)
        assert store.active_count() == store._legacy_active_count() == 0

    def test_start_does_not_recreate_unindexed_record(self):
        store, fake = _new_store()
        job_id = store.create("https://github.com/test/repo", {})
        fake.srem(INDEX, job_id)
        fake.srem(ACTIVE, job_id)

        store.start(job_id)

        # Record still exists, but it is not a known indexed job and must not
        # become running or be (re-)added to the active set.
        assert json.loads(fake.get(_job_key(job_id)))["status"] == "queued"
        assert not fake.sismember(ACTIVE, job_id)
        assert store.active_count() == 0

    def test_start_retry_exhaustion_leaves_record_and_memory_unchanged(self, caplog):
        store, fake = _new_store()
        job_id = store.create("https://github.com/test/repo", {})
        attempts = {"n": 0}

        def bump_record():
            attempts["n"] += 1
            payload = json.loads(fake.get(_job_key(job_id)))
            payload["progress_pct"] = attempts["n"]
            fake.set(_job_key(job_id), json.dumps(payload))

        store.connect_redis(_InterleavingClient(fake, bump_record))
        store.start(job_id)

        assert attempts["n"] == WATCH_MAX_ATTEMPTS
        assert json.loads(fake.get(_job_key(job_id)))["status"] == "queued"
        assert fake.sismember(ACTIVE, job_id)  # unchanged from create
        assert store._memory_jobs == {}
        assert "contention retries" in caplog.text


class TestPhaseWriters:
    def test_phase_update_after_finish_does_not_rewrite_terminal_record(self):
        store, fake = _new_store()
        job_id = store.create("https://github.com/test/repo", {})
        store.start(job_id)
        result = {"onboarding_doc": "x" * 1024}
        store.finish(job_id, result)

        store.update_phase(job_id, "ingestion", 20)
        store.complete_phase(job_id, "ingestion")

        job = store.get(job_id)
        assert job.status == "complete"
        assert job.result == result
        assert job.current_phase is None
        assert job.phases_completed == []
        assert not fake.sismember(ACTIVE, job_id)
        assert store.active_count() == 0
        _assert_fast_matches_legacy(store)

    def test_finish_between_phase_read_and_write_aborts_and_retries(self):
        store, fake = _new_store()
        job_id = store.create("https://github.com/test/repo", {})
        store.start(job_id)

        def finish_now():
            payload = json.loads(fake.get(_job_key(job_id)))
            payload["status"] = "complete"
            payload["result"] = {"kept": True}
            payload["progress_pct"] = 100
            fake.set(_job_key(job_id), json.dumps(payload))
            fake.srem(ACTIVE, job_id)

        store.connect_redis(_InterleavingClient(fake, _once(finish_now)))
        store.update_phase(job_id, "ingestion", 30)

        job = store.get(job_id)
        assert job.status == "complete"
        assert job.result == {"kept": True}
        assert job.progress_pct == 100
        assert not fake.sismember(ACTIVE, job_id)
        assert store.active_count() == store._legacy_active_count() == 0

    def test_phase_retry_exhaustion_leaves_record_unchanged(self, caplog):
        store, fake = _new_store()
        job_id = store.create("https://github.com/test/repo", {})
        store.start(job_id)
        attempts = {"n": 0}

        def bump_record():
            attempts["n"] += 1
            payload = json.loads(fake.get(_job_key(job_id)))
            payload["options"] = {"bump": attempts["n"]}
            fake.set(_job_key(job_id), json.dumps(payload))

        store.connect_redis(_InterleavingClient(fake, bump_record))
        store.update_phase(job_id, "ingestion", 42)

        assert attempts["n"] == WATCH_MAX_ATTEMPTS
        job = store.get(job_id)
        assert job.status == "running"
        assert job.current_phase is None
        assert job.progress_pct == 0
        assert store._memory_jobs == {}
        assert "contention retries" in caplog.text


class TestReconciliation:
    def test_empty_state_can_be_armed(self):
        store, fake = _new_store()
        stats = store.rebuild_active_index(arm=True)
        assert stats["armed"] == 1
        assert fake.smembers(ACTIVE) == {ACTIVE_INDEX_SENTINEL}
        assert store.active_count() == 0
        assert store._legacy_active_count() == 0

    def test_failed_initial_reconciliation_does_not_arm(self, monkeypatch):
        store, fake = _new_store()
        _seed_record(fake, "a", "queued")
        _seed_record(fake, "b", "running")
        _seed_record(fake, "c", "complete")

        original = store._reconcile_active_member
        calls = {"n": 0}

        def fail_on_second(job_id):
            calls["n"] += 1
            if calls["n"] == 2:
                raise ActiveIndexReconcileError("injected failure")
            return original(job_id)

        monkeypatch.setattr(store, "_reconcile_active_member", fail_on_second)
        with pytest.raises(ActiveIndexReconcileError):
            store.rebuild_active_index(arm=True)

        assert not fake.sismember(ACTIVE, ACTIVE_INDEX_SENTINEL)
        # Unarmed: health falls back to the exact legacy path.
        assert store.active_count() == store._legacy_active_count() == 2

        # A normal create after the failed pass must not arm the fast path.
        store.create("https://github.com/test/new", {})
        assert not fake.sismember(ACTIVE, ACTIVE_INDEX_SENTINEL)

    def test_reconciliation_converges_legacy_state(self):
        store, fake = _new_store()
        _seed_record(fake, "queued", "queued")
        _seed_record(fake, "running", "running")
        _seed_record(fake, "done", "complete")
        _seed_record(fake, "failed", "failed")
        fake.sadd(INDEX, "missing")
        fake.set(_job_key("broken"), "{not json")
        fake.sadd(INDEX, "broken")

        stats = store.rebuild_active_index(arm=True)

        assert stats["armed"] == 1
        assert fake.smembers(ACTIVE) == {
            ACTIVE_INDEX_SENTINEL,
            "queued",
            "running",
        }
        assert store.active_count() == 2
        assert store.active_count() == store._legacy_active_count()

        # Idempotent second pass.
        store.rebuild_active_index(arm=True)
        assert store.active_count() == 2

    def test_interrupted_armed_reconciliation_keeps_sentinel_and_repairs(self, monkeypatch):
        store, fake = _new_store()
        _seed_record(fake, "done", "complete")
        fake.sadd(ACTIVE, "done")
        store.rebuild_active_index(arm=True)
        assert fake.sismember(ACTIVE, ACTIVE_INDEX_SENTINEL)

        # Re-introduce a stale member reached in the index scan, plus a second
        # stale member reached in the active scan. Fail before repairing the
        # second so one repair is retained and the pass is interrupted.
        fake.sadd(ACTIVE, "done")
        fake.sadd(ACTIVE, "unindexed-member")
        original = store._reconcile_active_member
        calls = {"n": 0}

        def fail_after_one(job_id):
            calls["n"] += 1
            if calls["n"] == 1:
                return original(job_id)
            raise ActiveIndexReconcileError("injected failure")

        monkeypatch.setattr(store, "_reconcile_active_member", fail_after_one)
        with pytest.raises(ActiveIndexReconcileError):
            store.rebuild_active_index(arm=True)

        # The already-armed sentinel is not removed, the completed repair is
        # retained, and the interrupted member is left for the next run. The
        # failed run does not claim the whole set was converged.
        assert fake.sismember(ACTIVE, ACTIVE_INDEX_SENTINEL)
        assert not fake.sismember(ACTIVE, "done")
        assert fake.sismember(ACTIVE, "unindexed-member")
        assert store.active_count() == 1  # sentinel + unresolved member - 1

    def test_delete_during_reconciliation(self, monkeypatch):
        store, fake = _new_store()
        _seed_record(fake, "a", "queued")
        _seed_record(fake, "b", "running")

        original = store._reconcile_active_member
        calls = {"n": 0}

        def delete_other(job_id):
            calls["n"] += 1
            if calls["n"] == 1:
                store.delete("b" if job_id == "a" else "a")
            return original(job_id)

        monkeypatch.setattr(store, "_reconcile_active_member", delete_other)
        store.rebuild_active_index(arm=True)

        remaining = fake.smembers(INDEX)
        assert len(remaining) == 1
        assert fake.smembers(ACTIVE) == {ACTIVE_INDEX_SENTINEL, next(iter(remaining))}
        assert store.active_count() == store._legacy_active_count() == 1

    def test_create_during_reconciliation_is_self_registered(self, monkeypatch):
        store, fake = _new_store()
        _seed_record(fake, "a", "queued")

        original = store._reconcile_active_member
        calls = {"n": 0}
        created = {}

        def create_other(job_id):
            calls["n"] += 1
            if calls["n"] == 1:
                created["id"] = store.create("https://github.com/test/new", {})
            return original(job_id)

        monkeypatch.setattr(store, "_reconcile_active_member", create_other)
        store.rebuild_active_index(arm=True)

        assert fake.sismember(ACTIVE, created["id"])
        assert store.active_count() == store._legacy_active_count() == 2


class TestKeyLossAndDrift:
    def test_lost_active_set_falls_back_and_create_cannot_arm(self):
        store, fake = _new_store()
        job_id = store.create("https://github.com/test/repo", {})
        store.rebuild_active_index(arm=True)
        fake.delete(ACTIVE)

        assert store.active_count() == 1
        assert store.active_count() == store._legacy_active_count()

        # A normal create recreates the set but must not add the sentinel.
        newer = store.create("https://github.com/test/newer", {})
        assert fake.exists(ACTIVE)
        assert not fake.sismember(ACTIVE, ACTIVE_INDEX_SENTINEL)
        assert store.active_count() == 2
        assert store.active_count() == store._legacy_active_count()

        # Explicit reconciliation restores the fast path.
        store.rebuild_active_index(arm=True)
        assert fake.sismember(ACTIVE, ACTIVE_INDEX_SENTINEL)
        assert store.active_count() == 2

    def test_lost_sentinel_falls_back(self):
        store, fake = _new_store()
        store.create("https://github.com/test/repo", {})
        store.rebuild_active_index(arm=True)
        fake.srem(ACTIVE, ACTIVE_INDEX_SENTINEL)

        assert not fake.sismember(ACTIVE, ACTIVE_INDEX_SENTINEL)
        assert store.active_count() == 1
        assert store.active_count() == store._legacy_active_count()

    def test_lost_record_overcounts_until_reconciled(self):
        store, fake = _new_store()
        job_id = store.create("https://github.com/test/repo", {})
        store.rebuild_active_index(arm=True)

        fake.delete(_job_key(job_id))  # eviction/expiry of an active record

        assert store.active_count() == 1  # fast overcount (disclosed)
        assert store._legacy_active_count() == 0
        store._reconcile_active_member(job_id)
        assert store.active_count() == 0
        assert store.active_count() == store._legacy_active_count()

    def test_lost_index_overcounts_until_reconciled(self):
        store, fake = _new_store()
        store.create("https://github.com/test/repo", {})
        store.rebuild_active_index(arm=True)

        fake.delete(INDEX)

        assert store.active_count() == 1  # fast overcount (disclosed)
        assert store._legacy_active_count() == 0
        store.rebuild_active_index(arm=True)
        assert store.active_count() == 0
        assert store.active_count() == store._legacy_active_count()

    def test_external_member_removal_undercounts_until_reconciled(self):
        store, fake = _new_store()
        job_id = store.create("https://github.com/test/repo", {})
        store.rebuild_active_index(arm=True)

        fake.srem(ACTIVE, job_id)  # external mutation

        assert store.active_count() == 0  # fast undercount (disclosed)
        assert store._legacy_active_count() == 1
        store._reconcile_active_member(job_id)
        assert store.active_count() == 1

    def test_expiry_of_completed_record_does_not_affect_count(self, monkeypatch):
        monkeypatch.setenv("JOB_TTL_SECONDS", "60")
        store, fake = _new_store()
        job_id = store.create("https://github.com/test/repo", {})
        store.start(job_id)
        store.finish(job_id, {"done": True})
        store.rebuild_active_index(arm=True)

        ttl = fake.ttl(_job_key(job_id))
        assert ttl > 0
        assert store.active_count() == 0
        assert store.active_count() == store._legacy_active_count()

        fake.delete(_job_key(job_id))  # simulate expiry
        assert store.active_count() == 0

    def test_active_record_expiry_overcounts_until_reconciled(self):
        store, fake = _new_store()
        job_id = store.create("https://github.com/test/repo", {})
        store.rebuild_active_index(arm=True)

        fake.delete(_job_key(job_id))  # simulate expiry/eviction

        assert store.active_count() == 1
        assert store._legacy_active_count() == 0
        store._reconcile_active_member(job_id)
        assert store.active_count() == 0


class TestErrorsAndMemoryMode:
    def test_pipeline_failure_falls_back_to_legacy_count(self):
        store, fake = _new_store()
        store.create("https://github.com/test/active", {})
        completed = store.create("https://github.com/test/completed", {})
        store.finish(completed, {"done": True})

        class _PipelineFailure:
            def __init__(self):
                self.commands = []

            def pipeline(self, *args, **kwargs):
                self.commands.append("pipeline")
                raise RuntimeError("redis down")

            def __getattr__(self, name):
                attr = getattr(fake, name)

                def wrapper(*args, **kwargs):
                    self.commands.append(name)
                    return attr(*args, **kwargs)
                return wrapper

        failing = _PipelineFailure()
        store.connect_redis(failing)

        assert store.active_count() == 1
        assert "smembers" in failing.commands
        assert "mget" in failing.commands

    def test_both_redis_read_paths_fail_returns_original_memory_fallback(self):
        store = JobStore()
        store.create("https://github.com/test/memory-job", {})
        assert store.active_count() == 1

        class _BothReadPathsFailure:
            def __init__(self):
                self.commands = []

            def pipeline(self, *args, **kwargs):
                self.commands.append("pipeline")
                raise RuntimeError("redis pipeline down")

            def smembers(self, *args, **kwargs):
                self.commands.append("smembers")
                return ["unreadable-job"]

            def mget(self, *args, **kwargs):
                self.commands.append("mget")
                raise RuntimeError("redis mget down")

        failing = _BothReadPathsFailure()
        store.connect_redis(failing)

        # list_all() catches the legacy Redis failure and returns memory jobs;
        # that preserves the pre-change memory fallback count.
        assert store.active_count() == 1
        assert "pipeline" in failing.commands
        assert "smembers" in failing.commands
        assert "mget" in failing.commands

    def test_reconcile_retry_exhaustion_raises(self):
        store, fake = _new_store()
        _seed_record(fake, "a", "queued")
        attempts = {"n": 0}

        def bump_index():
            attempts["n"] += 1
            fake.sadd(INDEX, "noise")
            fake.srem(INDEX, "noise")

        store.connect_redis(_InterleavingClient(fake, bump_index))
        with pytest.raises(ActiveIndexReconcileError):
            store._reconcile_active_member("a")
        assert attempts["n"] == WATCH_MAX_ATTEMPTS

    def test_migration_cli_refuses_to_arm_without_writer_confirmation(self):
        from src.api.job_store_migrate import main as migrate_main

        assert migrate_main(["--arm"]) == 2

    def test_memory_mode_lifecycle_unchanged(self):
        store = JobStore()
        assert store.backend == "memory"

        job_id = store.create("https://github.com/test/repo", {})
        assert store.active_count() == 1
        store.start(job_id)
        assert store.active_count() == 1
        store.update_phase(job_id, "ingestion", 20)
        store.complete_phase(job_id, "ingestion")
        assert store.get(job_id).current_phase == "ingestion"
        assert store.active_count() == 1
        store.finish(job_id, {"done": True})
        assert store.active_count() == 0
        store.fail(job_id, "late")
        assert store.active_count() == 0
        assert store.delete(job_id) is True
        store.clear()
        assert store.list_all() == []

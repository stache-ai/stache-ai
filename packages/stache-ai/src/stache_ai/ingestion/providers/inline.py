"""Inline / null / self-hosted implementations of the ingestion seams.

These are the synchronous tier: no external services, stdlib only. They let the
existing pipeline run in-process behind the uniform POST /ingest contract.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading

from ..base import (
    BlobStore,
    IntakeProvider,
    IntakeTicket,
    Job,
    JobStatus,
    JobStore,
    Notifier,
    QueueProvider,
)


class NullBlobStore(BlobStore):
    """No original retention."""

    def put(self, key, data, metadata):
        return key

    def get(self, key):
        raise KeyError("NullBlobStore retains nothing")


class FilesystemBlobStore(BlobStore):
    """Persist originals on local disk (self-hosted option)."""

    def __init__(self, root: str):
        self.root = root
        os.makedirs(root, exist_ok=True)

    def _path(self, key: str) -> str:
        # Guard against path traversal from caller-supplied keys.
        path = os.path.normpath(os.path.join(self.root, key))
        if not path.startswith(os.path.abspath(self.root) + os.sep) and path != os.path.abspath(self.root):
            raise ValueError(f"Invalid blob key escapes root: {key!r}")
        return path

    def put(self, key, data, metadata):
        path = self._path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        with open(path + ".meta.json", "w") as f:
            json.dump(metadata, f)
        return key

    def get(self, key):
        path = self._path(key)
        with open(path, "rb") as f:
            data = f.read()
        meta = {}
        if os.path.exists(path + ".meta.json"):
            with open(path + ".meta.json") as f:
                meta = json.load(f)
        return data, meta


class EphemeralJobStore(JobStore):
    """In-process dict. Fine for sync tier (job returned inline) + tests."""

    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, job, *, principal=None):
        with self._lock:
            self._jobs[job.job_id] = job

    def update(self, job_id, **fields):
        with self._lock:
            job = self._jobs[job_id]
            for k, v in fields.items():
                setattr(job, k, v)
            return job

    def get(self, job_id):
        with self._lock:
            return self._jobs.get(job_id)

    def list(self, *, requested_by=None, status=None, limit=50, cursor=None,
             principal=None):
        with self._lock:
            jobs = [
                j for j in self._jobs.values()
                if (requested_by is None or j.requested_by == requested_by)
                and (status is None or j.status == status)
            ]
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs[:limit], None


class SqliteJobStore(JobStore):
    """Persistent JobStore for self-hosted deploys. Stdlib sqlite3 only.

    One table `jobs`: indexed columns for the query paths (requested_by,
    created_at, status, updated_at) plus a JSON `payload` holding the full Job.
    """

    def __init__(self, path: str):
        self._path = path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    requested_by TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    payload TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_owner ON jobs (requested_by, created_at)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status, updated_at)"
            )

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> Job:
        return Job.from_dict(json.loads(row["payload"]))

    def create(self, job, *, principal=None):
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO jobs (job_id, status, requested_by, created_at, updated_at, payload) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    job.job_id,
                    job.status.value,
                    job.requested_by,
                    job.created_at,
                    job.updated_at,
                    json.dumps(job.to_dict()),
                ),
            )

    def update(self, job_id, **fields):
        with self._lock, self._conn:
            cur = self._conn.execute("SELECT payload FROM jobs WHERE job_id = ?", (job_id,))
            row = cur.fetchone()
            if row is None:
                raise KeyError(job_id)
            job = Job.from_dict(json.loads(row["payload"]))
            for k, v in fields.items():
                setattr(job, k, v)
            self._conn.execute(
                "UPDATE jobs SET status = ?, requested_by = ?, created_at = ?, "
                "updated_at = ?, payload = ? WHERE job_id = ?",
                (
                    job.status.value,
                    job.requested_by,
                    job.created_at,
                    job.updated_at,
                    json.dumps(job.to_dict()),
                    job_id,
                ),
            )
            return job

    def get(self, job_id):
        with self._lock:
            cur = self._conn.execute("SELECT payload FROM jobs WHERE job_id = ?", (job_id,))
            row = cur.fetchone()
        return self._row_to_job(row) if row else None

    def list(self, *, requested_by=None, status=None, limit=50, cursor=None,
             principal=None):
        clauses, params = [], []
        if requested_by is not None:
            clauses.append("requested_by = ?")
            params.append(requested_by)
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        with self._lock:
            cur = self._conn.execute(
                f"SELECT payload FROM jobs{where} ORDER BY created_at DESC LIMIT ?",
                params,
            )
            rows = cur.fetchall()
        return [self._row_to_job(r) for r in rows], None

    def list_stuck(self, older_than_iso: str) -> list[Job]:
        active = [JobStatus.QUEUED.value, JobStatus.UPLOADING.value, JobStatus.PROCESSING.value]
        placeholders = ",".join("?" for _ in active)
        with self._lock:
            cur = self._conn.execute(
                f"SELECT payload FROM jobs WHERE status IN ({placeholders}) AND updated_at < ?",
                [*active, older_than_iso],
            )
            rows = cur.fetchall()
        return [self._row_to_job(r) for r in rows]


class NullNotifier(Notifier):
    def publish(self, event):
        pass


class InlineIntake(IntakeProvider):
    """No separate upload step - bytes arrive with POST /ingest."""

    def begin(self, *, job_id, **_):
        return IntakeTicket(job_id=job_id, upload_url=None)


class InlineQueue(QueueProvider):
    """enqueue() awaits the worker now => job is born terminal. (worker is async)"""

    def __init__(self, worker):
        self._worker = worker      # async callable

    async def enqueue(self, job_id):
        await self._worker(job_id)

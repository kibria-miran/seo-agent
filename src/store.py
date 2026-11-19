"""SQLite state, TTL cache and snapshot diffs (D-8, D-9, section 9).

One connection per Store. WAL, foreign keys and a 5 s busy timeout are set on
open. Writes are grouped into explicit transactions by the caller-facing
methods, so a killed run leaves the last committed step intact.

Diffs are computed here in code, never by the LLM.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from src import clock, config
from src.models import (
    AuditDiff,
    AuditSnapshot,
    BacklogItem,
    CompetitorPage,
    Gap,
    Keyword,
    PageData,
    SEOIssue,
    SerpResult,
)


class StoreError(RuntimeError):
    """Clear, actionable persistence failure (disk full, locked DB, etc.)."""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    url         TEXT NOT NULL DEFAULT '',
    domain      TEXT NOT NULL DEFAULT '',
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL,
    site_score  REAL NOT NULL DEFAULT 0,
    grade       TEXT NOT NULL DEFAULT 'F',
    llm_calls   INTEGER NOT NULL DEFAULT 0,
    tokens_in   INTEGER NOT NULL DEFAULT 0,
    tokens_out  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS audit_pages (
    run_id            TEXT NOT NULL,
    url               TEXT NOT NULL,
    status_code       INTEGER NOT NULL DEFAULT 0,
    title             TEXT,
    meta_desc         TEXT,
    h1_count          INTEGER NOT NULL DEFAULT 0,
    word_count        INTEGER NOT NULL DEFAULT 0,
    page_score        REAL NOT NULL DEFAULT 0,
    issues_json       TEXT NOT NULL DEFAULT '[]',
    h_tags_json       TEXT NOT NULL DEFAULT '{}',
    schema_types_json TEXT NOT NULL DEFAULT '[]',
    response_time_ms  REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (run_id, url),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS audit_issues (
    run_id        TEXT NOT NULL,
    page_url      TEXT NOT NULL,
    issue_type    TEXT NOT NULL,
    severity      TEXT NOT NULL,
    current_value TEXT NOT NULL DEFAULT '',
    suggestion    TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS keywords (
    run_id         TEXT NOT NULL,
    keyword        TEXT NOT NULL,
    source         TEXT NOT NULL DEFAULT '',
    cluster_id     TEXT,
    intent         TEXT NOT NULL DEFAULT 'informational',
    city           TEXT,
    gsc_clicks     REAL,
    gsc_impressions REAL,
    gsc_ctr        REAL,
    gsc_position   REAL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS serp (
    run_id  TEXT NOT NULL,
    query   TEXT NOT NULL,
    rank    INTEGER NOT NULL,
    url     TEXT NOT NULL,
    title   TEXT NOT NULL DEFAULT '',
    snippet TEXT NOT NULL DEFAULT '',
    domain  TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS competitor_pages (
    run_id            TEXT NOT NULL,
    domain            TEXT NOT NULL,
    url               TEXT NOT NULL,
    title             TEXT NOT NULL DEFAULT '',
    h_tags_json       TEXT NOT NULL DEFAULT '{}',
    word_count        INTEGER NOT NULL DEFAULT 0,
    schema_types_json TEXT NOT NULL DEFAULT '[]',
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS gaps (
    run_id        TEXT NOT NULL,
    keyword       TEXT NOT NULL,
    cluster_id    TEXT NOT NULL DEFAULT '',
    gap_type      TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    sources_json  TEXT NOT NULL DEFAULT '[]',
    target        TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS backlog (
    run_id   TEXT NOT NULL,
    item_id  TEXT NOT NULL,
    kind     TEXT NOT NULL,
    target   TEXT NOT NULL,
    priority REAL NOT NULL,
    effort   INTEGER NOT NULL,
    impact   INTEGER NOT NULL,
    status   TEXT NOT NULL DEFAULT 'open',
    confidence REAL NOT NULL DEFAULT 1.0,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    title    TEXT NOT NULL DEFAULT '',
    gap_type TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (run_id, item_id),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cache (
    key         TEXT PRIMARY KEY,
    fetched_at  REAL NOT NULL,
    ttl_seconds INTEGER NOT NULL,
    payload     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_issues_run ON audit_issues(run_id);
CREATE INDEX IF NOT EXISTS idx_keywords_run ON keywords(run_id);
CREATE INDEX IF NOT EXISTS idx_gaps_run ON gaps(run_id);
CREATE INDEX IF NOT EXISTS idx_backlog_run ON backlog(run_id);
"""


def _iso(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.isoformat(timespec="seconds")


def _epoch(value: datetime | float | None) -> float:
    if value is None:
        return clock.now().timestamp()
    if isinstance(value, datetime):
        return value.timestamp()
    return float(value)


def cache_key(source: str, query: str) -> str:
    """Stable cache key (I-3): ``source|query``, never a calendar date."""

    return f"{source}|{query.strip().casefold()}"


def _canonical_page(url: str) -> str:
    """Comparison key for a page URL: scheme, ``www.`` and trailing slash insensitive.

    A run sees ``https://www.example.com/x`` and the next sees
    ``https://example.com/x`` depending on how the profile spells the domain.
    Comparing raw URLs reports every issue as both new and closed (seen in
    ``run-live-real-2``), so the diff keys on the canonical form and renders
    the URL from the run it belongs to.
    """

    raw = (url or "").strip().casefold()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"https://{raw}"
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return raw
    host = (parsed.hostname or "").removeprefix("www.")
    path = parsed.path.rstrip("/") or "/"
    return f"{host}{path}"


def diff_snapshots(previous: AuditSnapshot | None, current: AuditSnapshot) -> AuditDiff:
    def issue_map(snapshot: AuditSnapshot | None) -> dict[tuple[str, str], str]:
        if snapshot is None:
            return {}
        return {
            (_canonical_page(issue.page_url), issue.issue_type): issue.page_url
            for issue in snapshot.issues
        }

    previous_issues = issue_map(previous)
    current_issues = issue_map(current)

    def render(items: dict[tuple[str, str], str]) -> list[str]:
        return sorted(f"{page} :: {issue[1]}" for issue, page in items.items())

    new_items = render(
        {key: current_issues[key] for key in current_issues.keys() - previous_issues.keys()}
    )
    closed_items = render(
        {key: previous_issues[key] for key in previous_issues.keys() - current_issues.keys()}
    )
    score_delta = (
        round(current.site_score - previous.site_score, 4) if previous is not None else None
    )
    return AuditDiff(
        score_delta=score_delta,
        new_items=new_items,
        closed_items=closed_items,
        # Gap diffs are computed in diff_runs() against Gap rows, not snapshots.
        new_gaps=[],
        closed_gaps=[],
    )


def diff_gaps(previous: Sequence[Gap], current: Sequence[Gap]) -> tuple[list[str], list[str]]:
    before = {(g.keyword, g.gap_type.value) for g in previous}
    after = {(g.keyword, g.gap_type.value) for g in current}
    def render(items: set[tuple[str, str]]) -> list[str]:
        return sorted(f"{keyword} :: {kind}" for keyword, kind in items)

    return render(after - before), render(before - after)


class Store:
    def __init__(self, path: str | Path | None = None) -> None:
        raw = str(path if path is not None else config.DB_PATH)
        self.path = raw
        if raw != ":memory:":
            Path(raw).parent.mkdir(parents=True, exist_ok=True)
        try:
            self.conn = sqlite3.connect(raw, timeout=5.0, isolation_level=None)
        except sqlite3.Error as exc:  # pragma: no cover - hard to force
            raise StoreError(f"cannot open SQLite database {raw!r}: {exc}") from exc
        self.conn.row_factory = sqlite3.Row
        try:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.execute("PRAGMA busy_timeout=5000")
            self.conn.executescript(_SCHEMA)
            columns = {
                row["name"] for row in self.conn.execute("PRAGMA table_info(keywords)")
            }
            for column in ("gsc_clicks", "gsc_impressions", "gsc_ctr", "gsc_position"):
                if column not in columns:
                    self.conn.execute(f"ALTER TABLE keywords ADD COLUMN {column} REAL")
            try:
                self.conn.execute("BEGIN IMMEDIATE")
                run_columns = {
                    row["name"] for row in self.conn.execute("PRAGMA table_info(runs)")
                }
                if "domain" not in run_columns:
                    self.conn.execute(
                        "ALTER TABLE runs ADD COLUMN domain TEXT NOT NULL DEFAULT ''"
                    )
                for row in self.conn.execute(
                    "SELECT run_id, url FROM runs WHERE domain = ''"
                ).fetchall():
                    self.conn.execute(
                        "UPDATE runs SET domain = ? WHERE run_id = ?",
                        (config.normalize_domain(row["url"]), row["run_id"]),
                    )
                self.conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_runs_domain ON runs(domain)"
                )
                self.conn.execute("COMMIT")
            except sqlite3.Error:
                self.conn.execute("ROLLBACK")
                raise
        except sqlite3.Error as exc:
            self.conn.close()
            raise StoreError(f"cannot initialise SQLite database {raw!r}: {exc}") from exc

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Store:  # noqa: PYI034 - py310 has no typing.Self
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            yield self.conn
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    def table_names(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        return [row["name"] for row in rows]

    # -- runs --------------------------------------------------------------

    def start_run(self, run_id: str, url: str = "", started_at: datetime | str | None = None) -> None:
        with self.transaction() as conn:
            # Re-running the same run_id is idempotent: cascade clears children.
            conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            conn.execute(
                "INSERT INTO runs(run_id, url, domain, started_at, status) VALUES (?, ?, ?, ?, 'running')",
                (run_id, url, config.normalize_domain(url), _iso(started_at or clock.now())),
            )

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        site_score: float = 0.0,
        grade: str = "F",
        llm_calls: int = 0,
        tokens_in: int = 0,
        tokens_out: int = 0,
        finished_at: datetime | str | None = None,
    ) -> None:
        with self.transaction() as conn:
            conn.execute(
                """UPDATE runs
                   SET finished_at = ?, status = ?, site_score = ?, grade = ?,
                       llm_calls = ?, tokens_in = ?, tokens_out = ?
                   WHERE run_id = ?""",
                (
                    _iso(finished_at or clock.now()),
                    status,
                    site_score,
                    grade,
                    llm_calls,
                    tokens_in,
                    tokens_out,
                    run_id,
                ),
            )

    def mark_running_as_aborted(self, except_run_id: str | None = None) -> int:
        with self.transaction() as conn:
            if except_run_id:
                cursor = conn.execute(
                    "UPDATE runs SET status='aborted', finished_at=? WHERE status='running' AND run_id != ?",
                    (_iso(clock.now()), except_run_id),
                )
            else:
                cursor = conn.execute(
                    "UPDATE runs SET status='aborted', finished_at=? WHERE status='running'",
                    (_iso(clock.now()),),
                )
            return cursor.rowcount

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def latest_run(
        self,
        exclude: str | None = None,
        domain: str | None = None,
        completed_only: bool = False,
    ) -> dict[str, Any] | None:
        clauses: list[str] = []
        params: list[Any] = []
        if exclude:
            clauses.append("run_id != ?")
            params.append(exclude)
        if domain:
            clauses.append("domain = ?")
            params.append(config.normalize_domain(domain))
        if completed_only:
            clauses.append("status = 'ok'")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        row = self.conn.execute(
            f"SELECT * FROM runs{where} ORDER BY started_at DESC, run_id DESC LIMIT 1",  # noqa: S608 - clauses are literal strings, only params are variable
            params,
        ).fetchone()
        return dict(row) if row else None

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM runs ORDER BY started_at DESC, run_id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]

    # -- audit snapshot ----------------------------------------------------

    def save_audit(self, run_id: str, audit: AuditSnapshot) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM audit_pages WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM audit_issues WHERE run_id = ?", (run_id,))
            for page in sorted(audit.pages, key=lambda item: item.url):
                page_issues = [issue.model_dump(mode="json") for issue in page.issues]
                conn.execute(
                    """INSERT INTO audit_pages(
                           run_id, url, status_code, title, meta_desc, h1_count,
                           word_count, page_score, issues_json, h_tags_json,
                           schema_types_json, response_time_ms)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_id,
                        page.url,
                        page.status_code,
                        page.title,
                        page.meta_description,
                        page.h1_count,
                        page.word_count,
                        page.page_score,
                        json.dumps(page_issues, sort_keys=True),
                        json.dumps(page.h_tags, sort_keys=True),
                        json.dumps(page.schema_types, sort_keys=True),
                        page.response_time_ms,
                    ),
                )
            # Top-level issues are authoritative, but accept page-attached
            # issues too so a hand-built fixture cannot silently lose them.
            issues = list(audit.issues) or [
                issue for page in audit.pages for issue in page.issues
            ]
            for issue in sorted(
                issues,
                key=lambda item: (item.page_url, item.issue_type, item.severity.value),
            ):
                conn.execute(
                    """INSERT INTO audit_issues(
                           run_id, page_url, issue_type, severity, current_value, suggestion)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        run_id,
                        issue.page_url,
                        issue.issue_type,
                        issue.severity.value,
                        issue.current_value,
                        issue.suggestion,
                    ),
                )

    def load_audit(self, run_id: str) -> AuditSnapshot:
        run = self.get_run(run_id)
        if run is None:
            raise StoreError(f"unknown run_id: {run_id}")
        issue_rows = self.conn.execute(
            """SELECT * FROM audit_issues WHERE run_id = ?
               ORDER BY page_url, issue_type, severity, current_value, suggestion""",
            (run_id,),
        ).fetchall()
        issues = [
            SEOIssue(
                page_url=row["page_url"],
                issue_type=row["issue_type"],
                severity=row["severity"],
                current_value=row["current_value"],
                suggestion=row["suggestion"],
            )
            for row in issue_rows
        ]
        by_page: dict[str, list[SEOIssue]] = {}
        for issue in issues:
            by_page.setdefault(issue.page_url, []).append(issue)

        page_rows = self.conn.execute(
            "SELECT * FROM audit_pages WHERE run_id = ? ORDER BY url", (run_id,)
        ).fetchall()
        pages = [
            PageData(
                url=row["url"],
                status_code=row["status_code"],
                title=row["title"],
                meta_description=row["meta_desc"],
                h1_count=row["h1_count"],
                word_count=row["word_count"],
                page_score=row["page_score"],
                response_time_ms=row["response_time_ms"],
                h_tags=json.loads(row["h_tags_json"] or "{}"),
                h1_tags=json.loads(row["h_tags_json"] or "{}").get("h1", []),
                schema_types=json.loads(row["schema_types_json"] or "[]"),
                issues=by_page.get(row["url"], []),
            )
            for row in page_rows
        ]
        return AuditSnapshot(
            url=run["url"],
            site_score=run["site_score"],
            grade=run["grade"],
            pages_crawled=len(pages),
            total_issues=len(issues),
            pages=pages,
            issues=issues,
        )

    # -- demand data -------------------------------------------------------

    def save_keywords(self, run_id: str, keywords: Sequence[Keyword]) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM keywords WHERE run_id = ?", (run_id,))
            conn.executemany(
                "INSERT INTO keywords(run_id, keyword, source, cluster_id, intent, city, "
                "gsc_clicks, gsc_impressions, gsc_ctr, gsc_position) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        run_id,
                        k.keyword,
                        k.source,
                        k.cluster_id,
                        k.intent.value,
                        k.city,
                        k.gsc_clicks,
                        k.gsc_impressions,
                        k.gsc_ctr,
                        k.gsc_position,
                    )
                    for k in sorted(keywords, key=lambda item: (item.keyword, item.source))
                ],
            )

    def load_keywords(self, run_id: str) -> list[Keyword]:
        rows = self.conn.execute(
            "SELECT * FROM keywords WHERE run_id = ? ORDER BY keyword, source", (run_id,)
        ).fetchall()
        return [
            Keyword(
                keyword=row["keyword"],
                source=row["source"],
                cluster_id=row["cluster_id"],
                intent=row["intent"],
                city=row["city"],
                gsc_clicks=row["gsc_clicks"],
                gsc_impressions=row["gsc_impressions"],
                gsc_ctr=row["gsc_ctr"],
                gsc_position=row["gsc_position"],
            )
            for row in rows
        ]

    def save_serp(self, run_id: str, results: Sequence[SerpResult]) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM serp WHERE run_id = ?", (run_id,))
            conn.executemany(
                "INSERT INTO serp(run_id, query, rank, url, title, snippet, domain) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (run_id, r.query, r.rank, r.url, r.title, r.snippet, r.domain)
                    for r in sorted(results, key=lambda item: (item.query, item.rank, item.url))
                ],
            )

    def load_serp(self, run_id: str) -> list[SerpResult]:
        rows = self.conn.execute(
            "SELECT * FROM serp WHERE run_id = ? ORDER BY query, rank, url", (run_id,)
        ).fetchall()
        return [
            SerpResult(
                query=row["query"],
                rank=row["rank"],
                url=row["url"],
                title=row["title"],
                snippet=row["snippet"],
                domain=row["domain"],
            )
            for row in rows
        ]

    def save_competitor_pages(self, run_id: str, pages: Sequence[CompetitorPage]) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM competitor_pages WHERE run_id = ?", (run_id,))
            conn.executemany(
                """INSERT INTO competitor_pages(
                       run_id, domain, url, title, h_tags_json, word_count, schema_types_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        run_id,
                        page.domain,
                        page.url,
                        page.title,
                        json.dumps(page.h_tags, sort_keys=True),
                        page.word_count,
                        json.dumps(page.schema_types, sort_keys=True),
                    )
                    for page in sorted(pages, key=lambda item: (item.domain, item.url))
                ],
            )

    def load_competitor_pages(self, run_id: str) -> list[CompetitorPage]:
        rows = self.conn.execute(
            "SELECT * FROM competitor_pages WHERE run_id = ? ORDER BY domain, url", (run_id,)
        ).fetchall()
        return [
            CompetitorPage(
                domain=row["domain"],
                url=row["url"],
                title=row["title"],
                h_tags=json.loads(row["h_tags_json"] or "{}"),
                word_count=row["word_count"],
                schema_types=json.loads(row["schema_types_json"] or "[]"),
            )
            for row in rows
        ]

    # -- gaps / backlog ----------------------------------------------------

    def save_gaps(self, run_id: str, gaps: Sequence[Gap]) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM gaps WHERE run_id = ?", (run_id,))
            conn.executemany(
                """INSERT INTO gaps(run_id, keyword, cluster_id, gap_type, evidence_json, sources_json, target)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        run_id,
                        gap.keyword,
                        gap.cluster_id,
                        gap.gap_type.value,
                        json.dumps(gap.evidence, sort_keys=True),
                        json.dumps(sorted(set(gap.sources)), sort_keys=True),
                        gap.target,
                    )
                    for gap in sorted(
                        gaps, key=lambda item: (item.gap_type.value, item.keyword, item.target or "")
                    )
                ],
            )

    def load_gaps(self, run_id: str) -> list[Gap]:
        rows = self.conn.execute(
            "SELECT * FROM gaps WHERE run_id = ? ORDER BY gap_type, keyword, target", (run_id,)
        ).fetchall()
        return [
            Gap(
                keyword=row["keyword"],
                cluster_id=row["cluster_id"],
                gap_type=row["gap_type"],
                evidence=json.loads(row["evidence_json"] or "{}"),
                sources=json.loads(row["sources_json"] or "[]"),
                target=row["target"],
            )
            for row in rows
        ]

    def save_backlog(self, run_id: str, items: Sequence[BacklogItem]) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM backlog WHERE run_id = ?", (run_id,))
            conn.executemany(
                """INSERT INTO backlog(
                       run_id, item_id, kind, target, priority, effort, impact,
                       status, confidence, evidence_json, title, gap_type)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        run_id,
                        item.item_id,
                        item.kind,
                        item.target,
                        item.priority,
                        item.effort,
                        item.impact,
                        item.status,
                        item.confidence,
                        json.dumps(item.evidence, sort_keys=True),
                        item.title,
                        item.gap_type,
                    )
                    for item in items
                ],
            )

    def load_backlog(self, run_id: str) -> list[BacklogItem]:
        rows = self.conn.execute(
            """SELECT * FROM backlog WHERE run_id = ?
               ORDER BY priority DESC, effort ASC, target ASC, item_id ASC""",
            (run_id,),
        ).fetchall()
        return [
            BacklogItem(
                item_id=row["item_id"],
                kind=row["kind"],
                target=row["target"],
                priority=row["priority"],
                effort=row["effort"],
                impact=row["impact"],
                status=row["status"],
                confidence=row["confidence"],
                evidence=json.loads(row["evidence_json"] or "{}"),
                title=row["title"],
                gap_type=row["gap_type"],
            )
            for row in rows
        ]

    def issue_counts(self, run_id: str) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT severity, COUNT(*) AS n FROM audit_issues WHERE run_id = ? GROUP BY severity",
            (run_id,),
        ).fetchall()
        return {row["severity"]: int(row["n"]) for row in rows}

    # -- diff --------------------------------------------------------------

    def _same_domain(self, previous_run_id: str, current_run_id: str) -> bool:
        previous = self.get_run(previous_run_id)
        current = self.get_run(current_run_id)
        if previous is None or current is None:
            return False
        previous_host = previous.get("domain") or config.normalize_domain(previous.get("url"))
        current_host = current.get("domain") or config.normalize_domain(current.get("url"))
        return bool(previous_host) and previous_host == current_host

    def diff_runs(self, previous_run_id: str | None, current_run_id: str) -> AuditDiff:
        current = self.load_audit(current_run_id)
        previous = None
        if previous_run_id and self._same_domain(previous_run_id, current_run_id):
            try:
                previous = self.load_audit(previous_run_id)
            except StoreError:
                previous = None
        else:
            # A cross-domain baseline would fabricate a score delta and
            # mislabel other sites' fixed issues as this site's wins.
            previous_run_id = None
        diff = diff_snapshots(previous, current)
        new_gaps, closed_gaps = diff_gaps(
            self.load_gaps(previous_run_id) if previous_run_id else [],
            self.load_gaps(current_run_id),
        )
        diff.new_gaps = new_gaps
        diff.closed_gaps = closed_gaps
        return diff

    # -- TTL cache (D-9 / I-3) --------------------------------------------

    def set_cache(
        self,
        key: str,
        payload: Any,
        ttl_seconds: int = config.CACHE_TTL_SECONDS,
        fetched_at: datetime | float | None = None,
    ) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cache(key, fetched_at, ttl_seconds, payload) VALUES (?, ?, ?, ?)",
                (key, _epoch(fetched_at), int(ttl_seconds), json.dumps(payload, sort_keys=True)),
            )

    def get_cache(
        self,
        key: str,
        now: datetime | float | None = None,
        *,
        delete_expired: bool = True,
    ) -> Any | None:
        row = self.conn.execute(
            "SELECT fetched_at, ttl_seconds, payload FROM cache WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        current = _epoch(now)
        if current > float(row["fetched_at"]) + int(row["ttl_seconds"]):
            if delete_expired:
                with self.transaction() as conn:
                    conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            return None
        return json.loads(row["payload"])

    def cache_count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) AS n FROM cache").fetchone()["n"])


__all__ = ["Store", "StoreError", "cache_key", "diff_gaps", "diff_snapshots"]

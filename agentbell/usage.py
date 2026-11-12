from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from PySide6.QtCore import QObject, Signal

from .config import UsageConfig

READ_CHUNK = 1024 * 1024
MAX_REMAINDER_BYTES = 8 * 1024 * 1024
MAX_SCAN_BYTES_PER_CYCLE = 256 * 1024 * 1024
MAX_SEEN_IDS = 200_000
PRICE_UNIT = 1_000_000.0
CACHE_DAYS = 7


@dataclass(frozen=True, slots=True)
class UsageRecord:
    source: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    timestamp: datetime | None = None
    record_id: str = ""

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
        )


@dataclass(frozen=True, slots=True)
class ModelUsage:
    model: str
    source: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    priced: bool

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
        )


@dataclass(frozen=True, slots=True)
class UsageSummary:
    date: date
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    unpriced_tokens: int
    token_budget: int
    cost_budget: float
    alert_percent: int
    models: tuple[ModelUsage, ...] = ()
    scanned_files: int = 0
    external_reports: int = 0
    updated_at: datetime | None = None

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
        )

    @property
    def token_percent(self) -> float | None:
        if self.token_budget <= 0:
            return None
        return self.total_tokens / self.token_budget * 100.0

    @property
    def cost_percent(self) -> float | None:
        if self.cost_budget <= 0:
            return None
        return self.cost_usd / self.cost_budget * 100.0

    @property
    def alert_level(self) -> str:
        ratios = [
            value / 100.0
            for value in (self.token_percent, self.cost_percent)
            if value is not None
        ]
        if not ratios:
            return ""
        highest = max(ratios)
        if highest >= 1.0:
            return "exceeded"
        if highest >= max(1, self.alert_percent) / 100.0:
            return "warning"
        return ""

    @property
    def alert_key(self) -> str:
        level = self.alert_level
        return f"usage:{self.date.isoformat()}:{level}" if level else ""

    @property
    def alert_message(self) -> str:
        level = self.alert_level
        if not level:
            return ""
        parts = [f"今日已用 {format_tokens(self.total_tokens)} Token"]
        if self.token_budget > 0:
            parts[0] += f" / {format_tokens(self.token_budget)}"
        text = "，".join(parts)
        if self.cost_budget > 0:
            text += f"，估算成本 ${self.cost_usd:.2f} / ${self.cost_budget:.2f}"
        if level == "exceeded":
            return text + "，已超过预算上限。"
        return text + f"，已达到 {self.alert_percent}% 预警线。"

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 4),
            "unpriced_tokens": self.unpriced_tokens,
            "token_budget": self.token_budget,
            "cost_budget": self.cost_budget,
            "token_percent": self.token_percent,
            "cost_percent": self.cost_percent,
            "alert_level": self.alert_level,
            "alert_key": self.alert_key,
            "alert_message": self.alert_message,
            "scanned_files": self.scanned_files,
            "external_reports": self.external_reports,
            "updated_at": (
                self.updated_at.isoformat(timespec="seconds")
                if self.updated_at
                else ""
            ),
            "models": [
                {
                    "model": item.model,
                    "source": item.source,
                    "input_tokens": item.input_tokens,
                    "output_tokens": item.output_tokens,
                    "cache_read_tokens": item.cache_read_tokens,
                    "cache_write_tokens": item.cache_write_tokens,
                    "total_tokens": item.total_tokens,
                    "cost_usd": round(item.cost_usd, 4),
                    "priced": item.priced,
                }
                for item in self.models
            ],
        }


@dataclass(frozen=True, slots=True)
class UsageReport:
    """One idempotent token report pushed by an external agent."""

    report_id: str
    source: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now().astimezone())
    session_id: str = ""
    run_id: str = ""
    project: str = ""

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
        )

    def to_record(self) -> UsageRecord:
        return UsageRecord(
            source=self.source,
            model=self.model,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cache_read_tokens=self.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens,
            timestamp=self.occurred_at,
            record_id=self.report_id,
        )


def default_report_id(
    source: str,
    model: str,
    occurred_at: datetime,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
) -> str:
    raw = "|".join(
        (
            source,
            model,
            occurred_at.isoformat(timespec="seconds"),
            str(input_tokens),
            str(output_tokens),
            str(cache_read_tokens),
            str(cache_write_tokens),
        )
    )
    return "auto:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


_USAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_reports (
    report_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL,
    occurred_at TEXT NOT NULL,
    session_id TEXT NOT NULL DEFAULT '',
    run_id TEXT NOT NULL DEFAULT '',
    project TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_reports_occurred
    ON usage_reports(occurred_at);
"""


class UsageLedger:
    """Persistent, idempotent ledger for usage reported over HTTP/MCP."""

    def __init__(
        self,
        path: Path | None = None,
        logger: logging.Logger | None = None,
        *,
        retention_days: int = 30,
        max_records: int = 50_000,
    ) -> None:
        self._path = Path(path) if path is not None else None
        self._logger = logger or logging.getLogger("agentbell.usage")
        self._retention_days = max(1, int(retention_days))
        self._max_records = max(100, int(max_records))
        self._lock = threading.RLock()
        self._memory: dict[str, UsageReport] = {}
        self._connection: sqlite3.Connection | None = None
        self._version = 0
        self._adds_since_prune = 0
        if self._path is not None:
            self._open()

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    @property
    def persistent(self) -> bool:
        return self._connection is not None

    @property
    def empty(self) -> bool:
        with self._lock:
            if self._connection is not None:
                try:
                    row = self._connection.execute(
                        "SELECT 1 FROM usage_reports LIMIT 1"
                    ).fetchone()
                    return row is None
                except sqlite3.Error:
                    pass
            return not self._memory

    def add(self, report: UsageReport) -> tuple[bool, UsageReport]:
        """Insert one report; duplicate report_id is ignored idempotently."""
        report = _normalize_report(report)
        with self._lock:
            if self._connection is not None:
                try:
                    cursor = self._connection.execute(
                        "INSERT OR IGNORE INTO usage_reports "
                        "(report_id, source, model, input_tokens, output_tokens, "
                        "cache_read_tokens, cache_write_tokens, cost_usd, "
                        "occurred_at, session_id, run_id, project, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            report.report_id,
                            report.source,
                            report.model,
                            report.input_tokens,
                            report.output_tokens,
                            report.cache_read_tokens,
                            report.cache_write_tokens,
                            report.cost_usd,
                            report.occurred_at.isoformat(timespec="seconds"),
                            report.session_id,
                            report.run_id,
                            report.project,
                            datetime.now().astimezone().isoformat(
                                timespec="seconds"
                            ),
                        ),
                    )
                    inserted = cursor.rowcount > 0
                    self._connection.commit()
                    if inserted:
                        self._version += 1
                        self._adds_since_prune += 1
                        if self._adds_since_prune >= 100:
                            self._adds_since_prune = 0
                            self.prune()
                    return inserted, report
                except sqlite3.Error as exc:
                    self._logger.warning(
                        "写入外部用量失败，改存内存：%s", exc
                    )
            inserted = report.report_id not in self._memory
            if inserted:
                self._memory[report.report_id] = report
                self._version += 1
            return inserted, report

    def records(self, day: date) -> list[UsageReport]:
        day_text = day.isoformat()
        with self._lock:
            if self._connection is not None:
                try:
                    rows = self._connection.execute(
                        "SELECT * FROM usage_reports "
                        "WHERE substr(occurred_at, 1, 10) = ? "
                        "ORDER BY occurred_at ASC, report_id ASC",
                        (day_text,),
                    ).fetchall()
                    return [
                        report
                        for row in rows
                        if (report := _row_to_usage_report(row)) is not None
                    ]
                except sqlite3.Error as exc:
                    self._logger.warning("读取外部用量失败：%s", exc)
            return [
                report
                for report in self._memory.values()
                if report.occurred_at.date() == day
            ]

    def prune(self, now: datetime | None = None) -> None:
        if self._connection is None:
            return
        current = (now or datetime.now().astimezone()).astimezone()
        cutoff = (
            current - timedelta(days=self._retention_days)
        ).date().isoformat()
        with self._lock:
            try:
                self._connection.execute(
                    "DELETE FROM usage_reports WHERE substr(occurred_at, 1, 10) < ?",
                    (cutoff,),
                )
                self._connection.execute(
                    "DELETE FROM usage_reports WHERE report_id NOT IN "
                    "(SELECT report_id FROM usage_reports "
                    "ORDER BY occurred_at DESC LIMIT ?)",
                    (self._max_records,),
                )
                self._connection.commit()
            except sqlite3.Error as exc:
                self._logger.warning("清理外部用量失败：%s", exc)

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                try:
                    self._connection.close()
                except sqlite3.Error:
                    pass
                self._connection = None

    def _open(self) -> None:
        path = self._path
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(
                str(path), check_same_thread=False, timeout=5.0
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.executescript(_USAGE_SCHEMA)
            connection.commit()
            self._connection = connection
            self.prune()
        except (OSError, sqlite3.Error) as exc:
            self._logger.warning(
                "无法打开用量账本 %s：%s；将仅在本次运行内保存", path, exc
            )
            self._connection = None


def _normalize_report(report: UsageReport) -> UsageReport:
    occurred = report.occurred_at
    if occurred.tzinfo is None:
        occurred = occurred.astimezone()
    else:
        occurred = occurred.astimezone()
    return UsageReport(
        report_id=(report.report_id or uuid.uuid4().hex)[:120],
        source=(report.source or "external")[:100],
        model=(report.model or "unknown")[:80],
        input_tokens=max(0, int(report.input_tokens)),
        output_tokens=max(0, int(report.output_tokens)),
        cache_read_tokens=max(0, int(report.cache_read_tokens)),
        cache_write_tokens=max(0, int(report.cache_write_tokens)),
        cost_usd=(
            round(max(0.0, float(report.cost_usd)), 8)
            if report.cost_usd is not None
            else None
        ),
        occurred_at=occurred,
        session_id=(report.session_id or "")[:120],
        run_id=(report.run_id or "")[:120],
        project=(report.project or "")[:200],
    )


def _row_to_usage_report(row: sqlite3.Row) -> UsageReport | None:
    occurred = _timestamp(row["occurred_at"])
    if occurred is None:
        return None
    cost = row["cost_usd"]
    return UsageReport(
        report_id=str(row["report_id"]),
        source=str(row["source"] or "external"),
        model=str(row["model"] or "unknown"),
        input_tokens=_int(row["input_tokens"]),
        output_tokens=_int(row["output_tokens"]),
        cache_read_tokens=_int(row["cache_read_tokens"]),
        cache_write_tokens=_int(row["cache_write_tokens"]),
        cost_usd=max(0.0, float(cost)) if cost is not None else None,
        occurred_at=occurred,
        session_id=str(row["session_id"] or ""),
        run_id=str(row["run_id"] or ""),
        project=str(row["project"] or ""),
    )


@dataclass
class _Tokens:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def add_record(self, record: UsageRecord) -> None:
        self.input_tokens += record.input_tokens
        self.output_tokens += record.output_tokens
        self.cache_read_tokens += record.cache_read_tokens
        self.cache_write_tokens += record.cache_write_tokens

    def add(self, other: "_Tokens") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_write_tokens += other.cache_write_tokens


@dataclass
class _FileUsage:
    offset: int = 0
    remainder: bytes = b""
    year: int = 0
    month: int = 0
    day: int = 0
    buckets: dict[tuple[str, str, str], _Tokens] = field(default_factory=dict)
    seen_ids: set[str] = field(default_factory=set)


def default_claude_root() -> Path:
    return Path.home() / ".claude" / "projects"


def default_qoder_root() -> Path:
    return Path.home() / ".qoder" / "projects"


def default_codex_root() -> Path:
    return Path.home() / ".codex" / "sessions"


def _int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float):
        return max(0, int(value))
    return 0


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone()


def _source_for(path: Path) -> str:
    parts = {part.lower() for part in path.parts}
    if ".codex" in parts:
        return "codex"
    if ".qoder" in parts:
        return "qoder"
    return "claude"


def parse_usage_line(
    line: str, source: str, *, fallback_time: datetime | None = None
) -> UsageRecord | None:
    text = line.strip()
    if not text or '"usage"' not in text and '"token_count"' not in text:
        return None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if source in {"claude", "qoder"}:
        if data.get("type") != "assistant":
            return None
        message = data.get("message")
        if not isinstance(message, dict):
            return None
        usage = message.get("usage")
        if not isinstance(usage, dict):
            return None
        model = str(message.get("model") or "unknown")[:80]
        cache_write = _int(usage.get("cache_creation_input_tokens"))
        cache_creation = usage.get("cache_creation")
        if not cache_write and isinstance(cache_creation, dict):
            cache_write = sum(
                _int(value) for value in cache_creation.values()
            )
        record = UsageRecord(
            source=source,
            model=model,
            input_tokens=_int(usage.get("input_tokens")),
            output_tokens=_int(usage.get("output_tokens")),
            cache_read_tokens=_int(usage.get("cache_read_input_tokens")),
            cache_write_tokens=cache_write,
            timestamp=_timestamp(data.get("timestamp")) or fallback_time,
            record_id=str(message.get("id") or "")[:120],
        )
        return record if record.total_tokens > 0 else None

    if data.get("type") != "event_msg":
        return None
    payload = data.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "token_count":
        return None
    info = payload.get("info")
    if not isinstance(info, dict):
        return None
    usage = info.get("last_token_usage") or info.get("total_token_usage")
    if not isinstance(usage, dict):
        return None
    model = str(
        data.get("model") or payload.get("model") or "codex"
    )[:80]
    record = UsageRecord(
        source="codex",
        model=model,
        input_tokens=_int(usage.get("input_tokens")),
        output_tokens=_int(usage.get("output_tokens")),
        cache_read_tokens=_int(usage.get("cached_input_tokens")),
        cache_write_tokens=_int(usage.get("cache_write_input_tokens")),
        timestamp=_timestamp(data.get("timestamp")) or fallback_time,
    )
    return record if record.total_tokens > 0 else None


def match_pricing(
    model: str, pricing: dict[str, dict[str, float]]
) -> dict[str, float] | None:
    needle = model.casefold()
    matched: str | None = None
    for candidate in pricing:
        key = candidate.casefold()
        if needle == key or needle.startswith(key):
            if matched is None or len(key) > len(matched):
                matched = candidate
    return pricing.get(matched) if matched else None


def estimate_cost(record: UsageRecord, pricing: dict[str, dict[str, float]]) -> float:
    rates = match_pricing(record.model, pricing)
    if not rates:
        return 0.0
    return (
        record.input_tokens * rates.get("input", 0.0)
        + record.output_tokens * rates.get("output", 0.0)
        + record.cache_read_tokens * rates.get("cache_read", 0.0)
        + record.cache_write_tokens * rates.get("cache_write", 0.0)
    ) / PRICE_UNIT


def format_tokens(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 10_000:
        return f"{value / 1000:.1f}K"
    return str(value)


def _iter_jsonl(path: Path) -> Iterable[Path]:
    try:
        yield from path.rglob("*.jsonl")
    except OSError:
        return


class UsageScanner(QObject):
    """Incrementally aggregates Claude/Qoder/Codex token usage per day."""

    scanned = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        config: UsageConfig,
        logger: logging.Logger,
        parent: QObject | None = None,
        claude_root: Path | None = None,
        qoder_root: Path | None = None,
        codex_root: Path | None = None,
        ledger: UsageLedger | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._logger = logger
        self._claude_root = claude_root or default_claude_root()
        self._qoder_root = qoder_root or default_qoder_root()
        self._codex_root = codex_root or default_codex_root()
        self._ledger = ledger
        self._files: dict[str, _FileUsage] = {}
        self._last_summary: UsageSummary | None = None
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def last_summary(self) -> UsageSummary | None:
        return self._last_summary

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="agentbell-usage-scan", daemon=True
        )
        self._thread.start()

    def apply_config(self, config: UsageConfig) -> None:
        self._config = config
        self._wake_event.set()

    def refresh(self) -> None:
        self._wake_event.set()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None

    def _run(self) -> None:
        while not self._stop_event.is_set():
            config = self._config
            if config.enabled:
                try:
                    summary = self.scan_once()
                except Exception as exc:  # pragma: no cover - defensive
                    self._logger.warning("扫描 Token 用量失败：%s", exc)
                    self.failed.emit(str(exc))
                else:
                    self._last_summary = summary
                    self.scanned.emit(summary)
                    self._logger.info(
                        "Token 用量：今日 %s tokens，成本 $%.2f，模型 %d 个",
                        format_tokens(summary.total_tokens),
                        summary.cost_usd,
                        len(summary.models),
                    )
            interval = max(60, int(config.scan_interval_seconds))
            self._wake_event.wait(interval)
            self._wake_event.clear()

    def scan_once(self) -> UsageSummary:
        now = datetime.now().astimezone()
        today = now.date()
        since = datetime.combine(
            today - timedelta(days=1), datetime.min.time()
        ).astimezone()
        files = self._collect_files(since)
        budget = MAX_SCAN_BYTES_PER_CYCLE
        scanned = 0
        for path in files:
            if budget <= 0:
                self._logger.info("本轮 Token 扫描达到读取上限，剩余文件下轮继续")
                break
            try:
                consumed = self._scan_file(path, since, budget)
            except OSError as exc:
                self._logger.warning("读取用量文件失败 %s：%s", path, exc)
                continue
            scanned += 1
            budget -= consumed
        self._prune(today)
        return self._build_summary(today, now, scanned)

    def _collect_files(self, since: datetime) -> list[Path]:
        found: dict[str, tuple[float, Path]] = {}
        for root in (self._claude_root, self._qoder_root, self._codex_root):
            if not root.exists():
                continue
            for path in _iter_jsonl(root):
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    continue
                if mtime < since.timestamp():
                    continue
                found[str(path)] = (mtime, path)
        ordered = sorted(found.values(), key=lambda item: item[0], reverse=True)
        return [path for _mtime, path in ordered]

    def _scan_file(self, path: Path, since: datetime, budget: int) -> int:
        try:
            stat = path.stat()
        except OSError:
            return 0
        key = str(path)
        state = self._files.get(key)
        if state is None:
            state = _FileUsage(year=since.year, month=since.month, day=since.day)
            self._files[key] = state
        if stat.st_size < state.offset:
            state.offset = 0
            state.remainder = b""
            state.buckets.clear()
            state.seen_ids.clear()
        elif stat.st_size == state.offset and not state.remainder:
            return 0

        source = _source_for(path)
        delta: dict[tuple[str, str, str], _Tokens] = {}
        bytes_read = 0
        new_offset = state.offset
        with path.open("rb") as handle:
            handle.seek(state.offset)
            buffer = state.remainder
            while bytes_read < budget:
                chunk = handle.read(min(READ_CHUNK, budget - bytes_read))
                if not chunk:
                    break
                bytes_read += len(chunk)
                buffer += chunk
                while True:
                    index = buffer.find(b"\n")
                    if index < 0:
                        break
                    raw = buffer[:index]
                    buffer = buffer[index + 1 :]
                    record = self._parse_line(raw, source, stat.st_mtime)
                    if record is None:
                        continue
                    if record.record_id:
                        if record.record_id in state.seen_ids:
                            continue
                        if len(state.seen_ids) >= MAX_SEEN_IDS:
                            state.seen_ids.clear()
                        state.seen_ids.add(record.record_id)
                    record_day = (record.timestamp or datetime.now().astimezone()).date()
                    if record_day < since.date():
                        continue
                    bucket_key = (
                        record_day.isoformat(),
                        record.source,
                        record.model,
                    )
                    bucket = delta.setdefault(bucket_key, _Tokens())
                    bucket.add_record(record)
                if len(buffer) > MAX_REMAINDER_BYTES:
                    buffer = b""
            new_offset = handle.tell() - len(buffer)
        state.offset = new_offset
        state.remainder = buffer
        for bucket_key, bucket in delta.items():
            state.buckets.setdefault(bucket_key, _Tokens()).add(bucket)
        future = (since + timedelta(days=CACHE_DAYS)).date()
        stale = [key for key in state.buckets if key[0] < since.date().isoformat() or key[0] > future.isoformat()]
        for stale_key in stale:
            state.buckets.pop(stale_key, None)
        return bytes_read

    @staticmethod
    def _parse_line(
        raw: bytes, source: str, mtime: float
    ) -> UsageRecord | None:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            return None
        fallback = datetime.fromtimestamp(mtime).astimezone()
        return parse_usage_line(text, source, fallback_time=fallback)

    def _prune(self, today: date) -> None:
        earliest = (today - timedelta(days=CACHE_DAYS)).isoformat()
        for key in list(self._files):
            if not Path(key).exists():
                self._files.pop(key, None)
                continue
            state = self._files[key]
            for bucket_key in list(state.buckets):
                if bucket_key[0] < earliest:
                    state.buckets.pop(bucket_key, None)

    def _build_summary(
        self, today: date, now: datetime, scanned_files: int
    ) -> UsageSummary:
        config = self._config
        pricing = config.pricing
        totals: dict[tuple[str, str], _Tokens] = {}
        date_text = today.isoformat()
        for state in self._files.values():
            for (day, source, model), bucket in state.buckets.items():
                if day != date_text:
                    continue
                key = (source, model)
                entry = totals.setdefault(key, _Tokens())
                entry.add(bucket)

        external_totals: dict[tuple[str, str], _Tokens] = {}
        external_cost: dict[tuple[str, str], float] = {}
        external_unpriced: dict[tuple[str, str], int] = {}
        external_reports = 0
        if self._ledger is not None:
            for report in self._ledger.records(today):
                if report.total_tokens <= 0 and not report.cost_usd:
                    continue
                key = (report.source, report.model)
                bucket = external_totals.setdefault(key, _Tokens())
                bucket.add_record(report.to_record())
                external_reports += 1
                if report.cost_usd is not None:
                    external_cost[key] = external_cost.get(key, 0.0) + report.cost_usd
                else:
                    rates = match_pricing(report.model, pricing)
                    if rates is None:
                        external_unpriced[key] = (
                            external_unpriced.get(key, 0) + report.total_tokens
                        )
                    else:
                        external_cost[key] = external_cost.get(
                            key, 0.0
                        ) + estimate_cost(report.to_record(), pricing)

        models: list[ModelUsage] = []
        model_positions: dict[tuple[str, str], int] = {}
        input_tokens = output_tokens = 0
        cache_read = cache_write = 0
        cost = 0.0
        unpriced = 0

        def add_totals(bucket: _Tokens) -> None:
            nonlocal input_tokens, output_tokens, cache_read, cache_write
            input_tokens += bucket.input_tokens
            output_tokens += bucket.output_tokens
            cache_read += bucket.cache_read_tokens
            cache_write += bucket.cache_write_tokens

        for (source, model), bucket in totals.items():
            rates = match_pricing(model, pricing)
            record = UsageRecord(
                source=source,
                model=model,
                input_tokens=bucket.input_tokens,
                output_tokens=bucket.output_tokens,
                cache_read_tokens=bucket.cache_read_tokens,
                cache_write_tokens=bucket.cache_write_tokens,
            )
            model_cost = estimate_cost(record, pricing) if rates else 0.0
            add_totals(bucket)
            cost += model_cost
            if rates is None:
                unpriced += record.total_tokens
            model_positions[(source, model)] = len(models)
            models.append(
                ModelUsage(
                    model=model,
                    source=source,
                    input_tokens=bucket.input_tokens,
                    output_tokens=bucket.output_tokens,
                    cache_read_tokens=bucket.cache_read_tokens,
                    cache_write_tokens=bucket.cache_write_tokens,
                    cost_usd=model_cost,
                    priced=rates is not None,
                )
            )

        for key, bucket in external_totals.items():
            source, model = key
            add_totals(bucket)
            model_cost = external_cost.get(key, 0.0)
            model_unpriced = external_unpriced.get(key, 0)
            cost += model_cost
            unpriced += model_unpriced
            position = model_positions.get(key)
            if position is None:
                model_positions[key] = len(models)
                models.append(
                    ModelUsage(
                        model=model,
                        source=source,
                        input_tokens=bucket.input_tokens,
                        output_tokens=bucket.output_tokens,
                        cache_read_tokens=bucket.cache_read_tokens,
                        cache_write_tokens=bucket.cache_write_tokens,
                        cost_usd=model_cost,
                        priced=model_unpriced == 0,
                    )
                )
            else:
                existing = models[position]
                models[position] = ModelUsage(
                    model=existing.model,
                    source=existing.source,
                    input_tokens=existing.input_tokens + bucket.input_tokens,
                    output_tokens=existing.output_tokens + bucket.output_tokens,
                    cache_read_tokens=(
                        existing.cache_read_tokens + bucket.cache_read_tokens
                    ),
                    cache_write_tokens=(
                        existing.cache_write_tokens + bucket.cache_write_tokens
                    ),
                    cost_usd=existing.cost_usd + model_cost,
                    priced=existing.priced and model_unpriced == 0,
                )

        models.sort(key=lambda item: item.total_tokens, reverse=True)
        return UsageSummary(
            date=today,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            cost_usd=cost,
            unpriced_tokens=unpriced,
            token_budget=config.daily_token_budget,
            cost_budget=config.daily_cost_budget,
            alert_percent=config.alert_percent,
            models=tuple(models),
            scanned_files=scanned_files,
            external_reports=external_reports,
            updated_at=now,
        )

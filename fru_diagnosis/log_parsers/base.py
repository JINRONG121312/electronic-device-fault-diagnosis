"""Shared interfaces for log parsing adapters.

The diagnosis pipeline consumes parser output as stable event templates,
template IDs, and per-window sequences. Parser implementations should adapt
their native output to these small dataclasses so experiments can swap parsing
methods without changing diagnostic graph code.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol


@dataclass(frozen=True)
class NormalizedLogEntry:
    line_id: int
    content: str
    event_id: str = ""
    event_template: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedLogLine:
    line_id: int
    content: str
    event_id: str
    event_template: str
    parameters: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_id": self.line_id,
            "content": self.content,
            "event_id": self.event_id,
            "event_template": self.event_template,
            "parameters": list(self.parameters),
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class LogParseResult:
    method: str
    lines: tuple[ParsedLogLine, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def event_template_counts(self) -> dict[str, int]:
        return dict(Counter(line.event_template for line in self.lines if line.event_template))

    @property
    def event_id_counts(self) -> dict[str, int]:
        return dict(Counter(line.event_id for line in self.lines if line.event_id))

    @property
    def event_id_sequence(self) -> list[str]:
        return [line.event_id for line in self.lines if line.event_id]

    @property
    def event_template_sequence(self) -> list[str]:
        return [line.event_template for line in self.lines if line.event_template]

    def to_log_evidence(self, *, include_parsed_events: bool = True) -> dict[str, Any]:
        evidence: dict[str, Any] = {
            "event_id_counts": self.event_id_counts,
            "event_template_counts": self.event_template_counts,
            "event_id_sequence": self.event_id_sequence,
            "event_template_sequence": self.event_template_sequence,
            "log_parser": {
                "method": self.method,
                "line_count": len(self.lines),
                "template_count": len(self.event_template_counts),
                **self.metadata,
            },
        }
        if include_parsed_events:
            evidence["parsed_events"] = [line.to_dict() for line in self.lines]
        return evidence


class LogParser(Protocol):
    name: str

    def parse(self, entries: Iterable[str | dict[str, Any] | NormalizedLogEntry]) -> LogParseResult:
        """Parse raw or structured log entries into event templates."""


def normalize_entries(entries: Iterable[str | dict[str, Any] | NormalizedLogEntry]) -> list[NormalizedLogEntry]:
    normalized = []
    for index, entry in enumerate(entries, start=1):
        if isinstance(entry, NormalizedLogEntry):
            normalized.append(entry)
            continue
        if isinstance(entry, str):
            normalized.append(NormalizedLogEntry(line_id=index, content=entry))
            continue
        if not isinstance(entry, dict):
            normalized.append(NormalizedLogEntry(line_id=index, content=str(entry)))
            continue
        line_id = safe_int(first_present(entry, ["LineId", "line_id", "lineId"]), index)
        content = str(first_present(entry, ["Content", "content", "message", "raw_message", "message_excerpt"]) or "")
        event_template = str(first_present(entry, ["EventTemplate", "event_template", "template"]) or "")
        event_id = str(first_present(entry, ["EventId", "event_id", "template_id"]) or "")
        metadata = {
            key: value
            for key, value in entry.items()
            if key
            not in {
                "LineId",
                "line_id",
                "lineId",
                "Content",
                "content",
                "message",
                "raw_message",
                "message_excerpt",
                "EventTemplate",
                "event_template",
                "template",
                "EventId",
                "event_id",
                "template_id",
            }
        }
        normalized.append(
            NormalizedLogEntry(
                line_id=line_id,
                content=content,
                event_id=event_id,
                event_template=event_template,
                metadata=metadata,
            )
        )
    return normalized


def stable_event_id(template: str) -> str:
    return hashlib.md5(template.encode("utf-8", errors="ignore")).hexdigest()[:8]


def extract_parameters(template: str, content: str) -> tuple[str, ...]:
    if "<*>" not in template:
        return ()
    escaped = re.escape(template)
    pattern = "^" + escaped.replace(re.escape("<*>"), "(.*?)") + "$"
    match = re.match(pattern, content)
    if not match:
        return ()
    return tuple(str(group) for group in match.groups())


def first_present(mapping: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None and value != "":
            return value
    return ""


def safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

"""Parser adapter that preserves source-provided templates."""

from __future__ import annotations

from typing import Any, Iterable

from .base import (
    LogParseResult,
    NormalizedLogEntry,
    ParsedLogLine,
    extract_parameters,
    normalize_entries,
    stable_event_id,
)


class SourceTemplateParser:
    """Use existing EventTemplate/EventId columns as parser output.

    This is the compatibility mode for Loghub-style structured CSV files. If an
    entry lacks a source template, the raw content becomes a one-line template.
    """

    name = "source"

    def parse(self, entries: Iterable[str | dict[str, Any] | NormalizedLogEntry]) -> LogParseResult:
        parsed = []
        for entry in normalize_entries(entries):
            template = entry.event_template or entry.content
            event_id = entry.event_id or stable_event_id(template)
            parsed.append(
                ParsedLogLine(
                    line_id=entry.line_id,
                    content=entry.content,
                    event_id=event_id,
                    event_template=template,
                    parameters=extract_parameters(template, entry.content),
                    metadata=dict(entry.metadata),
                )
            )
        return LogParseResult(
            method=self.name,
            lines=tuple(parsed),
            metadata={"source": "provided_event_template_or_raw_content"},
        )


"""Registry for project log parser adapters."""

from __future__ import annotations

from typing import Any, Callable, Iterable

from .base import LogParseResult, LogParser, NormalizedLogEntry
from .drain import DrainLogParser
from .source import SourceTemplateParser

ParserFactory = Callable[..., LogParser]

_PARSER_FACTORIES: dict[str, ParserFactory] = {}


def register_log_parser(name: str, factory: ParserFactory) -> None:
    normalized = name.strip().casefold()
    if not normalized:
        raise ValueError("Parser name must not be empty.")
    _PARSER_FACTORIES[normalized] = factory


def available_log_parsers() -> list[str]:
    return sorted(_PARSER_FACTORIES)


def get_log_parser(name: str = "source", **options: Any) -> LogParser:
    normalized = name.strip().casefold()
    try:
        factory = _PARSER_FACTORIES[normalized]
    except KeyError as exc:
        raise ValueError(
            f"Unknown log parser '{name}'. Available parsers: {', '.join(available_log_parsers())}"
        ) from exc
    return factory(**options)


def parse_logs(
    entries: Iterable[str | dict[str, Any] | NormalizedLogEntry],
    *,
    parser_name: str = "source",
    parser_options: dict[str, Any] | None = None,
) -> LogParseResult:
    parser = get_log_parser(parser_name, **(parser_options or {}))
    return parser.parse(entries)


def enrich_log_evidence(
    logs: dict[str, Any],
    *,
    parser_name: str = "drain",
    parser_options: dict[str, Any] | None = None,
    force: bool = False,
    include_parsed_events: bool = True,
) -> dict[str, Any]:
    """Return log evidence with template counts and sequences.

    Existing template counts are preserved unless ``force`` is true. This lets
    old datasets keep their source templates while runtime/raw-message imports
    can be parsed by Drain before graph fusion.
    """

    if not isinstance(logs, dict):
        return {}
    if not force and logs.get("event_template_counts"):
        return dict(logs)

    raw_messages = logs.get("raw_messages")
    if raw_messages is None:
        raw_messages = logs.get("evidence_messages")
    if not isinstance(raw_messages, list) or not raw_messages:
        return dict(logs)

    result = parse_logs(
        [str(message) for message in raw_messages],
        parser_name=parser_name,
        parser_options=parser_options,
    )
    enriched = dict(logs)
    enriched.update(result.to_log_evidence(include_parsed_events=include_parsed_events))
    return enriched


register_log_parser("source", SourceTemplateParser)
register_log_parser("drain", DrainLogParser)


"""Log parsing adapters used by diagnosis datasets and graph fusion."""

from .base import LogParseResult, LogParser, NormalizedLogEntry, ParsedLogLine
from .drain import DrainLogParser
from .registry import (
    available_log_parsers,
    enrich_log_evidence,
    get_log_parser,
    parse_logs,
    register_log_parser,
)
from .source import SourceTemplateParser

__all__ = [
    "DrainLogParser",
    "LogParseResult",
    "LogParser",
    "NormalizedLogEntry",
    "ParsedLogLine",
    "SourceTemplateParser",
    "available_log_parsers",
    "enrich_log_evidence",
    "get_log_parser",
    "parse_logs",
    "register_log_parser",
]


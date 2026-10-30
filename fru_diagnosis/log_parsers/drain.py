"""Drain log parser adapter.

This implementation follows the fixed-depth parse-tree logic used by the
Loghub-2.0/project_2026 Drain baseline, but exposes an in-project API that
does not require pandas CSV round-trips. It can be replaced or compared with
other parser adapters through the registry in this package.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .base import (
    LogParseResult,
    NormalizedLogEntry,
    ParsedLogLine,
    extract_parameters,
    normalize_entries,
    stable_event_id,
)

WILDCARD = "<*>"

DEFAULT_VARIABLE_PATTERNS = (
    r"\b\d{1,3}(?:\.\d{1,3}){3}\b",
    r"\b0x[0-9a-fA-F]+\b",
    r"\b[0-9a-fA-F]{8,}\b",
    r"\b\d+\b",
)


@dataclass
class _LogCluster:
    template_tokens: list[str]
    entry_indexes: list[int] = field(default_factory=list)


@dataclass
class _PrefixNode:
    depth: int = 0
    token: str | int | None = None
    children: dict[str | int, "_PrefixNode"] = field(default_factory=dict)
    clusters: list[_LogCluster] = field(default_factory=list)


class DrainLogParser:
    """Online fixed-depth-tree parser for log template extraction."""

    name = "drain"

    def __init__(
        self,
        *,
        depth: int = 4,
        similarity_threshold: float = 0.4,
        max_children: int = 100,
        variable_patterns: Iterable[str] | None = None,
    ) -> None:
        self.depth = max(2, int(depth))
        self.tree_depth = max(1, self.depth - 2)
        self.similarity_threshold = float(similarity_threshold)
        self.max_children = int(max_children)
        self.variable_patterns = tuple(variable_patterns or DEFAULT_VARIABLE_PATTERNS)

    def parse(self, entries: Iterable[str | dict[str, Any] | NormalizedLogEntry]) -> LogParseResult:
        normalized = normalize_entries(entries)
        root = _PrefixNode()
        clusters: list[_LogCluster] = []

        for index, entry in enumerate(normalized):
            tokens = self._tokenize(entry.content)
            match = self._tree_search(root, tokens)
            if match is None:
                cluster = _LogCluster(template_tokens=list(tokens), entry_indexes=[index])
                clusters.append(cluster)
                self._add_sequence(root, cluster)
                continue
            new_template = self._merge_template(tokens, match.template_tokens)
            match.entry_indexes.append(index)
            if new_template != match.template_tokens:
                match.template_tokens = new_template

        template_by_index: dict[int, str] = {}
        for cluster in clusters:
            template = " ".join(cluster.template_tokens)
            for index in cluster.entry_indexes:
                template_by_index[index] = template

        parsed = []
        for index, entry in enumerate(normalized):
            template = template_by_index.get(index) or entry.content
            event_id = stable_event_id(template)
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
            metadata={
                "depth": self.depth,
                "similarity_threshold": self.similarity_threshold,
                "max_children": self.max_children,
                "variable_pattern_count": len(self.variable_patterns),
                "reference": "project_2026 Loghub-2.0 Drain fixed-depth parser",
            },
        )

    def _tokenize(self, content: str) -> list[str]:
        text = str(content or "")
        for pattern in self.variable_patterns:
            text = re.sub(pattern, WILDCARD, text)
        return text.strip().split() or [WILDCARD]

    def _tree_search(self, root: _PrefixNode, seq: list[str]) -> _LogCluster | None:
        seq_len = len(seq)
        parent = root.children.get(seq_len)
        if parent is None:
            return None

        current_depth = 1
        for token in seq:
            if current_depth >= self.tree_depth or current_depth > seq_len:
                break
            if token in parent.children:
                parent = parent.children[token]
            elif WILDCARD in parent.children:
                parent = parent.children[WILDCARD]
            else:
                return None
            current_depth += 1
        return self._fast_match(parent.clusters, seq)

    def _add_sequence(self, root: _PrefixNode, cluster: _LogCluster) -> None:
        seq = cluster.template_tokens
        seq_len = len(seq)
        if seq_len not in root.children:
            root.children[seq_len] = _PrefixNode(depth=1, token=seq_len)
        parent = root.children[seq_len]

        current_depth = 1
        inserted = False
        for token in seq:
            if current_depth >= self.tree_depth or current_depth > seq_len:
                parent.clusters.append(cluster)
                inserted = True
                break

            child_key = self._child_key(parent, token, current_depth)
            if child_key not in parent.children:
                parent.children[child_key] = _PrefixNode(depth=current_depth + 1, token=child_key)
            parent = parent.children[child_key]
            current_depth += 1

        if not inserted:
            parent.clusters.append(cluster)

    def _child_key(self, parent: _PrefixNode, token: str, current_depth: int) -> str:
        if self._has_numbers(token):
            return WILDCARD
        if token in parent.children:
            return token
        if WILDCARD in parent.children and len(parent.children) >= self.max_children:
            return WILDCARD
        if len(parent.children) + 1 < self.max_children:
            return token
        if len(parent.children) + 1 == self.max_children:
            return WILDCARD
        return WILDCARD

    def _fast_match(self, clusters: list[_LogCluster], seq: list[str]) -> _LogCluster | None:
        best_cluster = None
        best_similarity = -1.0
        best_wildcard_count = -1
        for cluster in clusters:
            similarity, wildcard_count = self._sequence_distance(cluster.template_tokens, seq)
            if similarity > best_similarity or (
                similarity == best_similarity and wildcard_count > best_wildcard_count
            ):
                best_similarity = similarity
                best_wildcard_count = wildcard_count
                best_cluster = cluster
        if best_similarity >= self.similarity_threshold:
            return best_cluster
        return None

    def _sequence_distance(self, template: list[str], seq: list[str]) -> tuple[float, int]:
        if len(template) != len(seq) or not template:
            return 0.0, 0
        same = 0
        wildcard_count = 0
        for left, right in zip(template, seq):
            if left == WILDCARD:
                wildcard_count += 1
                continue
            if left == right:
                same += 1
        return same / len(template), wildcard_count

    def _merge_template(self, seq: list[str], template: list[str]) -> list[str]:
        return [left if left == right else WILDCARD for left, right in zip(seq, template)]

    def _has_numbers(self, token: str) -> bool:
        return any(char.isdigit() for char in token)


# Log Parser Integration

This project now uses `fru_diagnosis.log_parsers` as the adapter layer for log
template extraction.

## Current parsers

- `source`: preserve source-provided `EventTemplate` and `EventId` columns.
- `drain`: in-project Drain adapter based on the fixed-depth tree parser used
  by the migrated `project_2026` Loghub-2.0 benchmark.

## Dataset usage

```powershell
python scripts\prepare_loghub2k_diagnosis_dataset.py --datasets Apache --log-parser drain
```

`--log-parser source` keeps the old behavior. `--log-parser drain` reparses raw
`Content` messages and writes these fields into each `DatasetCase`:

- `event_template_counts`
- `event_id_counts`
- `event_template_sequence`
- `event_id_sequence`
- `parsed_events`
- `log_parser`

## Adding another parser

Implement a parser class with this shape:

```python
class MyParser:
    name = "my_parser"

    def parse(self, entries):
        ...
        return LogParseResult(method=self.name, lines=tuple(parsed_lines))
```

Then register it:

```python
from fru_diagnosis.log_parsers import register_log_parser

register_log_parser("my_parser", MyParser)
```

The downstream diagnosis graph consumes the normalized parser output, so new
parsers should not change `diagnostic_graph.py` or experiment evaluation code.


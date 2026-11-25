# Source and provenance notes

## Referenced conversation

The provided ChatGPT thread `Design Requirements Document` (`6afa75d2-b0ac-83e8-a1e7-63671555fe5a`) supplies the v0.4 requirements, v0.4.1 Ollama selection, v0.5 local technical design, and v0.6 Windows 8 GB / Sheets / SQLite baseline. The thread preview available to this package did not include the original v0.1–v0.3 documents or actual athlete workbooks. Later explicit decisions supersede earlier PostgreSQL, Docker, and local athlete-link/form suggestions.

## Official technical references checked 2026-11-16

- [Ollama chat endpoint](https://docs.ollama.com/api/chat): `POST /api/chat`, `format` JSON Schema, streaming, `keep_alive`, response duration/token fields.
- [Ollama local model list](https://docs.ollama.com/api/tags): `GET /api/tags`, model digest and size fields.
- [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs): JSON Schema responses and Pydantic validation example.
- [Google Sheets OAuth scopes](https://developers.google.com/workspace/sheets/api/scopes): read-only scope and per-file scope differences; scopes are not per worksheet.
- [Google Sheets values.get](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/get): range reads and accepted scopes.
- [SQLite PRAGMA reference](https://www.sqlite.org/pragma.html): foreign-key enforcement and WAL journal mode.

These references support interface choices, not a claim that the package has been executed against the user's hardware, Google account or workbook.

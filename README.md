# mysql-table-context

`mysql-table-context` is a Codex skill for inspecting one or more MySQL tables with CLI-friendly output for agent workflows.

It is designed for schema-aware AI systems that need:

- column names, types, keys, defaults, and comments
- a compact matched/unmatched table summary
- up to 5 sample rows per matched table
- a strict "configured database only" execution model

## Repository Layout

- `SKILL.md`: skill contract and response format
- `agents/openai.yaml`: interface metadata
- `scripts/inspect_mysql_table.py`: MySQL inspector CLI
- `scripts/vendor/`: vendored `PyMySQL`

## Requirements

The script reads these environment variables:

- `MYSQL_HOST`
- `MYSQL_PORT`
- `MYSQL_USER`
- `MYSQL_PASSWORD`
- `MYSQL_DATABASE`

## Usage

Single table:

```bash
python3 scripts/inspect_mysql_table.py --table users
```

Multiple tables:

```bash
python3 scripts/inspect_mysql_table.py --table users --table orders --table invoices
```

User mentioned another database name:

```bash
python3 scripts/inspect_mysql_table.py --table users --database analytics
```

## Notes

- MySQL only
- sample rows are fetched with `LIMIT 5`
- the vendored driver avoids a system-level `pip install`

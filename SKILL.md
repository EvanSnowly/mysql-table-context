---
name: mysql-table-context
description: Fetch MySQL table schema, column types, column comments, and up to 5 sample rows from the currently configured database. Use when a user working on a project needs database table context, mentions one or more table names, asks for table structure or sample data, or needs agent context grounded in live MySQL table metadata. Only query the single database configured by environment variables and explicitly report the mentioned tables, matched tables, and unmatched tables.
---

# MySQL Table Context

Use this skill when the user needs live MySQL table context during project development.

This skill only queries the single database configured in the current environment. It does not scan other databases or infer cross-database mappings.

## Workflow

1. Extract every table name mentioned by the user.
2. If the user wrote `db.table`, split the database name and table name.
3. Run `scripts/inspect_mysql_table.py` once with all requested tables.
4. Read the JSON result and convert it into two presentation blocks:
   - A summary table for mentioned, matched, and unmatched tables
   - One Navicat-style result table per matched table
5. Always report:
   - The configured database actually queried
   - Whether the user mentioned another database name
   - How many tables were mentioned
   - How many matched
   - How many did not match

## Command

Single table:

```bash
python3 scripts/inspect_mysql_table.py --table <table_name>
```

Multiple tables:

```bash
python3 scripts/inspect_mysql_table.py --table <table_a> --table <table_b> --table <table_c>
```

If the user explicitly mentions a database name, pass it through for reporting:

```bash
python3 scripts/inspect_mysql_table.py --table <table_name> --database <database_name>
```

## Environment Variables

Require these variables:

- `MYSQL_HOST`
- `MYSQL_PORT`
- `MYSQL_USER`
- `MYSQL_PASSWORD`
- `MYSQL_DATABASE`

This skill may also be driven by a local env file at `/home/snow/.codex/skills/mysql-table-context/.env` if the caller sources it before running the script.
This skill may also be driven by a local `.env` file if the caller sources it before running the script.

If any are missing, stop and tell the user exactly which variables are missing.

## Result Handling

The script returns JSON with these top-level keys:

- `database_status`
- `table_summary`
- `tables`
- `cli_rendered`
- `errors`

Interpret them with these rules:

- If `errors` is non-empty, surface the error clearly and do not invent missing database details.
- First show a summary table with exactly these rows:
  - user mentioned table count and list
  - matched table count and list
  - unmatched table count and list
- Then, for each matched table, render a Navicat-style table view from `cli_rendered.table_views[].rendered_table`.
- In each table view:
  - Row 1 is the field-name header
  - Row 2 is the structure-summary row built from column comments
  - Rows 3+ are sample data rows
- If a column comment is empty, render an empty cell in the structure-summary row.
- If `database_status.requested_database` differs from `database_status.configured_database`, explicitly tell the user that the skill only searched the configured database.
- If no tables match, still render the summary table and clearly state that nothing was found in the configured database.

## Output Requirements

When using this skill, always render the response in this order:

1. A short status line describing the configured database and any database-name mismatch
2. The exact ASCII summary table from `cli_rendered.summary_table`, inside a fenced code block
3. One ASCII Navicat-style table per matched table from `cli_rendered.table_views[].rendered_table`, each inside a fenced code block

Do not rebuild CLI tables manually. Use the pre-rendered ASCII tables from `cli_rendered` so widths stay aligned in terminal UIs.

Do not claim that other databases were searched.

## Notes

- This skill supports MySQL only.
- Sample rows are fetched with `LIMIT 5`.
- The skill vendors `PyMySQL` under `scripts/vendor`, so it should work without system-level `pip`.

#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path
import sys
from datetime import date, datetime, time
from decimal import Decimal
import unicodedata

VENDOR_DIR = Path(__file__).resolve().parent / "vendor"
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))

try:
    import pymysql
except ImportError:  # pragma: no cover
    pymysql = None


REQUIRED_ENV_VARS = [
    "MYSQL_HOST",
    "MYSQL_PORT",
    "MYSQL_USER",
    "MYSQL_PASSWORD",
    "MYSQL_DATABASE",
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Inspect one or more MySQL tables in the currently configured database."
    )
    parser.add_argument(
        "--table",
        required=True,
        action="append",
        help="Table name to inspect. Repeat this argument for multiple tables.",
    )
    parser.add_argument(
        "--database",
        help="Database name mentioned by the user. Used for reporting only.",
    )
    return parser.parse_args()


def json_default(value):
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def print_result(payload):
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=json_default))


def missing_env_vars():
    return [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]


def quote_identifier(name):
    return "`" + name.replace("`", "``") + "`"


def split_table_reference(table_name, database_name=None):
    if database_name:
        return database_name, table_name
    if "." not in table_name:
        return None, table_name
    db_name, raw_table_name = table_name.split(".", 1)
    return db_name or None, raw_table_name


def normalize_requested_tables(raw_tables, explicit_database=None):
    normalized_tables = []
    mentioned_databases = []
    seen = set()
    for raw_table in raw_tables:
        if not raw_table:
            continue
        for token in raw_table.split(","):
            token = token.strip()
            if not token:
                continue
            requested_database, table_name = split_table_reference(token, explicit_database)
            key = (requested_database or "", table_name)
            if key in seen:
                continue
            seen.add(key)
            normalized_tables.append(
                {
                    "input": token,
                    "requested_database": requested_database,
                    "table_name": table_name,
                }
            )
            if requested_database:
                mentioned_databases.append(requested_database)
    return normalized_tables, sorted(set(mentioned_databases))


def connect():
    return pymysql.connect(
        host=os.environ["MYSQL_HOST"],
        port=int(os.environ["MYSQL_PORT"]),
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        database=os.environ["MYSQL_DATABASE"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def fetch_table_metadata(cursor, database_name, table_name):
    cursor.execute(
        """
        SELECT TABLE_NAME, TABLE_COMMENT
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
        """,
        (database_name, table_name),
    )
    return cursor.fetchone()


def fetch_columns(cursor, database_name, table_name):
    cursor.execute(
        """
        SELECT
          COLUMN_NAME,
          COLUMN_TYPE,
          IS_NULLABLE,
          COLUMN_DEFAULT,
          COLUMN_COMMENT,
          COLUMN_KEY,
          EXTRA
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
        ORDER BY ORDINAL_POSITION
        """,
        (database_name, table_name),
    )
    return cursor.fetchall()


def fetch_sample_rows(cursor, table_name):
    query = f"SELECT * FROM {quote_identifier(table_name)} LIMIT 5"
    cursor.execute(query)
    return cursor.fetchall()


def build_view(columns, sample_rows):
    headers = [column["COLUMN_NAME"] for column in columns]
    summary_row = [column["COLUMN_COMMENT"] or "" for column in columns]
    data_rows = []
    for sample_row in sample_rows:
        data_rows.append([sample_row.get(header) for header in headers])
    return {
        "headers": headers,
        "structure_summary_row": summary_row,
        "data_rows": data_rows,
    }


def stringify_cell(value):
    if value is None:
        return ""
    return json_default(value)


def display_width(text):
    width = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
    return width


def pad_cell(text, width):
    return text + (" " * max(0, width - display_width(text)))


def truncate_cell(text, width):
    if display_width(text) <= width:
        return pad_cell(text, width)
    if width <= 1:
        return " " * width
    ellipsis = "..."
    limit = max(1, width - len(ellipsis))
    current = ""
    for char in text:
        if display_width(current + char) > limit:
            break
        current += char
    current += ellipsis
    return pad_cell(current, width)


def render_cli_table(rows, max_col_width=28):
    if not rows:
        return ""
    str_rows = [[stringify_cell(cell) for cell in row] for row in rows]
    col_count = max(len(row) for row in str_rows)
    normalized = [row + [""] * (col_count - len(row)) for row in str_rows]
    widths = []
    for idx in range(col_count):
        col_width = max(display_width(row[idx]) for row in normalized)
        widths.append(min(max(col_width, 3), max_col_width))

    def border():
        return "+" + "+".join("-" * (width + 2) for width in widths) + "+"

    lines = [border()]
    for row_index, row in enumerate(normalized):
        rendered = []
        for idx, cell in enumerate(row):
            rendered.append(" " + truncate_cell(cell, widths[idx]) + " ")
        lines.append("|" + "|".join(rendered) + "|")
        if row_index == 0:
            lines.append(border())
    lines.append(border())
    return "\n".join(lines)


def build_cli_summary(table_summary):
    rows = [
        ["Item", "Count", "Tables"],
        ["User mentioned tables", table_summary["mentioned_count"], ", ".join(table_summary["mentioned_tables"])],
        ["Matched tables", table_summary["matched_count"], ", ".join(table_summary["matched_tables"])],
        ["Unmatched tables", table_summary["unmatched_count"], ", ".join(table_summary["unmatched_tables"])],
    ]
    return render_cli_table(rows, max_col_width=40)


def build_cli_table_view(table_entry):
    rows = [
        table_entry["view"]["headers"],
        table_entry["view"]["structure_summary_row"],
        *table_entry["view"]["data_rows"],
    ]
    return render_cli_table(rows, max_col_width=28)


def make_payload(configured_database, normalized_tables, mentioned_databases):
    return {
        "database_status": {
            "configured_database": configured_database,
            "requested_database": normalized_tables[0]["requested_database"] if normalized_tables else None,
            "mentioned_databases": mentioned_databases,
            "searched_database": configured_database,
            "database_name_matches_config": all(
                entry["requested_database"] in (None, "", configured_database)
                for entry in normalized_tables
            ) if configured_database else all(
                entry["requested_database"] in (None, "")
                for entry in normalized_tables
            ),
            "message": "",
        },
        "table_summary": {
            "mentioned_count": len(normalized_tables),
            "mentioned_tables": [entry["table_name"] for entry in normalized_tables],
            "matched_count": 0,
            "matched_tables": [],
            "unmatched_count": 0,
            "unmatched_tables": [],
        },
        "tables": [],
        "cli_rendered": {
            "summary_table": "",
            "table_views": [],
        },
        "errors": [],
    }


def main():
    args = parse_args()
    normalized_tables, mentioned_databases = normalize_requested_tables(args.table, args.database)
    configured_database = os.environ.get("MYSQL_DATABASE")
    payload = make_payload(configured_database, normalized_tables, mentioned_databases)

    missing = missing_env_vars()
    if missing:
        payload["database_status"]["message"] = "Missing required MySQL environment variables."
        payload["errors"].append(
            {
                "code": "missing_environment_variables",
                "message": "Missing required environment variables.",
                "details": missing,
            }
        )
        print_result(payload)
        return 1

    if pymysql is None:
        payload["database_status"]["message"] = "PyMySQL is not installed."
        payload["errors"].append(
            {
                "code": "missing_dependency",
                "message": "PyMySQL is required. Install it with `python3 -m pip install PyMySQL`.",
            }
        )
        print_result(payload)
        return 1

    if payload["database_status"]["database_name_matches_config"]:
        payload["database_status"]["message"] = "Searched the configured database."
    else:
        payload["database_status"]["message"] = (
            "One or more requested database names differ from the configured database. "
            "This skill searched only the configured database."
        )

    try:
        with connect() as connection:
            with connection.cursor() as cursor:
                for requested in normalized_tables:
                    table_name = requested["table_name"]
                    table_metadata = fetch_table_metadata(cursor, configured_database, table_name)
                    if not table_metadata:
                        payload["table_summary"]["unmatched_tables"].append(table_name)
                        continue

                    columns = fetch_columns(cursor, configured_database, table_name)
                    sample_rows = fetch_sample_rows(cursor, table_name)
                    table_entry = {
                        "table_name": table_name,
                        "requested_database": requested["requested_database"],
                        "configured_database": configured_database,
                        "table_comment": table_metadata.get("TABLE_COMMENT"),
                        "schema": columns,
                        "sample_rows": sample_rows,
                        "view": build_view(columns, sample_rows),
                    }
                    payload["table_summary"]["matched_tables"].append(table_name)
                    payload["tables"].append(table_entry)

                payload["table_summary"]["matched_count"] = len(payload["table_summary"]["matched_tables"])
                payload["table_summary"]["unmatched_count"] = len(payload["table_summary"]["unmatched_tables"])
                payload["cli_rendered"]["summary_table"] = build_cli_summary(payload["table_summary"])
                payload["cli_rendered"]["table_views"] = [
                    {
                        "table_name": table_entry["table_name"],
                        "rendered_table": build_cli_table_view(table_entry),
                    }
                    for table_entry in payload["tables"]
                ]
                if payload["table_summary"]["unmatched_tables"]:
                    payload["errors"].append(
                        {
                            "code": "table_not_found",
                            "message": "Some tables were not found in the configured database.",
                            "details": payload["table_summary"]["unmatched_tables"],
                        }
                    )

                print_result(payload)
                return 0
    except Exception as exc:  # pragma: no cover
        payload["database_status"]["message"] = "Failed to inspect configured database."
        payload["errors"].append(
            {
                "code": "database_query_failed",
                "message": str(exc),
            }
        )
        print_result(payload)
        return 1


if __name__ == "__main__":
    sys.exit(main())

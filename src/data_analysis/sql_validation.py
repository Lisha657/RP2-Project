import sqlglot
from src.core.findings import add_finding


def inspect_sql(content, path, findings):
    try:
        parsed = sqlglot.parse(content)

        if parsed:
            add_finding(
                findings, "SQL", "PASS",
                f"Parsed {len(parsed)} SQL statement(s)",
                path,
                "Parsing does not execute SQL against a database."
            )
        else:
            add_finding(
                findings, "SQL", "WARNING",
                "No SQL statements were parsed", path
            )

    except Exception as exc:
        add_finding(
            findings, "SQL", "FAIL",
            f"SQL parsing failed: {exc}", path
        )


def execute_sql_readonly(connection_string, sql_text, findings):
    """Optionally execute read-only SQL against a user-provided database."""
    try:
        from sqlalchemy import create_engine, text as sql_text_clause
    except ImportError:
        add_finding(findings, "SQL Runtime", "NOT RUN", "SQLAlchemy is not installed.", evidence="Install with: python -m pip install sqlalchemy")
        return

    statements = [part.strip() for part in sql_text.split(';') if part.strip()]
    if not statements:
        add_finding(findings, "SQL Runtime", "NOT RUN", "No SQL statements were supplied for execution.")
        return
    engine = None
    try:
        engine = create_engine(connection_string, pool_pre_ping=True)
        with engine.connect() as conn:
            for statement in statements:
                first_word = statement.lstrip().split(None, 1)[0].upper() if statement.strip() else ""
                if first_word not in {"SELECT", "WITH", "EXPLAIN"}:
                    add_finding(findings, "SQL Runtime", "WARNING", "Skipped a non-read-only SQL statement.", evidence="Only SELECT, WITH, and EXPLAIN statements are permitted by this UI.")
                    continue
                try:
                    result = conn.execute(sql_text_clause(statement))
                    if result.returns_rows:
                        rows = result.fetchmany(5)
                        add_finding(findings, "SQL Runtime", "PASS", "Read-only SQL statement executed successfully.", evidence=f"Sample rows returned: {len(rows)}. Only up to 5 rows were fetched for validation.")
                    else:
                        add_finding(findings, "SQL Runtime", "PASS", "Read-only SQL statement executed successfully.")
                except Exception as exc:
                    add_finding(findings, "SQL Runtime", "FAIL", f"SQL execution failed: {exc}")
    except Exception as exc:
        add_finding(findings, "SQL Runtime", "FAIL", f"Could not connect to the database: {exc}")
    finally:
        if engine is not None:
            engine.dispose()

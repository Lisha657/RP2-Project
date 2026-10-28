import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError


def test_sql_query(query, dialect=None):
    """Validate a SQL query and identify referenced tables."""

    results = {
        "query": query,
        "status": "success",
        "syntax_valid": False,
        "tables_referenced": [],
        "issues_found": []
    }

    if not query or not query.strip():
        results["status"] = "failed"
        results["issues_found"].append({
            "issue": "Empty SQL input",
            "details": "No SQL query was provided."
        })
        return results

    try:
        parsed_queries = sqlglot.parse(
            query,
            read=dialect,
            error_level="RAISE"
        )

        parsed_queries = [
            parsed for parsed in parsed_queries
            if parsed is not None
        ]

        if not parsed_queries:
            raise ValueError("No SQL statements found.")

        tables = set()

        for parsed in parsed_queries:
            if not isinstance(
                parsed,
                (
                    exp.Query,
                    exp.Insert,
                    exp.Update,
                    exp.Delete,
                    exp.Create,
                    exp.Drop
                )
            ):
                raise ValueError(
                    "Input is not a recognised SQL statement."
                )

            for table in parsed.find_all(exp.Table):
                tables.add(table.sql())

        results["syntax_valid"] = True
        results["tables_referenced"] = sorted(tables)

    except (ParseError, ValueError) as error:
        results["status"] = "failed"
        results["issues_found"].append({
            "issue": "SQL validation error",
            "details": str(error)
        })

    return results


def test_sql_file(file_path, dialect=None):
    """Read a SQL file and test each statement separately."""

    try:
        with open(file_path, "r", encoding="utf-8") as file:
            sql_content = file.read()

    except OSError as error:
        return {
            "file": file_path,
            "status": "failed",
            "message": str(error),
            "total_statements": 0,
            "results": []
        }

    if not sql_content.strip():
        return {
            "file": file_path,
            "status": "failed",
            "message": "The SQL file is empty.",
            "total_statements": 0,
            "results": []
        }

    try:
        statements = sqlglot.parse(
            sql_content,
            read=dialect,
            error_level="RAISE"
        )
    except ParseError as error:
        return {
            "file": file_path,
            "status": "failed",
            "message": f"File parsing failed: {error}",
            "total_statements": 0,
            "results": []
        }

    results = []

    for statement in statements:
        if statement is None:
            continue

        results.append(
            test_sql_query(statement.sql(dialect=dialect), dialect)
        )

    failed_count = sum(
        result["status"] == "failed"
        for result in results
    )

    return {
        "file": file_path,
        "status": "success" if failed_count == 0 else "completed_with_issues",
        "total_statements": len(results),
        "passed_statements": len(results) - failed_count,
        "failed_statements": failed_count,
        "results": results
    }
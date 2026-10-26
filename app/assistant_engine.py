"""Constrained natural-language SQL reporting MVP.

Only the question and the curated semantic schema are sent to the cloud.
No database rows or connection credentials are sent to the model.
"""
import json
import os
import logging
from decimal import Decimal
from fastapi import HTTPException
from openai import OpenAI
from sqlglot import parse_one, exp

logger = logging.getLogger('uvicorn.error')

ALLOWED = {
    "fact_invoice": {
        "full": "sale.Fact_Invoice",
        "columns": {"Invoice_ID", "Invoice_Item_ID", "Product_ID", "Invoice_QTY",
                    "Net_Price", "Is_Return", "Invoice_Status", "Creation_Date_ID"}
    },
    "dim_date": {
        "full": "sale.Dim_Date",
        "columns": {"MiladiDateKey", "jyear", "jmonthN"}
    }
}
PROMPT = """You translate colloquial Persian questions into Microsoft SQL Server SELECT queries.
Return a JSON object with keys sql, title, chart, clarification.
sql must be a SELECT statement or empty if impossible; chart is one of table, bar, line, none.
If the user requests fields outside the available schema, return empty sql and explain in clarification.
Use only these tables and columns:
sale.Fact_Invoice f: Invoice_ID, Invoice_Item_ID, Product_ID, Invoice_QTY, Net_Price, Is_Return, Invoice_Status, Creation_Date_ID
sale.Dim_Date d: MiladiDateKey, jyear, jmonthN
JOIN f.Creation_Date_ID = d.MiladiDateKey.
Business rules: confirmed invoices f.Invoice_Status IN (2,11).
Gross sales = SUM(CASE WHEN Is_Return=0 THEN Net_Price ELSE 0 END).
Returns = SUM(CASE WHEN Is_Return=1 THEN Net_Price ELSE 0 END).
Net sales = gross minus returns. Net quantity likewise using Invoice_QTY.
Net_Price currency IRR. Dates jyear/jmonthN are Persian calendar.
Always use qualified column references. Never use SELECT *.\nDo not wrap SQL in Markdown fences and do not append a semicolon.
Never use any other tables, dynamic SQL, CTE, subqueries, or UNION.
Always constrain the Persian year when the question supplies it.
Return a short SQL query with TOP (100) for non-aggregated row listings.
Do not assume unsupported business definitions or unknown product names.
"""
SCHEMA = {
    "type": "object",
    "properties": {
        "sql": {"type": "string"},
        "title": {"type": "string"},
        "chart": {"type": "string", "enum": ["table", "bar", "line", "none"]},
        "clarification": {"type": "string"}
    },
    "required": ["sql", "title", "chart", "clarification"],
    "additionalProperties": False
}
ALLOWED_FUNCTIONS = {"SUM", "COUNT", "AVG", "MIN", "MAX", "COALESCE", "ISNULL", "NULLIF", "ABS", "ROUND"}
FORBIDDEN = (exp.Subquery, exp.Union, exp.Intersect, exp.Except, exp.CTE,
             exp.With, exp.Into, exp.Command, exp.Insert, exp.Update,
             exp.Delete, exp.Create, exp.Drop, exp.Alter, exp.Star,
             exp.Or, exp.Not, exp.Exists, exp.Window, exp.Lateral)


def validate_sql(sql: str) -> str:
    sql = sql.strip()
    if sql.endswith(";"):
        sql = sql[:-1].rstrip()
    if not sql or len(sql) > 7000 or ";" in sql or "--" in sql or "/*" in sql:
        raise ValueError("SQL syntax not permitted")
    try:
        tree = parse_one(sql, read="tsql")
    except Exception as exc:
        raise ValueError("Cannot parse SQL") from exc
    if not isinstance(tree, exp.Select):
        raise ValueError("Only a SELECT is permitted")
    for node in tree.walk():
        if isinstance(node, FORBIDDEN):
            raise ValueError("SQL construct not permitted")
        if isinstance(node, exp.Anonymous) and node.name.upper() not in ALLOWED_FUNCTIONS:
            raise ValueError("SQL function not permitted")
    tables = list(tree.find_all(exp.Table))
    if not tables or len(tables) > 2:
        raise ValueError("Unsupported table selection")
    aliases = {}
    for t in tables:
        schema = (t.db or "").lower()
        name = t.name.lower()
        if (schema, name) not in {("sale", "fact_invoice"), ("sale", "dim_date")}:
            raise ValueError("Table is not in the allowlist")
        key = t.alias_or_name.lower()
        if key in aliases:
            raise ValueError("Duplicate alias")
        aliases[key] = ALLOWED[name]["columns"]
    for col in tree.find_all(exp.Column):
        qualifier = col.table.lower()
        if not qualifier or qualifier not in aliases:
            raise ValueError("Columns must use known table aliases")
        if col.name.lower() not in {c.lower() for c in aliases[qualifier]}:
            # output aliases in ORDER BY are allowed when unqualified, but require explicit expressions for MVP
            raise ValueError("Unknown column")
    # Require the mandatory invoice status filter, verified structurally.
    invoice_aliases = [a for a, cols in aliases.items() if "Invoice_Status" in cols]
    if not invoice_aliases:
        raise ValueError("Sales fact table required")
    where = tree.args.get("where")
    if where is None:
        raise ValueError("Status filter is mandatory")
    # Keep this MVP fail-closed: require literal IN (2, 11), not an arbitrary equivalent.
    valid_status = False
    for item in where.find_all(exp.In):
        lhs = item.this
        if isinstance(lhs, exp.Column) and lhs.name.lower() == "invoice_status" and lhs.table.lower() in invoice_aliases:
            vals = {x.name for x in item.expressions if isinstance(x, exp.Literal)}
            if vals == {"2", "11"} and len(item.expressions) == 2:
                valid_status = True
    if not valid_status:
        raise ValueError("Confirmed status filter is missing")
    # Require an explicit bounded Persian year to prevent accidental full-history scans.
    if not any(isinstance(e, exp.EQ) and (
        (isinstance(e.left, exp.Column) and e.left.name.lower() == "jyear" and isinstance(e.right, exp.Literal)) or
        (isinstance(e.right, exp.Column) and e.right.name.lower() == "jyear" and isinstance(e.left, exp.Literal))
    ) for e in where.find_all(exp.EQ)):
        raise ValueError("A specific Persian year filter is required")
    if len(tables) == 2:
        joins = list(tree.find_all(exp.Join))
        if not joins or not any(
            isinstance(e, exp.EQ)
            and {getattr(e.left, "name", "").lower(), getattr(e.right, "name", "").lower()}
            == {"creation_date_id", "miladidatekey"}
            for j in joins for e in j.find_all(exp.EQ)
        ):
            raise ValueError("Approved date join is required")
    # Restrict output size even if the model omits TOP.
    tree.set("limit", exp.Limit(expression=exp.Literal.number(200)))
    return tree.sql(dialect="tsql")


def ask(question: str, connection_factory):
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(503, "OPENAI_API_KEY is not configured")
    try:
        client = OpenAI(timeout=35.0)
        result = client.responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
            instructions=PROMPT,
            input=question,
            text={"format": {"type": "json_schema", "name": "sql_plan",
                             "schema": SCHEMA, "strict": True}},
            store=False
        )
        plan = json.loads(result.output_text)
    except Exception as exc:
        raise HTTPException(502, "AI planning failed") from exc
    if not plan.get("sql"):
        return {"status": "needs_clarification", "message": plan.get("clarification") or "اطلاعات کافی نیست"}
    try:
        sql = validate_sql(plan["sql"])
    except ValueError as exc:
        return {"status": "rejected", "message": str(exc), "sql": None}
    try:
        with connection_factory() as connection:
            cursor = connection.cursor()
            cursor.timeout = 15
            cursor.execute("SET LOCK_TIMEOUT 5000")
            cursor.execute(sql)
            columns = [x[0] for x in cursor.description]
            rows = [
                {k: str(v) if isinstance(v, Decimal) else v for k, v in zip(columns, row)}
                for row in cursor.fetchmany(201)
            ]
    except Exception as exc:
        logger.error("Report execution failed: error_type=%s, sqlstate=%s, message=%s", type(exc).__name__, exc.args[0] if getattr(exc, "args", None) else "unknown", str(exc)[:700])
        raise HTTPException(503, "Report execution failed; check server logs") from exc
    return {"status": "ok", "title": plan["title"], "chart": plan["chart"],
            "currency": "IRR", "columns": columns, "rows": rows[:200],
            "row_count": min(len(rows), 200), "truncated": len(rows) > 200,
            "sql": sql}

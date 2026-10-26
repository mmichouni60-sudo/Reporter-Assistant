"""Read-only DWH metadata discovery. Does not read business data rows."""
from fastapi import HTTPException
import pyodbc

def discover(connection_factory, schema=None):
    sql = """
    SELECT s.name AS schema_name, t.name AS table_name,
           c.name AS column_name, ty.name AS data_type,
           c.is_nullable, c.column_id
    FROM sys.tables AS t
    JOIN sys.schemas AS s ON s.schema_id = t.schema_id
    JOIN sys.columns AS c ON c.object_id = t.object_id
    JOIN sys.types AS ty ON ty.user_type_id = c.user_type_id
    WHERE (? IS NULL OR s.name = ?)
      AND t.is_ms_shipped = 0
    ORDER BY s.name, t.name, c.column_id
    """
    fk_sql = """
    SELECT ps.name, pt.name, pc.name, rs.name, rt.name, rc.name, fk.name
    FROM sys.foreign_key_columns AS fkc
    JOIN sys.foreign_keys AS fk ON fk.object_id = fkc.constraint_object_id
    JOIN sys.tables AS pt ON pt.object_id = fkc.parent_object_id
    JOIN sys.schemas AS ps ON ps.schema_id = pt.schema_id
    JOIN sys.columns AS pc ON pc.object_id = pt.object_id AND pc.column_id = fkc.parent_column_id
    JOIN sys.tables AS rt ON rt.object_id = fkc.referenced_object_id
    JOIN sys.schemas AS rs ON rs.schema_id = rt.schema_id
    JOIN sys.columns AS rc ON rc.object_id = rt.object_id AND rc.column_id = fkc.referenced_column_id
    WHERE (? IS NULL OR ps.name = ? OR rs.name = ?)
    ORDER BY ps.name, pt.name, fk.name
    """
    try:
        with connection_factory() as connection:
            connection.timeout = 15
            cur = connection.cursor()
            column_rows = cur.execute(sql, schema, schema).fetchall()
            fk_rows = cur.execute(fk_sql, schema, schema, schema).fetchall()
    except pyodbc.Error as exc:
        raise HTTPException(503, "DWH metadata discovery failed") from exc
    tables = {}
    for r in column_rows:
        key = (r[0], r[1])
        if key not in tables:
            tables[key] = {"schema": r[0], "table": r[1], "columns": []}
        tables[key]["columns"].append({
            "name": r[2], "type": r[3], "nullable": bool(r[4])
        })
    relationships = [{
        "from": {"schema": r[0], "table": r[1], "column": r[2]},
        "to": {"schema": r[3], "table": r[4], "column": r[5]},
        "constraint": r[6]
    } for r in fk_rows]
    return {
        "table_count": len(tables),
        "relationship_count": len(relationships),
        "tables": list(tables.values()),
        "relationships": relationships,
        "note": "Metadata only. No business records were queried."
    }

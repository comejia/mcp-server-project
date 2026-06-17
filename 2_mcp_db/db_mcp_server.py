from fastmcp import FastMCP
import sqlite3
from typing import List, Dict, Any


DB_PATH = "/home/comejia/projects/mcp-servers-project/2_intro/tienda_videojuegos.db"

# MCP Server instance
mcp = FastMCP("Videogames store")


def connect_db():
    """Connect to the SQLite database."""
    return sqlite3.connect(DB_PATH)


# Tools
@mcp.tool()
def get_tables() -> List[str]:
    """
    Get all the tables in the database.
    Used for exploring the database schema.

    Returns:
        List[str]: A list of table names.
    """
    try:
        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table'
            ORDER BY name
        """)
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        return tables
    except sqlite3.Error as e:
        return [{"error": str(e), "tipo": "SQLError"}]


@mcp.tool()
def describe_table(table_name: str) -> Dict[str, Any]:
    """
    Get detailed information about a specific table.
    Includes columns, data types, and schema information.

    Args:
        table_name: Name of the table to describe

    Returns:
        Dictionary with the table schema
    """
    conn = connect_db()
    cursor = conn.cursor()

    # Get column information
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = cursor.fetchall()

    # Get record count
    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    record_count = cursor.fetchone()[0]

    conn.close()

    schema = {
        "nombre": table_name,
        "total_registros": record_count,
        "columnas": [
            {
                "nombre": col[1],
                "tipo": col[2],
                "no_nulo": bool(col[3]),
                "valor_por_defecto": col[4],
                "es_clave_primaria": bool(col[5]),
            }
            for col in columns
        ],
    }

    return schema


@mcp.tool()
def execute_query(sql: str) -> List[Dict[str, Any]]:
    """
    Execute a read-only SQL SELECT query on the database.

    IMPORTANT: Only SELECT (read-only) queries are allowed.
    No INSERT, UPDATE, DELETE, DROP, etc.

    Args:
        sql: SQL SELECT query to execute

    Returns:
        List of dictionaries with the results
    """
    # Security validation: only allow SELECT
    sql_upper = sql.strip().upper()
    if not sql_upper.startswith("SELECT"):
        return [{"error": "Only SELECT queries are allowed", "tipo": "SecurityError"}]

    # Forbidden words for security
    forbidden_words = ["DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "CREATE"]
    if any(palabra in sql_upper for palabra in forbidden_words):
        return [
            {
                "error": f"Forbidden query. Forbidden words: {', '.join(forbidden_words)}",
                "tipo": "SecurityError",
            }
        ]

    try:
        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute(sql)

        # Get column names
        columns = [description[0] for description in cursor.description]

        # Convert results to a list of dictionaries
        results = []
        for row in cursor.fetchall():
            results.append(dict(zip(columns, row)))

        conn.close()

        return results
    except sqlite3.Error as e:
        return [{"error": str(e), "tipo": "SQLError"}]


# Start point
if __name__ == "__main__":
    # mcp.run(transport="http", host="127.0.0.1", port=8080, path="/mcp")
    mcp.run()

# MCP Servers

Este repositorio contiene una serie de servidores MCP que pueden ser utilizados para integrar diferentes servicios con herramientas de IA. Actualmente se cuenta con: 

- 2_mcp_db: Servidor MCP para gestionar bases de datos.
- 3_mcp_gmail: Servidor MCP para gestionar Gmail.


## Recursos vs Herramientas

| Característica | Herramientas (Tools) | Recursos (Resources) |
|---|---|---|
| **Objetivo** | Realizar acciones específicas | Proveer contexto, datos o conocimientos |
| **Naturaleza** | Activas (verbos) | Pasivas (sustantivos) |
| **Ejemplos** | `list_emails()`, `send_email()`, `search_db()` | `emails`, `database_tables`, `user_profile` |
| **Interacción** | Llamadas directas con argumentos | Acceso y lectura/escritura de datos |
| **Dependencia** | El agente elige cuándo usarlas | El agente accede cuando necesita |


## Comandos útiles

Iniciar MCP server:
```bash
fastmcp run <path_to_server>
fastmcp run <path_to_server> --transport http --port 8080
```

Inspeccionar MCP servers:
```bash
fastmcp dev inspector <path_to_server>
```

## Referencias
- [Model Context Protocol](https://github.com/modelcontextprotocol/modelcontextprotocol)
- [MCP Servers](https://mcpservers.org/)
- [FastMcp](https://github.com/PrefectHQ/fastmcp)


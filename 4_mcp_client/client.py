from fastmcp import Client
import asyncio
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv
import os
import json

load_dotenv()


class GmailMCPClient:
    def __init__(self, mcp_server_path: str):
        self.mcp_server_path = mcp_server_path
        self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    async def _get_mcp_client(self):
        """Crear conexion con el servidor MCP"""
        return Client(self.mcp_server_path)

    async def get_system_info(self) -> dict:
        """Obtener informacion del sistema"""

        async with await self._get_mcp_client() as client:
            tools = await client.list_tools()
            resources = await client.list_resources()
            templates = await client.list_resource_templates()
            prompts = await client.list_prompts()

            return {
                "tools": [t.name for t in tools],
                "resources": [r.name for r in resources],
                "templates": [t.name for t in templates],
                "prompts": [p.name for p in prompts],
                "server": self.mcp_server_path,
            }

    async def get_tools_for_openai(self):
        """Convierte herramientas MCP a formato compatible con OpenAI"""

        async with await self._get_mcp_client() as client:
            tools = await client.list_tools()

            openai_tools = []

            for tool in tools:
                openai_tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description or "",
                            "parameters": tool.inputSchema,
                        },
                    }
                )

            return openai_tools, client

    async def get_resources_as_tools(self):
        """Encapsula rescursos y templates como herramientas"""

        async with await self._get_mcp_client() as client:
            resources = await client.list_resources()
            templates = await client.list_resource_templates()

            resources_tools = []
            resource_map = {}

            # Static Resources
            for resource in resources:
                uri = str(resource.uri)
                func_name = f"get_resource_{uri.replace('://', '_').replace('/', '_')}"

                resources_tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": func_name,
                            "description": resource.description or resource.name,
                            "parameters": {
                                "type": "object",
                                "properties": {},
                                "required": [],
                            },
                        },
                    }
                )

                resource_map[func_name] = {"uri": uri}

            # Resource Templates
            for template in templates:
                uri_template = str(template.uriTemplate)
                func_name = template.name

                # Extraer parametros del template
                import re

                params = re.findall(r"\{(\w+)\}", uri_template)

                properties = {
                    p: {"type": "string", "description": f"Parametro {p}"}
                    for p in params
                }

                resources_tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": func_name,
                            "description": template.description or template.name,
                            "parameters": {
                                "type": "object",
                                "properties": properties,
                                "required": params,
                            },
                        },
                    }
                )

                resource_map[func_name] = {"template": uri_template, "params": params}

            return resources_tools, resource_map

    async def get_prompt_messages(self, prompt_name: str, **kwargs) -> str:
        """Obtiene el mensaje de un prompt especifico"""
        async with await self._get_mcp_client() as client:
            prompt = await client.get_prompt(prompt_name, arguments=kwargs)
            return prompt.messages[0].content.text

    async def call_tool(self, tool_name: str, arguments: dict, client):
        """Ejecuta una herramienta MCP"""
        result = await client.call_tool(tool_name, arguments)

        if result and result.content and len(result.content) > 0:
            if hasattr(result.content[0], "text"):
                return result.content[0].text

        return "Herramienta ejecutada sin resultados"

    async def get_resource(self, uri: str, client):
        """Obtiene un recurso MCP"""
        result = await client.read_resource(uri)

        if result and len(result) > 0:
            if hasattr(result[0], "text"):
                return result[0].text
            elif hasattr(result[0], "content"):
                return result[0].content

        return "Recurso no disponible"

    async def chat(self, messages: list) -> str:
        """Procesa una conversacion con GPT utilizando MCP"""

        async with await self._get_mcp_client() as client:
            tools, _ = await self.get_tools_for_openai()
            resource_tools, resource_map = await self.get_resources_as_tools()
            all_tools = tools + resource_tools

            # Llamada inicial a OpenAI
            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                tools=all_tools,
                tool_choice="auto",
            )

            response_message = response.choices[0].message
            tool_calls = response_message.tool_calls

            if not tool_calls:
                return response_message.content

            # Ejecutar herramientas MCP
            messages.append(
                {
                    "role": "assistant",
                    "content": response_message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in tool_calls
                    ],
                }
            )

            for tool_call in tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)

                # Verificar si es un recurso
                if function_name in resource_map:
                    resource_info = resource_map[function_name]

                    if "template" in resource_info:
                        uri = resource_info["template"]
                        for param in resource_info["params"]:
                            uri = uri.replace(
                                f"{{{param}}}", str(function_args.get(param, ""))
                            )
                    else:  # Recurso estatico
                        uri = resource_info["uri"]

                    function_response = await self.get_resource(uri, client)
                else:  # Herramienta normal
                    function_response = await self.call_tool(
                        function_name, function_args, client
                    )

                messages.append(
                    {
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": function_name,
                        "content": function_response,
                    }
                )

            # Segunda llamada con los resultados de la herramienta
            second_response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini", messages=messages
            )
            return second_response.choices[0].message.content


ROOT_DIR = Path(__file__).resolve().parent


async def main():
    mcp_client = GmailMCPClient(str(ROOT_DIR / "gmail_mcp_server.py"))
    info = await mcp_client.get_system_info()
    print(info)


if __name__ == "__main__":
    asyncio.run(main())

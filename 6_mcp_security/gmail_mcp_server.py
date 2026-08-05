"""
Servidor MCP para gestionar Gmail
Requiere: uv pip install fastmcp google-auth-oauthlib google-api-python-client
"""

from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import JWTVerifier, RSAKeyPair
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.exceptions import ToolError, ResourceError, PromptError
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import base64
from email.mime.text import MIMEText
import os.path
import pickle
from pathlib import Path
import json
from pydantic import SecretStr
from typing import Optional
import jwt


ROOT_DIR = Path(__file__).resolve().parent

# Configuración
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


# ========= SISTEMA DE PERMISOS ==========

# Definir roles y permisos
PERMISSIONS = {
    "admin": {
        "tools": ["list_emails", "send_email"],
        "resources": ["gmail://profile", "docs://setup-manual/{version}"],
        "prompts": ["daily_email_summary", "compose_professional_email"],
    },
    "reader": {
        "tools": ["list_emails"],
        "resources": ["gmail://profile"],
        "prompts": ["daily_email_summary"],
    },
    "sender": {
        "tools": ["send_email"],
        "resources": [],
        "prompts": ["compose_professional_email"],
    },
}

# Mapeo de usuarios a roles
USER_ROLES = {
    "gmail-client": "admin",
    "read-only-user": "reader",
    "email-sender": "sender",
}


# ========= MIDDLEWARE DE AUTORIZACIÓN ==========


class AuthorizationMiddleware(Middleware):
    """Middleware para autorización basado en roles y permisos de tools, resources y prompts."""

    def __init__(self, public_key: str, issuer: str, audience: str):
        super().__init__()
        self.permissions = PERMISSIONS
        self.user_roles = USER_ROLES
        self.public_key = public_key
        self.issuer = issuer
        self.audience = audience

    def get_user_from_context(self, context: MiddlewareContext) -> Optional[str]:
        """Extrae y valida el usuario del contexto (por ejemplo, desde token JWT en el header Authorization)"""

        try:
            # Acceder al request desde el contexto
            request = None

            if hasattr(context, "fastmcp_context") and context.fastmcp_context:
                if hasattr(context.fastmcp_context, "request_context"):
                    req_ctx = context.fastmcp_context.request_context
                    if hasattr(req_ctx, "request"):
                        request = req_ctx.request

            if not request:
                print("No se pudo obtener el request del contexto.")
                return None

            # Extraer el token del header Authorization
            auth_header = request.headers.get("authorization", "")

            if not auth_header:
                print("No se encontró el header Authorization.")
                return None

            if not auth_header.startswith("Bearer "):
                print(
                    "El header Authorization no tiene el formato esperado 'Bearer <token>'."
                )
                return None

            token = auth_header.split(" ")[1]

            # Decodificar y validar el token JWT
            try:
                payload = jwt.decode(
                    token,
                    self.public_key,
                    algorithms=["RS256"],
                    issuer=self.issuer,
                    audience=self.audience,
                )

                # Extraer el subject (usuario) del payload
                user_id = payload.get("sub")

                if user_id:
                    print("Usuario extraído correctamente del token JWT")
                    return user_id
                else:
                    print("No se encontró el 'sub' en el payload del token JWT.")
                    return None
            except jwt.ExpiredSignatureError:
                print("El token JWT ha expirado.")
                return None
            except jwt.InvalidTokenError as e:
                print(f"El token JWT es inválido: {e}")
                return None

        except Exception as e:
            print(f"Error al obtener request del contexto: {e}")
            return None

    def get_user_permissions(self, user_id: str) -> dict:
        """Obtiene los permisos del usuario basado en su rol"""
        role = self.user_roles.get(user_id, "reader")
        return self.permissions.get(role, self.permissions["reader"])

    def has_permission(
        self, user: str, component_type: str, component_name: str
    ) -> bool:
        """Verifica si el usuario tiene permiso para acceder al componente del servidor MCP"""
        if not user:
            return False

        permissions = self.get_user_permissions(user)
        allowed_components = permissions.get(component_type, [])

        # Para resources con templates, verificar el patrón
        if component_type == "resources":
            for allowed in allowed_components:
                if "{" in allowed:
                    # Es un template, verificar el patron base
                    base_pattern = allowed.split("{")[0]
                    if component_name.startswith(base_pattern):
                        return True
                elif component_name == allowed:
                    return True
            return False

        return component_name in allowed_components

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        """Intercepta llamadas a tools y valida permisos"""
        user = self.get_user_from_context(context)
        tool_name = context.message.name

        if not self.has_permission(user, "tools", tool_name):
            raise ToolError(
                f"No tienes suficientes permisos para ejecutar '{tool_name}'."
                f"Tu rol actual no permite esta operación"
            )

        print(f"{user} ejecutando tool: {tool_name}")
        return await call_next(context)

    async def on_read_resource(self, context: MiddlewareContext, call_next):
        """Intercepta acceso a resources y valida permisos"""
        user = self.get_user_from_context(context)
        resource_uri = str(context.message.uri)

        if not self.has_permission(user, "resources", resource_uri):
            raise ResourceError(
                f"❌ No tienes permisos para acceder a '{resource_uri}'. "
                f"Tu rol actual no permite esta operación."
            )

        print(f"✅ {user} leyendo resource: {resource_uri}")
        return await call_next(context)

    async def on_get_prompt(self, context: MiddlewareContext, call_next):
        """Intercepta acceso a prompts y valida permisos"""
        user = self.get_user_from_context(context)
        prompt_name = context.message.name

        if not self.has_permission(user, "prompts", prompt_name):
            raise PromptError(
                f"❌ No tienes permisos para usar el prompt '{prompt_name}'. "
                f"Tu rol actual no permite esta operación."
            )

        print(f"✅ {user} usando prompt: {prompt_name}")
        return await call_next(context)

    async def on_list_tools(self, context: MiddlewareContext, call_next):
        """Filtra la lista de tools según permisos del usuario"""
        user = self.get_user_from_context(context)
        all_tools = await call_next(context)

        if not user:
            return []

        permissions = self.get_user_permissions(user)
        allowed_tools = permissions.get("tools", [])

        # Filtrar tools permitidos
        filtered_tools = [tool for tool in all_tools if tool.name in allowed_tools]

        print(f"📋 {user} tiene acceso a {len(filtered_tools)}/{len(all_tools)} tools")
        return filtered_tools

    async def on_list_resources(self, context: MiddlewareContext, call_next):
        """Filtra la lista de resources según permisos del usuario"""
        user = self.get_user_from_context(context)
        all_resources = await call_next(context)

        if not user:
            return []

        permissions = self.get_user_permissions(user)
        allowed_resources = permissions.get("resources", [])

        # Filtrar resources permitidos
        filtered_resources = [
            resource
            for resource in all_resources
            if any(
                str(resource.uri) == allowed
                or (
                    "{" in allowed
                    and str(resource.uri).startswith(allowed.split("{")[0])
                )
                for allowed in allowed_resources
            )
        ]

        print(
            f"📋 {user} tiene acceso a {len(filtered_resources)}/{len(all_resources)} resources"
        )
        return filtered_resources

    async def on_list_resource_templates(self, context: MiddlewareContext, call_next):
        """Filtra la lista de resource templates según permisos del usuario"""
        user = self.get_user_from_context(context)
        all_templates = await call_next(context)

        if not user:
            print("⚠️  Sin usuario: retornando lista vacía de templates")
            return []

        permissions = self.get_user_permissions(user)
        allowed_resources = permissions.get("resources", [])

        # Filtrar templates permitidos
        filtered_templates = []

        for template in all_templates:
            # Intentar diferentes atributos posibles
            template_uri = None

            if hasattr(template, "uri_template"):
                template_uri = str(template.uri_template)
            elif hasattr(template, "uriTemplate"):
                template_uri = str(template.uriTemplate)
            elif hasattr(template, "name"):
                # Último recurso: usar el nombre del template
                template_uri = template.name
            else:
                print(f"⚠️  Template sin uri_template. Atributos: {dir(template)}")
                continue

            # Verificar si este template está permitido
            is_allowed = False
            for allowed in allowed_resources:
                if "{" in allowed:
                    # Es un template pattern, verificar coincidencia
                    allowed_base = allowed.split("{")[0]
                    template_base = (
                        template_uri.split("{")[0]
                        if "{" in template_uri
                        else template_uri
                    )

                    if template_base == allowed_base or template_uri == allowed:
                        is_allowed = True
                        break
                elif template_uri == allowed or template_uri.startswith(allowed):
                    # Coincidencia exacta o prefijo
                    is_allowed = True
                    break

            if is_allowed:
                filtered_templates.append(template)

        print(
            f"📋 {user} tiene acceso a {len(filtered_templates)}/{len(all_templates)} templates"
        )
        return filtered_templates


# ========= AUTH ==========


# Autenticación con JWT
def get_or_create_keypair():
    """Obtiene o crea el par de claves RSA"""
    keypair_file = ROOT_DIR / "keypair.json"

    if os.path.exists(keypair_file):
        # Cargar par de claves desde archivo
        with open(keypair_file, "r") as file:
            data = json.load(file)
            return RSAKeyPair(
                private_key=SecretStr(data["private_key"]),
                public_key=data["public_key"],
            )
    else:
        # Generar un nuevo par de claves
        keypair = RSAKeyPair.generate()
        private_key = keypair.private_key.get_secret_value()
        public_key = keypair.public_key
        # Guardar par de claves en archivo
        with open(keypair_file, "w") as file:
            json.dump(
                {"private_key": private_key, "public_key": public_key}, file, indent=2
            )
        return keypair


# Generar/cargar par de claves
keypair = get_or_create_keypair()


# Crear token para el cliente
def create_client_token(user_id: str, role: str) -> str:
    """Crea un token JWT para un usuario específico"""
    token = keypair.create_token(
        subject=user_id,
        issuer="gmail-mcp-server",
        audience="gmail-mcp",
        additional_claims={"role": role},
    )

    with open(ROOT_DIR / f"{user_id}_token.txt", "w") as token_file:
        token_file.write(token)

    print(f"Token generado para {user_id} (rol: {role})")
    return token


# Generar tokens para usuarios de ejemplo
for user_id, role in USER_ROLES.items():
    create_client_token(user_id, role)

# Configurar auth con JWTVerifier
public_key_str = keypair.public_key

auth = JWTVerifier(
    public_key=public_key_str, issuer="gmail-mcp-server", audience="gmail-mcp"
)

# Crear servidor con auth
mcp = FastMCP("Gmail Manager", auth=auth)

# Agregar middleware de autorización al servidor MCP
mcp.add_middleware(
    AuthorizationMiddleware(
        public_key=public_key_str, issuer="gmail-mcp-server", audience="gmail-mcp"
    )
)


# ========= TOOLS ==========


def get_gmail_service():
    """Obtiene el servicio de Gmail autenticado"""
    creds = None

    # Token guardado previamente
    if os.path.exists(ROOT_DIR / "token.pickle"):
        with open(ROOT_DIR / "token.pickle", "rb") as token:
            creds = pickle.load(token)

    # Si no hay credenciales válidas, solicita login
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                ROOT_DIR / "credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Guarda las credenciales para la próxima vez
        with open(ROOT_DIR / "token.pickle", "wb") as token:
            pickle.dump(creds, token)

    return build("gmail", "v1", credentials=creds)


@mcp.tool()
def list_emails(max_results: int = 10, query: str = "") -> list[dict]:
    """
    Lista los emails recientes del usuario

    Args:
        max_results: Número máximo de emails a retornar (default: 10)
        query: Filtro de búsqueda de Gmail (ej: "from:juan@example.com", "is:unread")

    Returns:
        Lista de emails con id, asunto, remitente y snippet
    """
    service = get_gmail_service()

    results = (
        service.users()
        .messages()
        .list(userId="me", maxResults=max_results, q=query)
        .execute()
    )

    messages = results.get("messages", [])
    emails = []

    for msg in messages:
        # Obtener detalles del mensaje
        message = service.users().messages().get(userId="me", id=msg["id"]).execute()
        headers = message["payload"]["headers"]

        subject = next(
            (h["value"] for h in headers if h["name"] == "Subject"), "Sin asunto"
        )
        sender = next(
            (h["value"] for h in headers if h["name"] == "From"), "Desconocido"
        )

        emails.append(
            {
                "id": msg["id"],
                "subject": subject,
                "from": sender,
                "snippet": message["snippet"],
            }
        )

    return emails


@mcp.tool()
def send_email(to: str, subject: str, body: str) -> dict:
    """
    Envía un email desde la cuenta del usuario

    Args:
        to: Dirección de email del destinatario
        subject: Asunto del email
        body: Cuerpo del mensaje en texto plano

    Returns:
        Confirmación con el ID del mensaje enviado
    """
    service = get_gmail_service()

    # Crear el mensaje
    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject

    # Codificar en base64
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    # Enviar
    sent_message = (
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
    )

    return {
        "status": "sent",
        "message_id": sent_message["id"],
        "to": to,
        "subject": subject,
    }


# ========== RESOURCES ==========


@mcp.resource("gmail://profile")
def get_profile() -> str:
    """
    Obtiene el perfil del usuario en Gmail

    Returns:
        Perfil del usuario
    """

    service = get_gmail_service()
    profile = service.users().getProfile(userId="me").execute()
    output = f"""
    # Perfil de Gmail
    - **Email**: {profile["emailAddress"]}
    - **Mensajes totales**: {profile["messagesTotal"]}
    - **Hilos totales**: {profile["threadsTotal"]}
    """
    return output


# ========== RESOURCE TEMPLATES ===============


@mcp.resource("docs://setup-manual/{version}")
def get_setup_manual(version: str) -> str:
    """
    Resource Template: Manual de configuración en formato PDF.

    URIs válidas:
    - docs://setup-manual/latest -> Versión más reciente del manual
    - docs://setup-manual/v1 -> Versión 1 del manual
    - docs://setup-manual/v2 -> Versión 2 del manual
    - docs://setup-manual/v3 -> Versión 3 del manual

    Args:
        version: Versión del manual de setup

    Returns:
        Plantilla solicitada
    """

    import PyPDF2

    # Mapeo de versiones
    version_map = {
        "latest": "manual_v3.pdf",
        "v1": "manual_v1.pdf",
        "v2": "manual_v2.pdf",
        "v3": "manual_v3.pdf",
    }

    # Obtener versión solicitada
    filename = version_map.get(version.lower(), "manual_v3.pdf")

    if not filename:
        return f"Versión {version} no encontrada."

    # Construir la ruta del archivo
    pdf_path = ROOT_DIR / "manuals" / filename

    # Verificar si existe el archivo
    if not pdf_path.exists():
        return f"Archivo no encontrado: {pdf_path}"

    # Leer PDF
    try:
        with open(pdf_path, "rb") as file:
            reader = PyPDF2.PdfReader(file)
            # Extraer metadatos
            num_pages = len(reader.pages)

            # Extraer contenido de las páginas
            text = []
            for page in reader.pages:
                text.append(page.extract_text())

            full_text = "\n\n".join(text)

            # Formatear la respuesta para el LLM
            output = f"""
            # Manual de configuración - {version.upper()}
            - Archivo: {filename}
            - Páginas: {num_pages}
            - Ubicación: {pdf_path}

            {full_text}
            """

            return output
    except Exception as e:
        return f"Error al leer el PDF: {str(e)}"


# ========== PROMPTS ===============
@mcp.prompt()
def daily_email_summary() -> str:
    """
    Prompt: Genera un resumen ejecutivo de los emails del día
    """
    return """
    Analiza mis emails de hoy y crea un resumen ejecutivo con:

1. **Emails Urgentes**: Mensajes que requieren respuesta inmediata
2. **Tareas Pendientes**: Acciones que debo realizar
3. **Información Relevante**: Actualizaciones importantes
4. **Puede Esperar**: Emails de baja prioridad

Usa la herramienta list_emails con el filtro apropiado y presenta la información de forma clara y accionable.
    """


@mcp.prompt()
def compose_professional_email(recipient: str = "", subject: str = "") -> str:
    """
    Prompt: Asistente para redactar emails profesionales

    Args:
        recipient: Destinatario del email (opcional)
        subject: Asunto del email (opcional)
    """
    prompt_text = f"""Ayúdame a redactar un email profesional{"" if not recipient else f" para {recipient}"}{"" if not subject else f" con asunto '{subject}'"}.

Por favor:
1. Pregúntame el propósito del email si no está claro
2. Redacta el mensaje con un tono profesional y cordial
3. Estructura: saludo, contexto, mensaje principal, llamada a la acción, despedida
4. Revisa ortografía y gramática
5. Cuando esté listo, usa la herramienta send_email para enviarlo"""

    return prompt_text


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=9000, path="/mcp")

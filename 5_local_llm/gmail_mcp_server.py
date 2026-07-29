"""
Servidor MCP para gestionar Gmail
Requiere: uv pip install fastmcp google-auth-oauthlib google-api-python-client
"""

from fastmcp import FastMCP
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import base64
from email.mime.text import MIMEText
import os.path
import pickle
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent

# Configuración
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

mcp = FastMCP("Gmail Manager")


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
    mcp.run()

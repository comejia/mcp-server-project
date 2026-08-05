import streamlit as st
from client import GmailMCPClient
import asyncio
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
# MCP_SERVER_PATH = ROOT_DIR / "gmail_mcp_server.py"
MCP_SERVER_PATH = "http://localhost:9000/mcp"

st.set_page_config(
    page_title="Gmail Assistant with Auth", page_icon="🔐", layout="wide"
)

# Definición de usuarios y roles disponibles
USERS = {
    "gmail-client": {
        "name": "Admin",
        "role": "Administrador",
        "icon": "👑",
        "description": "Acceso completo: leer y enviar emails",
    },
    "read-only-user": {
        "name": "Reader",
        "role": "Solo Lectura",
        "icon": "📖",
        "description": "Solo puede leer emails y perfil",
    },
    "email-sender": {
        "name": "Sender",
        "role": "Solo Envío",
        "icon": "✉️",
        "description": "Solo puede enviar emails",
    },
}

# Inicializar estado de sesión
if "current_user" not in st.session_state:
    st.session_state.current_user = "gmail-client"

if "messages" not in st.session_state:
    st.session_state.messages = []


# Inicializar cliente
# @st.cache_resource
def get_client():
    """Obtiene el cliente según el usuario seleccionado"""
    return GmailMCPClient(str(MCP_SERVER_PATH), st.session_state.current_user)


client = get_client()

# ==================== HEADER ====================

# Selector de usuario en el header
col1, col2, col3 = st.columns([2, 2, 1])

with col1:
    st.title("🔐 Gmail Assistant with Authorization")
    st.markdown("Sistema con autorización granular por rol")

with col2:
    # Selector de usuario
    user_options = {
        user_id: f"{info['icon']} {info['name']} - {info['role']}"
        for user_id, info in USERS.items()
    }

    selected_user = st.selectbox(
        "👤 Usuario activo:",
        options=list(user_options.keys()),
        format_func=lambda x: user_options[x],
        index=list(user_options.keys()).index(st.session_state.current_user),
        key="user_selector",
    )

    # Si cambió el usuario, reiniciar el chat
    if selected_user != st.session_state.current_user:
        st.session_state.current_user = selected_user
        st.session_state.messages = []
        st.rerun()

with col3:
    if client.is_authenticated():
        st.success("🔓 Autenticado")
    else:
        st.error("🔒 Sin autenticar")

# Mostrar información del usuario actual
current_user_info = USERS[st.session_state.current_user]
st.info(
    f"{current_user_info['icon']} **{current_user_info['name']}**: {current_user_info['description']}"
)

# ==================== SIDEBAR ====================

with st.sidebar:
    st.header("🔐 Panel de Usuario")

    # Información del usuario actual
    st.markdown(f"### {current_user_info['icon']} {current_user_info['name']}")
    st.caption(current_user_info["description"])

    if client.is_authenticated():
        st.success("✅ Token válido")
        st.caption(f"Token: ...{client.token[-20:] if client.token else 'N/A'}")
    else:
        st.error("❌ No se encontró token")
        st.info("Ejecuta el servidor para generar el token")

    st.divider()

    # Información del sistema con permisos
    st.header("📊 Permisos del Usuario")

    with st.spinner("Cargando permisos..."):
        info = asyncio.run(client.get_system_info())

    if "error" in info:
        st.error(f"❌ Error: {info['error']}")
        st.warning("Verifica que el servidor esté ejecutándose")
    else:
        # Tools disponibles
        with st.expander("🔧 Tools Disponibles", expanded=True):
            st.caption(f"Total: {len(info['tools'])}")
            if info["tools"]:
                for tool in info["tools"]:
                    st.markdown(f"• `{tool}`")
            else:
                st.warning("Sin acceso a tools")

        # Resources disponibles
        with st.expander("📦 Resources Disponibles", expanded=True):
            st.caption(f"Total: {len(info['resources'])}")
            if info["resources"]:
                for res in info["resources"]:
                    st.markdown(f"• `{res}`")
            else:
                st.warning("Sin acceso a resources")

        # Templates disponibles
        with st.expander("📋 Templates Disponibles", expanded=False):
            st.caption(f"Total: {len(info.get('templates', []))}")
            if info.get("templates"):
                for template in info["templates"]:
                    st.markdown(f"• `{template}`")
            else:
                st.info("Sin templates disponibles")

        # Prompts disponibles
        with st.expander("💬 Prompts Disponibles", expanded=False):
            st.caption(f"Total: {len(info['prompts'])}")
            if info["prompts"]:
                for prompt in info["prompts"]:
                    st.markdown(f"• `{prompt}`")
            else:
                st.warning("Sin acceso a prompts")

    st.divider()

    # Prompts rápidos
    st.header("🚀 Acciones Rápidas")

    # Verificar si el usuario tiene permisos para cada acción
    has_daily_summary = "daily_email_summary" in info.get("prompts", [])
    has_compose = "compose_professional_email" in info.get("prompts", [])

    if st.button(
        "📊 Resumen diario de emails",
        use_container_width=True,
        disabled=not has_daily_summary,
    ):
        if has_daily_summary:
            st.session_state.use_prompt = "daily_email_summary"
            st.session_state.prompt_params = {}
        else:
            st.error("❌ No tienes permisos para usar este prompt")

    st.divider()

    with st.expander("✉️ Redactar email profesional"):
        if has_compose:
            recipient = st.text_input("Destinatario (opcional)", key="recipient")
            subject = st.text_input("Asunto (opcional)", key="subject")
            if st.button("Usar prompt", key="compose_btn"):
                st.session_state.use_prompt = "compose_professional_email"
                st.session_state.prompt_params = {
                    "recipient": recipient,
                    "subject": subject,
                }
        else:
            st.warning("❌ No tienes permisos para usar este prompt")

    st.divider()

    # Botón para limpiar chat
    if st.button("🗑️ Limpiar Chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

# ==================== CHAT INTERFACE ====================


def display_message(content: str, role: str = "assistant"):
    """Detecta y formatea respuestas que contienen recursos MCP"""
    if not content or content.strip() == "":
        return

    # Detectar errores de permisos
    if "❌" in content and (
        "Error de permisos" in content or "No tienes permisos" in content
    ):
        st.error(content)
        return

    lines = content.split("\n")

    if role == "tool":
        title = "📡 Resultado de herramienta"
        if len(lines) > 0 and lines[0].startswith("# "):
            title = f"📡 {lines[0].replace('# ', '')}"
            content = "\n".join(lines[1:])

        with st.expander(title, expanded=False):
            st.markdown(content)
    elif len(lines) > 5 and lines[0].startswith("# "):
        title = lines[0].replace("# ", "")
        rest_content = "\n".join(lines[1:])

        with st.expander(f"📄 {title}", expanded=False):
            st.markdown(rest_content)
    else:
        st.markdown(content)


# Mostrar historial
for msg in st.session_state.messages:
    msg_role = msg.get("role")
    msg_content = msg.get("content")

    if msg_role == "tool":
        with st.chat_message("assistant"):
            display_message(msg_content, role="tool")
    elif msg_role in ["user", "assistant"]:
        if msg_role == "assistant" and (not msg_content or msg_content.strip() == ""):
            continue

        with st.chat_message(msg_role):
            display_message(msg_content, role=msg_role)

# Manejar prompts
if "use_prompt" in st.session_state:
    prompt_name = st.session_state.pop("use_prompt")
    params = st.session_state.pop("prompt_params", {})

    with st.spinner("Cargando prompt..."):
        prompt_msg = asyncio.run(client.get_prompt_messages(prompt_name, **params))

    # Verificar si hay error de permisos
    if isinstance(prompt_msg, dict) and "❌" in prompt_msg.get("content", {}).get(
        "text", ""
    ):
        st.error(prompt_msg["content"]["text"])
    else:
        st.session_state.messages.append(
            {"role": "user", "content": prompt_msg["content"]["text"]}
        )
        with st.chat_message("user"):
            st.markdown(prompt_msg["content"]["text"])

        with st.chat_message("assistant"):
            with st.spinner("Pensando..."):
                response = asyncio.run(client.chat(st.session_state.messages))
            if response and response.strip():
                display_message(response, role="assistant")

        if response and response.strip():
            st.session_state.messages.append({"role": "assistant", "content": response})

    st.rerun()

# Input de usuario
if prompt := st.chat_input("Escribe tu mensaje..."):
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Pensando..."):
            response = asyncio.run(client.chat(st.session_state.messages))
        if response and response.strip():
            display_message(response, role="assistant")

    if response and response.strip():
        st.session_state.messages.append({"role": "assistant", "content": response})

    st.rerun()

# Footer
st.divider()
st.caption(
    f"Gmail Assistant with Granular Authorization | Usuario: {current_user_info['name']} | 🔐 JWT Auth"
)


# # Titulo
# st.title("📧 Gmail Assistant con MCP")
# st.markdown("Asistente inteligente para gestionar tu Gmail usando Ollama")

# # Sidebar para mostrar informacion del cliente MCP
# with st.sidebar:
#     st.header("🚀 Prompts Rápidos")

#     if st.button("📊 Resumen diario de emails", use_container_width=True):
#         st.session_state.use_prompt = "daily_email_summary"
#         st.session_state.prompt_params = {}

#     st.divider()

#     with st.expander("✉️ Redactar email profesional"):
#         recipient = st.text_input("Destinatario (opcional)", key="recipient")
#         subject = st.text_input("Asunto (opcional)", key="subject")
#         if st.button("Usar prompt", key="compose_btn"):
#             st.session_state.use_prompt = "compose_professional_email"
#             st.session_state.prompt_params = {
#                 "recipient": recipient,
#                 "subject": subject,
#             }

#     st.divider()

#     st.markdown("### ℹ️ Información del sistema")
#     with st.spinner("Cargando info..."):
#         info = asyncio.run(client.get_system_info())

#     # Mostrar información en desplegables organizados
#     with st.expander("🔧 Herramientas disponibles", expanded=False):
#         st.caption(f"Total: {len(info['tools'])}")
#         for tool in info["tools"]:
#             st.markdown(f"• `{tool}`")

#     with st.expander("📦 Recursos estáticos", expanded=False):
#         st.caption(f"Total: {len(info['resources'])}")
#         for res in info["resources"]:
#             st.markdown(f"• `{res}`")

#     with st.expander("📋 Plantillas de recursos", expanded=False):
#         st.caption(f"Total: {len(info.get('templates', []))}")
#         if info.get("templates"):
#             for template in info["templates"]:
#                 st.markdown(f"• `{template}`")
#         else:
#             st.info("No hay plantillas de recursos disponibles")

#     with st.expander("💬 Prompts disponibles", expanded=False):
#         st.caption(f"Total: {len(info['prompts'])}")
#         for prompt in info["prompts"]:
#             st.markdown(f"• `{prompt}`")

# # Chat interface
# if "messages" not in st.session_state:
#     st.session_state.messages = []


# # Función para mostrar respuestas con recursos MCP
# def display_message(content: str, role: str = "assistant"):
#     """Detecta y formatea respuestas que contienen recursos MCP"""
#     # Validar que content no sea None o vacío
#     if not content or content.strip() == "":
#         return  # No mostrar nada si está vacío

#     # Detectar si es una respuesta con recurso MCP (buscar patrones comunes)
#     lines = content.split("\n")

#     # Si es un mensaje de tool, mostrarlo en expander
#     if role == "tool":
#         # Buscar título en las primeras líneas
#         title = "📡 Resultado de herramienta"
#         if len(lines) > 0 and lines[0].startswith("# "):
#             title = f"📡 {lines[0].replace('# ', '')}"
#             content = "\n".join(lines[1:])

#         with st.expander(title, expanded=False):
#             st.markdown(content)
#     # Buscar encabezados de recursos (# Titulo)
#     elif len(lines) > 5 and lines[0].startswith("# "):
#         # Es un recurso MCP, mostrarlo en expander
#         title = lines[0].replace("# ", "")
#         rest_content = "\n".join(lines[1:])

#         with st.expander(f"📄 {title}", expanded=False):
#             st.markdown(rest_content)
#     else:
#         # Respuesta normal
#         st.markdown(content)


# # Mostrar historial
# for msg in st.session_state.messages:
#     msg_role = msg.get("role")
#     msg_content = msg.get("content")

#     # Si es un mensaje tool, mostrarlo bajo el contexto del assistant
#     if msg_role == "tool":
#         with st.chat_message("assistant"):
#             display_message(msg_content, role="tool")
#     # Para mensajes de usuario y assistant
#     elif msg_role in ["user", "assistant"]:
#         # Saltar assistant vacíos (solo con tool_calls)
#         if msg_role == "assistant" and (not msg_content or msg_content.strip() == ""):
#             continue

#         with st.chat_message(msg_role):
#             display_message(msg_content, role=msg_role)

# # Manejar prompts
# if "use_prompt" in st.session_state:
#     prompt_name = st.session_state.pop("use_prompt")
#     params = st.session_state.pop("prompt_params", {})

#     with st.spinner("Cargando prompt..."):
#         prompt_msg = asyncio.run(client.get_prompt_messages(prompt_name, **params))

#     # Mostrar el mensaje del usuario
#     st.session_state.messages.append({"role": "user", "content": prompt_msg})
#     with st.chat_message("user"):
#         st.markdown(prompt_msg)

#     # Obtener respuesta del assistant
#     with st.chat_message("assistant"):
#         with st.spinner("Pensando..."):
#             response = asyncio.run(client.chat(st.session_state.messages))
#         # Solo mostrar si hay contenido
#         if response and response.strip():
#             display_message(response, role="assistant")

#     # Guardar respuesta solo si no está vacía
#     if response and response.strip():
#         st.session_state.messages.append({"role": "assistant", "content": response})

#     st.rerun()

# # Input de usuario
# if prompt := st.chat_input("Escribe tu mensaje..."):
#     st.session_state.messages.append({"role": "user", "content": prompt})

#     with st.chat_message("user"):
#         st.markdown(prompt)

#     with st.chat_message("assistant"):
#         with st.spinner("Pensando..."):
#             response = asyncio.run(client.chat(st.session_state.messages))
#         # Solo mostrar si hay contenido
#         if response and response.strip():
#             display_message(response, role="assistant")

#     # Guardar respuesta solo si no está vacía
#     if response and response.strip():
#         st.session_state.messages.append({"role": "assistant", "content": response})

#     st.rerun()

# # Footer
# st.divider()
# st.caption("Gmail Assistant powered by MCP + Ollama")

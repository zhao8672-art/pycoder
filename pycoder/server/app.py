"""PyCoder App Server - FastAPI + WebSocket service for Electron Desktop."""

from __future__ import annotations

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from pycoder import __version__
from pycoder.server.app_lifecycle import run_server
from pycoder.server.ws_handler import websocket_chat
from pycoder.server.routers.files import router as files_router
from pycoder.server.routers.terminal import router as terminal_router
from pycoder.server.routers.diff import router as diff_router
from pycoder.server.routers.diff_list import router as diff_list_router
from pycoder.server.routers.git import router as git_router
from pycoder.server.routers.search import router as search_router
from pycoder.server.routers.code_exec import router as code_exec_router
from pycoder.server.routers.visualize import router as visualize_router
from pycoder.server.routers.rest_routes import router as rest_router
from pycoder.server.routers.health import router as health_router
from pycoder.server.routers.config import router as config_router
from pycoder.server.routers.chat_routes import router as chat_router

app = FastAPI(title="PyCoder API", description="Python AI Coding Agent", version=__version__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8420", "http://127.0.0.1:8420",
        "http://localhost:8423", "http://127.0.0.1:8423",
        "http://localhost:5173", "http://127.0.0.1:5173",
        "file://",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Register existing sub-routers
app.include_router(files_router)
app.include_router(terminal_router)
app.include_router(diff_router)
app.include_router(diff_list_router)
app.include_router(git_router)
app.include_router(search_router)
app.include_router(code_exec_router, prefix="/api/code")
app.include_router(visualize_router)

# Register extracted routes
app.include_router(health_router)
app.include_router(chat_router)
app.include_router(rest_router)
app.include_router(config_router)


@app.websocket("/ws/chat")
async def websocket_endpoint(ws: WebSocket):
    await websocket_chat(ws)


__all__ = ["app", "run_server"]

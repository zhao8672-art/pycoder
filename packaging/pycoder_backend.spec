# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for PyCoder backend.

Usage:
    pyinstaller packaging/pycoder_backend.spec
"""
import os
from pathlib import Path

block_cipher = None
SPEC = os.path.abspath(SPEC)
PROJECT_ROOT = os.path.dirname(os.path.dirname(SPEC))

# 显式包含的隐式依赖
hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "pycoder",
    "pycoder.server",
    "pycoder.server.app",
    "pycoder.brain",
    "pycoder.ai",
    "pycoder.capabilities",
    "pycoder.lifecycle",
    "pycoder.evolution",
    "pycoder.safety",
    "pycoder.providers",
    "pycoder.memory",
    "pycoder.lsp",
    "pycoder.bus",
    "pycoder.core",
    "pycoder.observability",
    "pycoder.config",
    "pycoder.extensions",
    "pycoder.tools",
    "pycoder._compat",
    "pycoder.python",
    "pycoder.env",
    "pycoder.knowledge",
    "pycoder.cli",
]

templates_dir = os.path.join(PROJECT_ROOT, "pycoder", "templates")
static_dir = os.path.join(PROJECT_ROOT, "pycoder", "static")
datas = []
if os.path.isdir(templates_dir):
    datas.append((templates_dir, "pycoder/templates"))
if os.path.isdir(static_dir):
    datas.append((static_dir, "pycoder/static"))

ENTRY = os.path.join(os.path.dirname(os.path.abspath(SPEC)), "pycoder_backend_entry.py")

a = Analysis(
    [ENTRY],
    pathex=[PROJECT_ROOT, os.path.join(PROJECT_ROOT, "pycoder")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy.tests",
        "pandas.tests",
        "pytest",
        "IPython",
        "jupyter",
        "notebook",
        "semgrep",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

icon_path = os.path.join(PROJECT_ROOT, "pycoder", "electron", "resources", "icon.ico")
if not os.path.exists(icon_path):
    icon_path = None

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="pycoder-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path) if icon_path else None,
)

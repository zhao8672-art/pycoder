# PyCoder 🤖

> A Native AI Coding Agent for Python Developers

[![PyPI version](https://img.shields.io/pypi/v/pycoder)](https://pypi.org/project/pycoder/)
[![License](https://img.shields.io/github/license/PyCoder-ai/pycoder)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12+-blue)](pyproject.toml)

**PyCoder** is an open-source AI coding assistant, built on top of [Aider](https://github.com/Aider-AI/aider), optimized for Chinese Python developers. It offers three usage modes: terminal TUI, Web API, and Electron desktop IDE, with native support for DeepSeek, Qwen, GLM, and other Chinese LLMs.

## Screenshot (TBD)

---

## 🚀 Quick Start

### Installation

`ash
pip install pycoder
`

### From Source

`ash
git clone https://github.com/PyCoder-ai/pycoder.git
cd pycoder
pip install -e .
`

### Configure API Key

Supports **DeepSeek**, **Qwen**, **GLM**, and more:

`ash
# Option 1: Environment variables
export DEEPSEEK_API_KEY=sk-xxxxxxxxxxxx
# or
export QWEN_API_KEY=sk-xxxxxxxxxxxx
# or
export GLM_API_KEY=xxxxxxxxxxxx

# Option 2: Setup wizard
python -m pycoder --setup

# Option 3: In-TUI command
/setup deepseek sk-xxxxxxxx
`

### Launch

`ash
# Terminal TUI (recommended)
python -m pycoder --tui

# Or just run (auto-detects TUI)
python -m pycoder

# App Server (FastAPI + WebSocket)
python -m pycoder --server

# Specify model
python -m pycoder -m deepseek-chat
python -m pycoder -m qwen-coder-plus
python -m pycoder -m glm-4
`

---

## ✨ Key Features

### 🖼️ Terminal TUI

Built with [Textual](https://textual.textualize.io/), Tokyo Night dark theme:

| Module | Description | Shortcut |
|--------|-------------|----------|
| **Chat Panel** | Streaming AI response | Default |
| **File Tree** | Project file navigator | Ctrl+F |
| **Diff Preview** | Visual code diff | Ctrl+D |
| **Model Selector** | Switch AI models on the fly | Ctrl+A |
| **Session Manager** | Multi-tab sessions, auto-save/restore | Ctrl+N |

**Keyboard Shortcuts:**

| Shortcut | Function |
|----------|----------|
| Ctrl+N | New session |
| Ctrl+A | Toggle Agent mode |
| Ctrl+D | Diff panel |
| Ctrl+F | File browser |
| Ctrl+K | Clear screen |
| Ctrl+S | Save session |
| Ctrl+Y | Accept changes |
| Ctrl+R | Reject changes |
| Ctrl+W | Close current session |
| Ctrl+Shift+P | Command palette |
| F1 | Help |
| Esc | Back to input |

### 🤖 Multi-Model Support

| Provider | Models | Input/Output ($/M tokens) |
|----------|--------|---------------------------|
| **DeepSeek** | deepseek-chat, deepseek-coder | .14 / .28 |
| **Qwen** | qwen-coder-plus, qwen-coder-turbo, qwen-max | .15-0.80 / .60-2.00 |
| **GLM** | glm-4, glm-4-flash, glm-4v-flash | .10 / .10 |
| **Ollama** | Local models (customizable) | Free |

Features: automatic API routing, intelligent fallback, response caching.

### 🐍 Python Ecosystem Auto-Detection

Automatically detects and adapts to your Python development environment:

- **Virtual environments:** venv / conda / poetry / uv
- **Package managers:** pip / poetry / pdm / pipenv
- **Frameworks:** Django / Flask / FastAPI / PyTorch / pandas
- **Project types:** web / data_science / library
- **Git info:** branch, changed files

### 🔑 BYOK Mode (Bring Your Own Key)

- Use your own API Key — data never touches third-party servers
- Configuration stored locally in ~/.pycoder/config.json
- Zero server dependency, fully offline-capable

### 📖 Open Source & Auditable

- Apache 2.0 license, derived from [Aider](https://github.com/Aider-AI/aider)
- Fully transparent codebase — inspect, modify, and customize freely
- Community contributions welcome

---

## 📦 Installation

### PyPI (Recommended)

`ash
pip install pycoder
`

### From Source

`ash
git clone https://github.com/PyCoder-ai/pycoder.git
cd pycoder
pip install -e ".[dev]"
`

### VS Code Extension

`ash
# Coming soon to VS Code Marketplace
# Install from source for now
cd vscode-extension
npm install
code --install-extension pycoder-*.vsix
`

---

## ⚙️ Configuration

### Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| DEEPSEEK_API_KEY | DeepSeek API Key | sk-xxx |
| QWEN_API_KEY | Qwen API Key | sk-xxx |
| GLM_API_KEY | GLM API Key | xxx |
| PYCODER_MODEL | Default model | deepseek-chat |
| PYCODER_SERVER_PORT | Server port | 8420 |

### Config File

Located at ~/.pycoder/config.json:

`json
{
  "api_keys": {
    "deepseek": "sk-xxxxxxxxxxxx",
    "qwen": "sk-xxxxxxxxxxxx",
    "glm": "xxxxxxxxxxxx"
  },
  "default_model": "deepseek-chat",
  "theme": "tokyo_night",
  "budget": {
    "max_tokens_per_session": 100000,
    "daily_budget_usd": 5.0
  }
}
`

In-TUI configuration commands:
- /setup — Configuration wizard
- /model <name> — Switch model
- /budget <token_count> — Set budget

---

## 🔧 Commands

### TUI Commands

| Command | Function |
|---------|----------|
| /help | Show help |
| /model <name> | Switch model |
| /models | List available models |
| /cost | Show cost report |
| /budget <n> | Set token budget |
| /env | Show environment info |
| /diff | Toggle diff panel |
| /accept | Accept current changes |
| /reject | Reject current changes |
| /undo | Undo last operation |
| /clear | Clear chat |
| /history | List sessions |
| /session load <id> | Load session |
| /export | Export session (JSON) |

### CLI Arguments

| Argument | Function |
|----------|----------|
| --tui, -t | Launch TUI |
| --server | Launch App Server |
| --server-port PORT | Server port (default: 8420) |
| --model, -m | Specify model |
| --setup | Run setup wizard |
| --env | Show environment info |
| --cost | Show cost report |
| --version, -V | Show version |

---

## 🏗️ Project Structure

`
pycoder/
├── __init__.py          # Version + Windows encoding compat
├── __main__.py          # CLI entry point
├── config/
│   ├── settings.py      # Configuration management
│   └── __init__.py
├── tui/                 # Terminal TUI (Textual)
│   ├── app.py           # Main TUI application
│   ├── app.tcss         # CSS stylesheet
│   ├── bridge.py        # TUI ↔ LLM bridge
│   ├── chat_panel.py    # Chat panel widget
│   ├── diff_panel.py    # Diff preview panel
│   ├── file_tree.py     # File tree widget
│   ├── model_selector.py # Model selector widget
│   ├── agent_loop.py    # Agent loop
│   ├── code_completer.py # Code completion
│   ├── mcp_client.py    # MCP client
│   └── ...
├── server/              # FastAPI + WebSocket
│   ├── app.py           # Server entry point
│   ├── session_store.py # Session persistence (SQLite)
│   ├── deploy.py        # Deployment tools
│   └── routers/         # API routes
├── providers/           # AI model providers
│   ├── deepseek.py      # DeepSeek adapter
│   ├── qwen.py          # Qwen adapter
│   ├── glm.py           # GLM adapter
│   ├── ollama_client.py # Ollama adapter
│   ├── cost_tracker.py  # Cost tracking
│   ├── unified.py       # Unified API
│   └── setup_wizard.py  # Setup wizard
├── python/              # Python ecosystem detection
│   ├── env_detector.py  # Environment detection
│   ├── dep_analyzer.py  # Dependency analysis
│   ├── venv_manager.py  # Virtual env management
│   └── jupyter.py       # Jupyter integration
├── prompts/             # Agent prompts
│   ├── agents_generator.py
│   └── agents_templates.py
├── electron/            # Electron desktop IDE
│   └── src/             # Vue 3 + Monaco Editor
└── tests/               # Test suite
    └── test_app.py
`

---

## 🤝 Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

Commit convention: eat: / ix: / docs: / 	est: / 
efactor: / chore:

---

## 📄 License

Apache 2.0 License © 2026 PyCoder Team — derived from [Aider](https://github.com/Aider-AI/aider).

## 🙏 Acknowledgments

- [Aider](https://aider.chat/) — AI Pair Programming in Your Terminal
- [Textual](https://textual.textualize.io/) — Rapid Application Development Framework
- [FastAPI](https://fastapi.tiangolo.com/) — Modern Web Framework
- DeepSeek / Qwen / GLM — Chinese AI model providers

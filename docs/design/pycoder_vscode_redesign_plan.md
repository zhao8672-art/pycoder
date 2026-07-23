# PyCoder IDE - VS Code 风格 UI 重设计方案

> 项目：pycode（PyCoder AI 编程智能体）
> 设计文件：https://ardot.tencent.com/file/707037527072410
> 生成时间：2026-07-23

---

## 一、项目分析总结

### 1.1 项目定位

PyCoder 是一个面向 Python 全栈开发的 **AI 编程智能体（AI Programming Agent）**，目标是通过自然语言交互辅助开发者完成代码编写、调试、测试、重构和项目管理。产品形态为 **FastAPI 后端 + Electron 桌面 IDE 前端**，同时支持本地模型（Ollama）与云端模型（DeepSeek / Qwen / GLM 等）的灵活切换。

核心产品价值：

- **对话式编程**：用户用自然语言描述需求，AI 直接生成、修改、解释代码。
- **全链路闭环**：从需求理解 → 代码编辑 → 终端运行 → 测试验证 → Git 提交，一站式完成。
- **可扩展能力**：通过技能市场、插件系统和自进化引擎持续增强 AI 能力。

### 1.2 技术架构

| 层级 | 技术栈 | 关键文件/规模 |
|------|--------|--------------|
| 后端服务 | FastAPI + WebSocket + Python 3.14 | `pycoder/` 模块约 528 个 Python 文件 |
| 桌面 IDE | Electron + React + TypeScript | `pycoder/electron/src/renderer/` 约 54 个组件 |
| 代码编辑器 | Monaco Editor | 与 VS Code 同源，具备语法高亮、IntelliSense、Diff 能力 |
| 状态管理 | Zustand | `useUIStore`、`useChatStore`、`useEditorStore`、`useGitStore` |
| AI 引擎 | 多模型适配 + 182 项 V2 能力注册表 | 支持 tool call、代码生成、自动修复 |
| 执行环境 | 沙箱执行 + 终端面板 | 安全运行测试与脚本 |

### 1.3 现有界面问题

通过对现有 `theme.css` 和主要组件的分析，当前界面存在以下主要问题：

1. **视觉风格不统一**：当前使用紫色主色调（`#9333EA` / `#7C3AED`），与开发者工具常见的蓝色/深色主题认知不符，专业感不足。
2. **图标体系不专业**：ActivityBar、Sidebar 等位置大量使用 emoji（📁、🔍、🤖 等），缺乏矢量图标的一致性和可缩放性。
3. **信息层级弱**：AI 面板、终端、状态栏等关键区域与编辑器区域的视觉边界不清晰，容易分散注意力。
4. **缺少 VS Code 级交互**：命令面板、快捷键提示、可拖拽面板分割、上下文菜单等高级 IDE 交互尚未完全落地。
5. **暗色/亮色主题质感差距大**：亮色主题停留在简单的反色，缺少 VS Code Light+ 的精致灰阶和阴影层次。

### 1.4 用户场景

主要用户为 Python 开发者、全栈工程师、AI 应用开发者。典型使用场景：

- 打开项目 → 浏览文件树 → 在编辑器中查看/修改代码。
- 选中代码 → 向 AI 提问或要求重构 → 查看 AI 回复与代码 Diff。
- 运行测试 → 在终端查看输出 → 一键修复失败用例。
- 查看 Git 状态 → 提交变更 → 推送到远程分支。

---

## 二、完整重新设计方案

### 2.1 设计目标

以 **Visual Studio Code** 为标杆，打造专业、克制、高效的开发者 IDE 界面：

- **熟悉感**：让 VS Code 用户零学习成本上手。
- **专注感**：降低界面装饰，突出代码与 AI 对话内容。
- **可控感**：通过面板、Tab、命令面板、快捷键提供高效的多任务操作。
- **一致性**：暗色（Dark+）与亮色（Light+）双主题在结构、间距、交互上完全对齐。

### 2.2 界面布局

采用 VS Code 经典的 **五区结构**：

```
┌─────────────────────────────────────────────────────────────┐
│ Menu Bar                                                    │  32px
├─────┬────────────────────────────────────────────┬──────────┤
│     │ Tab Bar                                    │          │
│ Act │ ┌────────────────────────────────────────┐ │  AI      │
│ ivi │ │ Breadcrumb                             │ │  Panel   │
│ ty  │ ├────────────────────────────────────────┤ │  360px   │
│ Bar │ │                                        │ │          │
│ 48px│ │          Code Editor                   │ │          │
│     │ │                                        │ │          │
│     │ ├────────────────────────────────────────┤ │          │
│     │ │ Bottom Panel (Terminal / Output / ...) │ │          │
│     │ └────────────────────────────────────────┘ │          │
├─────┴────────────────────────────────────────────┴──────────┤
│ Status Bar                                                  │  22px
└─────────────────────────────────────────────────────────────┘
```

#### 2.2.1 菜单栏（Menu Bar）

- 高度 32px，背景 `#3C3C3C`（Dark）/ `#DDDDDD`（Light）。
- 左侧：文件、编辑、视图、Git、运行、帮助等标准菜单。
- 右侧：窗口控制（最小化、最大化、关闭）与当前项目名。
- 所有菜单支持快捷键提示（如 `Ctrl+Shift+P` 打开命令面板）。

#### 2.2.2 活动栏（Activity Bar）

- 宽度 48px，位于最左侧。
- 使用单色矢量图标替代 emoji，分组如下：
  - **核心**：资源管理器、搜索、Git、AI 助手
  - **AI 工具**：团队、进化、技能、扩展、代码片段
  - **工具**：浏览器、终端、命令面板
  - **系统**：云端、设置
- 当前选中的视图高亮显示（左侧 2px 蓝色指示条）。

#### 2.2.3 侧边栏（Sidebar）

- 默认宽度 260px，可拖拽调整，最小 200px，最大 500px。
- 当前设计展示了 **EXPLORER** 视图：
  - 项目名大写标题 `PYCODER`。
  - 文件夹树展开/折叠，当前打开文件 `main.py` 高亮。
  - 文件/文件夹使用 VS Code 风格的小图标。
- 其他视图：Search、Git、Extensions、Settings 等按相同模式组织。

#### 2.2.4 编辑区（Editor Area）

- 中央核心区域，包含：
  - **Tab Bar**：已打开文件标签，支持关闭、拖拽、未保存指示点。
  - **Breadcrumb**：当前文件路径导航（如 `pycoder › server`）。
  - **Monaco Editor**：代码编辑主体，支持语法高亮、行号、 minimap（可选）。
- 当前设计展示 `main.py`，包含 FastAPI 代码与 Python 语法高亮。

#### 2.2.5 AI 面板（AI Panel）

- 默认宽度 360px，位于右侧，可折叠。
- 包含：
  - 面板标题 `PyCoder AI` 与模型选择器（`deepseek-chat`）。
  - 聊天消息流：用户消息（右侧蓝色气泡）与 AI 消息（左侧白色/深色卡片）。
  - 工具调用卡片：显示 AI 正在执行的操作（如 `edit_file`）与目标路径。
  - 输入框：底部固定，placeholder 提示可执行操作，发送按钮蓝色高亮。

#### 2.2.6 底层面板（Bottom Panel）

- 默认高度 180px，可拖拽调整，可折叠。
- Tab 切换：TERMINAL、OUTPUT、PROBLEMS、PYTHON、TEST、FIX、DEBUG、PREVIEW 等。
- 当前设计展示 TERMINAL OUTPUT，包含 pytest 运行结果。

#### 2.2.7 状态栏（Status Bar）

- 高度 22px，Dark 主题下使用 VS Code 标志性的蓝色 `#007ACC` 背景。
- 左侧：连接状态、Git 分支、模型名称、Token 与成本。
- 右侧：语言模式、行号列号、UTF-8、底部面板 Tab 快速切换。

### 2.3 视觉风格

#### 2.3.1 颜色系统

**Dark+ 主题**

| Token | 色值 | 用途 |
|-------|------|------|
| `canvas` | `#1E1E1E` | 编辑器主背景 |
| `sidebar.background` | `#252526` | 侧边栏/面板背景 |
| `activityBar.background` | `#333333` | 活动栏背景 |
| `titleBar.activeBackground` | `#3C3C3C` | 菜单栏背景 |
| `statusBar.background` | `#007ACC` | 状态栏背景 |
| `tab.activeBackground` | `#1E1E1E` | 当前 Tab 背景 |
| `tab.inactiveBackground` | `#2D2D2D` | 非活动 Tab 背景 |
| `border` | `#3C3C3C` | 分隔线、边框 |
| `foreground` | `#D4D4D4` | 主文字 |
| `descriptionForeground` | `#858585` | 次要文字 |
| `accent` | `#007ACC` | 强调色、选中指示 |

**Light+ 主题**

| Token | 色值 | 用途 |
|-------|------|------|
| `canvas` | `#FFFFFF` | 编辑器主背景 |
| `sidebar.background` | `#F3F3F3` | 侧边栏/面板背景 |
| `activityBar.background` | `#2C2C2C` | 活动栏背景（深色保持对比） |
| `titleBar.activeBackground` | `#DDDDDD` | 菜单栏背景 |
| `statusBar.background` | `#007ACC` | 状态栏背景 |
| `tab.activeBackground` | `#FFFFFF` | 当前 Tab 背景 |
| `tab.inactiveBackground` | `#ECECEC` | 非活动 Tab 背景 |
| `border` | `#E5E5E5` | 分隔线、边框 |
| `foreground` | `#3C3C3C` | 主文字 |
| `descriptionForeground` | `#6E6E6E` | 次要文字 |

#### 2.3.2 语法高亮

- 使用 VS Code Dark+/Light+ 默认语法色：
  - Dark：关键字 `#569CD6`、字符串 `#CE9178`、注释 `#6A9955`、函数 `#DCDCAA`、类/类型 `#4EC9B0`。
  - Light：关键字 `#0000FF`、字符串 `#A31515`、注释 `#008000`、函数 `#795E26`、类/类型 `#267F99`。
- 字体：代码使用 `JetBrains Mono` 或 `Fira Code`，UI 使用 `Inter`。

#### 2.3.3 图标与间距

- 全部使用 16×16 单色 SVG 图标，Hover 时颜色从 `#858585` 变为 `#D4D4D4`。
- 8px 网格系统：面板间距、padding、gap 均为 8 的倍数。
- 圆角克制：按钮/输入框 4px，卡片/弹窗 6-8px，图标容器 12px。

### 2.4 交互设计

#### 2.4.1 命令面板（Command Palette）

- 快捷键：`Ctrl+Shift+P` / `F1`。
- 居中浮层，宽度 560px，圆角 8px，半透明遮罩。
- 支持：打开文件、切换面板、运行命令、切换主题、调用 AI 技能。
- 设计稿中展示了命令面板的 Dark 主题状态。

#### 2.4.2 快捷键体系

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+K` | 打开命令面板 |
| `Ctrl+B` | 切换侧边栏 |
| `Ctrl+Shift+A` | 切换 AI 面板 |
| `Ctrl+J` / `` Ctrl+` `` | 切换底部面板 |
| `Ctrl+P` | 快速打开文件 |
| `Ctrl+Shift+F` | 全局搜索 |
| `Ctrl+Shift+G` | 打开 Source Control |

#### 2.4.3 可拖拽面板

- 侧边栏、AI 面板、底部面板均支持拖拽调整尺寸。
- 拖拽到临界宽度以下时自动折叠为图标模式。
- 拖拽手柄为 1px 分隔线，Hover 时显示 2px 蓝色高亮。

#### 2.4.4 Tab 交互

- 点击切换、中键关闭、拖拽排序。
- 未保存文件显示白色圆点指示器。
- 当前 Tab 底部/顶部有蓝色强调线。

#### 2.4.5 上下文菜单

- 右键文件树：新建文件、新建文件夹、复制路径、在终端中打开。
- 右键编辑器：转到定义、重命名符号、AI 解释代码、AI 重构代码。
- 右键 AI 消息：复制、重新生成、插入到编辑器。

### 2.5 功能适配

将 PyCoder 现有功能映射到 VS Code 风格的 UI 组件中：

| PyCoder 功能 | 对应 VS Code 组件 | 设计说明 |
|--------------|------------------|----------|
| 文件浏览 | Sidebar - Explorer | 树形文件列表，支持展开折叠、搜索过滤 |
| AI 对话 | AI Panel | 类聊天界面，支持代码块、工具调用卡片 |
| 代码编辑 | Monaco Editor | 语法高亮、IntelliSense、Diff 预览 |
| 终端执行 | Bottom Panel - Terminal | 集成终端，显示命令输入与输出 |
| 测试结果 | Bottom Panel - Test | pytest 结果展示，失败用例可跳转 |
| Git 管理 | Sidebar - Source Control | 变更列表、分支、提交信息 |
| 全局搜索 | Sidebar - Search | 跨文件搜索与替换 |
| 技能/扩展 | Sidebar - Extensions | 技能市场、已安装技能列表 |
| 设置 | Sidebar / 命令面板 | 主题切换、模型配置、快捷键 |
| 后端连接 | Status Bar | 实时显示连接状态与模型 |
| Token/成本 | Status Bar | 显示当前会话消耗 |

### 2.6 响应式适配

#### 2.6.1 宽度适配

| 视口宽度 | 行为 |
|----------|------|
| ≥1440px | 默认三栏布局：Sidebar + Editor + AI Panel |
| 1280-1440px | AI Panel 自动收窄至 300px，Sidebar 收窄至 220px |
| 1024-1280px | 默认折叠 AI Panel，需要时点击活动栏展开 |
| <1024px | 进入紧凑模式，Sidebar 和 AI Panel 均折叠，仅保留 Activity Bar |

#### 2.6.2 高度适配

- 底部面板默认 180px，最小 80px，最大占屏幕高度的 60%。
- 编辑器区域始终占据剩余空间。

#### 2.6.3 主题切换

- 提供 Dark+ / Light+ / 跟随系统三种模式。
- 通过命令面板或状态栏图标一键切换。
- 所有颜色通过 CSS 变量注入，切换无闪烁。

#### 2.6.4 触控与高分屏

- 所有交互元素最小触控区域 28×28px。
- 支持 `window.devicePixelRatio` 自适应，图标与文字在 4K 屏保持清晰。

---

## 三、实现建议

### 3.1 前端改造清单

1. **替换主题系统**：将 `theme.css` 中的紫色变量替换为 VS Code Dark+/Light+ 变量。
2. **图标替换**：将 ActivityBar、Sidebar、StatusBar 的 emoji 替换为 SVG 图标（可复用 VS Code Codicons）。
3. **组件结构调整**：确保 Sidebar、AI Panel、Bottom Panel 使用 flex 布局并支持拖拽宽度/高度。
4. **命令面板实现**：新增 `CommandPalette` 组件，支持模糊搜索与快捷键绑定。
5. **Monaco 主题同步**：根据当前 Dark/Light 模式动态切换 Monaco Editor 主题。
6. **Zustand 状态扩展**：在 `useUIStore` 中新增 `panelVisible`、`theme`、面板尺寸等状态。

### 3.2 后端配合

- 保持 FastAPI + WebSocket 架构不变。
- 在状态栏实时推送后端连接状态、模型信息、Token 消耗。

### 3.3 推荐依赖

- `@vscode/codicons`：官方图标库。
- `react-resizable-panels`：可拖拽面板分割。
- `allotment` 或 `react-split-pane`：替代方案。

---

## 四、设计稿说明

本方案已输出以下设计稿文件：

| 文件 | 说明 |
|------|------|
| `2_2.png` | Dark+ 主题完整界面（含命令面板） |
| `2_128.png` | Light+ 主题完整界面（含文件树、AI 对话、终端） |
| `pycoder_vscode_redesign_poster.png` | 双主题对比海报 |
| `generate_poster.py` | 海报生成脚本 |
| 在线设计稿 | https://ardot.tencent.com/file/707037527072410 |

---

*本方案由 WorkBuddy 基于 PyCoder 项目特点与 VS Code 设计规范生成，后续可根据开发排期分阶段落地。*

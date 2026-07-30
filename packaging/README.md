# PyCoder 安装包

本目录包含 PyCoder Windows 安装包的构建脚本和安装器。

## 📦 打包

```cmd
build_installer.bat
```

自动生成：

| 输出 | 路径 | 大小 |
|------|------|------|
| 便携版 ZIP | `dist\PyCoder-1.0.0-win32-x64-portable.zip` | ~123 MB |
| Wheel ZIP | `dist\pycoder-1.0.0-py3-none-any.zip` | ~2 MB |
| 安装目录 | `dist\PyCoder-win32-x64\` | ~328 MB |
| Wheel 文件 | `dist\wheels\pycoder-1.0.0-py3-none-any.whl` | ~2.1 MB |

## 🚀 安装方式

### 1. 双击 `install.bat`（最简单）

- 默认安装到 `%LOCALAPPDATA%\PyCoder`
- 自动创建桌面 + 开始菜单快捷方式

### 2. 命令行选项

```cmd
install.bat /dir "D:\Tools\PyCoder"     # 自定义目录
install.bat /addpath                      # 添加到 PATH
install.bat /installpython                # 同步安装 Python wheel
install.bat /portable                     # 便携模式（安装到当前目录）
```

### 3. PowerShell 高级安装

```powershell
# 完整安装：自定义目录 + 快捷方式 + PATH + 卸载注册
.\install.ps1 -InstallDir "C:\Program Files\PyCoder" -CreateShortcuts -AddToPath

# 便携模式
.\install.ps1 -Portable
```

## 🗑️ 卸载

- **控制面板** → 应用 → PyCoder → 卸载
- 或手动：`.\uninstall.ps1`

## 📁 文件说明

| 文件 | 用途 |
|------|------|
| `build_installer.bat` | 一键构建脚本 |
| `install.bat` | Windows 用户友好安装器 |
| `install.ps1` | PowerShell 高级安装器 |
| `uninstall.ps1` | 卸载脚本 |
| `PyCoder.bat` | 便携模式启动器 |
| `README.md` | 详细安装说明（被复制到安装目录） |

## 🔧 自定义

- **图标**：替换 `pycoder\electron\resources\icon.ico`
- **应用名**：修改 `pycoder\electron\package.json` 和 `pyproject.toml`
- **版本号**：修改 `pycoder\__init__.py`、`pycoder\electron\package.json`、`pyproject.toml`
- **NSIS 集成**：安装 NSIS 后，添加 `maker-squirrel` 配置到 `forge.config.js`

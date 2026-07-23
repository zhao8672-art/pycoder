# PyCoder Plugins Module

PyCoder 的插件系统在 `pycoder/plugins/` 子包中, **不**在仓库根.

## 真实位置

| 文件 | 用途 | 大小 |
|------|------|------|
| `pycoder/plugins/base.py` | 插件基类 (BasePlugin / PluginHook) | 2 KB |
| `pycoder/plugins/hermes_plugin.py` | 内置示例插件 (Hermes 集成) | 3 KB |
| `pycoder/runtime/plugin_registry.py` | 全局插件注册中心 | ~3 KB |

## 加载机制

1. **扫描**: 启动时扫描 `pycoder/plugins/` 和 `~/.pycoder/plugins/`
2. **注册**: 插件通过 `@register` 装饰器或 `register_plugin()` 显式注册
3. **钩子**: `PluginHook.BEFORE_REQUEST` / `AFTER_RESPONSE` 等事件触发
4. **热加载**: 支持运行时 `enable_plugin()` / `disable_plugin()`

## 自定义插件

```python
from pycoder.plugins.base import BasePlugin, PluginHook, register

@register(name="my_plugin", version="1.0.0")
class MyPlugin(BasePlugin):
    def setup(self):
        # 启动时初始化
        pass

    def teardown(self):
        # 关闭时清理
        pass

    @PluginHook.BEFORE_REQUEST
    async def on_request(self, request):
        # 拦截请求
        pass
```

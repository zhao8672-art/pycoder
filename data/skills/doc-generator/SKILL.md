# 文档生成器

## 技能描述
为 Python 代码自动生成 Google 风格的 docstring 和文档。

## 功能
- 为函数/类/模块生成 docstring
- 支持 Google 和 NumPy 风格
- 生成类型注解的文档
- 生成 README 文件
- 提取 API 文档

## 使用方式
```
请为 [文件路径/函数名] 生成文档
```

## 文档格式
```python
def example(param1: str, param2: int = 0) -> bool:
    """简短描述。

    Args:
        param1: 参数1的描述
        param2: 参数2的描述，默认值为0

    Returns:
        返回值的描述

    Raises:
        ValueError: 当参数无效时抛出
    """
```

## 生成规则
- 分析函数签名和类型注解
- 从代码逻辑推断参数含义
- 识别异常抛出点
- 提供使用示例

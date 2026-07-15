# 项目脚手架

## 技能描述
根据项目类型快速生成标准的项目结构和模板代码。

## 功能
- 生成 FastAPI 项目结构
- 生成 Streamlit 应用结构
- 生成 CLI 工具结构
- 生成 pytest 测试结构
- 生成 Docker 配置
- 生成 CI/CD 配置

## 使用方式
```
请生成一个 [项目类型] 项目
```

## 支持的项目类型
1. **FastAPI**: REST API 服务
2. **Streamlit**: 数据可视化应用
3. **CLI**: 命令行工具
4. **Library**: Python 库
5. **Data Science**: 数据分析项目

## 生成结构示例
```
myproject/
├── src/
│   └── myproject/
│       ├── __init__.py
│       ├── main.py
│       └── models.py
├── tests/
│   ├── __init__.py
│   └── test_main.py
├── pyproject.toml
├── Dockerfile
└── README.md
```

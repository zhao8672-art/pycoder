# Item API

Item 管理系统 - FastAPI + SQLAlchemy + SQLite

## 快速开始

```bash
pip install -r requirements.txt
uvicorn src.main:app --reload
```

## API 文档

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 测试

```bash
pytest tests/ -v
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /items | 获取列表 (分页+搜索) |
| GET | /items/{id} | 获取详情 |
| POST | /items | 创建 |
| PUT | /items/{id} | 更新 |
| DELETE | /items/{id} | 删除 |

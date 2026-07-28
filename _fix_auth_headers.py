"""为 test_task_api.py 添加 auth headers — 精简版"""
import re

path = r'C:\Users\Administrator\Desktop\pycode\tests\test_task_api.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add importlib
content = content.replace(
    'import time\nfrom unittest.mock',
    'import importlib\nimport time\nfrom unittest.mock'
)

# 2. Add auth constants
content = content.replace(
    'from pycoder.server.services.task_persistence import (\n    TaskPersistence,\n    TaskState,\n)',
    'from pycoder.server.services.task_persistence import (\n    TaskPersistence,\n    TaskState,\n)\n\n_TEST_API_KEY = "test-task-api-key-12345"\n_AUTH_HEADERS = {"X-API-Key": _TEST_API_KEY}'
)

# 3. Update fixture
old_fixture = '''@pytest.fixture
def client_with_services(
    mock_grader: MagicMock, mock_persistence: MagicMock
) -> TestClient:
    """注入模拟 TaskGrader 和 TaskPersistence 的 TestClient"""
    from pycoder.server.routers import task_api

    # 保存原始单例
    orig_grader = task_api._grader
    orig_persistence = task_api._persistence

    task_api._grader = mock_grader
    task_api._persistence = mock_persistence

    from pycoder.server.app import app

    with TestClient(app) as c:
        yield c

    task_api._grader = orig_grader
    task_api._persistence = orig_persistence'''

new_fixture = '''@pytest.fixture
def client_with_services(
    mock_grader: MagicMock, mock_persistence: MagicMock, monkeypatch
) -> TestClient:
    """注入模拟 TaskGrader 和 TaskPersistence 的 TestClient（自动设置 Auth）"""
    monkeypatch.setenv("PYCODER_API_KEY", _TEST_API_KEY)
    import pycoder.server.app as app_module
    importlib.reload(app_module)
    from pycoder.server.routers import task_api

    # 保存原始单例
    orig_grader = task_api._grader
    orig_persistence = task_api._persistence

    task_api._grader = mock_grader
    task_api._persistence = mock_persistence

    with TestClient(app_module.app) as c:
        yield c

    task_api._grader = orig_grader
    task_api._persistence = orig_persistence
    monkeypatch.delenv("PYCODER_API_KEY", raising=False)
    importlib.reload(app_module)'''

content = content.replace(old_fixture, new_fixture)

# 4. Add headers to all requests
lines = content.split('\n')
result = []
i = 0
while i < len(lines):
    line = lines[i]
    stripped = line.strip()
    
    # Check if this is a request call
    is_get = 'client_with_services.get(' in stripped
    is_post = 'client_with_services.post(' in stripped
    
    if (is_get or is_post) and 'headers=' not in line:
        if stripped.endswith(')') and not stripped.rstrip().endswith('('):
            # Single-line call: add headers before closing )
            idx = line.rfind(')')
            line = line[:idx] + ', headers=_AUTH_HEADERS)'
            result.append(line)
        elif stripped.endswith('('):
            # Multi-line call start
            result.append(line)
            i += 1
            # Collect all lines until the closing )
            block_lines = []
            url_seen = False
            headers_inserted = False
            while i < len(lines):
                blk = lines[i]
                blk_stripped = blk.strip()
                block_lines.append(blk)
                if blk_stripped.startswith('"') and not url_seen and 'headers=' not in blk_stripped:
                    url_seen = True
                    # Insert headers after URL line if next line doesn't have headers
                    if i + 1 < len(lines):
                        next_blk = lines[i + 1].strip()
                        if 'headers=' not in next_blk and not next_blk.startswith(')'):
                            indent = ' ' * (len(blk) - len(blk.lstrip()))
                            block_lines.append(f'{indent}headers=_AUTH_HEADERS,')
                            headers_inserted = True
                if blk_stripped == ')':
                    break
                i += 1
            result.extend(block_lines)
        else:
            result.append(line)
    else:
        result.append(line)
    i += 1

with open(path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(result))

print('Done')
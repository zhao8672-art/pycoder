"""
输入输出转换器模块测试

覆盖:
  - InputTransformer: normalize_path 路径规范化
  - InputTransformer: extract_paths 路径提取
  - InputTransformer: sanitize_shell_command 命令安全检查
  - InputTransformer: coerce_to_type 类型强制转换
  - InputTransformer: expand_template 模板展开
  - OutputTransformer: format_file_content 文件内容格式化
  - OutputTransformer: format_error 异常格式化
  - OutputTransformer: format_command_output 命令输出格式化
  - OutputTransformer: format_diff 差异格式化
  - OutputTransformer: format_list_result 列表格式化
  - OutputTransformer: to_json_safe JSON 安全转换
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from pycoder.bus.transformer import InputTransformer, OutputTransformer


# ══════════════════════════════════════════════════════════
# InputTransformer 路径规范化测试
# ══════════════════════════════════════════════════════════


class TestInputTransformerNormalizePath:
    """路径规范化"""

    def test_relative_path_become_absolute(self):
        """相对路径转为绝对路径"""
        result = InputTransformer.normalize_path("main.py", workspace_root="/home/user/project")
        assert result == str(Path("/home/user/project/main.py"))

    def test_absolute_path_unchanged(self):
        """绝对路径保持不变"""
        result = InputTransformer.normalize_path("/etc/hosts", workspace_root="/home/user")
        assert result == str(Path("/etc/hosts"))

    def test_default_workspace_root(self):
        """默认工作区根目录为当前目录"""
        result = InputTransformer.normalize_path("test.py")
        expected = str(Path(".") / "test.py")
        assert result == expected

    def test_nested_relative_path(self):
        """嵌套相对路径"""
        result = InputTransformer.normalize_path("src/module/main.py", workspace_root="/app")
        assert result == str(Path("/app/src/module/main.py"))

    def test_windows_path(self):
        """Windows 绝对路径"""
        result = InputTransformer.normalize_path("C:\\Users\\test\\file.txt", workspace_root="/tmp")
        assert result == "C:\\Users\\test\\file.txt"


# ══════════════════════════════════════════════════════════
# InputTransformer 路径提取测试
# ══════════════════════════════════════════════════════════


class TestInputTransformerExtractPaths:
    """路径提取"""

    def test_extract_path_key(self):
        """提取 path 键的值"""
        params = {"path": "main.py", "other": 123}
        paths = InputTransformer.extract_paths(params)
        assert "main.py" in paths

    def test_extract_file_key(self):
        """提取 file 键的值"""
        params = {"file": "config.json"}
        paths = InputTransformer.extract_paths(params)
        assert "config.json" in paths

    def test_extract_file_path_key(self):
        """提取 file_path 键的值"""
        params = {"file_path": "src/app.py"}
        paths = InputTransformer.extract_paths(params)
        assert "src/app.py" in paths

    def test_extract_source_target_keys(self):
        """提取 source 和 target 键的值"""
        params = {"source": "old.py", "target": "new.py"}
        paths = InputTransformer.extract_paths(params)
        assert "old.py" in paths
        assert "new.py" in paths

    def test_extract_paths_list_key(self):
        """提取 paths 列表键的值"""
        params = {"paths": ["a.py", "b.py", "c.py"]}
        paths = InputTransformer.extract_paths(params)
        assert len(paths) == 3
        assert "a.py" in paths

    def test_extract_files_list_key(self):
        """提取 files 列表键的值"""
        params = {"files": ["x.py", "y.py"]}
        paths = InputTransformer.extract_paths(params)
        assert len(paths) == 2

    def test_no_path_keys(self):
        """没有路径相关键时返回空列表"""
        params = {"foo": "bar", "count": 42}
        paths = InputTransformer.extract_paths(params)
        assert paths == []

    def test_skip_non_string_paths_in_list(self):
        """跳过列表中的非字符串元素"""
        params = {"paths": ["a.py", 123, None, "b.py"]}
        paths = InputTransformer.extract_paths(params)
        assert paths == ["a.py", "b.py"]


# ══════════════════════════════════════════════════════════
# InputTransformer 命令安全检查测试
# ══════════════════════════════════════════════════════════


class TestInputTransformerSanitizeShellCommand:
    """Shell 命令安全检查"""

    def test_safe_command(self):
        """安全命令通过检查"""
        is_safe, cmd = InputTransformer.sanitize_shell_command("ls -la")
        assert is_safe is True
        assert cmd == "ls -la"

    def test_rm_rf_root_dangerous(self):
        """rm -rf / 被识别为危险"""
        is_safe, msg = InputTransformer.sanitize_shell_command("rm -rf /")
        assert is_safe is False
        assert "危险模式" in msg

    def test_rm_rf_home_dangerous(self):
        """rm -rf ~ 被识别为危险"""
        is_safe, msg = InputTransformer.sanitize_shell_command("rm -rf ~")
        assert is_safe is False

    def test_rm_rf_dot_dangerous(self):
        """rm -rf . 被识别为危险"""
        is_safe, msg = InputTransformer.sanitize_shell_command("rm -rf .")
        assert is_safe is False

    def test_fork_bomb_dangerous(self):
        """fork bomb 被识别为危险"""
        is_safe, msg = InputTransformer.sanitize_shell_command(":(){ :|:& };:")
        assert is_safe is False

    def test_dev_sda_dangerous(self):
        """> /dev/sda 被识别为危险"""
        is_safe, msg = InputTransformer.sanitize_shell_command("echo test > /dev/sda")
        assert is_safe is False

    def test_dd_if_dangerous(self):
        """dd if= 被识别为危险"""
        is_safe, msg = InputTransformer.sanitize_shell_command("dd if=/dev/zero of=/dev/sda")
        assert is_safe is False

    def test_chmod_777_root_dangerous(self):
        """chmod 777 / 被识别为危险"""
        is_safe, msg = InputTransformer.sanitize_shell_command("chmod 777 /")
        assert is_safe is False

    def test_mkfs_dangerous(self):
        """mkfs. 被识别为危险"""
        is_safe, msg = InputTransformer.sanitize_shell_command("mkfs.ext4 /dev/sda1")
        assert is_safe is False

    def test_format_c_dangerous(self):
        """format c: 被识别为危险"""
        is_safe, msg = InputTransformer.sanitize_shell_command("format c:")
        assert is_safe is False

    def test_chown_r_dangerous(self):
        """chown -R 被识别为危险"""
        is_safe, msg = InputTransformer.sanitize_shell_command("chown -R root:root /")
        assert is_safe is False

    def test_case_insensitive_check(self):
        """大小写不敏感检查"""
        is_safe, msg = InputTransformer.sanitize_shell_command("RM -RF /")
        assert is_safe is False


# ══════════════════════════════════════════════════════════
# InputTransformer 类型强制转换测试
# ══════════════════════════════════════════════════════════


class TestInputTransformerCoerceToType:
    """类型强制转换"""

    def test_coerce_to_bool_true_strings(self):
        """True 字符串转换为布尔值"""
        for val in ("true", "True", "1", "yes", "on"):
            assert InputTransformer.coerce_to_type(val, bool) is True

    def test_coerce_to_bool_false_strings(self):
        """False 字符串转换为布尔值"""
        for val in ("false", "False", "0", "no", "off", ""):
            assert InputTransformer.coerce_to_type(val, bool) is False

    def test_coerce_to_bool_non_string(self):
        """非字符串转布尔"""
        assert InputTransformer.coerce_to_type(1, bool) is True
        assert InputTransformer.coerce_to_type(0, bool) is False
        assert InputTransformer.coerce_to_type([], bool) is False
        assert InputTransformer.coerce_to_type([1], bool) is True

    def test_coerce_to_int(self):
        """转换为 int"""
        assert InputTransformer.coerce_to_type("42", int) == 42
        assert InputTransformer.coerce_to_type(3.14, int) == 3

    def test_coerce_to_int_invalid(self):
        """无效的 int 转换返回原值"""
        result = InputTransformer.coerce_to_type("not_a_number", int)
        assert result == "not_a_number"

    def test_coerce_to_float(self):
        """转换为 float"""
        assert InputTransformer.coerce_to_type("3.14", float) == 3.14
        assert InputTransformer.coerce_to_type(42, float) == 42.0

    def test_coerce_to_str(self):
        """转换为 str"""
        assert InputTransformer.coerce_to_type(42, str) == "42"
        assert InputTransformer.coerce_to_type(True, str) == "True"

    def test_coerce_to_list(self):
        """转换为 list"""
        assert InputTransformer.coerce_to_type([1, 2], list) == [1, 2]
        result = InputTransformer.coerce_to_type("single", list)
        assert result == ["single"]

    def test_coerce_unknown_type_returns_value(self):
        """未知类型返回原值"""
        result = InputTransformer.coerce_to_type("hello", set)
        assert result == "hello"


# ══════════════════════════════════════════════════════════
# InputTransformer 模板展开测试
# ══════════════════════════════════════════════════════════


class TestInputTransformerExpandTemplate:
    """模板展开"""

    def test_expand_braced_variables(self):
        """展开 ${key} 格式的变量"""
        template = "Hello, ${name}! Your score is ${score}."
        variables = {"name": "Alice", "score": 95}
        result = InputTransformer.expand_template(template, variables)
        assert result == "Hello, Alice! Your score is 95."

    def test_expand_unbraced_variables(self):
        """展开 $key 格式的变量"""
        template = "User: $user, Path: $path"
        variables = {"user": "admin", "path": "/home"}
        result = InputTransformer.expand_template(template, variables)
        assert result == "User: admin, Path: /home"

    def test_expand_mixed_variables(self):
        """混合 ${} 和 $ 格式"""
        template = "${project}/src/$module/main.py"
        variables = {"project": "myapp", "module": "core"}
        result = InputTransformer.expand_template(template, variables)
        assert result == "myapp/src/core/main.py"

    def test_expand_missing_variable(self):
        """缺失变量保持原样"""
        template = "Hello, ${name}!"
        variables = {}
        result = InputTransformer.expand_template(template, variables)
        assert result == "Hello, ${name}!"

    def test_expand_empty_template(self):
        """空模板"""
        result = InputTransformer.expand_template("", {"a": "b"})
        assert result == ""


# ══════════════════════════════════════════════════════════
# OutputTransformer 文件内容格式化测试
# ══════════════════════════════════════════════════════════


class TestOutputTransformerFormatFileContent:
    """文件内容格式化"""

    def test_short_content_with_line_numbers(self):
        """短内容带行号"""
        content = "line1\nline2\nline3"
        result = OutputTransformer.format_file_content(content, max_lines=10)
        assert "1| line1" in result
        assert "2| line2" in result
        assert "3| line3" in result

    def test_short_content_without_line_numbers(self):
        """短内容不带行号"""
        content = "line1\nline2"
        result = OutputTransformer.format_file_content(content, show_line_numbers=False)
        assert "1|" not in result
        assert "line1" in result

    def test_long_content_truncated(self):
        """长内容被截断"""
        lines = [f"line_{i}" for i in range(1000)]
        content = "\n".join(lines)
        result = OutputTransformer.format_file_content(content, max_lines=10)
        # 应该有省略标记
        assert "省略" in result
        assert "文件开头" in result
        assert "文件结尾" in result

    def test_long_content_header_and_tail(self):
        """长内容包含首尾"""
        lines = [f"L{i:04d}" for i in range(1000)]
        content = "\n".join(lines)
        result = OutputTransformer.format_file_content(content, max_lines=10)
        # 应该包含开头几行
        assert "L0000" in result
        # 应该包含结尾几行
        assert "L0999" in result

    def test_empty_content(self):
        """空内容处理（空字符串 split 产生 ['']，带行号时输出 '     1| '）"""
        result = OutputTransformer.format_file_content("")
        # 空内容 split 后得到 ['']，带行号格式化后为 "     1| "
        assert "1|" in result

    def test_empty_content_no_line_numbers(self):
        """空内容不带行号时返回原内容"""
        result = OutputTransformer.format_file_content("", show_line_numbers=False)
        assert result == ""


# ══════════════════════════════════════════════════════════
# OutputTransformer 异常格式化测试
# ══════════════════════════════════════════════════════════


class TestOutputTransformerFormatError:
    """异常格式化"""

    def test_format_value_error(self):
        """格式化 ValueError"""
        try:
            raise ValueError("无效的值")
        except ValueError as e:
            result = OutputTransformer.format_error(e)

        assert result["type"] == "ValueError"
        assert result["message"] == "无效的值"
        assert "traceback" in result
        assert "full_traceback" in result

    def test_format_runtime_error(self):
        """格式化 RuntimeError"""
        try:
            raise RuntimeError("运行时错误")
        except RuntimeError as e:
            result = OutputTransformer.format_error(e)

        assert result["type"] == "RuntimeError"
        assert result["message"] == "运行时错误"

    def test_format_exception_without_traceback(self):
        """格式化没有 traceback 的异常"""
        e = Exception("简单异常")
        result = OutputTransformer.format_error(e)
        assert result["type"] == "Exception"
        assert result["message"] == "简单异常"


# ══════════════════════════════════════════════════════════
# OutputTransformer 命令输出格式化测试
# ══════════════════════════════════════════════════════════


class TestOutputTransformerFormatCommandOutput:
    """命令输出格式化"""

    def test_successful_command(self):
        """成功的命令输出"""
        result = OutputTransformer.format_command_output("Hello World", exit_code=0)
        assert result["exit_code"] == 0
        assert result["success"] is True
        assert result["output"] == "Hello World"
        assert result["truncated"] is False
        assert result["first_error"] is None

    def test_failed_command(self):
        """失败的命令输出"""
        result = OutputTransformer.format_command_output(
            "Error: 文件未找到\n其他输出", exit_code=1
        )
        assert result["exit_code"] == 1
        assert result["success"] is False
        assert result["first_error"] is not None

    def test_truncated_command_output(self):
        """超长命令输出被截断"""
        lines = [f"line_{i}" for i in range(300)]
        output = "\n".join(lines)
        result = OutputTransformer.format_command_output(output, exit_code=0, max_lines=10)
        assert result["truncated"] is True
        assert result["lines_count"] == 300
        # 输出只包含前 10 行
        assert len(result["output"].split("\n")) == 10

    def test_extract_error_from_output(self):
        """从输出中提取错误信息"""
        output = "Processing...\nError: 连接超时\nDone."
        result = OutputTransformer.format_command_output(output, exit_code=1)
        assert result["first_error"] == "Error: 连接超时"

    def test_extract_traceback_from_output(self):
        """从输出中提取 Traceback"""
        output = "Traceback (most recent call last):\n  File \"x.py\", line 1\nValueError: bad"
        result = OutputTransformer.format_command_output(output, exit_code=1)
        assert result["first_error"] is not None


# ══════════════════════════════════════════════════════════
# OutputTransformer 差异格式化测试
# ══════════════════════════════════════════════════════════


class TestOutputTransformerFormatDiff:
    """差异格式化"""

    def test_format_diff_with_changes(self):
        """格式化有变更的 diff"""
        diff = "--- a/main.py\n+++ b/main.py\n@@ -1,3 +1,4 @@\n old line\n+new line\n-more old\n+more new"
        result = OutputTransformer.format_diff(diff)
        assert "summary" in result
        assert "stats" in result
        assert "diff" in result
        assert result["stats"]["files_changed"] == 1
        assert result["stats"]["insertions"] > 0
        assert result["stats"]["deletions"] > 0

    def test_format_diff_no_changes(self):
        """格式化无变更的 diff"""
        result = OutputTransformer.format_diff("")
        assert result["stats"]["files_changed"] == 0
        assert result["stats"]["insertions"] == 0
        assert result["stats"]["deletions"] == 0

    def test_format_diff_truncated(self):
        """diff 内容被截断到 5000 字符"""
        long_diff = "x" * 10000
        result = OutputTransformer.format_diff(long_diff)
        assert len(result["diff"]) <= 5000

    def test_format_diff_with_dev_null(self):
        """diff 中包含 /dev/null 的文件不计入变更"""
        diff = "--- /dev/null\n+++ b/new.py\n@@ -0,0 +1,1 @@\n+new content"
        result = OutputTransformer.format_diff(diff)
        # 两个文件行（--- /dev/null 和 +++ b/new.py），但 /dev/null 不计入
        # files_changed 会是 0（因为 /dev/null 被排除，而 +++ 被计数但除以 2）
        assert result["stats"]["insertions"] == 1


# ══════════════════════════════════════════════════════════
# OutputTransformer 列表格式化测试
# ══════════════════════════════════════════════════════════


class TestOutputTransformerFormatListResult:
    """列表结果格式化"""

    def test_empty_list(self):
        """空列表"""
        result = OutputTransformer.format_list_result([])
        assert "没有找到" in result

    def test_items_within_limit(self):
        """列表项在限制内"""
        items = ["apple", "banana", "cherry"]
        result = OutputTransformer.format_list_result(items, max_items=10)
        assert "找到 3 个" in result
        assert "apple" in result
        assert "banana" in result
        assert "cherry" in result

    def test_items_exceed_limit(self):
        """列表项超过限制"""
        items = [f"item_{i}" for i in range(100)]
        result = OutputTransformer.format_list_result(items, max_items=10)
        assert "找到 100 个" in result
        assert "还有 90 个" in result
        # 只应显示前 10 个
        assert "item_9" in result
        assert "item_10" not in result

    def test_custom_item_name(self):
        """自定义条目名称"""
        result = OutputTransformer.format_list_result(["a"], item_name="文件")
        assert "找到 1 个文件" in result


# ══════════════════════════════════════════════════════════
# OutputTransformer JSON 安全转换测试
# ══════════════════════════════════════════════════════════


class TestOutputTransformerToJsonSafe:
    """JSON 安全转换"""

    def test_primitive_types(self):
        """原始类型直接返回"""
        assert OutputTransformer.to_json_safe("hello") == "hello"
        assert OutputTransformer.to_json_safe(42) == 42
        assert OutputTransformer.to_json_safe(3.14) == 3.14
        assert OutputTransformer.to_json_safe(True) is True
        assert OutputTransformer.to_json_safe(None) is None

    def test_list_conversion(self):
        """列表递归转换"""
        result = OutputTransformer.to_json_safe([1, "a", 3.14])
        assert result == [1, "a", 3.14]

    def test_tuple_conversion(self):
        """元组转为列表"""
        result = OutputTransformer.to_json_safe((1, 2, 3))
        assert result == [1, 2, 3]

    def test_dict_conversion(self):
        """字典递归转换"""
        result = OutputTransformer.to_json_safe({"key": "value", "num": 42})
        assert result == {"key": "value", "num": 42}

    def test_path_conversion(self):
        """Path 对象转为字符串"""
        result = OutputTransformer.to_json_safe(Path("/home/user/file.txt"))
        assert result == str(Path("/home/user/file.txt"))

    def test_object_with_to_dict(self):
        """有 to_dict 方法的对象"""
        class WithToDict:
            def to_dict(self):
                return {"name": "test", "value": 123}

        result = OutputTransformer.to_json_safe(WithToDict())
        assert result == {"name": "test", "value": 123}

    def test_object_with_dict(self):
        """有 __dict__ 属性的对象（排除私有属性）"""
        class RegularObject:
            def __init__(self):
                self.name = "test"
                self._private = "secret"
                self.__dunder = "hidden"

        result = OutputTransformer.to_json_safe(RegularObject())
        assert result["name"] == "test"
        assert "_private" not in result

    def test_unknown_type_to_string(self):
        """未知类型转为字符串"""
        result = OutputTransformer.to_json_safe(complex(1, 2))
        assert isinstance(result, str)


# ══════════════════════════════════════════════════════════
# OutputTransformer._extract_first_error 测试
# ══════════════════════════════════════════════════════════


class TestOutputTransformerExtractFirstError:
    """错误提取"""

    def test_extract_error_line(self):
        """提取 Error: 行"""
        from pycoder.bus.transformer import OutputTransformer

        output = "Some output\nError: 文件不存在\nMore output"
        result = OutputTransformer._extract_first_error(output)
        assert result == "Error: 文件不存在"

    def test_extract_traceback(self):
        """提取 Traceback 行"""
        from pycoder.bus.transformer import OutputTransformer

        output = "Traceback (most recent call last):\n  File \"x.py\""
        result = OutputTransformer._extract_first_error(output)
        assert result == "Traceback (most recent call last):"

    def test_extract_fatal(self):
        """提取 FATAL: 行"""
        from pycoder.bus.transformer import OutputTransformer

        output = "WARNING: something\nFATAL: critical error"
        result = OutputTransformer._extract_first_error(output)
        assert result == "FATAL: critical error"

    def test_fallback_to_last_lines(self):
        """没有标准错误指示符时返回最后 5 行"""
        from pycoder.bus.transformer import OutputTransformer

        output = "line1\nline2\nline3\nline4\nline5\nline6\nline7"
        result = OutputTransformer._extract_first_error(output)
        # 返回最后 5 行
        assert result is not None
        assert "line" in result

    def test_empty_output(self):
        """空输出返回空字符串"""
        from pycoder.bus.transformer import OutputTransformer

        result = OutputTransformer._extract_first_error("")
        assert result == ""
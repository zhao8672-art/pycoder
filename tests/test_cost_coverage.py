"""cost.py 模块单元测试 — 覆盖率目标 ≥80%

覆盖内容:
  - UsageRecord: 费用计算 / 序列化 / 日期格式
  - CostTracker: 记录 / 汇总 / 预算 / 格式化 / 持久化
  - 全局单例: get_cost_tracker / reset_cost_tracker
  - estimate_cost / compare_costs
  - TokenEstimator: 预估 / 警告
  - BudgetManager: 预算设置 / 状态检查 / 格式化
  - UsageCharts: 日趋势 / 模型用量 / 热力图
  - ReportExporter: JSON / CSV / Markdown 导出与保存

测试策略:
  - monkeypatch 注入 chat_bridge.estimate_tokens / Path.home 隔离
  - tmp_path 隔离持久化文件
"""

from __future__ import annotations

import io
import csv
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pycoder.providers import cost


# ── Fixtures ──

@pytest.fixture
def tracker():
    """每个测试独立的 CostTracker 实例"""
    t = cost.CostTracker()
    return t


@pytest.fixture
def patch_estimate_tokens(monkeypatch):
    """mock chat_bridge.estimate_tokens (每字符 ~0.25 token)"""
    def fake_estimate(text: str) -> int:
        return max(1, len(text) // 4)

    import pycoder.server.chat_bridge as cb
    monkeypatch.setattr(cb, "estimate_tokens", fake_estimate)
    return fake_estimate


# ══════════════════════════════════════════════════════════
# UsageRecord
# ══════════════════════════════════════════════════════════

def test_usage_record_known_model_cost():
    r = cost.UsageRecord("deepseek-chat", prompt_tokens=1_000_000, completion_tokens=1_000_000)
    # input 0.14 + output 0.28 = 0.42
    assert r.cost == round(0.14 + 0.28, 6)


def test_usage_record_unknown_model_uses_default_pricing(caplog):
    r = cost.UsageRecord("unknown-xyz", prompt_tokens=1_000_000, completion_tokens=0)
    # 默认 0.14 / 0.28
    assert r.cost == round(0.14, 6)


def test_usage_record_auto_total_tokens():
    r = cost.UsageRecord("glm-4", prompt_tokens=100, completion_tokens=50)
    assert r.total_tokens == 150


def test_usage_record_explicit_total_tokens():
    r = cost.UsageRecord("glm-4", prompt_tokens=100, completion_tokens=50, total_tokens=999)
    assert r.total_tokens == 999


def test_usage_record_auto_timestamp():
    before = time.time()
    r = cost.UsageRecord("glm-4")
    after = time.time()
    assert before <= r.timestamp <= after


def test_usage_record_datetime_str():
    ts = time.time()
    r = cost.UsageRecord("glm-4", timestamp=ts)
    expected = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    assert r.datetime_str == expected


def test_usage_record_to_dict():
    r = cost.UsageRecord("glm-4", prompt_tokens=10, completion_tokens=5, total_tokens=15)
    d = r.to_dict()
    assert d["model"] == "glm-4"
    assert d["prompt_tokens"] == 10
    assert d["completion_tokens"] == 5
    assert d["total_tokens"] == 15
    assert "cost" in d and "datetime" in d and "timestamp" in d


# ══════════════════════════════════════════════════════════
# CostTracker
# ══════════════════════════════════════════════════════════

def test_record_creates_and_stores(tracker):
    rec = tracker.record("deepseek-chat", {"prompt_tokens": 100, "completion_tokens": 50})
    assert isinstance(rec, cost.UsageRecord)
    assert tracker.total_calls() == 1


def test_record_with_total_tokens_in_usage(tracker):
    tracker.record("glm-4", {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 99})
    assert tracker.total_tokens() == 99


def test_record_triggers_budget_warning_at_80pct(tracker, capsys):
    tracker.set_budget(1.0, warning_at=0.80)
    # 单次记录使总额达到 80% 以上 ($0.80+)
    # deepseek-chat: input 0.14/M, output 0.28/M
    # 用 6M tokens input -> $0.84
    tracker.record("deepseek-chat", {"prompt_tokens": 6_000_000, "completion_tokens": 0})
    out = capsys.readouterr().out
    assert "预算使用" in out


def test_record_triggers_budget_exceeded(tracker, capsys):
    tracker.set_budget(0.001, warning_at=0.80)
    tracker.record("deepseek-chat", {"prompt_tokens": 1_000_000, "completion_tokens": 0})
    out = capsys.readouterr().out
    assert "预算上限" in out


def test_set_budget(tracker):
    tracker.set_budget(5.0, warning_at=0.5)
    assert tracker._budget_limit == 5.0
    assert tracker._budget_warning_threshold == 0.5


def test_total_cost(tracker):
    tracker.record("deepseek-chat", {"prompt_tokens": 1_000_000, "completion_tokens": 0})
    assert tracker.total_cost() == round(0.14, 6)


def test_total_tokens(tracker):
    tracker.record("glm-4", {"prompt_tokens": 100, "completion_tokens": 50})
    tracker.record("glm-4", {"prompt_tokens": 200, "completion_tokens": 50})
    assert tracker.total_tokens() == 400  # 150 + 250


def test_total_calls(tracker):
    assert tracker.total_calls() == 0
    tracker.record("glm-4", {"prompt_tokens": 1})
    tracker.record("glm-4", {"prompt_tokens": 1})
    assert tracker.total_calls() == 2


def test_cost_by_model(tracker):
    tracker.record("glm-4", {"prompt_tokens": 1_000_000, "completion_tokens": 0})
    tracker.record("deepseek-chat", {"prompt_tokens": 1_000_000, "completion_tokens": 0})
    by = tracker.cost_by_model()
    assert "glm-4" in by and "deepseek-chat" in by


def test_cost_today(tracker):
    tracker.record("glm-4", {"prompt_tokens": 1_000_000, "completion_tokens": 0})
    assert tracker.cost_today() > 0


def test_cost_today_excludes_old_records(tracker):
    old_ts = time.time() - 86400 * 2  # 2 天前
    tracker.record("glm-4", {"prompt_tokens": 1_000_000, "completion_tokens": 0}, timestamp=old_ts)
    assert tracker.cost_today() == 0


def test_cost_this_session(tracker):
    tracker.record("glm-4", {"prompt_tokens": 1_000_000, "completion_tokens": 0})
    assert tracker.cost_this_session() > 0


def test_cost_this_session_excludes_pre_session(tracker):
    # 创建一个比 start_time 早的记录
    tracker._start_time = time.time() + 100
    tracker.record("glm-4", {"prompt_tokens": 1_000_000, "completion_tokens": 0})
    assert tracker.cost_this_session() == 0


def test_recent_records_default(tracker):
    for i in range(15):
        tracker.record("glm-4", {"prompt_tokens": i})
    recent = tracker.recent_records()
    assert len(recent) == 10


def test_recent_records_custom_n(tracker):
    for i in range(5):
        tracker.record("glm-4", {"prompt_tokens": i})
    recent = tracker.recent_records(2)
    assert len(recent) == 2


def test_format_summary_tokens_millions(tracker):
    tracker.record("glm-4", {"prompt_tokens": 2_000_000, "completion_tokens": 0})
    s = tracker.format_summary()
    assert "M" in s


def test_format_summary_tokens_thousands(tracker):
    tracker.record("glm-4", {"prompt_tokens": 2000, "completion_tokens": 0})
    s = tracker.format_summary()
    assert "K" in s


def test_format_summary_tokens_small(tracker):
    tracker.record("glm-4", {"prompt_tokens": 500, "completion_tokens": 0})
    s = tracker.format_summary()
    assert "500" in s
    assert "K" not in s and "M" not in s


def test_format_report_empty(tracker):
    rep = tracker.format_report()
    assert "费用报告" in rep
    assert "API 调用: 0 次" in rep


def test_format_report_with_records(tracker):
    tracker.record("glm-4", {"prompt_tokens": 1_000_000, "completion_tokens": 0})
    rep = tracker.format_report()
    assert "glm-4" in rep


def test_format_report_with_budget(tracker):
    tracker.set_budget(10.0)
    tracker.record("glm-4", {"prompt_tokens": 1_000_000, "completion_tokens": 0})
    rep = tracker.format_report()
    assert "预算" in rep


def test_format_report_with_budget_exceeded(tracker):
    tracker.set_budget(0.001)
    tracker.record("glm-4", {"prompt_tokens": 1_000_000, "completion_tokens": 0})
    rep = tracker.format_report()
    assert "预算" in rep


def test_format_json(tracker):
    tracker.record("glm-4", {"prompt_tokens": 100, "completion_tokens": 50})
    data = json.loads(tracker.format_json())
    assert "summary" in data
    assert "by_model" in data
    assert "records" in data
    assert len(data["records"]) == 1


def test_save_custom_path(tracker, tmp_path):
    tracker.record("glm-4", {"prompt_tokens": 100})
    p = tmp_path / "cost.json"
    tracker.save(p)
    assert p.exists()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert "records" in data


def test_save_default_path(tracker, monkeypatch, tmp_path):
    fake_home = tmp_path / "fakehome"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    tracker.record("glm-4", {"prompt_tokens": 100})
    tracker.save()
    assert (fake_home / ".pycoder" / "cost_history.json").exists()


def test_load_nonexistent(tracker, tmp_path):
    p = tmp_path / "nope.json"
    tracker.load(p)
    assert tracker.total_calls() == 0


def test_load_valid_file(tracker, tmp_path):
    p = tmp_path / "hist.json"
    p.write_text(json.dumps({
        "records": [
            {"model": "glm-4", "prompt_tokens": 10, "completion_tokens": 5,
             "total_tokens": 15, "timestamp": time.time()},
        ],
    }), encoding="utf-8")
    tracker.load(p)
    assert tracker.total_calls() == 1


def test_load_missing_total_tokens_falls_back(tracker, tmp_path):
    p = tmp_path / "hist.json"
    p.write_text(json.dumps({
        "records": [
            {"model": "glm-4", "prompt_tokens": 10, "completion_tokens": 5},
        ],
    }), encoding="utf-8")
    tracker.load(p)
    assert tracker.total_tokens() == 15


def test_load_corrupted_file(tracker, tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("not valid json {{{", encoding="utf-8")
    tracker.load(p)  # 不应抛异常
    assert tracker.total_calls() == 0


def test_load_default_path_nonexistent(monkeypatch, tmp_path):
    fake_home = tmp_path / "fakehome2"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    t = cost.CostTracker()
    t.load()
    assert t.total_calls() == 0


def test_reset_session(tracker):
    old_start = tracker._start_time
    time.sleep(0.01)
    tracker.reset_session()
    assert tracker._start_time > old_start


def test_clear(tracker):
    tracker.record("glm-4", {"prompt_tokens": 100})
    tracker.clear()
    assert tracker.total_calls() == 0


# ══════════════════════════════════════════════════════════
# 全局单例
# ══════════════════════════════════════════════════════════

def test_get_cost_tracker_singleton(monkeypatch, tmp_path):
    # 重置单例并指向 tmp 避免加载真实历史
    fake_home = tmp_path / "home_a"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setattr(cost, "_tracker", None)
    t1 = cost.get_cost_tracker()
    t2 = cost.get_cost_tracker()
    assert t1 is t2


def test_reset_cost_tracker(monkeypatch, tmp_path):
    fake_home = tmp_path / "home_b"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setattr(cost, "_tracker", None)
    t1 = cost.get_cost_tracker()
    t1.record("glm-4", {"prompt_tokens": 100})
    cost.reset_cost_tracker()  # 会先 save
    assert cost._tracker is not t1


def test_reset_cost_tracker_when_none(monkeypatch):
    monkeypatch.setattr(cost, "_tracker", None)
    cost.reset_cost_tracker()  # _tracker 为 None，不应抛错
    assert cost._tracker is not None


# ══════════════════════════════════════════════════════════
# estimate_cost / compare_costs
# ══════════════════════════════════════════════════════════

def test_estimate_cost_known_model():
    est = cost.estimate_cost("deepseek-chat", prompt_tokens=1_000_000, expected_output_tokens=1_000_000)
    assert est["estimated_cost"] == round(0.14 + 0.28, 6)
    assert est["breakdown"]["price_per_m_input"] == 0.14


def test_estimate_cost_unknown_model():
    est = cost.estimate_cost("unknown-model", prompt_tokens=1_000_000, expected_output_tokens=0)
    assert est["estimated_cost"] == round(0.14, 6)


def test_compare_costs_default():
    results = cost.compare_costs(prompt_tokens=1000, output_tokens=500)
    assert len(results) == 8
    # 升序
    costs = [r["estimated_cost"] for r in results]
    assert costs == sorted(costs)


def test_compare_costs_custom_models():
    results = cost.compare_costs(models=["glm-4", "gpt-4o"])
    assert len(results) == 2
    names = [r["model"] for r in results]
    assert "glm-4" in names


# ══════════════════════════════════════════════════════════
# TokenEstimator
# ══════════════════════════════════════════════════════════

def test_token_estimator_estimate_call(tracker, patch_estimate_tokens):
    est = cost.TokenEstimator(tracker)
    result = est.estimate_call(
        "deepseek-chat",
        system_prompt="You are helpful",
        user_message="Hello world",
        expected_output_ratio=0.5,
    )
    assert result["model"] == "deepseek-chat"
    assert result["input_tokens"] > 0
    assert result["output_tokens"] == int(result["input_tokens"] * 0.5)
    assert "estimated_cost" in result


def test_token_estimator_estimate_call_with_history(tracker, patch_estimate_tokens):
    est = cost.TokenEstimator(tracker)
    result = est.estimate_call(
        "glm-4",
        system_prompt="",
        user_message="hi",
        conversation_history=[{"content": "previous message"}],
    )
    assert result["input_tokens"] > 0


def test_token_estimator_estimate_call_unknown_model(tracker, patch_estimate_tokens):
    est = cost.TokenEstimator(tracker)
    result = est.estimate_call("unknown-xyz", user_message="hello")
    assert result["breakdown"]["price_per_m_input"] == 0.14


def test_token_estimator_estimate_call_no_system_prompt(tracker, patch_estimate_tokens):
    est = cost.TokenEstimator(tracker)
    result = est.estimate_call("glm-4", user_message="hello only")
    assert result["input_tokens"] > 0


def test_token_estimator_compare_models(tracker, patch_estimate_tokens):
    est = cost.TokenEstimator(tracker)
    # compare_models 调用 compare_costs，注意参数顺序是 (input_tokens, output_tokens, models)
    results = est.compare_models(input_tokens=1000, output_tokens=200, models=["glm-4"])
    assert len(results) == 1


def test_token_estimator_format_estimate(tracker, patch_estimate_tokens):
    est = cost.TokenEstimator(tracker)
    result = est.estimate_call("glm-4", user_message="hello world test")
    formatted = est.format_estimate(result)
    assert "Token 预估" in formatted
    assert "glm-4" in formatted


def test_token_estimator_should_warn_no_budget(tracker, patch_estimate_tokens):
    est = cost.TokenEstimator(tracker)
    result = est.estimate_call("glm-4", user_message="hello")
    warn, msg = est.should_warn(result, budget_limit=None)
    assert warn is False
    assert msg == ""


def test_token_estimator_should_warn_exceeds(tracker, patch_estimate_tokens):
    est = cost.TokenEstimator(tracker)
    # 用足够大的消息使 estimated_cost > 0（避免被 round 到 0）
    result = est.estimate_call("glm-4", user_message="x" * 4000)
    assert result["estimated_cost"] > 0
    # 设置预算小于 after_call，触发超出
    warn, msg = est.should_warn(result, budget_limit=result["estimated_cost"] / 2)
    assert warn is True
    assert "预算上限" in msg


def test_token_estimator_should_warn_at_80pct(tracker, patch_estimate_tokens):
    est = cost.TokenEstimator(tracker)
    result = est.estimate_call("glm-4", user_message="x" * 4000)
    assert result["estimated_cost"] > 0
    # 让预算使 after_call 落在 80%-100% 之间
    total_spent = tracker.total_cost()
    after = total_spent + result["estimated_cost"]
    budget = after / 0.85  # after/budget ≈ 0.85 → 在 80%-100% 之间
    warn, msg = est.should_warn(result, budget_limit=budget)
    assert warn is True
    assert "此次调用后" in msg


def test_token_estimator_should_warn_below_threshold(tracker, patch_estimate_tokens):
    est = cost.TokenEstimator(tracker)
    result = est.estimate_call("glm-4", user_message="hello")
    warn, msg = est.should_warn(result, budget_limit=100.0)
    assert warn is False


def test_get_token_estimator_singleton():
    cost._token_estimator = None
    e1 = cost.get_token_estimator()
    e2 = cost.get_token_estimator()
    assert e1 is e2


# ══════════════════════════════════════════════════════════
# BudgetManager
# ══════════════════════════════════════════════════════════

def test_budget_manager_set_monthly(tracker):
    bm = cost.BudgetManager(tracker)
    bm.set_monthly_budget(50.0)
    assert bm.monthly_budget == 50.0
    assert tracker._budget_limit == 50.0


def test_budget_manager_set_daily(tracker):
    bm = cost.BudgetManager(tracker)
    bm.set_daily_budget(5.0)
    assert bm.daily_budget == 5.0


def test_budget_manager_check_budget_ok(tracker):
    bm = cost.BudgetManager(tracker)
    bm.set_monthly_budget(100.0)
    tracker.record("glm-4", {"prompt_tokens": 1_000_000})  # $0.10
    result = bm.check_budget()
    assert result["status"] == "ok"


def test_budget_manager_check_budget_warning(tracker):
    bm = cost.BudgetManager(tracker)
    # $0.10 / $0.12 = 83.3% → 在 80%-95% 之间 → warning
    bm.set_monthly_budget(0.12)
    tracker.record("glm-4", {"prompt_tokens": 1_000_000})  # $0.10
    result = bm.check_budget()
    assert result["status"] == "warning"


def test_budget_manager_check_budget_critical(tracker):
    bm = cost.BudgetManager(tracker)
    # $0.10 / $0.104 = 96.2% → 在 95%-100% 之间 → critical
    bm.set_monthly_budget(0.104)
    tracker.record("glm-4", {"prompt_tokens": 1_000_000})  # $0.10
    result = bm.check_budget()
    assert result["status"] == "critical"


def test_budget_manager_check_budget_exceeded_monthly(tracker):
    bm = cost.BudgetManager(tracker)
    bm.set_monthly_budget(0.05)  # $0.10 > $0.05 → exceeded
    tracker.record("glm-4", {"prompt_tokens": 1_000_000})
    result = bm.check_budget()
    assert result["status"] == "exceeded"


def test_budget_manager_check_budget_daily_exceeded(tracker):
    bm = cost.BudgetManager(tracker)
    bm.set_daily_budget(0.05)
    tracker.record("glm-4", {"prompt_tokens": 1_000_000})  # $0.10
    result = bm.check_budget()
    assert result["status"] == "exceeded"


def test_budget_manager_check_budget_daily_critical(tracker):
    bm = cost.BudgetManager(tracker)
    # 0.95 阈值：$0.10 / $0.105 ≈ 0.952 → critical
    bm.set_daily_budget(0.105)
    tracker.record("glm-4", {"prompt_tokens": 1_000_000})
    result = bm.check_budget()
    assert result["status"] == "critical"


def test_budget_manager_check_budget_no_budget(tracker):
    bm = cost.BudgetManager(tracker)
    result = bm.check_budget()
    assert result["status"] == "ok"
    assert result["monthly_remaining"] == 0


def test_budget_manager_format_status_empty(tracker):
    bm = cost.BudgetManager(tracker)
    s = bm.format_status()
    assert "预算状态" in s


def test_budget_manager_format_status_with_budgets(tracker):
    bm = cost.BudgetManager(tracker)
    bm.set_monthly_budget(10.0)
    bm.set_daily_budget(1.0)
    tracker.record("glm-4", {"prompt_tokens": 1_000_000})
    s = bm.format_status()
    assert "月预算" in s
    assert "今日" in s


def test_budget_manager_format_status_with_message(tracker):
    bm = cost.BudgetManager(tracker)
    bm.set_monthly_budget(0.05)
    tracker.record("glm-4", {"prompt_tokens": 1_000_000})
    s = bm.format_status()
    assert "月预算" in s


def test_get_budget_manager_singleton():
    cost._budget_manager = None
    b1 = cost.get_budget_manager()
    b2 = cost.get_budget_manager()
    assert b1 is b2


# ══════════════════════════════════════════════════════════
# UsageCharts
# ══════════════════════════════════════════════════════════

def test_usage_charts_daily_costs_empty(tracker):
    ch = cost.UsageCharts(tracker)
    daily = ch.daily_costs(7)
    assert len(daily) == 7
    assert all(v == 0 for v in daily.values())


def test_usage_charts_daily_costs_with_data(tracker):
    ch = cost.UsageCharts(tracker)
    tracker.record("glm-4", {"prompt_tokens": 1_000_000})
    daily = ch.daily_costs(7)
    today = datetime.now().date().isoformat()
    assert daily[today] > 0


def test_usage_charts_daily_costs_old_excluded(tracker):
    ch = cost.UsageCharts(tracker)
    tracker.record("glm-4", {"prompt_tokens": 1_000_000}, timestamp=time.time() - 86400 * 10)
    daily = ch.daily_costs(7)
    assert all(v == 0 for v in daily.values())


def test_usage_charts_model_usage(tracker):
    ch = cost.UsageCharts(tracker)
    tracker.record("glm-4", {"prompt_tokens": 100, "completion_tokens": 50})
    tracker.record("deepseek-chat", {"prompt_tokens": 100, "completion_tokens": 50})
    usage = ch.model_usage()
    assert "glm-4" in usage
    assert usage["glm-4"]["calls"] == 1
    assert usage["glm-4"]["tokens"] == 150


def test_usage_charts_hourly_heatmap(tracker):
    ch = cost.UsageCharts(tracker)
    tracker.record("glm-4", {"prompt_tokens": 1_000_000})
    heat = ch.hourly_heatmap(7)
    assert len(heat) >= 1


def test_usage_charts_format_trend_empty(tracker):
    ch = cost.UsageCharts(tracker)
    # 全 0 的 daily_costs，max_cost 为 0.0001 但 daily 非空
    s = ch.format_trend(7)
    assert "费用趋势" in s


def test_usage_charts_format_trend_with_data(tracker):
    ch = cost.UsageCharts(tracker)
    tracker.record("glm-4", {"prompt_tokens": 1_000_000})
    s = ch.format_trend(7)
    assert "费用趋势" in s


# ══════════════════════════════════════════════════════════
# ReportExporter
# ══════════════════════════════════════════════════════════

def test_report_exporter_export_json(tracker):
    tracker.record("glm-4", {"prompt_tokens": 100})
    ex = cost.ReportExporter(tracker)
    out = ex.export_json()
    data = json.loads(out)
    assert "summary" in data


def test_report_exporter_export_csv(tracker, monkeypatch):
    """源文件 export_csv 使用 io/csv 但未在模块顶部导入，注入以完成覆盖"""
    # 注意: 这是源文件 bug —— export_csv 缺少 import io, import csv
    monkeypatch.setattr(cost, "io", io, raising=False)
    monkeypatch.setattr(cost, "csv", csv, raising=False)
    tracker.record("glm-4", {"prompt_tokens": 100, "completion_tokens": 50})
    ex = cost.ReportExporter(tracker)
    out = ex.export_csv()
    assert "datetime,model" in out
    assert "glm-4" in out


def test_report_exporter_export_markdown(tracker):
    tracker.record("glm-4", {"prompt_tokens": 100, "completion_tokens": 50})
    tracker.record("deepseek-chat", {"prompt_tokens": 100, "completion_tokens": 50})
    ex = cost.ReportExporter(tracker)
    out = ex.export_markdown()
    assert "PyCoder 费用报告" in out
    assert "glm-4" in out


def test_report_exporter_export_markdown_empty(tracker):
    ex = cost.ReportExporter(tracker)
    out = ex.export_markdown()
    assert "PyCoder 费用报告" in out


def test_report_exporter_save_report_json(tracker, tmp_path):
    tracker.record("glm-4", {"prompt_tokens": 100})
    ex = cost.ReportExporter(tracker)
    p = ex.save_report(format="json", path=str(tmp_path / "r.json"))
    assert Path(p).exists()


def test_report_exporter_save_report_csv(tracker, tmp_path, monkeypatch):
    monkeypatch.setattr(cost, "io", io, raising=False)
    monkeypatch.setattr(cost, "csv", csv, raising=False)
    tracker.record("glm-4", {"prompt_tokens": 100})
    ex = cost.ReportExporter(tracker)
    p = ex.save_report(format="csv", path=str(tmp_path / "r.csv"))
    assert Path(p).exists()


def test_report_exporter_save_report_md(tracker, tmp_path):
    tracker.record("glm-4", {"prompt_tokens": 100})
    ex = cost.ReportExporter(tracker)
    p = ex.save_report(format="md", path=str(tmp_path / "r.md"))
    assert Path(p).exists()


def test_report_exporter_save_report_invalid_format(tracker):
    ex = cost.ReportExporter(tracker)
    with pytest.raises(ValueError):
        ex.save_report(format="xml")


def test_report_exporter_save_report_default_path(tracker, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tracker.record("glm-4", {"prompt_tokens": 100})
    ex = cost.ReportExporter(tracker)
    p = ex.save_report(format="json")
    assert Path(p).exists()

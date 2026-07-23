"""分析 PyCoder AI 会话和执行日志，生成诊断报告"""
import json
import os
import sqlite3
from pathlib import Path
from datetime import datetime

home = Path.home()
report = []

def header(title):
    report.append(f"\n{'='*60}")
    report.append(f"📊 {title}")
    report.append(f"{'='*60}")

# ═══════════════════════════════════════════════
# 1. 会话数据库分析
# ═══════════════════════════════════════════════
header("会话数据分析")
db_path = home / ".pycoder" / "unified.db"
if db_path.exists():
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()

    # 总会话
    c.execute("SELECT COUNT(*), COALESCE(SUM(total_tokens),0), COALESCE(SUM(message_count),0) FROM sessions")
    total, tokens, msgs = c.fetchone()
    report.append(f"总会话: {total} | 总消息: {msgs} | 总Token(估): {tokens}")

    # 模型分布
    c.execute("SELECT model, COUNT(*) FROM sessions WHERE model IS NOT NULL GROUP BY model ORDER BY COUNT(*) DESC")
    models = c.fetchall()
    report.append(f"\n模型分布:")
    for m, cnt in models:
        c.execute("SELECT COALESCE(SUM(total_tokens),0), COALESCE(AVG(message_count),0) FROM sessions WHERE model=?", (m,))
        mt, mam = c.fetchone()
        report.append(f"  {m}: {cnt}次会话, {mt} tokens, 均{int(mam)}消息/会话")

    # Token消耗TOP
    c.execute("SELECT id, model, total_tokens, message_count, title FROM sessions WHERE total_tokens > 0 ORDER BY total_tokens DESC LIMIT 15")
    top = c.fetchall()
    report.append(f"\nToken消耗TOP15:")
    for rid, rm, rt, rmc, rtitle in top:
        report.append(f"  [{rm}] {str(rtitle)[:50] if rtitle else '(无)'} — {rt}tok, {rmc}msg")

    # 空会话（有session无消息）
    c.execute("SELECT COUNT(*) FROM sessions WHERE id NOT IN (SELECT DISTINCT session_id FROM messages)")
    empty = c.fetchone()[0]
    report.append(f"\n空会话（无消息）: {empty}")

    # 最近会话标题
    c.execute("SELECT id, title, model, message_count FROM sessions ORDER BY ROWID DESC LIMIT 10")
    report.append(f"\n最近10个会话:")
    for sid, stitle, sm, smc in c.fetchall():
        t = str(stitle)[:60] if stitle else "(无标题)"
        report.append(f"  [{sm}] {t} ({smc}条消息)")

    # 错误模式: 消息中带error/失败/报错比例的会话
    c.execute("""
        SELECT COUNT(*) FROM messages 
        WHERE content LIKE '%error%' OR content LIKE '%Exception%' OR content LIKE '%失败%' OR content LIKE '%报错%' 
           OR content LIKE '%timeout%' OR content LIKE '%Traceback%'
    """)
    err_msgs = c.fetchone()[0]
    total_msgs = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    report.append(f"\n含错误关键词消息: {err_msgs}/{total_msgs} ({err_msgs/max(total_msgs,1)*100:.0f}%)")

    # 工具调用分析
    c.execute("""
        SELECT content FROM messages 
        WHERE content LIKE '%tool_calls%' OR content LIKE '%tool_use%' OR content LIKE '%工具%'
        ORDER BY ROWID DESC LIMIT 5
    """)
    tool_refs = c.fetchall()
    report.append(f"\n工具调用引用: {len(tool_refs)} 条最近消息含工具关键词")

    conn.close()
else:
    report.append("❌ unified.db 不存在")

# ═══════════════════════════════════════════════
# 2. 自进化学习数据
# ═══════════════════════════════════════════════
header("自进化学习数据")
learn_db = home / ".pycoder" / "learning" / "live_learn.db"
if learn_db.exists():
    conn = sqlite3.connect(str(learn_db))
    c = conn.cursor()
    c.execute("SELECT COUNT(*), COALESCE(SUM(success),0), COALESCE(AVG(rounds),0), COUNT(DISTINCT mode) FROM observations")
    total2, succ2, avg_r, modes = c.fetchone()
    report.append(f"总观察: {total2} | 成功: {succ2} ({succ2/max(total2,1)*100:.0f}%) | 平均轮次: {avg_r:.1f} | 模式数: {modes}")

    c.execute("SELECT pattern_name, success_count, total_count, avg_rounds FROM patterns ORDER BY total_count DESC")
    patterns = c.fetchall()
    if patterns:
        report.append(f"\n已学习模式 ({len(patterns)}):")
        for pn, psc, ptc, par in patterns:
            report.append(f"  {pn}: {psc}/{ptc}成功, {par:.1f}轮")
    else:
        report.append("  (无模式数据 — 观察数未达反思阈值)")

    c.execute("SELECT mode, COUNT(*), AVG(rounds), SUM(success) FROM observations GROUP BY mode")
    report.append(f"\n各模式表现:")
    for mode, cnt, avg_r, succ in c.fetchall():
        report.append(f"  {mode}: {cnt}次, {avg_r:.1f}轮均, {succ}成功")
    conn.close()
else:
    report.append("❌ live_learn.db 不存在")

# ═══════════════════════════════════════════════
# 3. 进化历史
# ═══════════════════════════════════════════════
header("进化历史")
hist_file = home / ".pycoder" / "evolution_history.json"
if hist_file.exists():
    data = json.loads(hist_file.read_text(encoding="utf-8"))
    succ3 = sum(1 for d in data if d.get("success"))
    report.append(f"共{len(data)}条, 成功{succ3}条 ({succ3/max(len(data),1)*100:.0f}%)")
    report.append(f"\n最近10条进化记录:")
    for d in data[-10:]:
        report.append(f"  {d.get('action','?')} | {d.get('file','?')} | {'✅' if d.get('success') else '❌'} | {str(d.get('fix_description',''))[:60]}")
    issue_types = {}
    for d in data:
        it = d.get("issue_type", "unknown")
        issue_types[it] = issue_types.get(it, 0) + 1
    report.append(f"\n问题类型分布:")
    for it, cnt in sorted(issue_types.items(), key=lambda x: -x[1]):
        report.append(f"  {it}: {cnt}")
else:
    report.append("❌ evolution_history.json 不存在")

# ═══════════════════════════════════════════════
# 4. 错误日志文件分析
# ═══════════════════════════════════════════════
header("错误日志文件")
project = Path.cwd()
error_files = list(project.glob("_*stderr*")) + list(project.glob("_*err*")) + list(project.glob("_*stdout*"))
if error_files:
    report.append(f"找到 {len(error_files)} 个日志文件:")
    for ef in error_files:
        size = ef.stat().st_size
        preview = ef.read_text(encoding="utf-8", errors="replace")[:300] if size < 50000 else "(过大跳过)"
        report.append(f"\n--- {ef.name} ({size/1024:.0f}KB) ---")
        report.append(preview)
else:
    report.append("无本地错误日志文件")

# ═══════════════════════════════════════════════
# 5. 测试与烟测结果
# ═══════════════════════════════════════════════
header("测试与烟测结果")
for tf in ["_smoke_summary.txt", "_test_summary.txt", "test_result_new.txt", "test_output_new.txt"]:
    fp = project / tf
    if fp.exists():
        content = fp.read_text(encoding="utf-8", errors="replace")
        report.append(f"\n--- {tf} ({fp.stat().st_size/1024:.0f}KB) ---")
        report.append(content[:500])

# ═══════════════════════════════════════════════
# 输出报告
# ═══════════════════════════════════════════════
output = "\n".join(report)
print(output)

# 保存到文件
out_path = project / "_diagnosis_report.txt"
out_path.write_text(output, encoding="utf-8")
print(f"\n{'='*60}")
print(f"📄 报告已保存: {out_path}")

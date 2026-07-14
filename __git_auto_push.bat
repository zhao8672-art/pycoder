@echo off
REM __git_auto_push.bat — 一键提交+推送（AI 助手每次完成任务后调用）
REM 用法: __git_auto_push.bat "fix: 你的提交信息"
cd /d "%~dp0"
python __git_commit_push.py %*
if %errorlevel% neq 0 (
    echo.
    echo ⚠️  执行失败，请手动执行:
    echo   git add -A
    echo   git commit -m "fix: ..."
    echo   git push origin master
)
pause

@echo off
REM PyCoder 一键测试脚本 — 运行全部测试并生成覆盖率报告
REM 用法: scripts\test.bat [--no-coverage]

setlocal

set COVERAGE=1
if /i "%1"=="--no-coverage" set COVERAGE=0

echo ========================================
echo   PyCoder Test Suite
echo ========================================

if %COVERAGE%==1 (
    echo Running tests with coverage...
    pytest tests/ -v --tb=short --timeout=60 --cov=pycoder --cov-report=term-missing --cov-report=html --cov-fail-under=80
) else (
    echo Running tests without coverage...
    pytest tests/ -v --tb=short --timeout=60
)

set EXITCODE=%ERRORLEVEL%

if %EXITCODE%==0 (
    echo.
    echo ========================================
    echo   ALL TESTS PASSED
    echo ========================================
) else (
    echo.
    echo ========================================
    echo   TESTS FAILED ^(exit code %EXITCODE%^)
    echo ========================================
)

endlocal & exit /b %EXITCODE%

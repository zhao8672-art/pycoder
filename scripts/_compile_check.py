import py_compile, sys
try:
    py_compile.compile("pycoder/server/services/execution_pipeline.py", doraise=True)
    print("PIPELINE_OK")
except py_compile.PyCompileError as e:
    print(f"FAIL: {e}")
    sys.exit(1)

import os, subprocess, sys
os.environ["PYCODER_CLOUD_JWT_SECRET"] = "test"
r = subprocess.run([sys.executable, r"C:\Users\Administrator\Desktop\pycode\test_ai_strategy.py"],
                   capture_output=True, text=True, cwd=r"C:\Users\Administrator\Desktop\pycode")
print(r.stdout)
if r.stderr: print("STDERR:", r.stderr[:500])

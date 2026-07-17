import shutil, os, glob
root = r"C:\Users\Administrator\Desktop\pycode"
for d in glob.glob(f"{root}/**/__pycache__", recursive=True):
    shutil.rmtree(d, True)
for f in glob.glob(f"{root}/**/*.pyc", recursive=True):
    os.remove(f)
print("CLEANED")

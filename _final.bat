@echo off
cd /d C:\Users\Administrator\Desktop\pycode
git restore --staged .
git add --all
git commit -m "chore: 清理项目无关文件 + 恢复源文件完整性"
git push --force origin master
echo ====== DONE ======

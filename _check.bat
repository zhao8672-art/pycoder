@echo off
cd /d C:\Users\Administrator\Desktop\pycode
.venv\Scripts\python.exe -c "import urllib.request,json; r=urllib.request.urlopen('http://127.0.0.1:8423/api/chat',data=json.dumps({'message':'回复:ok','model':'deepseek-chat'}).encode(),timeout=20); d=json.loads(r.read().decode()); print('DS:',(d.get('reply','') or 'EMPTY')[:100])" 2>&1
echo ---
.venv\Scripts\python.exe -c "import urllib.request,json; r=urllib.request.urlopen('http://127.0.0.1:8423/api/config/status',timeout=5); d=json.loads(r.read().decode()); print('Model:',d['recommended_model'],'Keys:',sum(1 for p in d['providers'] if p['has_key']))" 2>&1
echo DONE
pause

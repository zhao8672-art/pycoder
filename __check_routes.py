import urllib.request, json
r = urllib.request.urlopen(urllib.request.Request(
    'http://127.0.0.1:8423/openapi.json',
    headers={'X-API-Key': 'AX8iZWiH7B0aK2Lh1ZdC8F_hbjvA58h6QW6CkDFI9z0'}
))
data = json.loads(r.read())
paths = [p for p in data['paths'] if 'evolution' in p]
for p in sorted(paths):
    methods = list(data['paths'][p].keys())
    print(f"{' '.join(methods).upper():10s} {p}")

"""Fetch system prompts from the GitHub repo for comparison."""
import requests
import json
import os
import urllib.parse

BASE = "https://api.github.com/repos/x1xhlol/system-prompts-and-models-of-ai-tools/contents"
OUT = "scripts/_fetched_prompts"

os.makedirs(OUT, exist_ok=True)

# Key directories to explore
dirs = [
    "Cursor Prompts",
    "Devin AI", 
    "Anthropic",
    "Windsurf",
    "VSCode Agent",
    "Trae",
    "Augment Code",
    "Manus Agent Tools & Prompt",
    "Replit",
    "v0 Prompts and Tools",
    "Open Source prompts",
    "Amp",
]

def get_json(url):
    r = requests.get(url)
    if r.status_code == 200:
        return r.json()
    return None

def fetch_dir(dir_name):
    print(f"\n=== {dir_name} ===")
    url = f"{BASE}/{urllib.parse.quote(dir_name, safe='')}"
    items = get_json(url)
    if not items:
        print(f"  [404]")
        return
    
    if isinstance(items, dict):
        items = [items]
    
    for item in items:
        name = item["name"]
        print(f"  {name} ({item.get('size', 0)} bytes)")
        
        if item["type"] == "file" and item.get("size", 0) < 200000:
            # Fetch raw content
            raw_url = item["download_url"]
            if raw_url:
                content = requests.get(raw_url).text
                safe_name = f"{dir_name}_{name}".replace("/", "_").replace(" ", "_")
                with open(f"{OUT}/{safe_name}", "w", encoding="utf-8") as f:
                    f.write(content)
                print(f"    -> saved {len(content)} chars")
        
        elif item["type"] == "dir":
            # Recurse one level
            sub_url = f"{BASE}/{urllib.parse.quote(item['path'], safe='')}"
            sub_items = get_json(sub_url)
            if sub_items and isinstance(sub_items, list):
                for sub in sub_items:
                    if sub["type"] == "file" and sub.get("size", 0) < 200000:
                        raw_url = sub["download_url"]
                        if raw_url:
                            content = requests.get(raw_url).text
                            safe_name = f"{dir_name}_{sub['name']}".replace("/", "_").replace(" ", "_")
                            with open(f"{OUT}/{safe_name}", "w", encoding="utf-8") as f:
                                f.write(content)
                            print(f"    {sub['name']} -> saved {len(content)} chars")

for d in dirs:
    fetch_dir(d)

print(f"\n\nDone! Files saved to {OUT}/")
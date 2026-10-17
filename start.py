"""Local development launcher for AI Commerce Egypt Restaurant Edition.
Reads a local .env file without external dotenv dependency; never embeds provider keys
in browser JavaScript. Not a production WSGI/ASGI deployment configuration.
"""
from pathlib import Path
import os
import webbrowser
import threading
import uvicorn

ROOT = Path(__file__).resolve().parent

def load_env():
    path = ROOT / '.env'
    if not path.exists():
        return
    for raw in path.read_text(encoding='utf-8-sig').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        if key.isidentifier():
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)

if __name__ == '__main__':
    load_env()
    if os.environ.get('APP_ENV', 'development').lower() == 'production':
        raise SystemExit('استخدمي نشرًا آمنًا مع HTTPS وإعدادات إنتاجية؛ هذا المشغل للتجربة المحلية فقط.')
    url = 'http://127.0.0.1:8000'
    print('\nAI COMMERCE EGYPT — RESTAURANTS\n')
    print(f'واجهة الزبون: {url}')
    print(f'لوحة الإدارة: {url}/admin/login')
    print('كلمة المرور المحلية الافتراضية: demo12345 (غيّريها قبل النشر)')
    threading.Timer(2.5,lambda: webbrowser.open(url)).start()
    uvicorn.run('app:app',host='127.0.0.1',port=8000,app_dir=str(ROOT))

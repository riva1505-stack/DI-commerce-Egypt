from pathlib import Path
from fastapi.testclient import TestClient
from app import create_app


def test_brand_integrated_in_all_pages(tmp_path):
    app=create_app(db_path=tmp_path/'test.sqlite',admin_password='local-test',secret_key='a'*40)
    with TestClient(app) as c:
        home=c.get('/')
        assert home.status_code == 200
        assert '/static/brand.css?v=1.0' in home.text
        assert '/static/images/ai-commerce-logo.webp' in home.text
        assert 'chatMic' in home.text and 'submitOrder' in home.text
        login=c.get('/admin/login')
        assert login.status_code == 200
        assert '/static/brand.css?v=1.0' in login.text
        c.post('/admin/login',data={'password':'local-test'},follow_redirects=True)
        dashboard=c.get('/admin')
        assert dashboard.status_code==200
        assert 'class="admin-hero"' in dashboard.text
        assert '/static/images/ai-commerce-logo.webp' in dashboard.text


def test_brand_assets_and_menu_api(tmp_path):
    app=create_app(db_path=tmp_path/'test.sqlite',admin_password='local-test',secret_key='b'*40)
    with TestClient(app) as c:
        css=c.get('/static/brand.css')
        assert css.status_code==200
        assert '--magenta:#f649dc' in css.text
        assert '.sidebar' in css.text and '.chat-thread' in css.text
        image=c.get('/static/images/ai-commerce-logo.webp')
        assert image.status_code==200 and len(image.content)>30_000
        assert image.headers['content-type']=='image/webp'
        menu=c.get('/api/menu').json()
        assert len(menu['items'])>=9
        assert menu['settings']['restaurant_name']=='بيت المذاق'
        assert c.get('/health').json()['version']=='1.0.0-restaurant-edition'

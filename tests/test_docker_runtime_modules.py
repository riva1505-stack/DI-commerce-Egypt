from pathlib import Path


def test_docker_runtime_modules():
    docker = (Path(__file__).resolve().parents[1] / 'Dockerfile').read_text()
    assert 'bokharest_showcase.py' in docker
    assert 'restaurant_tenants.py' in docker

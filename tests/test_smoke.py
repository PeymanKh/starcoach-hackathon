from django.conf import settings
from django.core import management


def test_settings_load():
    assert settings.SECRET_KEY


def test_django_system_check_passes():
    management.call_command("check")


def test_health(client):
    assert client.get("/health/").status_code == 200

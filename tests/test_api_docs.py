from django.core import management


def test_schema_builds_without_warnings(tmp_path):
    """Every DRF view is described: a new view without @extend_schema fails here."""
    management.call_command(
        "spectacular", "--validate", "--fail-on-warn", "--file", str(tmp_path / "schema.yml")
    )


def test_schema_lists_the_endpoints(client):
    paths = client.get("/api/schema/?format=json").json()["paths"]
    for path in [
        "/api/agent/models/",
        "/api/agent/runs/",
        "/api/agent/threads/",
        "/api/agent/threads/{thread_id}/",
        "/api/agent/transcribe/",
    ]:
        assert path in paths


def test_docs_page(client):
    response = client.get("/api/docs/")
    assert response.status_code == 200
    # ReDoc 3 (what "latest" points to) renders a blank page here: keep version 2.
    assert b"redoc@2." in response.content

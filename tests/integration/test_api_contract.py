import uuid

import httpx
import pytest

pytestmark = pytest.mark.integration


def assert_error(response, status):
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error", "request_id"}
    assert set(body["error"]) == {"code", "message"}
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert body["error"]["code"] and body["error"]["message"]
    for secret in ("Traceback", "sqlalchemy", "password_hash", "mysql+pymysql"):
        assert secret not in response.text


def test_validation_envelopes_and_chunked_body_limit(user):
    for prompt in ("", "   \n\t", "x" * 10001):
        assert_error(
            user.post(
                "/api/v1/tasks", json={"prompt": prompt}, headers={"Idempotency-Key": uuid.uuid4().hex}
            ),
            422,
        )
    for key in ("", "x" * 129):
        assert_error(
            user.post("/api/v1/tasks", json={"prompt": "valid"}, headers={"Idempotency-Key": key}), 422
        )
    for query in ("limit=0", "limit=101", "limit=abc", "offset=-1", "offset=1000001"):
        assert_error(user.get("/api/v1/tasks?" + query), 422)
    assert_error(user.get("/api/v1/does-not-exist"), 404)
    assert_error(user.put("/api/v1/tasks", json={}), 405)
    assert_error(
        user.post("/api/v1/tasks", content=b"{not-json", headers={"Content-Type": "application/json"}), 422
    )
    # A generator forces Transfer-Encoding: chunked, without Content-Length.
    request = user.build_request(
        "POST",
        "/api/v1/tasks",
        content=(b"x" * 4096 for _ in range(20)),
        headers={"Content-Type": "application/json", "Idempotency-Key": uuid.uuid4().hex},
    )
    assert "content-length" not in request.headers
    assert request.headers["transfer-encoding"] == "chunked"
    assert_error(user.send(request), 413)


def test_all_auth_write_origin_and_csrf_boundaries(user, base_url):
    credentials = {"username": "origin_" + uuid.uuid4().hex[:16], "password": "Origin-test!password42"}
    for path in ("register", "login"):
        assert_error(
            user.post("/api/v1/auth/" + path, json=credentials, headers={"Origin": "https://evil.invalid"}),
            403,
        )
    for csrf in ("", "wrong-token"):
        assert_error(user.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}), 403)
        assert_error(
            user.post(
                "/api/v1/tasks",
                json={"prompt": "valid"},
                headers={"X-CSRF-Token": csrf, "Idempotency-Key": uuid.uuid4().hex},
            ),
            403,
        )
    assert_error(user.post("/api/v1/auth/logout", headers={"Origin": "https://evil.invalid"}), 403)
    with httpx.Client(base_url=base_url, timeout=15) as client:
        for path in ("/api/v1/auth/me", "/api/v1/tasks"):
            assert_error(client.get(path), 401)
        assert_error(client.post("/api/v1/auth/logout"), 401)
        assert_error(client.post("/api/v1/auth/login", json=credentials), 401)
        assert_error(client.post("/api/v1/auth/register", json={"username": "!", "password": "short"}), 422)

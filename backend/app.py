import logging
import time

from fastapi import FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

from backend.auth import Auth
from backend.runtime import Runtime
from backend.service import ServiceError, uid

REQUESTS = Counter("lab_http_requests_total", "HTTP responses", ["method", "route", "status"])
LATENCY = Histogram("lab_http_request_duration_seconds", "HTTP latency", ["route"])
log = logging.getLogger("lab")


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    password: str = Field(min_length=10, max_length=128)


class TaskInput(BaseModel):
    prompt: str = Field(min_length=1, max_length=10000)

    @field_validator("prompt")
    @classmethod
    def trim(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("prompt must not be blank")
        return value


def create_app(runtime=None):
    runtime = runtime or Runtime()
    auth = Auth(runtime)
    app = FastAPI(title="Agent Stack Lab 教学 API", version="0.1.0")
    app.state.runtime = runtime

    def error(request, status, code, message):
        return JSONResponse(
            status_code=status,
            headers={"X-Request-ID": getattr(request.state, "request_id", "unknown")},
            content={
                "error": {"code": code, "message": message},
                "request_id": getattr(request.state, "request_id", "unknown"),
            },
        )

    @app.middleware("http")
    async def context(request, call_next):
        request.state.request_id = uid()
        start = time.monotonic()
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.headers.get("origin") not in (
            None,
            runtime.settings.origin,
        ):
            response = error(request, 403, "origin_forbidden", "请求来源不被允许")
        elif (
            not request.headers.get("content-length", "0").isdigit()
            or int(request.headers.get("content-length", "0")) > 65536
        ):
            response = error(request, 413, "body_too_large", "请求过大")
        else:
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > 65536:
                    response = error(request, 413, "body_too_large", "请求过大")
                    break
                body.extend(chunk)
            else:
                request._body = bytes(body)
                response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        route = request.scope.get("route")
        template = getattr(route, "path", "unmatched")
        REQUESTS.labels(
            request.method
            if request.method in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}
            else "OTHER",
            template,
            str(response.status_code),
        ).inc()
        LATENCY.labels(template).observe(time.monotonic() - start)
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error(
            request,
            exc.status_code,
            "not_found" if exc.status_code == 404 else "http_error",
            "请求路径不存在" if exc.status_code == 404 else "请求方法不被允许",
        )

    @app.exception_handler(ServiceError)
    async def service_error(request, exc):
        return error(request, exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return error(request, 422, "validation_error", "输入格式或长度不符合要求")

    @app.exception_handler(SQLAlchemyError)
    async def db_error(request, exc):
        return error(request, 503, "database_unavailable", "数据库暂不可用")

    @app.exception_handler(Exception)
    async def unknown_error(request, exc):
        log.error("request_failed request_id=%s type=%s", request.state.request_id, type(exc).__name__)
        return error(request, 500, "internal_error", "请求处理失败")

    @app.get("/healthz")
    def live():
        return {"status": "ok"}

    @app.get("/readyz")
    def ready():
        dependencies = {}
        try:
            with runtime.engine.connect() as connection:
                connection.execute(text("SELECT version FROM schema_version WHERE version=1")).scalar_one()
            dependencies[runtime.engine.dialect.name] = "up"
        except Exception:
            dependencies[runtime.engine.dialect.name] = "down"
        for name, adapter in (("mongo", runtime.documents), ("kafka", runtime.bus)):
            try:
                dependencies[name] = "up" if adapter.ping() else "down"
            except Exception:
                dependencies[name] = "down"
        if runtime.settings.mode != "production":
            dependencies["mongo"] = dependencies["kafka"] = "in_memory_test_adapter"
        healthy = "down" not in dependencies.values()
        return JSONResponse(
            {
                "status": "ready" if healthy else "not_ready",
                "mode": runtime.settings.mode,
                "model_mode": runtime.settings.model_mode,
                "dependencies": dependencies,
            },
            status_code=200 if healthy else 503,
        )

    @app.get("/metrics")
    def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    def authenticate(body, response, register=False):
        data, token = auth.login(body.username, body.password, register)
        response.set_cookie(
            "lab_session",
            token,
            max_age=86400,
            httponly=True,
            secure=runtime.settings.secure_cookie,
            samesite="strict",
            path="/",
        )
        return data

    @app.post("/api/v1/auth/register", status_code=201)
    def register(body: Credentials, response: Response):
        return authenticate(body, response, True)

    @app.post("/api/v1/auth/login")
    def login(body: Credentials, response: Response):
        return authenticate(body, response)

    @app.get("/api/v1/auth/me")
    def me(request: Request):
        return auth.refresh(request)

    @app.post("/api/v1/auth/logout", status_code=204)
    def logout(request: Request):
        auth.logout(request)
        response = Response(status_code=204)
        response.delete_cookie("lab_session", path="/")
        return response

    @app.post("/api/v1/tasks", status_code=202)
    def submit(body: TaskInput, request: Request):
        owner = auth.identity(request, write=True)["id"]
        key = request.headers.get("idempotency-key", "")
        if not 1 <= len(key) <= 128:
            raise ServiceError(422, "idempotency_key_required", "幂等键长度必须为 1..128")
        return runtime.tasks.create(owner, key, body.prompt, request.state.request_id)

    @app.get("/api/v1/tasks")
    def listing(
        request: Request, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0, le=1000000)
    ):
        return runtime.tasks.listing(auth.identity(request)["id"], limit, offset)

    @app.get("/api/v1/tasks/{task_id}")
    def detail(task_id: str, request: Request):
        return runtime.tasks.get(auth.identity(request)["id"], task_id)

    @app.get("/api/v1/tasks/{task_id}/events")
    def events(task_id: str, request: Request):
        return runtime.tasks.events(auth.identity(request)["id"], task_id)

    @app.get("/api/v1/tasks/{task_id}/attempts")
    def attempts(task_id: str, request: Request):
        return runtime.tasks.attempts(auth.identity(request)["id"], task_id)

    @app.get("/api/v1/tasks/{task_id}/results")
    def results(task_id: str, request: Request):
        return runtime.tasks.document(auth.identity(request)["id"], task_id)

    return app


app = create_app()

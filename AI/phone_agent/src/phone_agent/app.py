"""REST API (contracts/io.md). 실행: uvicorn phone_agent.app:app --port 8090"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from .config import Settings
from .policy import PolicyError
from .schemas import BatchRequest, ConfirmRequest
from .service import CallService, build_service  # noqa: F401  (app.build_service)

TICK_SEC = 5


def _build_mcp(service: CallService):
    """mcp 패키지가 없으면 REST만 연다(오류 아님)."""
    try:
        from .mcp_server import build_mcp
    except ImportError:
        return None
    return build_mcp(service)


def _notify_channel(settings: Settings) -> str:
    if settings.kakao_access_token:
        return "kakao"
    if settings.mode == "demo" and settings.notify_number:
        return "sms"
    return "log"


def _error(status: int, code: str, message: Optional[str] = None, detail=None) -> JSONResponse:
    body: dict = {"error": code}
    if message:
        body["message"] = message
    if detail is not None:
        body["detail"] = detail
    return JSONResponse(body, status_code=status)


def _invalid(exc: ValidationError) -> JSONResponse:
    detail = [{"field": ".".join(str(p) for p in err["loc"]) or "body", "message": err["msg"]}
              for err in exc.errors()]
    return _error(422, "invalid_request", detail=detail)


async def _parse(request: Request, model: type[BaseModel]):
    try:
        data = json.loads(await request.body() or b"null")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, _error(422, "invalid_request", detail=[{"field": "body", "message": "JSON이 아닙니다"}])
    try:
        return model.model_validate(data), None
    except ValidationError as exc:
        return None, _invalid(exc)


def _scenarios(request: Request, settings: Settings) -> Optional[list[Optional[str]]]:
    header = request.headers.get("x-mock-scenario")
    if settings.mode != "mock" or not header:
        return None
    return [part.strip() or None for part in header.split(",")]


def create_app(service: Optional[CallService] = None, background: bool = True, with_mcp: bool = True) -> FastAPI:
    if service is None:
        service = build_service(Settings.from_env())
    settings = service.settings
    mcp = _build_mcp(service) if with_mcp else None

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        mcp_running = mcp.session_manager.run() if mcp else contextlib.nullcontext()
        await mcp_running.__aenter__()
        task = None
        if background:
            async def loop():
                while True:
                    await asyncio.sleep(TICK_SEC)
                    with contextlib.suppress(Exception):
                        await asyncio.to_thread(service.tick)
            task = asyncio.create_task(loop())
        try:
            yield
        finally:
            if task:
                task.cancel()
            await mcp_running.__aexit__(None, None, None)

    app = FastAPI(title="살구 전화 에이전트", version="0.3.1", lifespan=lifespan)
    app.state.service = service
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                       allow_methods=["GET", "POST", "DELETE"], allow_headers=["*"])
    if mcp:  # /mcp (Streamable HTTP). PHONE_AGENT_MCP_HOST=127.0.0.1이면 localhost로 온 요청만 받음
        app.router.routes.extend(mcp.streamable_http_app(host=settings.mcp_host).routes)

    @app.get("/api/health")
    def health():
        return {"ok": True, "mode": settings.mode, "notify": _notify_channel(settings),
                "mcp": mcp is not None, "registry_inbox": settings.mode == "demo" and bool(settings.registry_number)}

    @app.post("/api/broker-call-batches")
    async def create_batch(request: Request):
        body, error = await _parse(request, BatchRequest)
        if error:
            return error
        try:
            batch, created = await asyncio.to_thread(service.create_batch, body, _scenarios(request, settings))
        except PolicyError as exc:
            return JSONResponse(exc.body(), status_code=409)
        return JSONResponse(service.accepted(batch), status_code=201 if created else 200)

    @app.get("/api/broker-call-batches/{batch_id}")
    def get_inquiry_batch(batch_id: str):
        batch = service.get_batch(batch_id)
        if not batch or batch["kind"] != "inquiry":
            return _error(404, "not_found")
        return service.batch_result(batch)

    @app.post("/api/visit-confirmations")
    async def create_confirmations(request: Request):
        body, error = await _parse(request, ConfirmRequest)
        if error:
            return error
        try:
            batch, created = await asyncio.to_thread(service.create_confirmations, body, _scenarios(request, settings))
        except PolicyError as exc:
            return JSONResponse(exc.body(), status_code=409)
        return JSONResponse(service.accepted(batch), status_code=201 if created else 200)

    @app.get("/api/visit-confirmations/{batch_id}")
    def get_confirm_batch(batch_id: str):
        batch = service.get_batch(batch_id)
        if not batch or batch["kind"] != "confirm":
            return _error(404, "not_found")
        return service.batch_result(batch)

    @app.get("/api/broker-calls/{call_id}")
    def get_call(call_id: str):
        rec = service.get(call_id)
        if not rec:
            return _error(404, "not_found")
        return service.to_result(rec)

    return app


app = create_app()

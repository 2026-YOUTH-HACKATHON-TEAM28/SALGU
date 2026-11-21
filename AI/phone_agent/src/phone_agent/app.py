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
from .extract import LLMExtractor
from .policy import PolicyError
from .provider import KatProvider, MockProvider
from .schemas import BatchRequest
from .service import CallService, Store

TICK_SEC = 5


def build_service(settings: Settings) -> CallService:
    if settings.mode == "mock":
        return CallService(settings, MockProvider(), store=Store())
    return CallService(settings, KatProvider(settings), extractor=LLMExtractor(settings),
                       store=Store(settings.store_path))


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

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
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

    app = FastAPI(title="살구 전화 에이전트", version="0.3.1", lifespan=lifespan)
    app.state.service = service
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                       allow_methods=["GET", "POST", "DELETE"], allow_headers=["*"])

    @app.get("/api/health")
    def health():
        return {"ok": True, "mode": settings.mode, "notify": _notify_channel(settings),
                "mcp": False, "registry_inbox": settings.mode == "demo" and bool(settings.registry_number)}

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

    @app.get("/api/broker-calls/{call_id}")
    def get_call(call_id: str):
        rec = service.get(call_id)
        if not rec:
            return _error(404, "not_found")
        return service.to_result(rec)

    return app


app = create_app()

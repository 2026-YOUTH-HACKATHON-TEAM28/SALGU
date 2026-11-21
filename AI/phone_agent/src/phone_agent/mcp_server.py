"""MCP 입구 `mcp-phone` (specs/07-mcp-dedupe.md).

챗봇 LLM이 도구로 부를 수 있게 REST와 **같은 서비스**를 얇게 감싼다. 하루 제한·안전장치도 그대로 적용된다.
- 같은 서버의 /mcp (Streamable HTTP): app.create_app()이 붙인다. 기본으로 localhost로 온 요청만 받음
- stdio: python -m phone_agent.mcp_server
"""

from __future__ import annotations

import asyncio
from typing import Optional

from mcp.server.mcpserver import MCPServer

from .config import Settings
from .policy import PolicyError
from .schemas import BatchRequest, Broker, ConfirmRequest, Prep, Search, Share, VisitRequest
from .service import CallService, build_service

INSTRUCTIONS = (
    "살구 전화 에이전트. 사용자가 승인한 중개사무소에 AI가 전화해 방·조건·보여 줄 수 있는 시간을 묻고(call_brokers), "
    "사용자가 방과 시각을 승인하면 다시 전화해 방문을 확정한다(confirm_visits). 통화는 한 통에 1~2분이고 한 번에 한 통씩 "
    "걸리므로 get_call_results를 몇 초마다 불러 status가 done이 될 때까지 기다린다. 금액은 만원, 시각은 한국 시간 ISO."
)


def build_mcp(service: CallService) -> MCPServer:
    mcp = MCPServer("mcp-phone", instructions=INSTRUCTIONS, version="0.3.1")

    @mcp.tool()
    async def call_brokers(approval_id: str, search: Search, share: Share, brokers: list[Broker],
                           prep: Optional[Prep] = None, keep_transcript: bool = False) -> dict:
        """사용자가 승인한 중개사무소들에 문의 전화를 건다(POST /api/broker-call-batches).

        brokers 순서가 전화 순서(최대 10곳). 같은 approval_id로 다시 부르면 새로 걸지 않고 기존 묶음을 돌려준다.
        결과는 get_call_results(batch_id)로 본다.
        """
        try:
            request = BatchRequest(approval_id=approval_id, search=search, share=share, brokers=brokers,
                                   prep=prep or Prep(), keep_transcript=keep_transcript)
            batch, _ = await asyncio.to_thread(service.create_batch, request)
        except PolicyError as exc:
            return exc.body()
        except ValueError as exc:
            return {"error": "invalid_request", "detail": [{"field": "brokers", "message": str(exc)}]}
        return service.accepted(batch)

    @mcp.tool()
    async def get_call_results(batch_id: str) -> dict:
        """문의(bb_…)·확정(vb_…) 묶음의 진행과 결과. status가 done이 될 때까지 몇 초마다 부른다."""
        batch = await asyncio.to_thread(service.get_batch, batch_id)
        if not batch:
            return {"error": "not_found"}
        return service.batch_result(batch)

    @mcp.tool()
    async def confirm_visits(approval_id: str, visits: list[VisitRequest]) -> dict:
        """사용자가 승인한 방과 시각으로 확정 전화를 건다(POST /api/visit-confirmations).

        visits[].call_id는 그 방을 들은 문의 통화, listing_index는 그 통화의 몇 번째 방, at은 방문 시각.
        at이 중개사가 문의 때 된다고 한 시간 밖이면 걸지 않고 outside_broker_slots를 돌려준다.
        """
        try:
            request = ConfirmRequest(approval_id=approval_id, visits=visits)
            batch, _ = await asyncio.to_thread(service.create_confirmations, request)
        except PolicyError as exc:
            return exc.body()
        except ValueError as exc:
            return {"error": "invalid_request", "detail": [{"field": "visits", "message": str(exc)}]}
        return service.accepted(batch)

    return mcp


def main() -> None:
    build_mcp(build_service(Settings.from_env())).run("stdio")


if __name__ == "__main__":
    main()

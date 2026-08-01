"""OpenAI-compatible data plane."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from .. import providers
from ..db import get_session
from ..gateway import GatewayError, GatewayResult, RequestContext, gateway
from ..models import ModelEntry
from ..runtime import config as runtime_config
from ..schemas import ChatCompletionRequest
from ..security import Principal, allow_read, require_caller

router = APIRouter(tags=["inference"])


def _context(
    payload: ChatCompletionRequest, request: Request, principal: Principal
) -> RequestContext:
    return RequestContext(
        messages=payload.as_messages(),
        model=payload.model,
        policy=payload.policy,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
        top_p=payload.top_p,
        stop=payload.stop,
        presence_penalty=payload.presence_penalty,
        frequency_penalty=payload.frequency_penalty,
        response_format=payload.response_format,
        stream=payload.stream,
        cache=payload.cache,
        required_capabilities=payload.capabilities,
        subject=principal.subject,
        api_key_id=principal.key_id,
        client=principal.subject[:80],
        trace_id=getattr(request.state, "trace_id", ""),
        parent_span_id=getattr(request.state, "parent_span_id", None),
        route="/v1/chat/completions",
        redact=runtime_config.redact_pii,
    )


@router.post("/v1/chat/completions")
async def chat_completions(
    payload: ChatCompletionRequest,
    request: Request,
    principal: Principal = Depends(require_caller),
):
    """Drop-in replacement for the OpenAI endpoint.

    Extra fields (`policy`, `cache`, `capabilities`) are additive, and the
    response carries a `sentinel` block with the routing decision, cost and
    trace id. Existing OpenAI clients ignore both and keep working.
    """
    ctx = _context(payload, request, principal)

    if not payload.stream:
        try:
            result = await gateway.complete(ctx)
        except GatewayError as exc:
            raise HTTPException(
                exc.status_code, {"message": str(exc), "reason": exc.reason}
            ) from exc
        return result.openai_payload()

    async def event_stream() -> AsyncIterator[str]:
        created = int(time.time())
        chunk_id = ""
        model_slug = payload.model or "sentinel"
        try:
            async for kind, data in gateway.stream(ctx):
                if kind == "meta":
                    chunk_id = f"chatcmpl-{data['request_id']}"
                    model_slug = data["model"]
                    yield _sse(
                        {
                            "id": chunk_id,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": model_slug,
                            "choices": [
                                {"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}
                            ],
                            "sentinel": data,
                        }
                    )
                elif kind == "delta":
                    yield _sse(
                        {
                            "id": chunk_id,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": model_slug,
                            "choices": [
                                {"index": 0, "delta": {"content": data}, "finish_reason": None}
                            ],
                        }
                    )
                elif kind == "reasoning":
                    yield _sse(
                        {
                            "id": chunk_id,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": model_slug,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"reasoning_content": data},
                                    "finish_reason": None,
                                }
                            ],
                        }
                    )
                elif kind == "result":
                    result: GatewayResult = data
                    payload_out = result.openai_payload()
                    yield _sse(
                        {
                            "id": chunk_id or f"chatcmpl-{result.request_id}",
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": result.model.slug,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {},
                                    "finish_reason": result.finish_reason,
                                }
                            ],
                            "usage": payload_out["usage"],
                            "sentinel": payload_out["sentinel"],
                        }
                    )
        except GatewayError as exc:
            yield _sse(
                {"error": {"message": str(exc), "type": exc.reason, "code": exc.status_code}}
            )
        except Exception as exc:
            yield _sse({"error": {"message": f"gateway failure: {exc}", "type": "internal"}})
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


@router.get("/v1/models")
async def list_models(
    session: AsyncSession = Depends(get_session),
    _: Principal = Depends(allow_read),
) -> dict[str, Any]:
    """OpenAI-compatible catalogue, filtered to what can actually serve."""
    rows = list(
        (
            await session.execute(
                select(ModelEntry)
                .where(ModelEntry.enabled.is_(True))
                .order_by(ModelEntry.tier, ModelEntry.slug)
            )
        ).scalars()
    )
    return {
        "object": "list",
        "data": [
            {
                "id": row.slug,
                "object": "model",
                "created": int(row.created_at.timestamp()),
                "owned_by": row.provider,
                "sentinel": {
                    "display_name": row.display_name,
                    "tier": row.tier,
                    "context_window": row.context_window,
                    "max_output_tokens": row.max_output_tokens,
                    "capabilities": row.capabilities,
                    "input_price_per_mtok": row.input_price_per_mtok,
                    "output_price_per_mtok": row.output_price_per_mtok,
                    "routable": providers.available(row.provider),
                },
            }
            for row in rows
        ],
    }

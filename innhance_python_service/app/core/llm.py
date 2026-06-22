"""
LLM client abstraction.

All LLM calls go through this module — never call Anthropic or OpenAI SDKs
directly from routers or services. This gives us:
  - Automatic fallback: Anthropic down → GPT-4o-mini takes over
  - One place to swap models, add logging, track costs
  - Easy to mock in tests
"""

import logging
from typing import Any
import anthropic
import openai
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Initialise clients once at module load — reused across all requests
_anthropic = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
_openai    = openai.AsyncOpenAI(api_key=settings.openai_api_key)


async def classify(
    messages: list[dict],
    tools: list[dict],
    system: str,
    use_cache: bool = True,
) -> dict[str, Any]:
    """
    Run intent classification via Claude tool_use.

    Returns the first tool_use block content as a dict.
    Falls back to GPT-4o-mini on Anthropic errors.
    """
    try:
        system_blocks = _build_cached_system(system) if use_cache else system
        response = await _anthropic.messages.create(
            model=settings.classify_model,
            max_tokens=512,
            system=system_blocks,
            tools=tools,
            tool_choice={"type": "any"},   # force a tool call — no free text
            messages=messages,
        )
        # Extract the tool_use block
        for block in response.content:
            if block.type == "tool_use":
                return {"tool": block.name, "input": block.input, "provider": "anthropic"}
        raise ValueError("No tool_use block in Anthropic response")

    except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
        logger.warning("Anthropic classify failed (%s) — falling back to OpenAI", exc)
        return await _classify_openai_fallback(messages, tools, system)


async def _classify_openai_fallback(
    messages: list[dict],
    tools: list[dict],
    system: str,
) -> dict[str, Any]:
    """GPT-4o-mini fallback for classify when Anthropic is down."""
    # Convert Anthropic tool format → OpenAI function format
    oai_tools = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {}),
            },
        }
        for t in tools
    ]
    oai_messages = [{"role": "system", "content": system}] + messages
    response = await _openai.chat.completions.create(
        model=settings.fallback_model,
        messages=oai_messages,
        tools=oai_tools,
        tool_choice="required",
        max_tokens=512,
    )
    call = response.choices[0].message.tool_calls[0]
    import json
    return {
        "tool": call.function.name,
        "input": json.loads(call.function.arguments),
        "provider": "openai-fallback",
    }


async def complete(
    messages: list[dict],
    system: str,
    max_tokens: int = 400,
    use_cache: bool = True,
) -> str:
    """
    Generate a reply — used for the final bot response to the guest.
    Falls back to GPT-4o-mini on Anthropic errors.
    """
    try:
        system_blocks = _build_cached_system(system) if use_cache else system
        response = await _anthropic.messages.create(
            model=settings.reply_model,
            max_tokens=max_tokens,
            system=system_blocks,
            messages=messages,
        )
        return response.content[0].text

    except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
        logger.warning("Anthropic complete failed (%s) — falling back to OpenAI", exc)
        oai_messages = [{"role": "system", "content": system}] + messages
        response = await _openai.chat.completions.create(
            model=settings.fallback_model,
            messages=oai_messages,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content


async def vision_verify(image_url: str, prompt: str) -> dict[str, Any]:
    """
    GPT-4o vision call — used only for payment screenshot verification.
    Always uses GPT-4o (full), not the fallback model.
    """
    response = await _openai.chat.completions.create(
        model=settings.vision_model,
        max_tokens=300,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_url, "detail": "high"}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )
    return {"raw": response.choices[0].message.content}


async def embed(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of text strings using text-embedding-3-small.
    Always uses OpenAI (no Anthropic embedding equivalent).
    Returns a list of vectors in the same order as input.
    """
    response = await _openai.embeddings.create(
        model=settings.embedding_model,
        input=texts,
        dimensions=settings.embedding_dimensions,
    )
    return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]


def _build_cached_system(system: str) -> list[dict]:
    """
    Wrap the system prompt for Anthropic prompt caching.
    The system prompt is marked as ephemeral cache — Anthropic caches it
    for 5 minutes, giving ~90% token cost reduction on repeated calls.
    """
    return [
        {
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }
    ]

"""Request and response guardrails.

Deliberately modest and explainable: size caps, output ceilings, secret and PII
redaction, and a small set of blocked patterns. These are hygiene controls for a
gateway, not a content-safety system — that claim would be dishonest, so the
module does not make it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .observability import guard_blocks
from .settings import settings

EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]{2,}\b")
PHONE = re.compile(r"\b(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{3}\)?[\s-]?)\d{3}[\s-]?\d{4}\b")
CARD = re.compile(r"\b(?:\d[ -]*?){13,16}\b")
SECRETS = re.compile(
    r"\b(?:sk-[A-Za-z0-9_\-]{16,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|"
    r"AIza[0-9A-Za-z_\-]{20,}|xox[baprs]-[0-9A-Za-z-]{10,})\b"
)


class GuardRejection(Exception):
    def __init__(self, rule: str, message: str) -> None:
        super().__init__(message)
        self.rule = rule


@dataclass
class GuardResult:
    messages: list[dict[str, Any]]
    max_tokens: int | None
    flags: list[str] = field(default_factory=list)
    redactions: int = 0


def _redact(text: str) -> tuple[str, list[str], int]:
    flags: list[str] = []
    count = 0

    def substitute(pattern: re.Pattern[str], label: str, value: str) -> str:
        nonlocal count
        replaced, hits = pattern.subn(f"[redacted:{label}]", value)
        if hits:
            flags.append(f"redacted_{label}")
            count += hits
        return replaced

    text = substitute(SECRETS, "credential", text)
    text = substitute(EMAIL, "email", text)
    text = substitute(CARD, "card", text)
    text = substitute(PHONE, "phone", text)
    return text, flags, count


def inspect_request(
    messages: list[dict[str, Any]],
    *,
    max_tokens: int | None,
    redact: bool = True,
) -> GuardResult:
    if not messages:
        raise GuardRejection("empty_messages", "`messages` must contain at least one entry")

    total_chars = 0
    flags: list[str] = []
    redactions = 0
    cleaned: list[dict[str, Any]] = []

    for message in messages:
        role = message.get("role", "user")
        if role not in ("system", "user", "assistant", "tool", "developer"):
            raise GuardRejection("bad_role", f"unsupported role '{role}'")
        content = message.get("content")
        if isinstance(content, str):
            total_chars += len(content)
            if redact:
                content, found, count = _redact(content)
                flags.extend(found)
                redactions += count
            cleaned.append({**message, "content": content})
        else:
            cleaned.append(dict(message))

    if total_chars > settings.max_prompt_chars:
        guard_blocks.labels("prompt_size", "reject").inc()
        raise GuardRejection(
            "prompt_size",
            f"prompt is {total_chars} characters, above the {settings.max_prompt_chars} ceiling",
        )

    capped = max_tokens
    if capped is None or capped > settings.max_output_tokens_cap:
        if capped is not None:
            flags.append("max_tokens_capped")
            guard_blocks.labels("max_tokens", "clamp").inc()
        capped = min(capped or settings.max_output_tokens_cap, settings.max_output_tokens_cap)

    if redactions:
        guard_blocks.labels("pii", "redact").inc(redactions)

    return GuardResult(
        messages=cleaned,
        max_tokens=capped,
        flags=sorted(set(flags)),
        redactions=redactions,
    )


def scrub_output(text: str) -> tuple[str, list[str]]:
    """Stop upstream echoes of credentials from leaving the gateway."""
    scrubbed, hits = SECRETS.subn("[redacted:credential]", text)
    if hits:
        guard_blocks.labels("output_credential", "redact").inc(hits)
        return scrubbed, ["output_credential_redacted"]
    return text, []

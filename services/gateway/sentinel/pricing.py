"""Token accounting and the seed price book.

Cost is computed from the catalogue's per-million-token prices, so every number
the dashboard shows is traceable to an editable row rather than a constant
buried in code.

Seed prices for DeepSeek reflect the provider's published rates at the time of
writing (flash tier $0.14 in / $0.28 out per MTok, pro tier $1.74 / $3.48, cache
hits billed at a tenth of the input rate). Verify them against
https://api-docs.deepseek.com/quick_start/pricing before trusting cost figures —
`price_verified_at` and `price_source` on each catalogue row exist for exactly
that reason.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

MTOK = 1_000_000

DEEPSEEK_PRICE_SOURCE = "https://api-docs.deepseek.com/quick_start/pricing"


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def estimate_tokens(text: str) -> int:
    """Heuristic token count used only when an upstream omits usage.

    Roughly 4 characters per token for English prose, with a floor of one token
    per whitespace-delimited word so short strings are not undercounted. Exact
    counts always come from the provider when reported.
    """
    if not text:
        return 0
    words = len(text.split())
    chars = len(text)
    return max(1, int(max(words, math.ceil(chars / 4))))


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    total = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):  # multimodal content blocks
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    total += estimate_tokens(block["text"])
        # Per-message envelope overhead (role, delimiters).
        total += 4
    return total


def compute_cost(
    *,
    prompt_tokens: int,
    completion_tokens: int,
    input_price_per_mtok: float,
    output_price_per_mtok: float,
    cached_prompt_tokens: int = 0,
    cached_input_price_per_mtok: float = 0.0,
) -> float:
    billable_prompt = max(0, prompt_tokens - cached_prompt_tokens)
    cost = (billable_prompt / MTOK) * input_price_per_mtok
    cost += (cached_prompt_tokens / MTOK) * cached_input_price_per_mtok
    cost += (completion_tokens / MTOK) * output_price_per_mtok
    return round(cost, 8)


# --------------------------------------------------------------------------- #
# prompt complexity -> minimum capability tier
# --------------------------------------------------------------------------- #
_REASONING_HINTS = re.compile(
    r"\b(prove|derive|step[- ]by[- ]step|reason|analy[sz]e|optimi[sz]e|refactor|"
    r"architect|trade[- ]?off|complexity|algorithm|theorem|integral|regression|"
    r"debug|root cause|migrate|design a|explain why)\b",
    re.IGNORECASE,
)
_CODE_HINTS = re.compile(r"```|\bdef \w|\bclass \w|SELECT .* FROM|import \w+|=>|</\w+>")
_TRIVIAL_HINTS = re.compile(
    r"^\s*(hi|hey|hello|thanks|thank you|ok|okay|yes|no|ping|status)\b", re.IGNORECASE
)

TIER_LABELS = {1: "trivial", 2: "standard", 3: "complex", 4: "frontier"}


def classify_prompt(messages: list[dict[str, Any]]) -> tuple[str, int]:
    """Cheap, explainable complexity classifier.

    Deliberately rule-based: the router must be auditable, and paying an LLM to
    decide which LLM to pay is a poor trade at the gateway hot path.
    """
    text = "\n".join(
        m.get("content", "") if isinstance(m.get("content"), str) else ""
        for m in messages
        if m.get("role") != "system"
    ).strip()

    length = len(text)
    score = 1

    if length > 400:
        score = max(score, 2)
    if length > 2000:
        score = max(score, 3)
    if length > 8000:
        score = max(score, 4)
    if _CODE_HINTS.search(text):
        score = max(score, 3)
    if _REASONING_HINTS.search(text):
        score = max(score, 3)
    if _REASONING_HINTS.search(text) and length > 1200:
        score = 4
    if length < 60 and _TRIVIAL_HINTS.match(text):
        score = 1

    return TIER_LABELS.get(score, "standard"), score


# --------------------------------------------------------------------------- #
# seed catalogue
# --------------------------------------------------------------------------- #
def seed_catalogue() -> list[dict[str, Any]]:
    """Simulated tiers are always present; live rows are enabled when keyed.

    The simulated provider is not a stub for missing functionality — it is what
    makes load tests, CI and the public demo reproducible and free. It streams
    tokens with configurable time-to-first-token and throughput.
    """
    return [
        # --- simulated (always available, zero cost, deterministic) ----------
        {
            "slug": "sim-nano",
            "display_name": "Sentinel Nano (simulated)",
            "provider": "simulated",
            "upstream_model": "nano",
            "tier": 1,
            "context_window": 16_384,
            "max_output_tokens": 1024,
            "capabilities": ["chat"],
            "input_price_per_mtok": 0.05,
            "output_price_per_mtok": 0.10,
            "cached_input_price_per_mtok": 0.005,
            "expected_ttft_ms": 90.0,
            "expected_tokens_per_second": 220.0,
            "notes": "Fast, cheap, short answers. Handles trivial traffic.",
        },
        {
            "slug": "sim-small",
            "display_name": "Sentinel Small (simulated)",
            "provider": "simulated",
            "upstream_model": "small",
            "tier": 2,
            "context_window": 32_768,
            "max_output_tokens": 2048,
            "capabilities": ["chat", "json"],
            "input_price_per_mtok": 0.20,
            "output_price_per_mtok": 0.60,
            "cached_input_price_per_mtok": 0.02,
            "expected_ttft_ms": 190.0,
            "expected_tokens_per_second": 130.0,
            "notes": "Default workhorse for standard prompts.",
        },
        {
            "slug": "sim-large",
            "display_name": "Sentinel Large (simulated)",
            "provider": "simulated",
            "upstream_model": "large",
            "tier": 3,
            "context_window": 131_072,
            "max_output_tokens": 4096,
            "capabilities": ["chat", "json", "tools", "reasoning"],
            "input_price_per_mtok": 3.00,
            "output_price_per_mtok": 12.00,
            "cached_input_price_per_mtok": 0.30,
            "expected_ttft_ms": 620.0,
            "expected_tokens_per_second": 55.0,
            "notes": "Expensive tier used to show what routing avoids.",
        },
        {
            "slug": "sim-frontier",
            "display_name": "Sentinel Frontier (simulated)",
            "provider": "simulated",
            "upstream_model": "frontier",
            "tier": 4,
            "context_window": 200_000,
            "max_output_tokens": 8192,
            "capabilities": ["chat", "json", "tools", "reasoning", "long-context"],
            "input_price_per_mtok": 10.00,
            "output_price_per_mtok": 40.00,
            "cached_input_price_per_mtok": 1.00,
            "expected_ttft_ms": 1150.0,
            "expected_tokens_per_second": 32.0,
            "simulated_failure_rate": 0.01,
            "notes": "Premium baseline for cost-saving comparisons.",
        },
        # --- DeepSeek (enabled when DEEPSEEK_API_KEY is present) ------------
        {
            "slug": "deepseek-chat",
            "display_name": "DeepSeek Chat",
            "provider": "deepseek",
            "upstream_model": "deepseek-chat",
            "tier": 3,
            "context_window": 65_536,
            "max_output_tokens": 8192,
            "capabilities": ["chat", "json", "tools"],
            "input_price_per_mtok": 0.14,
            "output_price_per_mtok": 0.28,
            "cached_input_price_per_mtok": 0.014,
            "expected_ttft_ms": 700.0,
            "expected_tokens_per_second": 45.0,
            "price_source": DEEPSEEK_PRICE_SOURCE,
            "notes": "Live upstream. Flash-tier pricing; confirm on the pricing page.",
        },
        {
            "slug": "deepseek-reasoner",
            "display_name": "DeepSeek Reasoner",
            "provider": "deepseek",
            "upstream_model": "deepseek-reasoner",
            "tier": 4,
            "context_window": 65_536,
            "max_output_tokens": 8192,
            "capabilities": ["chat", "reasoning", "long-context"],
            "input_price_per_mtok": 1.74,
            "output_price_per_mtok": 3.48,
            "cached_input_price_per_mtok": 0.174,
            "expected_ttft_ms": 1800.0,
            "expected_tokens_per_second": 28.0,
            "price_source": DEEPSEEK_PRICE_SOURCE,
            "notes": "Live upstream. Pro-tier pricing; confirm on the pricing page.",
        },
    ]

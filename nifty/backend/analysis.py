"""
Claude advisory layer.

IMPORTANT: This NEVER places orders. It takes the market context you give it
(spot, IV, your candidate strike, your stated thesis) and returns a structured
read — what supports the trade, what argues against it, and which of YOUR
pre-defined rules apply. It is a second opinion, not a signal generator.

The actual decision and the actual order stay with you / your coded rules.
"""
import json
import logging

try:
    import anthropic
except ImportError:  # allow running without advisory deps installed
    anthropic = None

from config import settings

log = logging.getLogger("analysis")

SYSTEM = """You are a disciplined options-trading risk reviewer for NIFTY index
options (CE/PE buying, intraday). You are NOT a directional oracle and you must
not pretend to predict the market. Given a context blob (which may include
spot range, EMA/RSI/VWAP/ATR, short-term momentum, and CE/PE premiums), respond
ONLY with JSON:

{
  "bias_read": "neutral|supportive|cautionary",
  "supports": ["..."],        // factors that support the user's thesis
  "against": ["..."],         // factors that argue against it
  "theta_iv_note": "...",     // decay / IV-compression risk for this premium
  "checklist": ["..."],       // which of the user's stated rules are/aren't met
  "entry_checks": ["..."],    // concrete confirmations to wait for (no prices invented)
  "verdict": "consider|wait|skip",
  "one_liner": "..."          // single blunt sentence
}

Never invent prices. Never say 'buy now'. If data is thin, prefer 'wait'."""


def review_setup(context: dict) -> dict:
    """
    context example:
    {
      "spot": 24500, "candidate": "24600CE", "premium": 85, "iv": 12.3,
      "thesis": "expecting breakout above 24550 on volume",
      "rules": ["only trade 09:30-14:30", "skip if IV > 20", "max 1% risk"]
    }
    """
    if not settings.anthropic_key:
        return {"error": "ANTHROPIC_API_KEY not set"}
    if anthropic is None:
        return {"error": "anthropic library not installed (pip install -r requirements.txt)"}

    client = anthropic.Anthropic(api_key=settings.anthropic_key)
    msg = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=700,
        system=SYSTEM,
        messages=[{"role": "user", "content": json.dumps(context)}],
    )
    text = "".join(b.text for b in msg.content if b.type == "text")
    text = text.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text, "error": "model did not return clean JSON"}

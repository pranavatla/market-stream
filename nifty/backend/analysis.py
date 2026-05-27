"""
Advisory layer (read-only).

Runs structured trade review prompts against one or more LLM providers.
Never places orders and never bypasses risk checks.
"""
import json
import logging
import time
from collections import deque
from threading import Lock

import requests

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
  "supports": ["..."],
  "against": ["..."],
  "theta_iv_note": "...",
  "checklist": ["..."],
  "entry_checks": ["..."],
  "verdict": "consider|wait|skip",
  "one_liner": "..."
}

Never invent prices. Never say 'buy now'. If data is thin, prefer 'wait'."""

_AB_LOCK = Lock()
_AB_HISTORY: deque[dict] = deque(maxlen=200)


def _strip_json_text(text: str) -> str:
    return text.replace("```json", "").replace("```", "").strip()


def _safe_parse_json(text: str) -> dict:
    cleaned = _strip_json_text(text)
    return json.loads(cleaned)


def _run_claude(context: dict) -> dict:
    if not settings.anthropic_key:
        return {"error": "ANTHROPIC_API_KEY not set"}
    if anthropic is None:
        return {"error": "anthropic library not installed (pip install -r requirements.txt)"}

    t0 = time.perf_counter()
    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_key)
        msg = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=700,
            system=SYSTEM,
            messages=[{"role": "user", "content": json.dumps(context)}],
        )
        text = "".join(b.text for b in msg.content if b.type == "text")
        out = _safe_parse_json(text)
        return {
            "ok": True,
            "provider": "claude",
            "model": settings.anthropic_model,
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "usage": {
                "input_tokens": getattr(msg, "usage", None).input_tokens if getattr(msg, "usage", None) else None,
                "output_tokens": getattr(msg, "usage", None).output_tokens if getattr(msg, "usage", None) else None,
            },
            "advice": out,
        }
    except Exception as e:
        return {
            "ok": False,
            "provider": "claude",
            "model": settings.anthropic_model,
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "error": str(e),
        }


def _run_gemini(context: dict) -> dict:
    if not settings.gemini_key:
        return {"error": "GEMINI_API_KEY not set"}

    t0 = time.perf_counter()
    model = settings.gemini_model
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": json.dumps(context)}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 900,
            "responseMimeType": "application/json",
        },
    }
    try:
        r = requests.post(url, params={"key": settings.gemini_key}, json=payload, timeout=45)
        r.raise_for_status()
        data = r.json()
        parts = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [])
        )
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        out = _safe_parse_json(text)
        usage = data.get("usageMetadata", {})
        return {
            "ok": True,
            "provider": "gemini",
            "model": model,
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "usage": {
                "input_tokens": usage.get("promptTokenCount"),
                "output_tokens": usage.get("candidatesTokenCount"),
            },
            "advice": out,
        }
    except Exception as e:
        return {
            "ok": False,
            "provider": "gemini",
            "model": model,
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "error": str(e),
        }


def _score_advice(run: dict) -> float:
    if not run.get("ok"):
        return -999.0
    advice = run.get("advice", {}) or {}
    score = 0.0
    verdict = str(advice.get("verdict", "")).strip().lower()
    if verdict in {"consider", "wait", "skip"}:
        score += 15.0
    else:
        score -= 20.0
    for key in ("supports", "against", "checklist", "entry_checks"):
        val = advice.get(key)
        if isinstance(val, list):
            score += min(len(val), 5) * 2.5
        else:
            score -= 5.0
    one_liner = advice.get("one_liner")
    if isinstance(one_liner, str) and len(one_liner.strip()) >= 8:
        score += 8.0
    else:
        score -= 8.0
    theta_note = advice.get("theta_iv_note")
    if isinstance(theta_note, str) and len(theta_note.strip()) >= 8:
        score += 6.0
    else:
        score -= 4.0
    bias = str(advice.get("bias_read", "")).strip().lower()
    if bias in {"neutral", "supportive", "cautionary"}:
        score += 4.0
    latency_ms = int(run.get("latency_ms", 0) or 0)
    score -= min(latency_ms / 450.0, 12.0)
    return round(score, 2)


def _record_ab(candidate_runs: list[dict], winner: str) -> None:
    with _AB_LOCK:
        _AB_HISTORY.append(
            {
                "ts": int(time.time()),
                "winner": winner,
                "runs": candidate_runs,
            }
        )


def advisory_stats() -> dict:
    with _AB_LOCK:
        rows = list(_AB_HISTORY)
    totals = {"claude": 0, "gemini": 0, "tie": 0}
    lat = {"claude": [], "gemini": []}
    scores = {"claude": [], "gemini": []}
    for row in rows:
        w = row.get("winner", "tie")
        totals[w if w in totals else "tie"] += 1
        for run in row.get("runs", []):
            name = run.get("provider")
            if name not in ("claude", "gemini"):
                continue
            if run.get("latency_ms") is not None:
                lat[name].append(int(run["latency_ms"]))
            if run.get("score") is not None:
                scores[name].append(float(run["score"]))
    return {
        "samples": len(rows),
        "wins": totals,
        "latency_ms_avg": {
            "claude": round(sum(lat["claude"]) / len(lat["claude"]), 1) if lat["claude"] else None,
            "gemini": round(sum(lat["gemini"]) / len(lat["gemini"]), 1) if lat["gemini"] else None,
        },
        "score_avg": {
            "claude": round(sum(scores["claude"]) / len(scores["claude"]), 2) if scores["claude"] else None,
            "gemini": round(sum(scores["gemini"]) / len(scores["gemini"]), 2) if scores["gemini"] else None,
        },
        "last_winner": rows[-1]["winner"] if rows else None,
    }


def review_setup(context: dict) -> dict:
    """Back-compat: single model according to ADVISORY_PRIMARY or fallback to auto."""
    pref = (settings.advisory_primary or "auto").strip().lower()
    if pref == "claude":
        run = _run_claude(context)
        if not run.get("ok"):
            return {"error": run.get("error", "Claude request failed")}
        out = run["advice"]
        out["_model"] = {"provider": "claude", "model": run.get("model"), "latency_ms": run.get("latency_ms")}
        return out
    if pref == "gemini":
        run = _run_gemini(context)
        if not run.get("ok"):
            return {"error": run.get("error", "Gemini request failed")}
        out = run["advice"]
        out["_model"] = {"provider": "gemini", "model": run.get("model"), "latency_ms": run.get("latency_ms")}
        return out
    return review_setup_auto(context)["advice"]


def review_setup_auto(context: dict) -> dict:
    """
    Run Claude and Gemini on the same context, score both, and pick the better output.
    If only one provider is configured, it becomes the winner by default.
    """
    runs = []
    c = _run_claude(context)
    if c:
        c["score"] = _score_advice(c) if c.get("ok") else -999.0
        runs.append(c)
    g = _run_gemini(context)
    if g:
        g["score"] = _score_advice(g) if g.get("ok") else -999.0
        runs.append(g)

    ok_runs = [r for r in runs if r.get("ok")]
    if not ok_runs:
        errors = {r.get("provider", "unknown"): r.get("error", "not available") for r in runs}
        return {"error": f"No advisory model succeeded: {errors}", "runs": runs}

    ok_runs.sort(key=lambda r: (r.get("score", -999.0), -(r.get("latency_ms") or 10**9)), reverse=True)
    best = ok_runs[0]
    winner = best.get("provider", "tie")
    # tie detection
    if len(ok_runs) > 1 and abs(float(ok_runs[0].get("score", 0.0)) - float(ok_runs[1].get("score", 0.0))) < 0.35:
        winner = "tie"

    _record_ab(runs, winner)
    advice = dict(best["advice"])
    advice["_model"] = {
        "provider": best.get("provider"),
        "model": best.get("model"),
        "latency_ms": best.get("latency_ms"),
        "score": best.get("score"),
    }
    return {
        "winner": winner,
        "advice": advice,
        "runs": [
            {
                "provider": r.get("provider"),
                "model": r.get("model"),
                "ok": r.get("ok"),
                "score": r.get("score"),
                "latency_ms": r.get("latency_ms"),
                "error": r.get("error"),
                "usage": r.get("usage"),
            }
            for r in runs
        ],
        "stats": advisory_stats(),
    }

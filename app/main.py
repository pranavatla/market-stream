import asyncio
import json
import time
from contextlib import asynccontextmanager
from typing import Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from app.models import Tick, AlertConfig, AlertDirection
from app.market_feed import MockFeed
from app.storage import TickStore
from app.alerts import AlertEngine
from app.config import SYMBOLS, HOST, PORT


# --- Global state ---
feed = MockFeed()
store = TickStore()
alert_engine = AlertEngine()
ws_clients: Set[WebSocket] = set()
feed_task = None


async def broadcast(message: dict):
    """Fan out a JSON message to all connected WebSocket clients."""
    dead = set()
    payload = json.dumps(message)
    for ws in ws_clients:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.add(ws)
    ws_clients.difference_update(dead)


async def run_feed():
    """Core feed loop: generate ticks → store → broadcast → check alerts."""
    batch = []
    batch_interval = 5.0  # flush to DB every 5s
    last_flush = time.time()

    async for tick in feed.stream():
        # Broadcast immediately (low latency to clients)
        await broadcast({
            "type": "tick",
            "data": tick.model_dump(),
        })

        # Batch for storage
        batch.append(tick)
        if time.time() - last_flush >= batch_interval:
            await store.insert_batch(batch)
            batch.clear()
            last_flush = time.time()

        # Evaluate alerts
        events = alert_engine.evaluate(tick)
        for evt in events:
            await broadcast({
                "type": "alert",
                "data": evt.model_dump(),
            })


@asynccontextmanager
async def lifespan(app: FastAPI):
    global feed_task
    await store.init()
    feed_task = asyncio.create_task(run_feed())
    yield
    feed.stop()
    feed_task.cancel()
    await store.close()


app = FastAPI(
    title="market-stream",
    description="Real-time Market Data Streaming Service",
    version="1.0.0",
    lifespan=lifespan,
)

# --- Static files ---
app.mount("/static", StaticFiles(directory="frontend"), name="static")


# --- REST endpoints ---

@app.get("/")
async def index():
    return FileResponse("frontend/index.html")


@app.get("/api/symbols")
async def get_symbols():
    return {"symbols": SYMBOLS}


@app.get("/api/summary/{symbol}")
async def get_summary(symbol: str):
    summary = await store.get_summary(symbol.upper())
    if not summary:
        return JSONResponse({"error": "No data yet"}, status_code=404)
    return summary.model_dump()


@app.get("/api/history/{symbol}")
async def get_history(symbol: str, minutes: int = Query(default=60, le=1440)):
    since = time.time() - (minutes * 60)
    ticks = await store.get_history(symbol.upper(), since=since, limit=2000)
    return {"symbol": symbol.upper(), "count": len(ticks), "ticks": [t.model_dump() for t in ticks]}


# --- Alert CRUD ---

@app.get("/api/alerts")
async def list_alerts():
    return {"alerts": [a.model_dump() for a in alert_engine.list_alerts()]}


@app.post("/api/alerts")
async def create_alert(config: AlertConfig):
    alert = alert_engine.add(config)
    return alert.model_dump()


@app.delete("/api/alerts/{alert_id}")
async def delete_alert(alert_id: str):
    if alert_engine.remove(alert_id):
        return {"deleted": alert_id}
    return JSONResponse({"error": "Not found"}, status_code=404)


# --- WebSocket ---

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    try:
        while True:
            # Keep connection alive; client can send ping/commands
            data = await ws.receive_text()
            # Could handle subscribe/unsubscribe per symbol here
    except WebSocketDisconnect:
        ws_clients.discard(ws)
    except Exception:
        ws_clients.discard(ws)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=True)

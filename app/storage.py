import os
import time
from typing import List, Optional
from app.models import Tick, TickSummary


class TickStore:
    """
    Dual-backend tick storage.
    - DB_TYPE=postgres → asyncpg + RDS PostgreSQL (production)
    - DB_TYPE=sqlite   → aiosqlite (local dev, default)
    """

    def __init__(self):
        self.db_type = os.getenv("DB_TYPE", "sqlite")
        self._db = None

    async def init(self):
        if self.db_type == "postgres":
            await self._init_postgres()
        else:
            await self._init_sqlite()

    # =========================================================================
    # POSTGRESQL
    # =========================================================================
    async def _init_postgres(self):
        import asyncpg

        self._db = await asyncpg.create_pool(
            host=os.getenv("DB_HOST"),
            port=int(os.getenv("DB_PORT", "5432")),
            database=os.getenv("DB_NAME", "marketstream"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            min_size=2,
            max_size=10,
        )
        async with self._db.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ticks (
                    id BIGSERIAL PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    price DOUBLE PRECISION NOT NULL,
                    open DOUBLE PRECISION NOT NULL,
                    high DOUBLE PRECISION NOT NULL,
                    low DOUBLE PRECISION NOT NULL,
                    volume INTEGER NOT NULL,
                    timestamp DOUBLE PRECISION NOT NULL
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ticks_symbol_ts
                ON ticks (symbol, timestamp)
            """)

    # =========================================================================
    # SQLITE
    # =========================================================================
    async def _init_sqlite(self):
        import aiosqlite

        db_path = os.getenv("DB_PATH", "data/ticks.db")
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._db = await aiosqlite.connect(db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS ticks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                price REAL NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                volume INTEGER NOT NULL,
                timestamp REAL NOT NULL
            )
        """)
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_ticks_symbol_ts
            ON ticks (symbol, timestamp)
        """)
        await self._db.commit()

    # =========================================================================
    # INSERT
    # =========================================================================
    async def insert(self, tick: Tick):
        await self.insert_batch([tick])

    async def insert_batch(self, ticks: List[Tick]):
        if not ticks:
            return

        if self.db_type == "postgres":
            async with self._db.acquire() as conn:
                await conn.executemany(
                    "INSERT INTO ticks (symbol, price, open, high, low, volume, timestamp) VALUES ($1, $2, $3, $4, $5, $6, $7)",
                    [(t.symbol, t.price, t.open, t.high, t.low, t.volume, t.timestamp) for t in ticks],
                )
        else:
            await self._db.executemany(
                "INSERT INTO ticks (symbol, price, open, high, low, volume, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(t.symbol, t.price, t.open, t.high, t.low, t.volume, t.timestamp) for t in ticks],
            )
            await self._db.commit()

    # =========================================================================
    # QUERY
    # =========================================================================
    async def get_history(self, symbol: str, since: Optional[float] = None, limit: int = 500) -> List[Tick]:
        if since is None:
            since = time.time() - 3600

        if self.db_type == "postgres":
            async with self._db.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT symbol, price, open, high, low, volume, timestamp FROM ticks WHERE symbol = $1 AND timestamp >= $2 ORDER BY timestamp ASC LIMIT $3",
                    symbol, since, limit,
                )
        else:
            rows = await self._db.execute_fetchall(
                "SELECT symbol, price, open, high, low, volume, timestamp FROM ticks WHERE symbol = ? AND timestamp >= ? ORDER BY timestamp ASC LIMIT ?",
                (symbol, since, limit),
            )

        return [Tick(symbol=r[0], price=r[1], open=r[2], high=r[3], low=r[4], volume=r[5], timestamp=r[6]) for r in rows]

    async def get_summary(self, symbol: str) -> Optional[TickSummary]:
        today_start = time.time() - 86400

        if self.db_type == "postgres":
            async with self._db.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT
                        symbol,
                        (SELECT price FROM ticks WHERE symbol = $1 AND timestamp >= $2 ORDER BY timestamp DESC LIMIT 1) as last_price,
                        (SELECT price FROM ticks WHERE symbol = $1 AND timestamp >= $2 ORDER BY timestamp ASC LIMIT 1) as open_price,
                        MAX(price) as high,
                        MIN(price) as low,
                        SUM(volume) as total_volume,
                        COUNT(*) as tick_count
                    FROM ticks WHERE symbol = $1 AND timestamp >= $2
                    GROUP BY symbol
                """, symbol, today_start)
                if not row or row["last_price"] is None:
                    return None
                last = row["last_price"]
                opn = row["open_price"]
                change = last - opn
                change_pct = (change / opn * 100) if opn else 0
                return TickSummary(
                    symbol=row["symbol"], last_price=last, open=opn,
                    high=row["high"], low=row["low"],
                    volume=int(row["total_volume"] or 0),
                    change=round(change, 2), change_pct=round(change_pct, 2),
                    tick_count=row["tick_count"],
                )
        else:
            rows = await self._db.execute_fetchall(
                """SELECT symbol,
                    (SELECT price FROM ticks WHERE symbol = ? AND timestamp >= ? ORDER BY timestamp DESC LIMIT 1),
                    (SELECT price FROM ticks WHERE symbol = ? AND timestamp >= ? ORDER BY timestamp ASC LIMIT 1),
                    MAX(price), MIN(price), SUM(volume), COUNT(*)
                FROM ticks WHERE symbol = ? AND timestamp >= ?""",
                (symbol, today_start, symbol, today_start, symbol, today_start),
            )
            if not rows or rows[0][1] is None:
                return None
            r = rows[0]
            last = r[1]
            opn = r[2]
            change = last - opn
            change_pct = (change / opn * 100) if opn else 0
            return TickSummary(
                symbol=r[0], last_price=last, open=opn,
                high=r[3], low=r[4], volume=int(r[5] or 0),
                change=round(change, 2), change_pct=round(change_pct, 2),
                tick_count=r[6],
            )

    async def close(self):
        if self._db:
            if self.db_type == "postgres":
                await self._db.close()
            else:
                await self._db.close()

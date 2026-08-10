import os

# Feed
FEED_INTERVAL_MS = int(os.getenv("FEED_INTERVAL_MS", "500"))  # tick every 500ms
SYMBOLS = os.getenv("SYMBOLS", "NIFTY50,SENSEX,BANKNIFTY,RELIANCE,TCS").split(",")

# Mock seed prices (realistic INR values)
SEED_PRICES = {
    "NIFTY50": 24850.0,
    "SENSEX": 81200.0,
    "BANKNIFTY": 52400.0,
    "RELIANCE": 2950.0,
    "TCS": 3720.0,
}

# Storage
DB_PATH = os.getenv("DB_PATH", "data/ticks.db")

# Server
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

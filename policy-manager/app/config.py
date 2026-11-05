import os
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://llnet:llnet@localhost:5432/llnet")
RYU_URL = os.environ.get("RYU_URL", "http://ryu-controller:8080").rstrip("/")

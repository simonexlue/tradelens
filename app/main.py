from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .core.config import settings
from .api.routes import uploads, trades, images

app = FastAPI(title="TradeLens Backend (Phase 3)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.FRONTEND_ORIGINS,
    allow_origin_regex=r"^https?://localhost(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

app.include_router(uploads.router)
app.include_router(trades.router)
app.include_router(images.router)

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/")
def root():
    return {"message": "TradeLens backend is running"}
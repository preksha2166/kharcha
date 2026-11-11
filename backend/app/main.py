"""FastAPI app: creates tables, seeds the demo student, runs the daily check every hour."""

import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session

from app import clock
from app.api import router
from app.config import settings
from app.db import engine, init_db
from app.seed.demo_data import get_demo_user, seed_demo
from app.services.daily import check_all_users

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("kharcha")


def _hourly_check() -> None:
    try:
        with Session(engine) as session:
            check_all_users(session, clock.today(session))
    except Exception:
        log.exception("Daily check failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    with Session(engine) as session:
        if settings.demo_mode and get_demo_user(session) is None:
            seed_demo(session, clock.real_today())
    # Catch up on anything missed while the server was off, for every student.
    _hourly_check()
    log.info("Kharcha started. PayPal mode: %s. AI: %s.", settings.paypal_mode, "on" if settings.ai_enabled else "off")
    scheduler = BackgroundScheduler(timezone=settings.student_timezone)
    scheduler.add_job(_hourly_check, "interval", hours=1, id="daily-check")
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="Kharcha API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/")
def root():
    return {"name": "Kharcha API", "docs": "/docs", "health": "/api/health"}

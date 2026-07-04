from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.telegram_webhook import router as telegram_webhook_router
from app.bot.telegram.runtime import setup_telegram_webhook, shutdown_telegram_bot
from app.config import settings
from app.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    del app
    await setup_telegram_webhook()
    yield
    await shutdown_telegram_bot()
    await engine.dispose()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(health_router)
app.include_router(telegram_webhook_router)

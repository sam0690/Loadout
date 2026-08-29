"""FastAPI app. 2.1 mounts only the event route; auth and the rest arrive in 2.2."""

from fastapi import FastAPI

from api.auth import router as auth_router
from api.events import router as events_router

app = FastAPI(title="Loadout", version="0.1.0")
app.include_router(auth_router)
app.include_router(events_router)

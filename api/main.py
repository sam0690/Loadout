"""FastAPI app. 2.1 mounts only the event route; auth and the rest arrive in 2.2."""

from fastapi import FastAPI

from api.events import router

app = FastAPI(title="Loadout", version="0.1.0")
app.include_router(router)

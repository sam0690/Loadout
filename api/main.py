"""FastAPI app. 2.1 mounts only the event route; auth and the rest arrive in 2.2."""

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.contexts import router as contexts_router
from api.core import errors
from api.events import router as events_router
from api.plans import router as plans_router
from api.routers.auth import router as auth_router

# Without this the magic link is dropped on the floor. It is emitted at INFO on the
# "loadout" logger, and Python's default root level is WARNING, so the one delivery
# mechanism auth has (D23) produced nothing at all until this was added.
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logging.getLogger("loadout").setLevel(logging.INFO)

app = FastAPI(title="Loadout", version="0.1.0")

# The PWA is served from a different origin than the API, so without this the browser
# refuses every request. Explicit origins rather than "*", because credentials travel on
# these requests and a wildcard would let any page on the internet make them.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get(
        "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
errors.register(app)
app.include_router(auth_router)
app.include_router(contexts_router)
app.include_router(events_router)
app.include_router(plans_router)

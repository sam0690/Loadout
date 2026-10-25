"""The app factory. Layers and their import rules: docs/backend-structure.md."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.core import errors
from api.core.config import get_settings
from api.routers import auth, contexts, events, plans


def create_app() -> FastAPI:
    # Without this the magic link is dropped on the floor. It is emitted at INFO on the
    # "loadout" logger, and Python's default root level is WARNING, so the one delivery
    # mechanism auth has (D23) produced nothing at all until this was added.
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    logging.getLogger("loadout").setLevel(logging.INFO)

    app = FastAPI(title="Loadout", version="0.1.0")
    # The PWA is served from a different origin than the API, so without this the browser
    # refuses every request. Explicit origins rather than "*", because credentials travel
    # on these requests and a wildcard would let any page on the internet make them.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    errors.register(app)
    # Order is OpenAPI path order, which the generated web client is diffed against.
    for module in (auth, contexts, events, plans):
        app.include_router(module.router)
    return app


app = create_app()

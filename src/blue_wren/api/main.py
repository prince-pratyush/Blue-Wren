from fastapi import FastAPI

from blue_wren import __version__
from blue_wren.api.routes import router


def create_app() -> FastAPI:
    app = FastAPI(title="Blue Wren API", version=__version__)
    app.include_router(router, prefix="/v1")
    return app


app = create_app()

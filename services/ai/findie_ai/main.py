import asyncio
from contextlib import asynccontextmanager, suppress
import secrets
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from .config import Settings
from .worker import Worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    app.state.settings = settings
    app.state.service_token = settings.service_token.encode('utf-8')
    worker = Worker(settings) if settings.enabled else None
    app.state.worker = worker
    task = asyncio.create_task(worker.run()) if worker else None
    try:
        yield
    finally:
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            await worker.close()


app = FastAPI(title='Findie AI', version='0.2.0', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


def authenticate(request: Request, token: Annotated[str | None, Header(alias='X-Service-Token')] = None):
    if token is None or not secrets.compare_digest(token.encode('utf-8'), request.app.state.service_token):
        raise HTTPException(status_code=401, detail='Invalid service credentials.')


@app.get('/health/live')
def live(request: Request):
    return {'status': 'ok', 'stage': 'multimodal_search' if request.app.state.settings.image_search_enabled else 'text_search'}


@app.get('/health/ready', dependencies=[Depends(authenticate)])
async def ready(request: Request):
    worker = request.app.state.worker
    available = bool(worker and await worker.probe())
    return JSONResponse(status_code=200 if available else 503, content={
        'status': 'ready' if available else 'not_ready',
        'reason': None if available else 'dependency_unavailable' if worker else 'configuration_required',
    })


@app.get('/v1/status', dependencies=[Depends(authenticate)])
async def status(request: Request):
    settings = request.app.state.settings
    worker = request.app.state.worker
    available = bool(worker and await worker.probe())
    return {
        'stage': 'multimodal_search' if settings.image_search_enabled else 'text_search',
        'inferenceReady': available,
        'execution': 'ollama',
        'models': {'embedding': settings.model_id, 'redaction': settings.redaction_model if settings.redaction_revision else None},
        'modelRevision': settings.revision or None,
        'redactionRevision': settings.redaction_revision or None,
        'redactionProfileId': 'redact-v4',
        'embeddingDimensions': settings.dimensions,
        'searchProfileId': settings.search_profile,
        'imageSearchProfileId': settings.image_search_profile,
        'capabilities': {'textSearch': available, 'imageSearch': available and settings.image_search_enabled,
                         'imageRedaction': available and bool(settings.redaction_revision)},
    }

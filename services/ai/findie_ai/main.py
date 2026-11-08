import asyncio
from contextlib import asynccontextmanager, suppress
import secrets
import base64
import json
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from .config import Settings
from .worker import Worker
from .ranking import MAX_SEARCH_CANDIDATES
from .contracts import BatchSearchMetadata, ImageEmbeddingMetadata, RedactMetadata, SearchMetadata


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


@app.post('/v1/images/{kind}', dependencies=[Depends(authenticate)])
async def private_images(kind: str, request: Request):
    models = {'image.embed': ImageEmbeddingMetadata, 'image.redact': RedactMetadata,
              'search.hybrid.image': SearchMetadata, 'search.hybrid.images': BatchSearchMetadata}
    if kind not in models:
        raise HTTPException(status_code=404)
    worker = request.app.state.worker
    if not worker or not worker.connected:
        raise HTTPException(status_code=503, detail='AI unavailable.')
    raw = bytearray()
    try:
        header = request.headers.get('X-Ai-Metadata', '')
        if not header or len(header) > 22000:
            raise ValueError('invalid_metadata')
        metadata = models[kind].model_validate_json(base64.b64decode(header, validate=True))
        worker.identity(metadata)
        content_type = request.headers.get('content-type', '')
        batch = kind == 'search.hybrid.images'
        if content_type not in ({'application/octet-stream'} if batch else {'image/jpeg', 'image/png', 'image/webp'}):
            raise ValueError('invalid_content_type')
        maximum = (30 if batch else 10) * 1024 * 1024
        # Stream the binary body in RAM; multipart parsing and temporary files are deliberately avoided.
        async with asyncio.timeout(min(metadata.remaining(), 30)):
            async for chunk in request.stream():
                if len(raw) + len(chunk) > maximum:
                    raise HTTPException(status_code=413, detail='Image size limit exceeded.')
                raw.extend(chunk)
        if not raw:
            raise ValueError('empty_body')
        async with asyncio.timeout(metadata.remaining()):
            async with worker.capacity:
                metadata.remaining()
                result = await worker.execute(kind, metadata, bytes(raw), content_type)
        response = metadata.model_dump(mode='json', by_alias=True) | {'kind': kind, 'succeeded': True}
        if kind == 'image.redact':
            result, output_metadata = result
            response.update(output_metadata)
        payload = result if isinstance(result, bytes) else json.dumps(result, allow_nan=False, separators=(',', ':')).encode()
        encoded = json.dumps(response, separators=(',', ':')).encode()
        if len(encoded) > 16384 or len(payload) > 10 * 1024 * 1024:
            raise ValueError('response_too_large')
        return Response(len(encoded).to_bytes(4, 'big') + encoded + payload,
                        media_type='application/octet-stream', headers={'Cache-Control': 'no-store'})
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail='Image processing failed; upload again to retry.') from None
    finally:
        raw[:] = b'\x00' * len(raw)
        raw.clear()


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
        'models': {'embedding': settings.model_id, 'redaction': settings.redaction_model if settings.redaction_revision else None,
                   'reranker': settings.reranker_model if settings.reranker_revision else None},
        'modelRevision': settings.revision or None,
        'redactionRevision': settings.redaction_revision or None,
        'redactionProfileId': 'redact-v4',
        'embeddingDimensions': settings.dimensions,
        'searchProfileId': settings.search_profile,
        'imageSearchProfileId': settings.image_search_profile,
        'searchQuality': {'candidateLimit': MAX_SEARCH_CANDIDATES, 'rerankerConfigured': bool(settings.reranker_revision),
                          'rerankerRevision': settings.reranker_revision or None, 'rerankBudgetSeconds': 15},
        'capabilities': {'textSearch': available, 'imageSearch': available and settings.image_search_enabled,
                         'imageRedaction': available and bool(settings.redaction_revision)},
    }

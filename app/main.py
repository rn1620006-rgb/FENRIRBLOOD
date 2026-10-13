from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from . import config
from .db import initialize
from .auth_routes import router as auth_router
from .guild_routes import router as guild_router
from .social_routes import router as social_router
from .admin_routes import router as admin_router
from .media_routes import router as media_router
from .insights_routes import router as insights_router

@asynccontextmanager
async def lifespan(app):
    initialize()
    yield

app=FastAPI(title="FENRIRBLOOD API",docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
app.include_router(auth_router)
app.include_router(guild_router)
app.include_router(social_router)
app.include_router(admin_router)
app.include_router(media_router)
app.include_router(insights_router)
app.mount("/static",StaticFiles(directory=str(config.ROOT / "static")),name="static")

@app.exception_handler(RequestValidationError)
async def validation_error(request:Request,exc:RequestValidationError):
    errors=[f"{'.'.join(map(str,e['loc']))}: {e['msg']}" for e in exc.errors()]
    return JSONResponse(status_code=422,content={"detail":"Dados inválidos: " + "; ".join(errors)[:500]})

@app.middleware("http")
async def security_headers(request,call_next):
    # Fail closed: Vercel cannot persist SQLite data. Prevent account/data loss.
    if config.ON_VERCEL and not config.DATABASE_URL and request.method not in ("GET", "HEAD", "OPTIONS"):
        return JSONResponse(status_code=503, content={"detail": "A base de dados persistente ainda não está configurada. Esta instalação no Vercel está em modo de visualização, sem registo nem alterações."})
    response=await call_next(request)
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["Referrer-Policy"]="strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"]="DENY"
    response.headers["Permissions-Policy"]="camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"]="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    response.headers["Cache-Control"]="no-store" if request.url.path.startswith("/api") else "no-cache"
    if config.SECURE_COOKIES:
        response.headers["Strict-Transport-Security"]="max-age=31536000; includeSubDomains"
    return response

@app.get("/api/health")
def health():
    return {"ok":True,"service":"FENRIRBLOOD"}

@app.get("/",include_in_schema=False)
def index():
    return FileResponse(config.ROOT / "templates" / "index.html")

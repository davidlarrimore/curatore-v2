from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routers import health, files, jobs, settings as settings_router

app = FastAPI(title="Curatore API", version="0.1.0")

# Future: plug in auth provider (Office365) here if ENABLE_AUTH is true
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # replace with specific origins once deployed
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, tags=["health"])
app.include_router(settings_router.router, tags=["settings"])
app.include_router(files.router, tags=["files"])
app.include_router(jobs.router, tags=["jobs"])
# backend/src/curatore_api/routers/health.py

# Import necessary components from FastAPI and local dependencies.
from fastapi import APIRouter, Depends
# `get_llm` is a dependency that provides an instance of the LLM service.
from ..deps import get_llm

# Create a new APIRouter instance for organizing health-related endpoints.
router = APIRouter()

# Define a GET endpoint for the health check.
# The path "/healthz" is a common convention for liveness probes in container orchestration systems.
@router.get("/healthz")
async def healthz(llm = Depends(get_llm)):
    """
    Performs a health check of the service, primarily focusing on the
    connection and status of the downstream LLM service.

    This endpoint is crucial for monitoring and orchestration systems (like Kubernetes)
    to determine if the application is running correctly and can serve requests.

    Args:
        llm: An instance of the LLM service, injected by FastAPI's dependency system.

    Returns:
        A dictionary containing the overall health status (`ok`) and detailed
        information from the LLM health probe (`llm`).
    """
    # Asynchronously call the health_probe method on the LLM service instance.
    probe = await llm.health_probe()
    # Return a JSON response indicating the service is "ok" and include the LLM probe results.
    return {"ok": True, "llm": probe}
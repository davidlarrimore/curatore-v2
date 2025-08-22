from fastapi import APIRouter, Depends
from ..deps import get_llm

router = APIRouter()

@router.get("/healthz")
async def healthz(llm = Depends(get_llm)):
    probe = await llm.health_probe()
    return {"ok": True, "llm": probe}
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="RFN API", version="0.2.0")

# Allow Next.js dev server
origins = ["http://localhost:3000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
def health():
    return {"status": "ok"}

class Item(BaseModel):
    id: int
    name: str

ITEMS = [
    Item(id=1, name="Alpha"),
    Item(id=2, name="Bravo"),
    Item(id=3, name="Charlie"),
]

@app.get("/api/items")
def list_items():
    return [i.model_dump() for i in ITEMS]

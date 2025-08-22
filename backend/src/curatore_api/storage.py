from pathlib import Path
from typing import Iterable, List
from .config import Settings

class Storage:
    def __init__(self, cfg: Settings):
        self.root = Path(cfg.DATA_ROOT)
        self.uploaded = self.root / cfg.UPLOADED_DIR
        self.processed = self.root / cfg.PROCESSED_DIR
        self.batch = self.root / cfg.BATCH_DIR
        for d in (self.uploaded, self.processed, self.batch):
            d.mkdir(parents=True, exist_ok=True)

    def uploaded_files(self) -> List[Path]:
        return sorted([p for p in self.uploaded.glob("*") if p.is_file()])

    def processed_files(self) -> List[Path]:
        return sorted([p for p in self.processed.glob("*") if p.is_file()])

    def save_upload(self, filename: str, content: bytes) -> Path:
        path = self.uploaded / filename
        path.write_bytes(content)
        return path

    def save_processed_text(self, filename: str, markdown: str) -> Path:
        path = self.processed / filename
        path.write_text(markdown, encoding="utf-8")
        return path

    def delete(self, paths: Iterable[Path]) -> int:
        n = 0
        for p in paths:
            if p.exists():
                p.unlink()
                n += 1
        return n
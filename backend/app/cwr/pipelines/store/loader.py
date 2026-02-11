# backend/app/pipelines/loader.py
"""
Pipeline Loader - Load pipeline definitions from JSON files.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from ..runtime.definitions import PipelineDefinition

logger = logging.getLogger("curatore.pipelines.loader")


class PipelineLoader:
    """Loads pipeline definitions from JSON files."""

    def __init__(self, additional_paths: List[str] = None):
        self._definitions: Dict[str, PipelineDefinition] = {}
        self._additional_paths = additional_paths or []

    def _get_definition_paths(self) -> List[Path]:
        """Get paths to search for pipeline definitions."""
        paths = []

        # Built-in definitions
        builtin_path = Path(__file__).parent / "definitions"
        if builtin_path.exists():
            paths.append(builtin_path)

        # Additional paths
        for p in self._additional_paths:
            path = Path(p)
            if path.exists():
                paths.append(path)

        return paths

    def load_json(self, path: Path) -> Optional[PipelineDefinition]:
        """Load a single JSON pipeline definition."""
        try:
            with open(path, "r") as f:
                data = json.load(f)

            if not data:
                return None

            if "name" not in data or "slug" not in data:
                logger.warning(f"Pipeline missing name/slug: {path}")
                return None

            definition = PipelineDefinition.from_dict(
                data,
                source_type="system",
                source_path=str(path),
            )

            logger.debug(f"Loaded pipeline: {definition.slug}")
            return definition

        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error in {path}: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to load pipeline {path}: {e}")
            return None

    def discover_all(self) -> Dict[str, PipelineDefinition]:
        """Discover and load all pipeline definitions."""
        self._definitions = {}

        for search_path in self._get_definition_paths():
            logger.info(f"Scanning for pipelines in: {search_path}")

            for json_file in search_path.glob("*.json"):
                definition = self.load_json(json_file)
                if definition:
                    self._definitions[definition.slug] = definition

        logger.info(f"Discovered {len(self._definitions)} pipelines")
        return self._definitions

    def get(self, slug: str) -> Optional[PipelineDefinition]:
        """Get a pipeline definition by slug."""
        if not self._definitions:
            self.discover_all()
        return self._definitions.get(slug)

    def list_all(self) -> List[PipelineDefinition]:
        """List all discovered pipeline definitions."""
        if not self._definitions:
            self.discover_all()
        return list(self._definitions.values())


# Global loader
pipeline_loader = PipelineLoader()

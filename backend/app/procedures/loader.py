# backend/app/procedures/loader.py
"""
Procedure Loader - Load procedure definitions from YAML files.

Supports:
- YAML parsing with schema validation
- Jinja2 templating in parameter values
- Automatic discovery of procedure files
"""

import os
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

import yaml
from jinja2 import Environment, BaseLoader

from .base import ProcedureDefinition

logger = logging.getLogger("curatore.procedures.loader")


class ProcedureLoader:
    """
    Loads procedure definitions from YAML files.

    Discovery paths:
    1. backend/app/procedures/definitions/ (built-in procedures)
    2. Custom paths configured via settings
    """

    def __init__(self, additional_paths: List[str] = None):
        self._definitions: Dict[str, ProcedureDefinition] = {}
        self._additional_paths = additional_paths or []
        self._jinja_env = Environment(loader=BaseLoader())

    def _get_definition_paths(self) -> List[Path]:
        """Get all paths to search for procedure definitions."""
        paths = []

        # Built-in definitions
        builtin_path = Path(__file__).parent / "definitions"
        if builtin_path.exists():
            paths.append(builtin_path)

        # Additional configured paths
        for p in self._additional_paths:
            path = Path(p)
            if path.exists():
                paths.append(path)

        return paths

    def load_yaml(self, path: Path) -> Optional[ProcedureDefinition]:
        """Load a single YAML procedure definition."""
        try:
            with open(path, "r") as f:
                data = yaml.safe_load(f)

            if not data:
                logger.warning(f"Empty procedure file: {path}")
                return None

            # Validate required fields
            if "name" not in data or "slug" not in data:
                logger.warning(f"Procedure missing name/slug: {path}")
                return None

            definition = ProcedureDefinition.from_dict(
                data,
                source_type="yaml",
                source_path=str(path),
            )

            logger.debug(f"Loaded procedure: {definition.slug} from {path}")
            return definition

        except yaml.YAMLError as e:
            logger.error(f"YAML parse error in {path}: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to load procedure {path}: {e}")
            return None

    def discover_all(self) -> Dict[str, ProcedureDefinition]:
        """
        Discover and load all procedure definitions.

        Returns dict mapping slug -> definition.
        """
        self._definitions = {}

        for search_path in self._get_definition_paths():
            logger.info(f"Scanning for procedures in: {search_path}")

            for yaml_file in search_path.glob("*.yaml"):
                definition = self.load_yaml(yaml_file)
                if definition:
                    if definition.slug in self._definitions:
                        logger.warning(f"Duplicate procedure slug: {definition.slug}")
                    self._definitions[definition.slug] = definition

            for yml_file in search_path.glob("*.yml"):
                definition = self.load_yaml(yml_file)
                if definition:
                    if definition.slug in self._definitions:
                        logger.warning(f"Duplicate procedure slug: {definition.slug}")
                    self._definitions[definition.slug] = definition

        logger.info(f"Discovered {len(self._definitions)} procedures")
        return self._definitions

    def get(self, slug: str) -> Optional[ProcedureDefinition]:
        """Get a procedure definition by slug."""
        if not self._definitions:
            self.discover_all()
        return self._definitions.get(slug)

    def list_all(self) -> List[ProcedureDefinition]:
        """List all discovered procedure definitions."""
        if not self._definitions:
            self.discover_all()
        return list(self._definitions.values())

    def render_params(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Render Jinja2 templates in parameter values.

        Context includes:
        - params: User-provided parameters
        - steps: Results from previous steps
        - now: Function to get current datetime
        """
        def render_value(value: Any) -> Any:
            if isinstance(value, str) and "{{" in value:
                template = self._jinja_env.from_string(value)
                return template.render(**context)
            elif isinstance(value, dict):
                return {k: render_value(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [render_value(item) for item in value]
            return value

        return render_value(params)


# Global loader instance
procedure_loader = ProcedureLoader()

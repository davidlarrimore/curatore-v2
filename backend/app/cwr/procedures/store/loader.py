# backend/app/procedures/loader.py
"""
Procedure Loader - Load procedure definitions from YAML files.

Supports:
- YAML parsing with schema validation
- Jinja2 templating in parameter values
- Automatic discovery of procedure files
"""

import json
import os
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

import yaml
from jinja2 import Environment, BaseLoader

from .definitions import ProcedureDefinition, StepDefinition

logger = logging.getLogger("curatore.procedures.loader")

# Flow function names that require branch validation
FLOW_FUNCTIONS = {"if_branch", "switch_branch", "parallel", "foreach"}


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

            # Validate flow function branches
            errors = self._validate_procedure_steps(definition.steps)
            if errors:
                for error in errors:
                    logger.warning(f"Validation error in {path}: {error}")
                # Still return the definition but log warnings
                # Strict validation can be added as a flag if needed

            logger.debug(f"Loaded procedure: {definition.slug} from {path}")
            return definition

        except yaml.YAMLError as e:
            logger.error(f"YAML parse error in {path}: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to load procedure {path}: {e}")
            return None

    def load_json(self, path: Path) -> Optional[ProcedureDefinition]:
        """Load a single JSON procedure definition."""
        try:
            with open(path, "r") as f:
                data = json.load(f)

            if not data:
                logger.warning(f"Empty procedure file: {path}")
                return None

            # Validate required fields
            if "name" not in data or "slug" not in data:
                logger.warning(f"Procedure missing name/slug: {path}")
                return None

            definition = ProcedureDefinition.from_dict(
                data,
                source_type="json",
                source_path=str(path),
            )

            # Validate flow function branches
            errors = self._validate_procedure_steps(definition.steps)
            if errors:
                for error in errors:
                    logger.warning(f"Validation error in {path}: {error}")

            logger.debug(f"Loaded procedure: {definition.slug} from {path}")
            return definition

        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error in {path}: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to load procedure {path}: {e}")
            return None

    def _load_file(self, path: Path) -> Optional[ProcedureDefinition]:
        """Load a procedure definition from a YAML or JSON file."""
        suffix = path.suffix.lower()
        if suffix == ".json":
            return self.load_json(path)
        return self.load_yaml(path)

    def discover_all(self) -> Dict[str, ProcedureDefinition]:
        """
        Discover and load all procedure definitions.

        Scans for *.yaml, *.yml, and *.json files in all definition paths.

        Returns dict mapping slug -> definition.
        """
        self._definitions = {}

        for search_path in self._get_definition_paths():
            logger.info(f"Scanning for procedures in: {search_path}")

            for ext in ("*.yaml", "*.yml", "*.json"):
                for def_file in search_path.glob(ext):
                    definition = self._load_file(def_file)
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

    def reload(self) -> Dict[str, ProcedureDefinition]:
        """
        Clear the cache and reload all procedure definitions from disk.

        Use this to pick up changes to YAML files without restarting the server.

        Returns:
            Dict mapping slug -> definition
        """
        logger.info("Reloading procedure definitions from disk...")
        self._definitions = {}
        return self.discover_all()

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

    def _validate_procedure_steps(self, steps: List[StepDefinition], path: str = "") -> List[str]:
        """
        Validate all steps in a procedure, including nested branches.

        Returns a list of validation error messages.
        """
        errors = []
        seen_names = set()

        for step in steps:
            step_path = f"{path}.{step.name}" if path else step.name

            # Check for duplicate step names within scope
            if step.name in seen_names:
                errors.append(f"Duplicate step name '{step.name}' in {path or 'root'}")
            seen_names.add(step.name)

            # Validate flow function branches
            if step.function in FLOW_FUNCTIONS:
                branch_errors = self._validate_flow_branches(step, step_path)
                errors.extend(branch_errors)
            elif step.branches:
                # Non-flow function has branches - warn but don't error
                logger.debug(f"Step '{step_path}' has branches but is not a flow function")

        return errors

    def _validate_flow_branches(self, step: StepDefinition, step_path: str) -> List[str]:
        """
        Validate branches for a flow control function step.

        Each flow function has specific branch requirements:
        - if_branch: requires 'then' with ≥1 step; 'else' is optional
        - switch_branch: requires ≥1 named case; 'default' is optional
        - parallel: requires ≥2 branches
        - foreach: requires 'each' with ≥1 step
        """
        errors = []
        function = step.function
        branches = step.branches or {}

        if function == "if_branch":
            if "then" not in branches:
                errors.append(f"if_branch '{step_path}' requires 'branches.then'")
            elif not branches["then"]:
                errors.append(f"if_branch '{step_path}' requires at least one step in 'branches.then'")

        elif function == "switch_branch":
            non_default_branches = [k for k in branches.keys() if k != "default"]
            if not non_default_branches:
                errors.append(f"switch_branch '{step_path}' requires at least one case in 'branches'")
            for branch_name, branch_steps in branches.items():
                if not branch_steps:
                    errors.append(f"switch_branch '{step_path}' branch '{branch_name}' has no steps")

        elif function == "parallel":
            if len(branches) < 2:
                errors.append(f"parallel '{step_path}' requires at least 2 branches (found {len(branches)})")
            for branch_name, branch_steps in branches.items():
                if not branch_steps:
                    errors.append(f"parallel '{step_path}' branch '{branch_name}' has no steps")

        elif function == "foreach":
            if "each" not in branches:
                errors.append(f"foreach '{step_path}' requires 'branches.each'")
            elif not branches["each"]:
                errors.append(f"foreach '{step_path}' requires at least one step in 'branches.each'")

        # Recursively validate nested steps in all branches
        for branch_name, branch_steps in branches.items():
            if branch_steps:
                nested_errors = self._validate_procedure_steps(
                    branch_steps,
                    path=f"{step_path}.branches.{branch_name}"
                )
                errors.extend(nested_errors)

        return errors

    def validate_procedure(self, definition: ProcedureDefinition) -> List[str]:
        """
        Validate a complete procedure definition.

        Returns a list of validation error messages. Empty list means valid.
        """
        errors = []

        # Check required fields
        if not definition.name:
            errors.append("Procedure missing 'name'")
        if not definition.slug:
            errors.append("Procedure missing 'slug'")

        # Validate all steps
        step_errors = self._validate_procedure_steps(definition.steps)
        errors.extend(step_errors)

        return errors


# Global loader instance
procedure_loader = ProcedureLoader()

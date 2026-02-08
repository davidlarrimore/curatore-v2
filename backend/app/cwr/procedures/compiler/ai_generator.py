# backend/app/cwr/procedures/compiler/ai_generator.py
"""
Procedure Generator Service v2 - AI-powered procedure generation using Typed Plans.

Replaces v1's monolithic YAML-emitting approach with:
- Typed Plan JSON as LLM output (schema-first validation)
- Agentic repair loops (max 3 plan repairs + max 2 procedure repairs)
- Generation profiles (safe_readonly, workflow_standard, admin_full)
- Contract-pack-driven prompts

Flow:
    User Prompt + Profile
      -> ContextBuilder (TCP + org catalog + data sources)
      -> LLM emits Typed Plan (JSON)
      -> PlanValidator (schema + tool args + refs + side-effect policy)
      -> [repair loop: max 3 plan repairs]
      -> PlanCompiler (Plan JSON -> Procedure dict)
      -> ProcedureValidator (existing validate_procedure + contract checks)
      -> [repair loop: max 2 procedure repairs]
      -> Return Draft Procedure (YAML + diagnostics)

Usage:
    from app.cwr.procedures.compiler.ai_generator import procedure_generator_service

    result = await procedure_generator_service.generate_procedure(
        prompt="Create a procedure that sends a daily email summary of new assets",
        organization_id=org_id,
        profile="workflow_standard",
    )

    if result["success"]:
        yaml_content = result["yaml"]
        plan_json = result["plan_json"]
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import UUID
import asyncio

import yaml

from app.core.models.llm_models import LLMTaskType
from app.core.llm.llm_service import llm_service
from app.core.shared.config_loader import config_loader
from app.cwr.contracts.contract_pack import get_tool_contract_pack
from app.cwr.contracts.validation import validate_procedure
from app.cwr.governance.generation_profiles import get_profile, GenerationProfile
from app.cwr.procedures.compiler.context_builder import ContextBuilder
from app.cwr.procedures.compiler.plan_compiler import PlanCompiler
from app.cwr.procedures.compiler.plan_validator import PlanValidator

logger = logging.getLogger("curatore.services.procedure_generator")


@dataclass
class GenerationDiagnostics:
    """Diagnostics collected during procedure generation."""
    profile_used: str = ""
    tools_available: int = 0
    tools_referenced: List[str] = field(default_factory=list)
    plan_attempts: int = 0
    procedure_attempts: int = 0
    total_attempts: int = 0
    validation_error_types: List[str] = field(default_factory=list)
    clamps_applied: List[str] = field(default_factory=list)
    timing_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile_used": self.profile_used,
            "tools_available": self.tools_available,
            "tools_referenced": self.tools_referenced,
            "plan_attempts": self.plan_attempts,
            "procedure_attempts": self.procedure_attempts,
            "total_attempts": self.total_attempts,
            "validation_error_types": self.validation_error_types,
            "clamps_applied": self.clamps_applied,
            "timing_ms": round(self.timing_ms, 1),
        }


class ProcedureGeneratorService:
    """
    AI-powered procedure generation service (v2).

    Generates procedures through a two-phase agentic loop:
    - Phase A: Plan generation + repair (max 3 attempts)
    - Phase B: Compilation + procedure validation + repair (max 2 attempts)

    Total budget: MAX_TOTAL_ATTEMPTS = 5
    """

    MAX_PLAN_REPAIRS = 3
    MAX_PROCEDURE_REPAIRS = 2
    MAX_TOTAL_ATTEMPTS = 5

    async def generate_procedure(
        self,
        prompt: str,
        organization_id: Optional[UUID] = None,
        session: Optional[Any] = None,
        include_examples: bool = True,
        current_yaml: Optional[str] = None,
        profile: str = "workflow_standard",
        current_plan: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Generate or refine a procedure from a natural language prompt.

        Args:
            prompt: Natural language description or change request
            organization_id: Optional org ID for LLM and data source context
            session: Optional database session
            include_examples: Whether to include examples (reserved)
            current_yaml: Optional existing YAML to refine
            profile: Generation profile name
            current_plan: Optional existing plan JSON to refine

        Returns:
            Dict with: success, yaml, procedure, plan_json, error, attempts,
            validation_errors, validation_warnings, profile_used, diagnostics
        """
        start_time = time.time()
        diagnostics = GenerationDiagnostics()

        # Resolve profile
        gen_profile = get_profile(profile)
        diagnostics.profile_used = gen_profile.name.value

        # Check LLM availability
        if not llm_service.is_available:
            return self._error_result(
                "LLM service is not available. Please configure an LLM connection.",
                diagnostics=diagnostics,
            )

        # Build contract pack
        contract_pack = get_tool_contract_pack(
            org_id=organization_id, profile=gen_profile
        )
        diagnostics.tools_available = len(contract_pack.contracts)

        # Build system prompt via ContextBuilder
        context_builder = ContextBuilder(contract_pack, gen_profile)
        try:
            system_prompt = await context_builder.build_system_prompt(
                session=session, org_id=organization_id
            )
        except Exception as e:
            logger.error(f"Failed to build system prompt: {e}")
            return self._error_result(
                f"Failed to build generation context: {e}",
                diagnostics=diagnostics,
            )

        # Build user prompt
        user_prompt = self._build_user_prompt(prompt, current_yaml, current_plan)

        # Initialize conversation
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # =====================================================================
        # Phase A: Plan generation + repair loop
        # =====================================================================
        plan_validator = PlanValidator(contract_pack)
        plan_dict = None
        plan_errors: List[Dict[str, Any]] = []
        plan_attempt = 0

        while plan_attempt < self.MAX_PLAN_REPAIRS:
            plan_attempt += 1
            diagnostics.plan_attempts = plan_attempt
            logger.info(f"Plan generation attempt {plan_attempt}/{self.MAX_PLAN_REPAIRS}")

            try:
                raw_response = await self._call_llm(messages)
            except Exception as e:
                logger.error(f"LLM call failed on plan attempt {plan_attempt}: {e}")
                plan_errors = [{"code": "LLM_ERROR", "path": "", "message": str(e), "details": {}}]
                messages.append({"role": "assistant", "content": str(e)})
                messages.append({"role": "user", "content": self._build_plan_error_feedback(plan_errors)})
                continue

            # Parse JSON
            parsed = self._parse_plan_json(raw_response)
            if parsed is None:
                plan_errors = [{
                    "code": "INVALID_JSON",
                    "path": "",
                    "message": "LLM output is not valid JSON. Output must be a JSON object matching the Typed Plan schema.",
                    "details": {"raw_preview": raw_response[:500]},
                }]
                logger.warning(f"Plan attempt {plan_attempt}: JSON parse failed")
                messages.append({"role": "assistant", "content": raw_response})
                messages.append({"role": "user", "content": self._build_plan_error_feedback(plan_errors)})
                continue

            # Validate plan
            validation_result = plan_validator.validate(parsed)

            if validation_result.valid:
                plan_dict = parsed
                logger.info(f"Plan validated successfully on attempt {plan_attempt}")
                break
            else:
                plan_errors = [e.to_dict() for e in validation_result.errors]
                diagnostics.validation_error_types.extend(
                    e.code.value for e in validation_result.errors
                )
                logger.warning(
                    f"Plan attempt {plan_attempt}: {len(plan_errors)} validation errors"
                )
                messages.append({"role": "assistant", "content": raw_response})
                messages.append({"role": "user", "content": self._build_plan_error_feedback(plan_errors)})

        if plan_dict is None:
            diagnostics.timing_ms = (time.time() - start_time) * 1000
            diagnostics.total_attempts = plan_attempt
            return self._error_result(
                f"Failed to generate valid plan after {plan_attempt} attempts",
                validation_errors=plan_errors,
                diagnostics=diagnostics,
                attempts=plan_attempt,
            )

        # =====================================================================
        # Phase B: Compilation + procedure validation + repair loop
        # =====================================================================
        compiler = PlanCompiler(gen_profile)
        procedure_dict = None
        procedure_yaml = None
        proc_errors: List[Dict[str, Any]] = []
        proc_warnings: List[Dict[str, Any]] = []
        proc_attempt = 0

        while proc_attempt < self.MAX_PROCEDURE_REPAIRS:
            proc_attempt += 1
            diagnostics.procedure_attempts = proc_attempt

            try:
                compiled = compiler.compile(plan_dict)
            except Exception as e:
                logger.error(f"Compilation failed: {e}")
                proc_errors = [{
                    "code": "COMPILATION_ERROR",
                    "path": "",
                    "message": str(e),
                    "details": {},
                }]
                # Feed back to LLM for plan repair
                messages.append({"role": "assistant", "content": json.dumps(plan_dict)})
                messages.append({"role": "user", "content": self._build_procedure_error_feedback(proc_errors)})

                # Try to get a new plan from LLM
                try:
                    raw_response = await self._call_llm(messages)
                    new_plan = self._parse_plan_json(raw_response)
                    if new_plan and plan_validator.validate(new_plan).valid:
                        plan_dict = new_plan
                except Exception:
                    pass
                continue

            # Validate compiled procedure
            proc_validation = validate_procedure(compiled)

            if proc_validation.valid:
                procedure_dict = compiled
                proc_warnings = [w.to_dict() for w in proc_validation.warnings]

                # Generate YAML
                try:
                    procedure_yaml = yaml.dump(
                        compiled, default_flow_style=False, sort_keys=False, allow_unicode=True,
                    )
                except Exception as e:
                    logger.error(f"YAML serialization failed: {e}")
                    procedure_yaml = json.dumps(compiled, indent=2)

                # Collect referenced tools
                diagnostics.tools_referenced = list({
                    s.get("function", "") for s in compiled.get("steps", [])
                    if s.get("function")
                })

                logger.info(f"Procedure compiled and validated on attempt {proc_attempt}")
                break
            else:
                proc_errors = [e.to_dict() for e in proc_validation.errors]
                diagnostics.validation_error_types.extend(
                    e.code.value for e in proc_validation.errors
                )
                logger.warning(
                    f"Procedure attempt {proc_attempt}: {len(proc_errors)} validation errors"
                )

                # Feed errors back to LLM for plan repair
                messages.append({"role": "assistant", "content": json.dumps(plan_dict)})
                messages.append({"role": "user", "content": self._build_procedure_error_feedback(proc_errors)})

                # Try to get a repaired plan
                try:
                    raw_response = await self._call_llm(messages)
                    new_plan = self._parse_plan_json(raw_response)
                    if new_plan and plan_validator.validate(new_plan).valid:
                        plan_dict = new_plan
                except Exception:
                    pass

        diagnostics.total_attempts = plan_attempt + proc_attempt
        diagnostics.timing_ms = (time.time() - start_time) * 1000

        if procedure_dict is None:
            return self._error_result(
                f"Failed to compile valid procedure after {proc_attempt} attempts",
                validation_errors=proc_errors,
                diagnostics=diagnostics,
                attempts=diagnostics.total_attempts,
                plan_json=plan_dict,
            )

        return {
            "success": True,
            "yaml": procedure_yaml,
            "procedure": procedure_dict,
            "plan_json": plan_dict,
            "error": None,
            "attempts": diagnostics.total_attempts,
            "validation_errors": [],
            "validation_warnings": proc_warnings,
            "profile_used": gen_profile.name.value,
            "diagnostics": diagnostics.to_dict(),
        }

    # ------------------------------------------------------------------
    # LLM Interaction
    # ------------------------------------------------------------------

    async def _call_llm(self, messages: List[Dict[str, str]]) -> str:
        """
        Call the LLM with the given messages.

        Returns:
            Raw string response from the LLM
        """
        if llm_service._client is None:
            raise RuntimeError("LLM client not initialized")

        task_config = config_loader.get_task_type_config(LLMTaskType.REASONING)
        model = task_config.model
        temperature = task_config.temperature if task_config.temperature is not None else 0.2

        def _sync_call():
            return llm_service._client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=4000,
                temperature=temperature,
            )

        response = await asyncio.to_thread(_sync_call)
        return response.choices[0].message.content.strip()

    # ------------------------------------------------------------------
    # JSON Parsing
    # ------------------------------------------------------------------

    def _parse_plan_json(self, raw: str) -> Optional[Dict[str, Any]]:
        """
        Parse plan JSON from LLM response, stripping fences if present.

        Args:
            raw: Raw LLM response string

        Returns:
            Parsed dict or None if parsing fails
        """
        text = raw.strip()

        # Strip markdown code fences
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
            return None
        except (json.JSONDecodeError, ValueError):
            # Try to find JSON object in the response
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    result = json.loads(text[start:end + 1])
                    if isinstance(result, dict):
                        return result
                except (json.JSONDecodeError, ValueError):
                    pass
            return None

    # ------------------------------------------------------------------
    # User Prompt Building
    # ------------------------------------------------------------------

    def _build_user_prompt(
        self,
        prompt: str,
        current_yaml: Optional[str] = None,
        current_plan: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build the user prompt based on generation mode."""
        if current_plan:
            plan_json = json.dumps(current_plan, indent=2)
            return f"""Here is an existing Typed Plan:

```json
{plan_json}
```

Please modify this plan according to the following instructions:

{prompt}

Return the complete modified Typed Plan JSON. Keep all existing steps unless the instructions specifically ask to remove or change them."""

        elif current_yaml:
            return f"""Here is an existing procedure definition in YAML:

```yaml
{current_yaml}
```

Please create a new Typed Plan JSON that represents this procedure with the following modifications:

{prompt}

Return a complete Typed Plan JSON that incorporates the changes. Keep all existing functionality unless the instructions specifically ask to remove or change it."""

        else:
            return f"""Create a Typed Plan JSON for the following requirement:

{prompt}"""

    # ------------------------------------------------------------------
    # Error Feedback
    # ------------------------------------------------------------------

    def _build_plan_error_feedback(self, errors: List[Dict[str, Any]]) -> str:
        """Build structured error feedback for plan repair."""
        error_lines = []
        for err in errors:
            error_lines.append(f"- {err['code']} at `{err.get('path', '')}`: {err['message']}")

        return f"""The Typed Plan JSON has validation errors:

{chr(10).join(error_lines)}

Fix these errors and return the corrected Typed Plan JSON. Key reminders:
- UNKNOWN_FUNCTION: Use only tools from the TOOL CATALOG
- MISSING_REQUIRED_PARAM: Add the missing required arg to the step
- INVALID_STEP_REFERENCE: Refs can only point to earlier steps
- INVALID_PARAM_REFERENCE: Refs must point to defined parameters
- TOOL_BLOCKED_BY_PROFILE: That tool is not allowed under the current profile
- MISSING_SIDE_EFFECT_CONFIRMATION: Admin profile requires confirm_side_effects: true on side-effect steps

Return ONLY the corrected JSON."""

    def _build_procedure_error_feedback(self, errors: List[Dict[str, Any]]) -> str:
        """Build error feedback for procedure-level repair."""
        error_lines = []
        for err in errors:
            error_lines.append(f"- {err['code']} at `{err.get('path', '')}`: {err['message']}")

        return f"""The compiled procedure has validation errors:

{chr(10).join(error_lines)}

The plan compiled to a procedure that didn't pass validation. Please fix the plan to avoid these issues.

Common fixes:
- UNKNOWN_FUNCTION: The tool name in the plan doesn't match any registered function
- MISSING_REQUIRED_FIELD: The compiled procedure is missing name, slug, or steps
- CONTRADICTORY_PARAMETER: A parameter cannot be both required and have a default value
- MISSING_REQUIRED_BRANCH: Flow functions need correct branches (foreach→each, if_branch→then)

Return the corrected Typed Plan JSON."""

    # ------------------------------------------------------------------
    # Result Helpers
    # ------------------------------------------------------------------

    def _error_result(
        self,
        error: str,
        validation_errors: Optional[List] = None,
        diagnostics: Optional[GenerationDiagnostics] = None,
        attempts: int = 0,
        plan_json: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Build a standardized error result dict."""
        return {
            "success": False,
            "yaml": None,
            "procedure": None,
            "plan_json": plan_json,
            "error": error,
            "attempts": attempts,
            "validation_errors": validation_errors or [],
            "validation_warnings": [],
            "profile_used": diagnostics.profile_used if diagnostics else None,
            "diagnostics": diagnostics.to_dict() if diagnostics else None,
        }


# Global service instance (same name for drop-in replacement)
procedure_generator_service = ProcedureGeneratorService()

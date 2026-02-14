# backend/app/cwr/procedures/compiler/ai_generator.py
"""
Procedure Generator Service — AI-powered procedure generation with agentic planning.

Flow:
    User Prompt + Profile
      -> ContextBuilder (tool catalog + data sources + planning tools section)
      -> Planning Phase: LLM uses tool-calling to research/verify data
      -> Plan Phase: LLM emits Typed Plan JSON
      -> PlanValidator (schema + tool args + refs + side-effect policy)
      -> [1 repair attempt if validation fails, no tools]
      -> PlanCompiler (Plan JSON -> Procedure dict)
      -> ProcedureValidator (contract checks)
      -> Return Draft Procedure (YAML + diagnostics)

Usage:
    from app.cwr.procedures.compiler.ai_generator import procedure_generator_service

    result = await procedure_generator_service.generate_procedure(
        prompt="Create a procedure that sends a daily email summary of new assets",
        organization_id=org_id,
        profile="workflow_standard",
    )
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional
from uuid import UUID

import yaml

from app.core.llm.llm_service import llm_service
from app.core.models.llm_models import LLMTaskType
from app.core.shared.config_loader import config_loader
from app.cwr.contracts.contract_pack import get_tool_contract_pack
from app.cwr.contracts.validation import validate_procedure
from app.cwr.governance.generation_profiles import get_profile
from app.cwr.procedures.compiler.context_builder import ContextBuilder
from app.cwr.procedures.compiler.plan_compiler import PlanCompiler
from app.cwr.procedures.compiler.plan_validator import PlanValidator

logger = logging.getLogger("curatore.services.procedure_generator")

# Planning phase limits
MAX_PLANNING_TOOL_CALLS = 5
MAX_PLAN_REPAIRS = 2  # 1 initial + 1 repair


# Progress event types for SSE streaming
ProgressCallback = Callable[[Dict[str, Any]], Awaitable[None]]


@dataclass
class GenerationDiagnostics:
    """Diagnostics collected during procedure generation."""
    profile_used: str = ""
    tools_available: int = 0
    tools_referenced: List[str] = field(default_factory=list)
    plan_attempts: int = 0
    total_attempts: int = 0
    validation_error_types: List[str] = field(default_factory=list)
    clamps_applied: List[str] = field(default_factory=list)
    timing_ms: float = 0.0
    # Planning phase diagnostics
    planning_tool_calls: int = 0
    planning_tools_used: List[str] = field(default_factory=list)
    planning_results_summary: List[Dict[str, str]] = field(default_factory=list)
    # Prompt caching diagnostics
    prompt_caching_enabled: bool = False
    cached_tokens: int = 0
    total_prompt_tokens: int = 0

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "profile_used": self.profile_used,
            "tools_available": self.tools_available,
            "tools_referenced": self.tools_referenced,
            "plan_attempts": self.plan_attempts,
            "total_attempts": self.total_attempts,
            "validation_error_types": self.validation_error_types,
            "clamps_applied": self.clamps_applied,
            "timing_ms": round(self.timing_ms, 1),
            "planning_tool_calls": self.planning_tool_calls,
            "planning_tools_used": self.planning_tools_used,
            "planning_results_summary": self.planning_results_summary,
        }
        if self.prompt_caching_enabled:
            result["prompt_caching"] = {
                "enabled": True,
                "cached_tokens": self.cached_tokens,
                "total_prompt_tokens": self.total_prompt_tokens,
            }
        return result


class ProcedureGeneratorService:
    """
    AI-powered procedure generation service with agentic planning.

    Two-phase generation (like Claude Code):
    1. Research phase: LLM uses tool-calling to discover and verify data
    2. Plan + compile phase: LLM emits Typed Plan JSON, validated and compiled
    """

    async def generate_procedure(
        self,
        prompt: str,
        organization_id: Optional[UUID] = None,
        session: Optional[Any] = None,
        include_examples: bool = True,
        profile: str = "workflow_standard",
        current_plan: Optional[Dict[str, Any]] = None,
        on_progress: Optional[ProgressCallback] = None,
        use_planning_tools: bool = True,
    ) -> Dict[str, Any]:
        """
        Generate or refine a procedure from a natural language prompt.

        Args:
            prompt: Natural language description or change request
            organization_id: Optional org ID for LLM and data source context
            session: Optional database session
            include_examples: Whether to include examples (reserved)
            profile: Generation profile name
            current_plan: Optional existing plan JSON to refine
            on_progress: Optional async callback for SSE streaming events
            use_planning_tools: Whether to enable agentic planning tools (default True).
                When True, the LLM can call planning tools to research/verify data.
                When False, the LLM generates the plan using only static context.
                Planning tools require both session and organization_id to activate.

        Returns:
            Dict with: success, yaml, procedure, plan_json, error, attempts,
            validation_errors, validation_warnings, profile_used, diagnostics
        """
        start_time = time.time()
        diagnostics = GenerationDiagnostics()

        async def _emit(event: Dict[str, Any]) -> None:
            if on_progress:
                try:
                    await on_progress(event)
                except Exception:
                    pass  # Don't let callback errors break generation

        # Resolve profile
        gen_profile = get_profile(profile)
        diagnostics.profile_used = gen_profile.name.value

        # Check LLM availability
        if not llm_service.is_available:
            return self._error_result(
                "LLM service is not available. Please configure an LLM connection.",
                diagnostics=diagnostics,
            )

        # Resolve org-specific data source availability
        enabled_ds = None
        if organization_id and session:
            from app.core.metadata.registry_service import metadata_registry_service

            enabled_ds = await metadata_registry_service.get_enabled_data_sources(
                session, organization_id
            )

        # Build contract pack
        contract_pack = get_tool_contract_pack(
            org_id=organization_id,
            profile=gen_profile,
            enabled_data_sources=enabled_ds,
        )
        diagnostics.tools_available = len(contract_pack.contracts)

        # Build system prompt via ContextBuilder
        await _emit({"event": "phase", "phase": "context", "message": "Building context..."})
        context_builder = ContextBuilder(contract_pack, gen_profile)
        try:
            system_prompt = await context_builder.build_system_prompt(
                session=session,
                org_id=organization_id,
                include_planning_tools=use_planning_tools,
            )
        except Exception as e:
            logger.error(f"Failed to build system prompt: {e}")
            return self._error_result(
                f"Failed to build generation context: {e}",
                diagnostics=diagnostics,
            )

        # Build user prompt
        user_prompt = self._build_user_prompt(prompt, current_plan)

        # Initialize conversation
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # =================================================================
        # Planning + Plan Generation Phase
        # =================================================================
        planning_tools = None
        planning_ctx = None

        if use_planning_tools and session and organization_id:
            await _emit({"event": "phase", "phase": "researching", "message": "Starting planning phase..."})
            try:
                from app.cwr.procedures.compiler.planning_tools import (
                    get_planning_tools_openai_format,
                )
                from app.cwr.tools.context import FunctionContext

                planning_tools = get_planning_tools_openai_format()
                planning_ctx = FunctionContext(
                    session=session,
                    organization_id=organization_id,
                )
            except Exception as e:
                logger.warning(f"Failed to initialize planning tools: {e}")
                planning_tools = None
        else:
            await _emit({"event": "phase", "phase": "researching", "message": "Generating plan..."})

        plan_dict = None
        plan_errors: List[Dict[str, Any]] = []
        plan_attempt = 0
        tool_call_count = 0

        while plan_attempt < MAX_PLAN_REPAIRS:
            plan_attempt += 1
            diagnostics.plan_attempts = plan_attempt
            logger.info(f"Plan generation attempt {plan_attempt}/{MAX_PLAN_REPAIRS}")

            # Agentic tool-calling loop
            raw_response = await self._run_planning_phase(
                messages=messages,
                planning_tools=planning_tools,
                planning_ctx=planning_ctx,
                diagnostics=diagnostics,
                tool_call_count=tool_call_count,
                emit=_emit,
                allow_tool_calls=(plan_attempt == 1),  # Tools only on first attempt
            )

            if raw_response is None:
                plan_errors = [{"code": "LLM_ERROR", "path": "", "message": "LLM returned no response", "details": {}}]
                continue

            tool_call_count = diagnostics.planning_tool_calls  # Carry forward

            # Parse JSON
            await _emit({"event": "phase", "phase": "validating", "message": f"Validating plan (attempt {plan_attempt})..."})
            parsed = self._parse_plan_json(raw_response)
            if parsed is None:
                # Check if this is a clarification question from the AI
                if self._is_clarification_response(raw_response):
                    logger.info("AI responded with clarification request instead of plan")
                    await _emit({
                        "event": "clarification",
                        "message": raw_response,
                    })
                    diagnostics.timing_ms = (time.time() - start_time) * 1000
                    diagnostics.total_attempts = plan_attempt
                    return {
                        "success": False,
                        "needs_clarification": True,
                        "clarification_message": raw_response,
                        "yaml": None,
                        "procedure": None,
                        "plan_json": None,
                        "error": None,
                        "attempts": plan_attempt,
                        "validation_errors": [],
                        "validation_warnings": [],
                        "profile_used": diagnostics.profile_used,
                        "diagnostics": diagnostics.to_dict(),
                    }

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
            plan_validator = PlanValidator(contract_pack)
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

        # =================================================================
        # Compilation Phase (no repair loop — compiler bugs are bugs)
        # =================================================================
        await _emit({"event": "phase", "phase": "compiling", "message": "Compiling procedure..."})

        compiler = PlanCompiler(gen_profile)
        try:
            procedure_dict = compiler.compile(plan_dict)
        except Exception as e:
            logger.error(f"Compilation failed: {e}")
            diagnostics.timing_ms = (time.time() - start_time) * 1000
            diagnostics.total_attempts = plan_attempt
            return self._error_result(
                f"Plan compiled but compilation failed: {e}",
                diagnostics=diagnostics,
                attempts=plan_attempt,
                plan_json=plan_dict,
            )

        # Validate compiled procedure
        proc_validation = validate_procedure(procedure_dict)
        if not proc_validation.valid:
            proc_errors = [e.to_dict() for e in proc_validation.errors]
            diagnostics.timing_ms = (time.time() - start_time) * 1000
            diagnostics.total_attempts = plan_attempt
            return self._error_result(
                "Plan validated but compiled procedure failed validation",
                validation_errors=proc_errors,
                diagnostics=diagnostics,
                attempts=plan_attempt,
                plan_json=plan_dict,
            )

        proc_warnings = [w.to_dict() for w in proc_validation.warnings]

        # Generate YAML
        try:
            procedure_yaml = yaml.dump(
                procedure_dict, default_flow_style=False, sort_keys=False, allow_unicode=True,
            )
        except Exception as e:
            logger.error(f"YAML serialization failed: {e}")
            procedure_yaml = json.dumps(procedure_dict, indent=2)

        # Collect referenced tools
        diagnostics.tools_referenced = list({
            s.get("function", "") for s in procedure_dict.get("steps", [])
            if s.get("function")
        })
        diagnostics.total_attempts = plan_attempt
        diagnostics.timing_ms = (time.time() - start_time) * 1000

        logger.info(f"Procedure generated successfully in {diagnostics.timing_ms:.0f}ms")

        result = {
            "success": True,
            "yaml": procedure_yaml,
            "procedure": procedure_dict,
            "plan_json": plan_dict,
            "error": None,
            "attempts": plan_attempt,
            "validation_errors": [],
            "validation_warnings": proc_warnings,
            "profile_used": gen_profile.name.value,
            "diagnostics": diagnostics.to_dict(),
        }

        return result

    # ------------------------------------------------------------------
    # Planning Phase: Tool-Calling Agentic Loop
    # ------------------------------------------------------------------

    async def _run_planning_phase(
        self,
        messages: List[Dict[str, Any]],
        planning_tools: Optional[List[Dict[str, Any]]],
        planning_ctx: Optional[Any],
        diagnostics: GenerationDiagnostics,
        tool_call_count: int,
        emit: Callable,
        allow_tool_calls: bool = True,
    ) -> Optional[str]:
        """
        Run the LLM with optional tool-calling for research.

        The LLM may call planning tools to discover/verify data before
        emitting the Typed Plan JSON. This loop handles parallel tool calls,
        budget limits, and result formatting.

        Args:
            allow_tool_calls: If False, tool-related messages are stripped from
                history and no tools are passed. This avoids Bedrock compatibility
                issues (Bedrock rejects both tool_calls without tools= and tool_choice=none).

        Returns:
            The final text response (plan JSON string), or None on failure.
        """
        # Safety ceiling: max iterations = tool budget + 2 (for initial + final)
        max_iterations = MAX_PLANNING_TOOL_CALLS + 2
        tools_param = planning_tools if (planning_tools and planning_ctx and allow_tool_calls) else None

        # When tools are disabled (repair attempts), strip tool-related messages
        # from history. Bedrock rejects tool_calls in history without tools= param,
        # and also rejects tool_choice=none. Cleaning the history is the only safe path.
        if not tools_param:
            self._strip_tool_messages(messages)

        for iteration in range(max_iterations):
            try:
                response = await self._call_llm(
                    messages,
                    tools=tools_param,
                    diagnostics=diagnostics,
                )
            except Exception as e:
                logger.error(f"LLM call failed: {e}")
                messages.append({"role": "assistant", "content": str(e)})
                return None

            message = response.choices[0].message

            # Check for tool calls
            if hasattr(message, "tool_calls") and message.tool_calls:
                # Append the assistant message with tool_calls
                messages.append(message.model_dump() if hasattr(message, "model_dump") else {
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in message.tool_calls
                    ],
                })

                # Execute each tool call (may be parallel from the LLM)
                from app.cwr.procedures.compiler.planning_tools import (
                    execute_planning_tool,
                    format_tool_result_for_llm,
                )

                for tc in message.tool_calls:
                    tool_call_count += 1
                    diagnostics.planning_tool_calls = tool_call_count
                    func_name = tc.function.name

                    # Parse arguments
                    try:
                        args = json.loads(tc.function.arguments)
                    except (json.JSONDecodeError, TypeError):
                        args = {}

                    await emit({
                        "event": "tool_call",
                        "tool": func_name,
                        "args": args,
                        "call_index": tool_call_count,
                    })

                    # Execute
                    result = await execute_planning_tool(func_name, args, planning_ctx)
                    result_text = format_tool_result_for_llm(result)

                    if func_name not in diagnostics.planning_tools_used:
                        diagnostics.planning_tools_used.append(func_name)
                    diagnostics.planning_results_summary.append({
                        "tool": func_name,
                        "summary": result.get("summary", ""),
                    })

                    await emit({
                        "event": "tool_result",
                        "tool": func_name,
                        "call_index": tool_call_count,
                        "summary": result.get("summary", ""),
                    })

                    # Append tool result message
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_text,
                    })

                # Check budget
                if tool_call_count >= MAX_PLANNING_TOOL_CALLS:
                    logger.info(f"Planning tool budget exhausted ({tool_call_count} calls)")
                    # Condense tool history and disable tools for the final call.
                    # Must strip tool messages before disabling tools — Bedrock rejects
                    # tool_calls in history without tools= param.
                    self._strip_tool_messages(messages)
                    messages.append({
                        "role": "user",
                        "content": "Tool call budget reached. Emit the Typed Plan JSON now based on what you've learned.",
                    })
                    tools_param = None

                continue  # Next iteration to get LLM response after tool results

            # No tool calls — this is the final text response
            content = message.content
            if content:
                return content.strip()
            return None

        # Exhausted iterations
        logger.error(f"Planning phase exhausted {max_iterations} iterations")
        return None

    # ------------------------------------------------------------------
    # LLM Interaction
    # ------------------------------------------------------------------

    async def _call_llm(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        diagnostics: Optional[GenerationDiagnostics] = None,
    ) -> Any:
        """
        Call the LLM with the given messages and optional tools.

        Applies cache_control breakpoints to the system message and the last
        tool definition so Bedrock / Anthropic can cache the static prefix
        across calls (90% input-token discount on cache hits).  Providers
        that don't support cache_control simply ignore the extra key.

        Returns:
            Raw response object from the OpenAI-compatible client.
        """
        if llm_service._client is None:
            raise RuntimeError("LLM client not initialized")

        task_config = config_loader.get_task_type_config(LLMTaskType.REASONING)
        model = task_config.model
        temperature = task_config.temperature if task_config.temperature is not None else 0.2

        # Apply cache_control breakpoints so the LLM provider can cache the
        # static prefix (system prompt + tool schemas) across calls.
        # Providers that don't support cache_control simply ignore the extra key.
        messages = self._apply_prompt_caching(messages)
        if diagnostics:
            diagnostics.prompt_caching_enabled = True

        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": 4000,
            "temperature": temperature,
        }

        if tools is not None and len(tools) > 0:
            kwargs["tools"] = self._apply_tools_caching(tools)
            kwargs["tool_choice"] = "auto"

        def _sync_call():
            return llm_service._client.chat.completions.create(**kwargs)

        response = await asyncio.to_thread(_sync_call)

        # Track cache hit metrics from the response
        if diagnostics and response.usage:
            diagnostics.total_prompt_tokens += response.usage.prompt_tokens or 0
            # LiteLLM/Bedrock report cached tokens in prompt_tokens_details
            details = getattr(response.usage, "prompt_tokens_details", None)
            if details:
                diagnostics.cached_tokens += getattr(details, "cached_tokens", 0) or 0

        return response

    # ------------------------------------------------------------------
    # Prompt Caching Helpers
    # ------------------------------------------------------------------

    def _apply_prompt_caching(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Convert system messages to content-block format with cache_control.

        Transforms:
            {"role": "system", "content": "..."}
        Into:
            {"role": "system", "content": [
                {"type": "text", "text": "...", "cache_control": {"type": "ephemeral"}}
            ]}

        Only modifies system messages; other messages pass through unchanged.
        Returns a shallow copy to avoid mutating the caller's list.
        """
        result = []
        for msg in messages:
            if msg.get("role") == "system" and isinstance(msg.get("content"), str):
                result.append({
                    "role": "system",
                    "content": [
                        {
                            "type": "text",
                            "text": msg["content"],
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                })
            else:
                result.append(msg)
        return result

    def _apply_tools_caching(
        self, tools: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Add cache_control to the last tool definition.

        Providers that support explicit caching (Bedrock, Anthropic) cache
        the prefix up to and including the last cache_control breakpoint.
        By marking the final tool, the entire tools array becomes part of
        the cached prefix.  Providers with automatic caching (OpenAI)
        ignore this key and cache based on prefix matching instead.

        Returns a shallow copy with the last tool modified.
        """
        if not tools:
            return tools
        tools = list(tools)  # shallow copy
        last_tool = dict(tools[-1])  # copy last tool
        last_fn = dict(last_tool.get("function", {}))
        last_fn["cache_control"] = {"type": "ephemeral"}
        last_tool["function"] = last_fn
        tools[-1] = last_tool
        return tools

    # ------------------------------------------------------------------
    # JSON Parsing
    # ------------------------------------------------------------------

    def _parse_plan_json(self, raw: str) -> Optional[Dict[str, Any]]:
        """
        Parse plan JSON from LLM response, stripping fences if present.

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
    # Clarification Detection
    # ------------------------------------------------------------------

    def _is_clarification_response(self, content: str) -> bool:
        """Detect if the AI is asking for clarification instead of producing a plan."""
        if not content:
            return False
        # If content has question marks and no JSON-like structure, it's likely a clarification
        has_questions = content.count("?") >= 1
        has_json = "{" in content and "}" in content
        return has_questions and not has_json

    # ------------------------------------------------------------------
    # Message History Cleaning
    # ------------------------------------------------------------------

    def _strip_tool_messages(self, messages: List[Dict[str, Any]]) -> None:
        """
        Remove tool-related messages from conversation history in-place.

        Bedrock rejects both:
        1. tool_calls in history without tools= param
        2. tool_choice=none

        This method condenses the tool interaction into a text summary
        so the LLM retains research context without tool message artifacts.
        """
        # Collect tool result summaries before stripping
        tool_summaries: List[str] = []
        for msg in messages:
            if msg.get("role") == "tool":
                content = msg.get("content", "")
                # Truncate large tool results for the summary
                if len(content) > 500:
                    content = content[:500] + "..."
                tool_summaries.append(content)

        # Remove assistant messages with tool_calls and tool result messages
        i = 0
        while i < len(messages):
            msg = messages[i]
            if msg.get("role") == "tool":
                messages.pop(i)
                continue
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                messages.pop(i)
                continue
            i += 1

        # Insert a summary of the research findings after the user prompt
        if tool_summaries:
            # Find the first user message to insert after
            insert_idx = 2  # After system + user prompt
            for idx, msg in enumerate(messages):
                if msg.get("role") == "user":
                    insert_idx = idx + 1
                    break

            summary_text = "Research findings from planning phase:\n\n" + "\n\n---\n\n".join(tool_summaries)
            messages.insert(insert_idx, {
                "role": "assistant",
                "content": summary_text,
            })

    # ------------------------------------------------------------------
    # User Prompt Building
    # ------------------------------------------------------------------

    def _build_user_prompt(
        self,
        prompt: str,
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

Fix these errors and return the corrected Typed Plan JSON.

Return ONLY the corrected JSON."""

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


# Global service instance
procedure_generator_service = ProcedureGeneratorService()

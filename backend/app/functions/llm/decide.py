# backend/app/functions/llm/decide.py
"""
Decide function - Boolean decision gate using LLM.

Evaluates data against a question/criteria and returns a boolean (true/false)
decision. Designed to be used as a conditional gate in procedures.

The function forces the LLM to output a strict JSON response with:
- decision: true or false
- confidence: 0.0-1.0
- reasoning: explanation (optional)

Example usage in a procedure:
    - name: should_escalate
      function: llm_decide
      params:
        question: "Does this notice require immediate attention?"
        data: "{{ item.description }}"
        criteria: "Urgent if deadline is within 7 days or marked high priority"

    - name: send_alert
      function: send_email
      condition: "steps.should_escalate.decision == true"
      params:
        to: "alerts@company.com"
        subject: "Urgent Notice Requires Attention"
"""

import json
from typing import Any, Dict, List, Optional
import logging

from jinja2 import Template

from ..base import (
    BaseFunction,
    FunctionMeta,
    FunctionCategory,
    FunctionResult,
    ParameterDoc,
    OutputFieldDoc,
    OutputSchema,
    OutputVariant,
)
from ..context import FunctionContext
from ...models.llm_models import LLMTaskType
from ...services.config_loader import config_loader

logger = logging.getLogger("curatore.functions.llm.decide")


def _render_item_template(template_str: str, item: Any) -> str:
    """Render a Jinja2 template string with item context."""
    template = Template(template_str)
    return template.render(item=item)


class DecideFunction(BaseFunction):
    """
    Make a boolean decision using an LLM.

    Evaluates data against a question or criteria and returns true/false.
    Designed as a decision gate for conditional procedure flow.

    The function returns:
    - decision: boolean (true/false)
    - confidence: float (0.0-1.0)
    - reasoning: string (optional explanation)

    Example:
        result = await fn.decide(ctx,
            question="Is this document relevant to federal contracting?",
            data="Request for Proposal for IT services...",
            criteria="Relevant if mentions federal agency, contracting, or procurement",
        )
        # result.data = {"decision": true, "confidence": 0.92, "reasoning": "..."}
    """

    meta = FunctionMeta(
        name="llm_decide",
        category=FunctionCategory.LOGIC,
        description="Make a boolean (yes/no) decision using an LLM",
        parameters=[
            ParameterDoc(
                name="question",
                type="str",
                description="The yes/no question to answer about the data",
                required=True,
                example="Should this opportunity be flagged for review?",
            ),
            ParameterDoc(
                name="data",
                type="str",
                description="The data/content to evaluate",
                required=True,
                example="Contract opportunity for IT modernization...",
            ),
            ParameterDoc(
                name="criteria",
                type="str",
                description="Additional criteria or context for making the decision",
                required=False,
                default=None,
                example="Flag if value > $1M or involves AI/ML technologies",
            ),
            ParameterDoc(
                name="system_prompt",
                type="str",
                description="Custom system prompt to override the default",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="default_on_error",
                type="bool",
                description="Default decision if LLM fails to respond properly",
                required=False,
                default=False,
            ),
            ParameterDoc(
                name="confidence_threshold",
                type="float",
                description="Minimum confidence required (below this returns default_on_error)",
                required=False,
                default=0.0,
            ),
            ParameterDoc(
                name="include_reasoning",
                type="bool",
                description="Include reasoning in the response",
                required=False,
                default=True,
            ),
            ParameterDoc(
                name="model",
                type="str",
                description="Model to use (uses default if not specified)",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="items",
                type="list",
                description="Collection of items to evaluate. When provided, data is rendered for each item with {{ item.xxx }} placeholders.",
                required=False,
                default=None,
                example=[{"title": "Item 1", "desc": "..."}, {"title": "Item 2", "desc": "..."}],
            ),
        ],
        returns="dict: {decision: bool, confidence: float, reasoning: str}",
        output_schema=OutputSchema(
            type="dict",
            description="Boolean decision result with confidence and reasoning",
            fields=[
                OutputFieldDoc(name="decision", type="bool",
                              description="The yes/no decision (true=yes, false=no)",
                              example=True),
                OutputFieldDoc(name="confidence", type="float",
                              description="Confidence score (0.0-1.0)",
                              example=0.92),
                OutputFieldDoc(name="reasoning", type="str",
                              description="Explanation for the decision",
                              nullable=True),
                OutputFieldDoc(name="below_threshold", type="bool",
                              description="True if confidence was below threshold and default was used",
                              nullable=True),
            ],
        ),
        output_variants=[
            OutputVariant(
                mode="collection",
                condition="when `items` parameter is provided",
                schema=OutputSchema(
                    type="list[dict]",
                    description="List of decision results for each item",
                    fields=[
                        OutputFieldDoc(name="item_id", type="str",
                                      description="ID of the processed item"),
                        OutputFieldDoc(name="decision", type="bool",
                                      description="The yes/no decision"),
                        OutputFieldDoc(name="confidence", type="float",
                                      description="Confidence score (0.0-1.0)"),
                        OutputFieldDoc(name="reasoning", type="str",
                                      description="Explanation", nullable=True),
                        OutputFieldDoc(name="success", type="bool",
                                      description="Whether evaluation succeeded"),
                        OutputFieldDoc(name="error", type="str",
                                      description="Error message if failed", nullable=True),
                    ],
                ),
            ),
        ],
        tags=["llm", "decision", "gate", "conditional", "boolean"],
        requires_llm=True,
        examples=[
            {
                "description": "Simple yes/no decision",
                "params": {
                    "question": "Is this email spam?",
                    "data": "FREE MONEY! Click here now!!!",
                },
            },
            {
                "description": "Decision with criteria",
                "params": {
                    "question": "Should this opportunity be pursued?",
                    "data": "RFP for cloud migration services, $2M value",
                    "criteria": "Pursue if aligns with our core capabilities (cloud, DevOps, AI) and value > $500K",
                },
            },
            {
                "description": "Decision with confidence threshold",
                "params": {
                    "question": "Is this document classified?",
                    "data": "Internal memo about Q4 planning...",
                    "confidence_threshold": 0.8,
                    "default_on_error": True,
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Execute boolean decision."""
        question = params["question"]
        data = params["data"]
        criteria = params.get("criteria")
        system_prompt = params.get("system_prompt")
        default_on_error = params.get("default_on_error", False)
        confidence_threshold = params.get("confidence_threshold", 0.0)
        include_reasoning = params.get("include_reasoning", True)
        model = params.get("model")
        items = params.get("items")

        if not ctx.llm_service.is_available:
            return FunctionResult.failed_result(
                error="LLM service is not available",
                message="Cannot decide: LLM service not configured",
            )

        # Collection mode: iterate over items
        if items and isinstance(items, list):
            return await self._execute_collection(
                ctx=ctx,
                items=items,
                question=question,
                data_template=data,
                criteria=criteria,
                system_prompt=system_prompt,
                default_on_error=default_on_error,
                confidence_threshold=confidence_threshold,
                include_reasoning=include_reasoning,
                model=model,
            )

        # Single mode: decide once
        return await self._execute_single(
            ctx=ctx,
            question=question,
            data=data,
            criteria=criteria,
            system_prompt=system_prompt,
            default_on_error=default_on_error,
            confidence_threshold=confidence_threshold,
            include_reasoning=include_reasoning,
            model=model,
        )

    def _build_system_prompt(self, custom_prompt: Optional[str], criteria: Optional[str]) -> str:
        """Build the system prompt for decision making."""
        if custom_prompt:
            return custom_prompt

        base_prompt = """You are a precise decision-making assistant. Your task is to answer a yes/no question about the provided data.

IMPORTANT RULES:
1. You MUST respond with valid JSON only - no markdown, no explanation outside the JSON
2. The "decision" field MUST be exactly true or false (boolean, not string)
3. The "confidence" field MUST be a number between 0.0 and 1.0
4. Be decisive - avoid confidence values near 0.5 unless truly ambiguous

OUTPUT FORMAT (respond with ONLY this JSON structure):
{"decision": true, "confidence": 0.95, "reasoning": "Brief explanation"}"""

        if criteria:
            base_prompt += f"""

DECISION CRITERIA:
{criteria}"""

        return base_prompt

    def _parse_decision_response(self, response_text: str) -> dict:
        """Parse JSON from response, handling various formats."""
        # Strip markdown code blocks if present
        text = response_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                if line.startswith("```"):
                    in_block = not in_block
                    continue
                if in_block:
                    json_lines.append(line)
            text = "\n".join(json_lines)

        result = json.loads(text)

        # Normalize decision to boolean
        decision = result.get("decision")
        if isinstance(decision, str):
            decision = decision.lower() in ("true", "yes", "1", "y")
        elif isinstance(decision, (int, float)):
            decision = bool(decision)
        else:
            decision = bool(decision)

        result["decision"] = decision

        # Ensure confidence is a float
        confidence = result.get("confidence", 0.5)
        if isinstance(confidence, str):
            try:
                confidence = float(confidence)
            except ValueError:
                confidence = 0.5
        result["confidence"] = max(0.0, min(1.0, float(confidence)))

        return result

    async def _execute_single(
        self,
        ctx: FunctionContext,
        question: str,
        data: str,
        criteria: Optional[str],
        system_prompt: Optional[str],
        default_on_error: bool,
        confidence_threshold: float,
        include_reasoning: bool,
        model: Optional[str],
    ) -> FunctionResult:
        """Execute single decision."""
        try:
            final_system_prompt = self._build_system_prompt(system_prompt, criteria)

            user_prompt = f"""QUESTION: {question}

DATA TO EVALUATE:
---
{data[:5000]}
---

Respond with JSON only:"""

            # Get model and temperature from task type routing (QUICK for decisions)
            task_config = config_loader.get_task_type_config(LLMTaskType.QUICK)
            resolved_model = model or task_config.model
            temperature = task_config.temperature if task_config.temperature is not None else 0.1

            # Generate
            response = ctx.llm_service._client.chat.completions.create(
                model=resolved_model,
                messages=[
                    {"role": "system", "content": final_system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=300,
            )

            response_text = response.choices[0].message.content.strip()
            result = self._parse_decision_response(response_text)

            # Apply confidence threshold
            if result["confidence"] < confidence_threshold:
                logger.info(
                    f"Decision confidence {result['confidence']:.2f} below threshold {confidence_threshold}, using default"
                )
                result["decision"] = default_on_error
                result["below_threshold"] = True

            if not include_reasoning:
                result.pop("reasoning", None)

            return FunctionResult.success_result(
                data=result,
                message=f"Decision: {'YES' if result['decision'] else 'NO'} (confidence: {result['confidence']:.2f})",
                metadata={
                    "model": response.model,
                    "question": question[:100],
                    "criteria_provided": criteria is not None,
                },
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse decision response: {e}")
            # Return default on JSON parse error
            return FunctionResult.success_result(
                data={
                    "decision": default_on_error,
                    "confidence": 0.0,
                    "reasoning": f"Failed to parse LLM response, using default: {default_on_error}",
                    "parse_error": True,
                },
                message=f"Decision: {'YES' if default_on_error else 'NO'} (default due to parse error)",
            )
        except Exception as e:
            logger.exception(f"Decision failed: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Decision evaluation failed",
            )

    async def _execute_collection(
        self,
        ctx: FunctionContext,
        items: List[Any],
        question: str,
        data_template: str,
        criteria: Optional[str],
        system_prompt: Optional[str],
        default_on_error: bool,
        confidence_threshold: float,
        include_reasoning: bool,
        model: Optional[str],
    ) -> FunctionResult:
        """Execute decision for each item in collection."""
        results = []
        failed_count = 0
        true_count = 0

        final_system_prompt = self._build_system_prompt(system_prompt, criteria)

        # Get model and temperature from task type routing (BULK for collection mode)
        task_config = config_loader.get_task_type_config(LLMTaskType.BULK)
        resolved_model = model or task_config.model
        temperature = task_config.temperature if task_config.temperature is not None else 0.1

        for idx, item in enumerate(items):
            try:
                # Render data with item context
                rendered_data = _render_item_template(data_template, item)

                user_prompt = f"""QUESTION: {question}

DATA TO EVALUATE:
---
{rendered_data[:5000]}
---

Respond with JSON only:"""

                # Generate
                response = ctx.llm_service._client.chat.completions.create(
                    model=resolved_model,
                    messages=[
                        {"role": "system", "content": final_system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature,
                    max_tokens=300,
                )

                response_text = response.choices[0].message.content.strip()
                decision_result = self._parse_decision_response(response_text)

                # Apply confidence threshold
                if decision_result["confidence"] < confidence_threshold:
                    decision_result["decision"] = default_on_error
                    decision_result["below_threshold"] = True

                if not include_reasoning:
                    decision_result.pop("reasoning", None)

                if decision_result["decision"]:
                    true_count += 1

                # Extract item ID if available
                item_id = None
                if isinstance(item, dict):
                    item_id = item.get("id") or item.get("item_id") or str(idx)
                else:
                    item_id = str(idx)

                results.append({
                    "item_id": item_id,
                    "decision": decision_result["decision"],
                    "confidence": decision_result["confidence"],
                    "reasoning": decision_result.get("reasoning"),
                    "success": True,
                })

            except json.JSONDecodeError as e:
                logger.warning(f"Decision failed for item {idx}: invalid JSON - {e}")
                failed_count += 1
                results.append({
                    "item_id": item.get("id") if isinstance(item, dict) else str(idx),
                    "decision": default_on_error,
                    "confidence": 0.0,
                    "success": False,
                    "error": f"Invalid JSON response: {e}",
                })
                if default_on_error:
                    true_count += 1
            except Exception as e:
                logger.warning(f"Decision failed for item {idx}: {e}")
                failed_count += 1
                results.append({
                    "item_id": item.get("id") if isinstance(item, dict) else str(idx),
                    "decision": default_on_error,
                    "confidence": 0.0,
                    "success": False,
                    "error": str(e),
                })
                if default_on_error:
                    true_count += 1

        return FunctionResult.success_result(
            data=results,
            message=f"Evaluated {len(results)} items: {true_count} YES, {len(results) - true_count} NO",
            metadata={
                "mode": "collection",
                "total_items": len(items),
                "successful_items": len(items) - failed_count,
                "failed_items": failed_count,
                "true_count": true_count,
                "false_count": len(results) - true_count,
            },
            items_processed=len(items),
            items_failed=failed_count,
        )

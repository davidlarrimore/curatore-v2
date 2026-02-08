# backend/app/api/v1/routers/procedures.py
"""
Procedures API router.

Provides endpoints for:
- Listing procedures
- Getting procedure details
- Running procedures
- Managing triggers
"""

from typing import Any, Dict, List, Optional
from uuid import UUID
from datetime import datetime
import logging

from croniter import croniter
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel, Field
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.shared.database_service import database_service
from app.dependencies import get_current_user, get_current_user_optional, get_optional_current_user, get_current_org_id
from app.core.database.models import User
from app.core.database.procedures import Procedure, ProcedureTrigger, ProcedureVersion
from app.cwr.procedures import procedure_executor, procedure_loader

logger = logging.getLogger("curatore.api.procedures")


def calculate_next_trigger_at(cron_expression: str, base_time: Optional[datetime] = None) -> Optional[datetime]:
    """
    Calculate the next trigger time for a cron expression.

    Args:
        cron_expression: A valid cron expression (5-field or 6-field)
        base_time: Base time to calculate from (defaults to now)

    Returns:
        The next trigger datetime, or None if invalid
    """
    if not cron_expression:
        return None
    try:
        base = base_time or datetime.utcnow()
        cron = croniter(cron_expression, base)
        return cron.get_next(datetime)
    except Exception as e:
        logger.warning(f"Failed to parse cron expression '{cron_expression}': {e}")
        return None

router = APIRouter(prefix="/procedures", tags=["Procedures"])


# =============================================================================
# PYDANTIC MODELS
# =============================================================================


class TriggerSchema(BaseModel):
    """Trigger configuration schema."""
    id: Optional[str] = None
    trigger_type: str
    cron_expression: Optional[str] = None
    event_name: Optional[str] = None
    event_filter: Optional[Dict[str, Any]] = None
    is_active: bool = True
    last_triggered_at: Optional[datetime] = None
    next_trigger_at: Optional[datetime] = None


class ProcedureSchema(BaseModel):
    """Procedure schema."""
    id: str
    name: str
    slug: str
    description: Optional[str] = None
    version: int
    is_active: bool
    is_system: bool
    source_type: str
    definition: Dict[str, Any]
    triggers: List[TriggerSchema] = []
    created_at: datetime
    updated_at: datetime


class ProcedureListItem(BaseModel):
    """Procedure list item schema."""
    id: str
    name: str
    slug: str
    description: Optional[str] = None
    version: int
    is_active: bool
    is_system: bool
    source_type: str
    trigger_count: int = 0
    next_trigger_at: Optional[datetime] = None  # Soonest scheduled run time
    tags: List[str] = []
    created_at: datetime
    updated_at: datetime


class ProcedureListResponse(BaseModel):
    """List of procedures response."""
    procedures: List[ProcedureListItem]
    total: int


class RunProcedureRequest(BaseModel):
    """Request to run a procedure."""
    params: Dict[str, Any] = Field(default_factory=dict, description="Procedure parameters")
    dry_run: bool = Field(default=False, description="If true, don't make changes")
    async_execution: bool = Field(default=True, description="Run asynchronously via Celery")


class RunProcedureResponse(BaseModel):
    """Procedure run response."""
    run_id: Optional[str] = None
    status: str
    message: Optional[str] = None
    results: Optional[Dict[str, Any]] = None


class CreateTriggerRequest(BaseModel):
    """Request to create a trigger."""
    trigger_type: str = Field(..., description="Type: cron, event, webhook")
    cron_expression: Optional[str] = Field(None, description="Cron expression (for cron triggers)")
    event_name: Optional[str] = Field(None, description="Event name (for event triggers)")
    event_filter: Optional[Dict[str, Any]] = Field(None, description="Event filter")
    trigger_params: Optional[Dict[str, Any]] = Field(None, description="Parameters to pass when triggered")


class StepSchema(BaseModel):
    """Step definition for a procedure."""
    name: str = Field(..., description="Unique name for this step")
    function: str = Field(..., description="Function to call (e.g., 'query_model', 'llm_generate')")
    params: Dict[str, Any] = Field(default_factory=dict, description="Function parameters (supports Jinja2 templates)")
    on_error: str = Field(default="fail", description="Error policy: fail, skip, or continue")
    condition: Optional[str] = Field(None, description="Jinja2 condition - step runs only if true")
    description: str = Field(default="", description="Step description")
    foreach: Optional[str] = Field(None, description="Jinja2 expression for iteration (e.g., '{{ steps.query.data }}')")
    branches: Optional[Dict[str, List["StepSchema"]]] = Field(
        None,
        description="Named branches for flow control functions (if_branch, switch_branch, parallel, foreach). "
        "Each key is a branch name, and the value is a list of steps to execute for that branch."
    )


# Resolve forward reference for recursive StepSchema
StepSchema.model_rebuild()


class ParameterSchema(BaseModel):
    """Parameter definition for a procedure."""
    name: str = Field(..., description="Parameter name")
    type: str = Field(default="str", description="Parameter type")
    description: str = Field(default="", description="Parameter description")
    required: bool = Field(default=False, description="Whether parameter is required")
    default: Any = Field(default=None, description="Default value")
    enum_values: Optional[List[str]] = Field(default=None, description="Allowed values")


class CreateProcedureRequest(BaseModel):
    """Request to create a new procedure."""
    name: str = Field(..., description="Human-readable procedure name")
    slug: str = Field(..., description="URL-friendly identifier (unique per org)", pattern=r"^[a-z][a-z0-9_-]*$")
    description: Optional[str] = Field(None, description="Procedure description")
    parameters: List[ParameterSchema] = Field(default_factory=list, description="Input parameters")
    steps: List[StepSchema] = Field(..., description="Procedure steps (at least one required)", min_length=1)
    on_error: str = Field(default="fail", description="Default error policy: fail, skip, or continue")
    tags: List[str] = Field(default_factory=list, description="Tags for organization")


class UpdateProcedureRequest(BaseModel):
    """Request to update procedure settings or definition."""
    is_active: Optional[bool] = None
    description: Optional[str] = None
    # For updating the definition (user-created procedures only)
    name: Optional[str] = None
    parameters: Optional[List[ParameterSchema]] = None
    steps: Optional[List[StepSchema]] = None
    on_error: Optional[str] = None
    tags: Optional[List[str]] = None
    change_summary: Optional[str] = Field(None, description="Optional description of what changed in this version")


class ValidationErrorDetail(BaseModel):
    """A single validation error."""
    code: str
    message: str
    path: str
    details: Dict[str, Any] = Field(default_factory=dict)


class ValidationErrorResponse(BaseModel):
    """Response when procedure validation fails."""
    valid: bool = False
    errors: List[ValidationErrorDetail]
    warnings: List[ValidationErrorDetail] = Field(default_factory=list)
    error_count: int
    warning_count: int = 0


class GenerateProcedureRequest(BaseModel):
    """Request to generate or refine a procedure using AI."""
    prompt: str = Field(
        ...,
        description="Natural language description of the procedure to generate, or changes to make if refining an existing procedure",
        min_length=10,
        max_length=5000,
        examples=[
            "Create a procedure that sends a daily email summary of new SAM.gov opportunities",
            "Add a logging step before the email is sent",
        ],
    )
    current_yaml: Optional[str] = Field(
        default=None,
        description="Current procedure YAML to refine. If provided, the prompt describes changes to make to this procedure.",
        max_length=50000,
    )
    include_examples: bool = Field(
        default=True,
        description="Whether to include example procedures in the AI context",
    )
    profile: Optional[str] = Field(
        default="workflow_standard",
        description="Generation profile: safe_readonly, workflow_standard, or admin_full",
    )
    current_plan: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Current Typed Plan JSON to refine. If provided, modifications apply to this plan.",
    )


class GenerateProcedureResponse(BaseModel):
    """Response from procedure generation."""
    success: bool = Field(description="Whether generation succeeded")
    yaml: Optional[str] = Field(default=None, description="Generated YAML content (if successful)")
    procedure: Optional[Dict[str, Any]] = Field(default=None, description="Parsed procedure definition (if successful)")
    plan_json: Optional[Dict[str, Any]] = Field(default=None, description="Typed Plan JSON (intermediate representation)")
    error: Optional[str] = Field(default=None, description="Error message (if failed)")
    attempts: int = Field(description="Number of generation attempts made")
    validation_errors: List[ValidationErrorDetail] = Field(
        default_factory=list,
        description="Final validation errors (if generation failed)",
    )
    validation_warnings: List[ValidationErrorDetail] = Field(
        default_factory=list,
        description="Validation warnings after LLM review (procedure is valid but may have issues)",
    )
    profile_used: Optional[str] = Field(default=None, description="Generation profile that was used")
    diagnostics: Optional[Dict[str, Any]] = Field(default=None, description="Generation diagnostics (timing, tools, attempts)")


# =============================================================================
# ENDPOINTS
# =============================================================================


class ReloadProceduresResponse(BaseModel):
    """Response for procedure reload."""
    status: str
    message: str
    procedures_loaded: int = Field(description="Number of procedures loaded from disk")
    slugs: List[str] = Field(default_factory=list, description="List of procedure slugs loaded")
    database: Dict[str, Any] = Field(default_factory=dict, description="Database sync statistics")


@router.post("/reload", response_model=ReloadProceduresResponse)
async def reload_procedures(
    organization_id: UUID = Depends(get_current_org_id),
):
    """
    Reload all procedure definitions from YAML files.

    Clears the in-memory cache and re-discovers all procedure YAML files,
    then syncs them with the database. Use this to pick up changes to
    procedure definitions without restarting the server.

    Returns statistics about what was reloaded.
    """
    from app.cwr.procedures import procedure_discovery_service

    # Reload from disk (clears cache and re-discovers)
    definitions = procedure_loader.reload()
    slugs = list(definitions.keys())

    logger.info(f"Reloaded {len(definitions)} procedure definitions from disk")

    # Sync with database
    async with database_service.get_session() as session:
        db_stats = await procedure_discovery_service.discover_and_register(
            session=session,
            organization_id=organization_id,
        )

    return ReloadProceduresResponse(
        status="success",
        message=f"Reloaded {len(definitions)} procedures from disk",
        procedures_loaded=len(definitions),
        slugs=slugs,
        database=db_stats,
    )


@router.post("/validate", response_model=ValidationErrorResponse)
async def validate_procedure(
    request: CreateProcedureRequest,
    organization_id: UUID = Depends(get_current_org_id),
):
    """
    Validate a procedure definition without saving.

    Returns validation errors and warnings. Use this to check a procedure
    before saving.
    """
    from app.cwr.contracts.validation import validate_procedure as do_validate

    # Build definition dict
    definition = {
        "name": request.name,
        "slug": request.slug,
        "description": request.description or "",
        "version": "1.0.0",
        "parameters": [p.model_dump() for p in request.parameters],
        "steps": [s.model_dump() for s in request.steps],
        "outputs": [],
        "triggers": [],
        "on_error": request.on_error,
        "tags": request.tags,
    }

    result = do_validate(definition)

    return ValidationErrorResponse(
        valid=result.valid,
        errors=[ValidationErrorDetail(**e.to_dict()) for e in result.errors],
        warnings=[ValidationErrorDetail(**w.to_dict()) for w in result.warnings],
        error_count=len(result.errors),
        warning_count=len(result.warnings),
    )


@router.post("/generate", response_model=GenerateProcedureResponse)
async def generate_procedure(
    request: GenerateProcedureRequest,
    organization_id: UUID = Depends(get_current_org_id),
):
    """
    Generate or refine a procedure YAML definition using AI.

    **Generate Mode** (no current_yaml):
    Takes a natural language description and generates a valid procedure YAML
    from scratch.

    **Refine Mode** (with current_yaml):
    Modifies the provided procedure YAML based on the prompt.
    Use this to make incremental changes like "add a logging step" or
    "change the email recipient".

    The AI is provided with:
    - Complete catalog of available functions and their parameters
    - Example procedure patterns
    - Understanding of the Curatore system and procedure structure
    - The current procedure definition (in refine mode)

    Args:
        request: GenerateProcedureRequest with:
            - prompt: Description of procedure to create, or changes to make
            - current_yaml: (optional) Current procedure YAML to refine

    Returns:
        GenerateProcedureResponse with:
        - success: Whether generation succeeded
        - yaml: Generated/modified YAML content (if successful)
        - procedure: Parsed procedure dict (if successful)
        - error: Error message (if failed)
        - attempts: Number of generation attempts
        - validation_errors: Final validation errors (if failed)

    Example prompts (generate mode):
        - "Create a procedure that sends a daily email summary of new assets"
        - "Build a workflow that analyzes SAM.gov opportunities"

    Example prompts (refine mode):
        - "Add a step that logs the results before sending email"
        - "Change the email recipient to reports@company.com"
        - "Increase the search limit to 100"

    Note:
        The generated procedure is NOT saved automatically. Use the POST /procedures
        endpoint to save the generated procedure after reviewing it.
    """
    from app.cwr.procedures.compiler.ai_generator import procedure_generator_service
    from app.core.shared.database_service import database_service

    if request.current_yaml:
        logger.info(f"Refining procedure with prompt: {request.prompt[:100]}...")
    else:
        logger.info(f"Generating procedure from prompt: {request.prompt[:100]}...")

    # Use database session to fetch available data sources for context
    async with database_service.get_session() as session:
        result = await procedure_generator_service.generate_procedure(
            prompt=request.prompt,
            organization_id=organization_id,
            session=session,
            include_examples=request.include_examples,
            current_yaml=request.current_yaml,
            profile=request.profile or "workflow_standard",
            current_plan=request.current_plan,
        )

    # Convert validation errors to response format
    validation_errors = [
        ValidationErrorDetail(
            code=e.get("code", "UNKNOWN"),
            message=e.get("message", "Unknown error"),
            path=e.get("path", ""),
            details=e.get("details", {}),
        )
        for e in result.get("validation_errors", [])
    ]

    # Convert validation warnings to response format
    validation_warnings = [
        ValidationErrorDetail(
            code=w.get("code", "UNKNOWN"),
            message=w.get("message", "Unknown warning"),
            path=w.get("path", ""),
            details=w.get("details", {}),
        )
        for w in result.get("validation_warnings", [])
    ]

    return GenerateProcedureResponse(
        success=result["success"],
        yaml=result.get("yaml"),
        procedure=result.get("procedure"),
        plan_json=result.get("plan_json"),
        error=result.get("error"),
        attempts=result.get("attempts", 0),
        validation_errors=validation_errors,
        validation_warnings=validation_warnings,
        profile_used=result.get("profile_used"),
        diagnostics=result.get("diagnostics"),
    )


@router.get("/profiles")
async def get_generation_profiles():
    """
    Get available generation profiles for the AI procedure generator.

    Returns a list of profiles with their names, descriptions, and constraints.
    """
    from app.cwr.governance.generation_profiles import get_available_profiles
    return get_available_profiles()


class ValidateDraftRequest(BaseModel):
    """Request to validate a Typed Plan JSON."""
    plan: Dict[str, Any] = Field(..., description="Typed Plan JSON to validate")
    profile: Optional[str] = Field(
        default="workflow_standard",
        description="Generation profile to validate against",
    )


@router.post("/drafts/validate")
async def validate_draft(
    request: ValidateDraftRequest,
    organization_id: UUID = Depends(get_current_org_id),
):
    """
    Validate a Typed Plan JSON against schema, tool contracts, and policy.

    Returns validation result with errors and warnings.
    """
    from app.cwr.governance.generation_profiles import get_profile
    from app.cwr.contracts.contract_pack import get_tool_contract_pack
    from app.cwr.procedures.compiler.plan_validator import PlanValidator

    profile = get_profile(request.profile)
    contract_pack = get_tool_contract_pack(org_id=organization_id, profile=profile)
    validator = PlanValidator(contract_pack)
    result = validator.validate(request.plan)

    return {
        "valid": result.valid,
        "errors": [e.to_dict() for e in result.errors],
        "warnings": [w.to_dict() for w in result.warnings],
        "error_count": len(result.errors),
        "warning_count": len(result.warnings),
    }


@router.post("/", response_model=ProcedureSchema, status_code=201)
async def create_procedure(
    request: CreateProcedureRequest,
    organization_id: UUID = Depends(get_current_org_id),
    user: Optional[Any] = Depends(get_optional_current_user),
):
    """
    Create a new user-defined procedure.

    User-created procedures are stored in the database and can be edited
    via the API. They run alongside YAML-defined system procedures.

    The procedure definition uses Jinja2 templating for dynamic values:
    - {{ params.xxx }}: Access procedure parameters
    - {{ steps.step_name }}: Access results from previous steps
    - {{ item }}: Current item when using foreach
    - {{ now() }}, {{ today() }}: Date/time functions

    Returns 422 with validation errors if the procedure is invalid.
    """
    from app.core.database.procedures import Procedure
    from app.cwr.contracts.validation import validate_procedure as do_validate

    # Build definition dict
    definition = {
        "name": request.name,
        "slug": request.slug,
        "description": request.description or "",
        "version": "1.0.0",
        "parameters": [p.model_dump() for p in request.parameters],
        "steps": [s.model_dump() for s in request.steps],
        "outputs": [],
        "triggers": [],
        "on_error": request.on_error,
        "tags": request.tags,
    }

    # Validate before saving
    validation_result = do_validate(definition)
    if not validation_result.valid:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Procedure validation failed",
                "validation": validation_result.to_dict(),
            },
        )

    async with database_service.get_session() as session:
        # Check for duplicate slug
        existing_query = select(Procedure).where(
            Procedure.organization_id == organization_id,
            Procedure.slug == request.slug,
        )
        result = await session.execute(existing_query)
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=400,
                detail=f"Procedure with slug '{request.slug}' already exists",
            )

        # Create procedure
        procedure = Procedure(
            organization_id=organization_id,
            name=request.name,
            slug=request.slug,
            description=request.description,
            definition=definition,
            version=1,
            is_active=True,
            is_system=False,
            source_type="user",
            source_path=None,
            created_by=user.id if user else None,
        )
        session.add(procedure)
        await session.flush()  # Get the procedure.id before creating version

        # Save initial version snapshot
        version_record = ProcedureVersion(
            procedure_id=procedure.id,
            version=1,
            definition=definition,
            change_summary="Initial version",
            created_by=user.id if user else None,
        )
        session.add(version_record)

        await session.commit()
        await session.refresh(procedure)

        logger.info(f"Created user procedure: {request.slug}")

        return ProcedureSchema(
            id=str(procedure.id),
            name=procedure.name,
            slug=procedure.slug,
            description=procedure.description,
            version=procedure.version,
            is_active=procedure.is_active,
            is_system=procedure.is_system,
            source_type=procedure.source_type,
            definition=procedure.definition,
            triggers=[],
            created_at=procedure.created_at,
            updated_at=procedure.updated_at,
        )


@router.get("/", response_model=ProcedureListResponse)
async def list_procedures(
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    organization_id: UUID = Depends(get_current_org_id),
):
    """
    List all procedures.
    """
    async with database_service.get_session() as session:
        query = select(Procedure).where(
            Procedure.organization_id == organization_id,
        )

        if is_active is not None:
            query = query.where(Procedure.is_active == is_active)

        result = await session.execute(query)
        procedures = result.scalars().all()

        items = []
        for proc in procedures:
            definition = proc.definition or {}
            tags = definition.get("tags", [])

            # Filter by tag if specified
            if tag and tag not in tags:
                continue

            # Get triggers for count and next_trigger_at
            trigger_query = select(ProcedureTrigger).where(
                ProcedureTrigger.procedure_id == proc.id,
                ProcedureTrigger.is_active == True,
            )
            trigger_result = await session.execute(trigger_query)
            triggers = trigger_result.scalars().all()
            trigger_count = len(triggers)

            # Find soonest next_trigger_at among cron triggers
            next_trigger_at = None
            for trigger in triggers:
                if trigger.trigger_type == "cron" and trigger.next_trigger_at:
                    if next_trigger_at is None or trigger.next_trigger_at < next_trigger_at:
                        next_trigger_at = trigger.next_trigger_at

            items.append(ProcedureListItem(
                id=str(proc.id),
                name=proc.name,
                slug=proc.slug,
                description=proc.description,
                version=proc.version,
                is_active=proc.is_active,
                is_system=proc.is_system,
                source_type=proc.source_type,
                trigger_count=trigger_count,
                next_trigger_at=next_trigger_at,
                tags=tags,
                created_at=proc.created_at,
                updated_at=proc.updated_at,
            ))

        return ProcedureListResponse(
            procedures=items,
            total=len(items),
        )


@router.get("/{slug}", response_model=ProcedureSchema)
async def get_procedure(
    slug: str,
    organization_id: UUID = Depends(get_current_org_id),
):
    """
    Get procedure details by slug.
    """
    async with database_service.get_session() as session:
        query = select(Procedure).where(
            Procedure.organization_id == organization_id,
            Procedure.slug == slug,
        )
        result = await session.execute(query)
        procedure = result.scalar_one_or_none()

        if not procedure:
            raise HTTPException(status_code=404, detail=f"Procedure not found: {slug}")

        # Get triggers
        trigger_query = select(ProcedureTrigger).where(
            ProcedureTrigger.procedure_id == procedure.id,
        )
        trigger_result = await session.execute(trigger_query)
        triggers = trigger_result.scalars().all()

        return ProcedureSchema(
            id=str(procedure.id),
            name=procedure.name,
            slug=procedure.slug,
            description=procedure.description,
            version=procedure.version,
            is_active=procedure.is_active,
            is_system=procedure.is_system,
            source_type=procedure.source_type,
            definition=procedure.definition,
            triggers=[
                TriggerSchema(
                    id=str(t.id),
                    trigger_type=t.trigger_type,
                    cron_expression=t.cron_expression,
                    event_name=t.event_name,
                    event_filter=t.event_filter,
                    is_active=t.is_active,
                    last_triggered_at=t.last_triggered_at,
                    next_trigger_at=t.next_trigger_at,
                )
                for t in triggers
            ],
            created_at=procedure.created_at,
            updated_at=procedure.updated_at,
        )


@router.put("/{slug}", response_model=ProcedureSchema)
async def update_procedure(
    slug: str,
    request: UpdateProcedureRequest,
    organization_id: UUID = Depends(get_current_org_id),
    user: Optional[Any] = Depends(get_optional_current_user),
):
    """
    Update procedure settings or definition.

    For user-created procedures (source_type='user'), you can update the
    full definition including name, parameters, steps, and tags.

    For system procedures (YAML-defined), only is_active can be changed.
    To update a system procedure's definition, edit the YAML file and
    call POST /procedures/reload.
    """
    async with database_service.get_session() as session:
        query = select(Procedure).where(
            Procedure.organization_id == organization_id,
            Procedure.slug == slug,
        )
        result = await session.execute(query)
        procedure = result.scalar_one_or_none()

        if not procedure:
            raise HTTPException(status_code=404, detail=f"Procedure not found: {slug}")

        # Check if trying to modify definition of system procedure
        definition_fields = [request.name, request.parameters, request.steps, request.on_error, request.tags]
        modifying_definition = any(f is not None for f in definition_fields)

        if procedure.source_type != "user" and modifying_definition:
            raise HTTPException(
                status_code=400,
                detail="Cannot modify definition of system procedures. Edit the YAML file and call POST /procedures/reload instead.",
            )

        if procedure.is_system and request.description is not None:
            raise HTTPException(
                status_code=400,
                detail="Cannot modify description of system procedures",
            )

        # Update basic fields
        if request.is_active is not None:
            procedure.is_active = request.is_active
        if request.description is not None:
            procedure.description = request.description

        # Update definition for user-created procedures
        if procedure.source_type == "user" and modifying_definition:
            from app.cwr.contracts.validation import validate_procedure as do_validate

            definition = procedure.definition.copy() if procedure.definition else {}

            if request.name is not None:
                procedure.name = request.name
                definition["name"] = request.name

            if request.parameters is not None:
                definition["parameters"] = [p.model_dump() for p in request.parameters]

            if request.steps is not None:
                definition["steps"] = [s.model_dump() for s in request.steps]

            if request.on_error is not None:
                definition["on_error"] = request.on_error

            if request.tags is not None:
                definition["tags"] = request.tags

            # Validate the updated definition before saving
            validation_result = do_validate(definition)
            if not validation_result.valid:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "message": "Procedure validation failed",
                        "validation": validation_result.to_dict(),
                    },
                )

            procedure.definition = definition
            procedure.version = procedure.version + 1

            # Save version snapshot
            version_record = ProcedureVersion(
                procedure_id=procedure.id,
                version=procedure.version,
                definition=definition,
                change_summary=request.change_summary,
                created_by=user.id if user else None,
            )
            session.add(version_record)

            logger.info(f"Updated user procedure: {slug} (version {procedure.version})")

        procedure.updated_at = datetime.utcnow()
        await session.commit()

        return await get_procedure(slug, organization_id)


@router.delete("/{slug}")
async def delete_procedure(
    slug: str,
    organization_id: UUID = Depends(get_current_org_id),
):
    """
    Delete a user-created procedure.

    Only user-created procedures (source_type='user') can be deleted.
    System procedures (YAML-defined) cannot be deleted via API.
    """
    async with database_service.get_session() as session:
        query = select(Procedure).where(
            Procedure.organization_id == organization_id,
            Procedure.slug == slug,
        )
        result = await session.execute(query)
        procedure = result.scalar_one_or_none()

        if not procedure:
            raise HTTPException(status_code=404, detail=f"Procedure not found: {slug}")

        if procedure.source_type != "user":
            raise HTTPException(
                status_code=400,
                detail="Cannot delete system procedures. Remove the YAML file and call POST /procedures/reload instead.",
            )

        await session.delete(procedure)
        await session.commit()

        logger.info(f"Deleted user procedure: {slug}")

        return {"status": "deleted", "slug": slug}


@router.post("/{slug}/run", response_model=RunProcedureResponse)
async def run_procedure(
    slug: str,
    request: RunProcedureRequest,
    organization_id: UUID = Depends(get_current_org_id),
    user: Optional[Any] = Depends(get_optional_current_user),
):
    """
    Run a procedure.

    If async_execution is true (default), the procedure runs in the background
    via Celery and returns a run_id for tracking.
    """
    async with database_service.get_session() as session:
        # Verify procedure exists and is active
        query = select(Procedure).where(
            Procedure.organization_id == organization_id,
            Procedure.slug == slug,
        )
        result = await session.execute(query)
        procedure = result.scalar_one_or_none()

        if not procedure:
            raise HTTPException(status_code=404, detail=f"Procedure not found: {slug}")

        if not procedure.is_active:
            raise HTTPException(status_code=400, detail="Procedure is not active")

        user_id = user.id if user else None

        if request.async_execution:
            # Create a Run and dispatch to Celery
            from app.core.shared.run_service import run_service

            run = await run_service.create_run(
                session=session,
                organization_id=organization_id,
                run_type="procedure",
                origin="user" if user_id else "api",
                config={
                    "procedure_slug": slug,
                    "procedure_name": procedure.name,
                    "params": request.params,
                    "dry_run": request.dry_run,
                },
                created_by=user_id,
            )

            # Update run with procedure reference
            from app.core.database.models import Run
            run_query = select(Run).where(Run.id == run.id)
            run_result = await session.execute(run_query)
            run_obj = run_result.scalar_one()
            run_obj.procedure_id = procedure.id
            run_obj.procedure_version = procedure.version

            await session.commit()

            # Dispatch to Celery
            from app.core.tasks import execute_procedure_task
            execute_procedure_task.delay(
                str(run.id),
                str(organization_id),
                slug,
                request.params,
                str(user_id) if user_id else None,
            )

            return RunProcedureResponse(
                run_id=str(run.id),
                status="submitted",
                message=f"Procedure {slug} submitted for execution",
            )
        else:
            # Execute synchronously
            try:
                results = await procedure_executor.execute(
                    session=session,
                    organization_id=organization_id,
                    procedure_slug=slug,
                    params=request.params,
                    user_id=user_id,
                    dry_run=request.dry_run,
                )

                await session.commit()

                return RunProcedureResponse(
                    status=results.get("status", "completed"),
                    message=f"Procedure {slug} executed",
                    results=results,
                )
            except Exception as e:
                logger.exception(f"Procedure execution failed: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Procedure execution failed: {str(e)}",
                )


@router.post("/{slug}/enable", response_model=ProcedureSchema)
async def enable_procedure(
    slug: str,
    organization_id: UUID = Depends(get_current_org_id),
):
    """
    Enable a procedure.
    """
    async with database_service.get_session() as session:
        query = select(Procedure).where(
            Procedure.organization_id == organization_id,
            Procedure.slug == slug,
        )
        result = await session.execute(query)
        procedure = result.scalar_one_or_none()

        if not procedure:
            raise HTTPException(status_code=404, detail=f"Procedure not found: {slug}")

        procedure.is_active = True
        procedure.updated_at = datetime.utcnow()
        await session.commit()

        return await get_procedure(slug, organization_id)


@router.post("/{slug}/disable", response_model=ProcedureSchema)
async def disable_procedure(
    slug: str,
    organization_id: UUID = Depends(get_current_org_id),
):
    """
    Disable a procedure.
    """
    async with database_service.get_session() as session:
        query = select(Procedure).where(
            Procedure.organization_id == organization_id,
            Procedure.slug == slug,
        )
        result = await session.execute(query)
        procedure = result.scalar_one_or_none()

        if not procedure:
            raise HTTPException(status_code=404, detail=f"Procedure not found: {slug}")

        procedure.is_active = False
        procedure.updated_at = datetime.utcnow()
        await session.commit()

        return await get_procedure(slug, organization_id)


# =============================================================================
# TRIGGER ENDPOINTS
# =============================================================================


@router.get("/{slug}/triggers", response_model=List[TriggerSchema])
async def list_triggers(
    slug: str,
    organization_id: UUID = Depends(get_current_org_id),
):
    """
    List triggers for a procedure.
    """
    async with database_service.get_session() as session:
        # Get procedure
        proc_query = select(Procedure).where(
            Procedure.organization_id == organization_id,
            Procedure.slug == slug,
        )
        result = await session.execute(proc_query)
        procedure = result.scalar_one_or_none()

        if not procedure:
            raise HTTPException(status_code=404, detail=f"Procedure not found: {slug}")

        # Get triggers
        trigger_query = select(ProcedureTrigger).where(
            ProcedureTrigger.procedure_id == procedure.id,
        )
        result = await session.execute(trigger_query)
        triggers = result.scalars().all()

        return [
            TriggerSchema(
                id=str(t.id),
                trigger_type=t.trigger_type,
                cron_expression=t.cron_expression,
                event_name=t.event_name,
                event_filter=t.event_filter,
                is_active=t.is_active,
                last_triggered_at=t.last_triggered_at,
                next_trigger_at=t.next_trigger_at,
            )
            for t in triggers
        ]


@router.post("/{slug}/triggers", response_model=TriggerSchema)
async def create_trigger(
    slug: str,
    request: CreateTriggerRequest,
    organization_id: UUID = Depends(get_current_org_id),
):
    """
    Create a trigger for a procedure.
    """
    async with database_service.get_session() as session:
        # Get procedure
        proc_query = select(Procedure).where(
            Procedure.organization_id == organization_id,
            Procedure.slug == slug,
        )
        result = await session.execute(proc_query)
        procedure = result.scalar_one_or_none()

        if not procedure:
            raise HTTPException(status_code=404, detail=f"Procedure not found: {slug}")

        # Validate trigger type
        if request.trigger_type not in ["cron", "event", "webhook"]:
            raise HTTPException(status_code=400, detail="Invalid trigger type")

        if request.trigger_type == "cron" and not request.cron_expression:
            raise HTTPException(status_code=400, detail="Cron expression required for cron triggers")

        if request.trigger_type == "event" and not request.event_name:
            raise HTTPException(status_code=400, detail="Event name required for event triggers")

        # Calculate next trigger time for cron triggers
        next_trigger_at = None
        if request.trigger_type == "cron" and request.cron_expression:
            next_trigger_at = calculate_next_trigger_at(request.cron_expression)

        # Create trigger
        trigger = ProcedureTrigger(
            procedure_id=procedure.id,
            organization_id=organization_id,
            trigger_type=request.trigger_type,
            cron_expression=request.cron_expression,
            event_name=request.event_name,
            event_filter=request.event_filter,
            trigger_params=request.trigger_params,
            is_active=True,
            next_trigger_at=next_trigger_at,
        )
        session.add(trigger)
        await session.commit()

        return TriggerSchema(
            id=str(trigger.id),
            trigger_type=trigger.trigger_type,
            cron_expression=trigger.cron_expression,
            event_name=trigger.event_name,
            event_filter=trigger.event_filter,
            is_active=trigger.is_active,
            last_triggered_at=trigger.last_triggered_at,
            next_trigger_at=trigger.next_trigger_at,
        )


@router.delete("/{slug}/triggers/{trigger_id}")
async def delete_trigger(
    slug: str,
    trigger_id: str,
    organization_id: UUID = Depends(get_current_org_id),
):
    """
    Delete a trigger.
    """
    async with database_service.get_session() as session:
        trigger_query = select(ProcedureTrigger).where(
            ProcedureTrigger.id == UUID(trigger_id),
            ProcedureTrigger.organization_id == organization_id,
        )
        result = await session.execute(trigger_query)
        trigger = result.scalar_one_or_none()

        if not trigger:
            raise HTTPException(status_code=404, detail="Trigger not found")

        await session.delete(trigger)
        await session.commit()

        return {"status": "deleted"}


# =============================================================================
# VERSION HISTORY ENDPOINTS
# =============================================================================


async def _get_procedure_by_slug(session, organization_id: UUID, slug: str) -> Procedure:
    """Helper to fetch a procedure by slug, raising 404 if not found."""
    query = select(Procedure).where(
        Procedure.organization_id == organization_id,
        Procedure.slug == slug,
    )
    result = await session.execute(query)
    procedure = result.scalar_one_or_none()
    if not procedure:
        raise HTTPException(status_code=404, detail=f"Procedure not found: {slug}")
    return procedure


@router.get("/{slug}/versions")
async def list_versions(
    slug: str,
    organization_id: UUID = Depends(get_current_org_id),
):
    """
    List all versions for a procedure.

    Returns version summaries ordered by version number (newest first).
    """
    async with database_service.get_session() as session:
        procedure = await _get_procedure_by_slug(session, organization_id, slug)

        query = (
            select(ProcedureVersion)
            .where(ProcedureVersion.procedure_id == procedure.id)
            .order_by(ProcedureVersion.version.desc())
        )
        result = await session.execute(query)
        versions = result.scalars().all()

        return {
            "versions": [
                {
                    "version": v.version,
                    "change_summary": v.change_summary,
                    "created_by": str(v.created_by) if v.created_by else None,
                    "created_at": v.created_at.isoformat() if v.created_at else None,
                }
                for v in versions
            ],
            "total": len(versions),
        }


@router.get("/{slug}/versions/{version}")
async def get_version(
    slug: str,
    version: int,
    organization_id: UUID = Depends(get_current_org_id),
):
    """
    Get the full definition of a specific procedure version.
    """
    async with database_service.get_session() as session:
        procedure = await _get_procedure_by_slug(session, organization_id, slug)

        query = select(ProcedureVersion).where(
            ProcedureVersion.procedure_id == procedure.id,
            ProcedureVersion.version == version,
        )
        result = await session.execute(query)
        version_record = result.scalar_one_or_none()

        if not version_record:
            raise HTTPException(
                status_code=404,
                detail=f"Version {version} not found for procedure '{slug}'",
            )

        return {
            "version": version_record.version,
            "change_summary": version_record.change_summary,
            "created_by": str(version_record.created_by) if version_record.created_by else None,
            "created_at": version_record.created_at.isoformat() if version_record.created_at else None,
            "definition": version_record.definition,
        }


@router.post("/{slug}/versions/{version}/restore")
async def restore_version(
    slug: str,
    version: int,
    organization_id: UUID = Depends(get_current_org_id),
    user: Optional[Any] = Depends(get_optional_current_user),
):
    """
    Restore a procedure to a previous version.

    Creates a NEW version (N+1) with the restored definition.
    History is never overwritten — the restore is recorded as a new version
    with change_summary indicating which version was restored.
    """
    async with database_service.get_session() as session:
        procedure = await _get_procedure_by_slug(session, organization_id, slug)

        if procedure.source_type != "user":
            raise HTTPException(
                status_code=400,
                detail="Cannot restore versions for system procedures",
            )

        # Fetch the version to restore
        query = select(ProcedureVersion).where(
            ProcedureVersion.procedure_id == procedure.id,
            ProcedureVersion.version == version,
        )
        result = await session.execute(query)
        version_record = result.scalar_one_or_none()

        if not version_record:
            raise HTTPException(
                status_code=404,
                detail=f"Version {version} not found for procedure '{slug}'",
            )

        # Create new version with restored definition
        new_version = procedure.version + 1
        restored_definition = version_record.definition

        procedure.definition = restored_definition
        procedure.version = new_version
        procedure.updated_at = datetime.utcnow()

        # Update name if it changed in the restored definition
        if "name" in restored_definition:
            procedure.name = restored_definition["name"]

        # Save version snapshot
        new_version_record = ProcedureVersion(
            procedure_id=procedure.id,
            version=new_version,
            definition=restored_definition,
            change_summary=f"Restored from version {version}",
            created_by=user.id if user else None,
        )
        session.add(new_version_record)
        await session.commit()

        logger.info(f"Restored procedure {slug} to version {version} (now version {new_version})")

        return {
            "status": "restored",
            "previous_version": version,
            "new_version": new_version,
            "message": f"Procedure restored from version {version} to new version {new_version}",
        }


def _json_diff(a: Any, b: Any, path: str = "") -> list:
    """
    Compute a structural diff between two JSON-compatible values.

    Returns a list of change dicts: {path, type, old_value, new_value}
    """
    changes = []

    if isinstance(a, dict) and isinstance(b, dict):
        all_keys = set(list(a.keys()) + list(b.keys()))
        for key in sorted(all_keys):
            child_path = f"{path}.{key}" if path else key
            if key not in a:
                changes.append({
                    "path": child_path,
                    "type": "added",
                    "old_value": None,
                    "new_value": b[key],
                })
            elif key not in b:
                changes.append({
                    "path": child_path,
                    "type": "removed",
                    "old_value": a[key],
                    "new_value": None,
                })
            else:
                changes.extend(_json_diff(a[key], b[key], child_path))
    elif isinstance(a, list) and isinstance(b, list):
        max_len = max(len(a), len(b))
        for i in range(max_len):
            child_path = f"{path}[{i}]"
            if i >= len(a):
                changes.append({
                    "path": child_path,
                    "type": "added",
                    "old_value": None,
                    "new_value": b[i],
                })
            elif i >= len(b):
                changes.append({
                    "path": child_path,
                    "type": "removed",
                    "old_value": a[i],
                    "new_value": None,
                })
            else:
                changes.extend(_json_diff(a[i], b[i], child_path))
    elif a != b:
        changes.append({
            "path": path or "(root)",
            "type": "changed",
            "old_value": a,
            "new_value": b,
        })

    return changes


@router.get("/{slug}/versions/{version_a}/diff/{version_b}")
async def diff_versions(
    slug: str,
    version_a: int,
    version_b: int,
    organization_id: UUID = Depends(get_current_org_id),
):
    """
    Compare two versions of a procedure definition.

    Returns a structural diff showing added, removed, and changed values.
    """
    async with database_service.get_session() as session:
        procedure = await _get_procedure_by_slug(session, organization_id, slug)

        # Fetch both versions
        query_a = select(ProcedureVersion).where(
            ProcedureVersion.procedure_id == procedure.id,
            ProcedureVersion.version == version_a,
        )
        query_b = select(ProcedureVersion).where(
            ProcedureVersion.procedure_id == procedure.id,
            ProcedureVersion.version == version_b,
        )

        result_a = await session.execute(query_a)
        result_b = await session.execute(query_b)

        record_a = result_a.scalar_one_or_none()
        record_b = result_b.scalar_one_or_none()

        if not record_a:
            raise HTTPException(
                status_code=404,
                detail=f"Version {version_a} not found for procedure '{slug}'",
            )
        if not record_b:
            raise HTTPException(
                status_code=404,
                detail=f"Version {version_b} not found for procedure '{slug}'",
            )

        changes = _json_diff(record_a.definition, record_b.definition)

        return {
            "version_a": version_a,
            "version_b": version_b,
            "changes": changes,
        }

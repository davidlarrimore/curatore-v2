# backend/app/core/commands/fix_procedure_step_refs.py
"""
Fix procedure definitions that reference step results with `.results` or `.data`
suffixes. Step results are stored as raw data directly, not wrapper objects.

Targets:
- daily_sam_gov_notices_digest: steps.fetch_todays_notices.results → steps.fetch_todays_notices

Usage:
    python -m app.core.commands.fix_procedure_step_refs [--dry-run]
"""

import argparse
import asyncio
import json
import re
import sys
from typing import Any, Dict, List, Tuple


async def fix_procedures(dry_run: bool = False) -> None:
    from sqlalchemy import select, text
    from app.core.database.procedures import Procedure
    from app.core.shared.database_service import database_service

    async with database_service.get_session() as session:
        # Find all active procedures
        result = await session.execute(
            select(Procedure).where(Procedure.is_active == True)
        )
        procedures = result.scalars().all()

        if not procedures:
            print("No active procedures found.")
            return

        # Pattern: steps.<step_name>.results or steps.<step_name>.data
        # These are wrong because step results ARE the data directly.
        pattern = re.compile(r'steps\.(\w+)\.(results|data)\b')

        fixed_count = 0
        for proc in procedures:
            definition = proc.definition
            if not definition:
                continue

            # Serialize to string, find/replace, deserialize back
            def_str = json.dumps(definition)
            matches = pattern.findall(def_str)

            if not matches:
                continue

            # Deduplicate for display
            unique_refs = sorted(set(
                f"steps.{m[0]}.{m[1]}" for m in matches
            ))

            print(f"\n{'[DRY RUN] ' if dry_run else ''}Procedure: {proc.name} ({proc.slug})")
            print(f"  Found {len(matches)} reference(s) to fix:")
            for ref in unique_refs:
                fixed_ref = pattern.sub(r'steps.\1', ref)
                print(f"    {ref} → {fixed_ref}")

            if not dry_run:
                fixed_str = pattern.sub(r'steps.\1', def_str)
                proc.definition = json.loads(fixed_str)
                proc.version = (proc.version or 1) + 1
                fixed_count += 1

        if not dry_run and fixed_count > 0:
            await session.commit()
            print(f"\nFixed {fixed_count} procedure(s).")
        elif dry_run:
            print(f"\n[DRY RUN] Would fix {len([p for p in procedures if p.definition and pattern.search(json.dumps(p.definition))])} procedure(s).")
        else:
            print("\nNo procedures needed fixing.")


def main():
    parser = argparse.ArgumentParser(
        description="Fix procedure step result references (.results/.data → direct)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be changed without modifying the database"
    )
    args = parser.parse_args()

    asyncio.run(fix_procedures(dry_run=args.dry_run))


if __name__ == "__main__":
    main()

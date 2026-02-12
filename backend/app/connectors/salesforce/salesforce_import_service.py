"""
Salesforce Import Service for processing export zip files.

Handles importing Salesforce data from zip files containing Account, Contact,
and Opportunity CSV exports. Performs upsert operations and relationship linking.

Key Features:
- Processes zip files with Account.csv, Contact.csv, Opportunity.csv
- Latin-1 encoding handling for CSV files
- Upsert by Salesforce ID (creates or updates)
- Post-import linking of contacts/opportunities to accounts
- Search indexing after import
- Progress tracking via Run records

Usage:
    from app.connectors.salesforce.salesforce_import_service import salesforce_import_service

    result = await salesforce_import_service.import_from_zip(
        session=session,
        organization_id=org_id,
        zip_path="/path/to/export.zip",
        run_id=run_id,
    )
    # result = {"accounts": 305, "contacts": 325, "opportunities": 595, ...}
"""

import csv
import io
import logging
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.salesforce.salesforce_service import salesforce_service
from app.core.search.pg_index_service import pg_index_service
from app.core.shared.run_log_service import run_log_service

logger = logging.getLogger("curatore.salesforce_import_service")


class SalesforceImportService:
    """
    Service for importing Salesforce CRM data from export zip files.

    Processes Account.csv, Contact.csv, and Opportunity.csv files from
    Salesforce data exports.
    """

    # Known field mappings for each object type
    ACCOUNT_FIELDS = {
        "Id": "salesforce_id",
        "Name": "name",
        "ParentId": "parent_salesforce_id",
        "Type": "account_type",
        "Industry": "industry",
        "Department__c": "department",
        "Description": "description",
        "Website": "website",
        "Phone": "phone",
        # Address fields
        "BillingStreet": "billing_street",
        "BillingCity": "billing_city",
        "BillingState": "billing_state",
        "BillingPostalCode": "billing_postal_code",
        "BillingCountry": "billing_country",
        "ShippingStreet": "shipping_street",
        "ShippingCity": "shipping_city",
        "ShippingState": "shipping_state",
        "ShippingPostalCode": "shipping_postal_code",
        "ShippingCountry": "shipping_country",
        # Small business flags
        "SBA_8_a__c": "sba_8a",
        "HubZone__c": "hubzone",
        "WOSB__c": "wosb",
        "SDVOSB__c": "sdvosb",
        "Small_Business__c": "small_business",
        "Small_Disadvantaged_Business__c": "small_disadvantaged",
    }

    CONTACT_FIELDS = {
        "Id": "salesforce_id",
        "AccountId": "account_salesforce_id",
        "FirstName": "first_name",
        "LastName": "last_name",
        "Email": "email",
        "Title": "title",
        "Phone": "phone",
        "MobilePhone": "mobile_phone",
        "Department": "department",
        "Current_Employee__c": "is_current_employee",
        # Address fields
        "MailingStreet": "mailing_street",
        "MailingCity": "mailing_city",
        "MailingState": "mailing_state",
        "MailingPostalCode": "mailing_postal_code",
        "MailingCountry": "mailing_country",
    }

    OPPORTUNITY_FIELDS = {
        "Id": "salesforce_id",
        "AccountId": "account_salesforce_id",
        "Name": "name",
        "StageName": "stage_name",
        "Amount": "amount",
        "Probability": "probability",
        "CloseDate": "close_date",
        "IsClosed": "is_closed",
        "IsWon": "is_won",
        "Type": "opportunity_type",
        "Role__c": "role",
        "LeadSource": "lead_source",
        "FiscalYear": "fiscal_year",
        "FiscalQuarter": "fiscal_quarter",
        "Description": "description",
    }

    async def import_from_zip(
        self,
        session: AsyncSession,
        organization_id: UUID,
        zip_path: str,
        run_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """
        Import Salesforce data from a zip file.

        Args:
            session: Database session
            organization_id: Organization UUID
            zip_path: Path to the zip file
            run_id: Optional Run ID for progress tracking

        Returns:
            Dictionary with import statistics:
            {
                "accounts": {"created": N, "updated": N, "total": N},
                "contacts": {"created": N, "updated": N, "total": N, "linked": N},
                "opportunities": {"created": N, "updated": N, "total": N, "linked": N},
                "errors": [...],
            }
        """
        result = {
            "accounts": {"created": 0, "updated": 0, "deleted": 0, "total": 0},
            "contacts": {"created": 0, "updated": 0, "deleted": 0, "total": 0, "linked": 0},
            "opportunities": {"created": 0, "updated": 0, "deleted": 0, "total": 0, "linked": 0},
            "errors": [],
        }

        # Track imported Salesforce IDs for full sync (delete missing records)
        imported_account_ids: Set[str] = set()
        imported_contact_ids: Set[str] = set()
        imported_opportunity_ids: Set[str] = set()

        try:
            # Log start
            if run_id:
                await run_log_service.log_event(
                    session, run_id, "INFO", "import_start",
                    f"Starting Salesforce import from {Path(zip_path).name}"
                )

            # Open and process zip file
            with zipfile.ZipFile(zip_path, 'r') as zf:
                file_list = zf.namelist()
                logger.info(f"Zip contains: {file_list}")

                # Find and process CSV files
                account_file = self._find_csv(file_list, "Account")
                contact_file = self._find_csv(file_list, "Contact")
                opportunity_file = self._find_csv(file_list, "Opportunity")

                # Import accounts first (needed for relationship linking)
                if account_file:
                    if run_id:
                        await run_log_service.log_event(
                            session, run_id, "INFO", "import_accounts",
                            f"Processing {account_file}"
                        )
                    account_stats, imported_account_ids = await self._import_accounts(
                        session, organization_id, zf, account_file
                    )
                    result["accounts"].update(account_stats)
                    await session.commit()
                    logger.info(f"Imported accounts: {account_stats}")
                else:
                    logger.warning("No Account CSV found in zip")
                    result["errors"].append("No Account CSV found")

                # Import contacts
                if contact_file:
                    if run_id:
                        await run_log_service.log_event(
                            session, run_id, "INFO", "import_contacts",
                            f"Processing {contact_file}"
                        )
                    contact_stats, imported_contact_ids = await self._import_contacts(
                        session, organization_id, zf, contact_file
                    )
                    result["contacts"].update(contact_stats)
                    await session.commit()
                    logger.info(f"Imported contacts: {contact_stats}")
                else:
                    logger.warning("No Contact CSV found in zip")
                    result["errors"].append("No Contact CSV found")

                # Import opportunities
                if opportunity_file:
                    if run_id:
                        await run_log_service.log_event(
                            session, run_id, "INFO", "import_opportunities",
                            f"Processing {opportunity_file}"
                        )
                    opp_stats, imported_opportunity_ids = await self._import_opportunities(
                        session, organization_id, zf, opportunity_file
                    )
                    result["opportunities"].update(opp_stats)
                    await session.commit()
                    logger.info(f"Imported opportunities: {opp_stats}")
                else:
                    logger.warning("No Opportunity CSV found in zip")
                    result["errors"].append("No Opportunity CSV found")

            # Link relationships
            if run_id:
                await run_log_service.log_event(
                    session, run_id, "INFO", "link_relationships",
                    "Linking contacts and opportunities to accounts"
                )

            contacts_linked = await salesforce_service.link_contacts_to_accounts(
                session, organization_id
            )
            result["contacts"]["linked"] = contacts_linked

            opps_linked = await salesforce_service.link_opportunities_to_accounts(
                session, organization_id
            )
            result["opportunities"]["linked"] = opps_linked

            await session.commit()

            # Delete records not in import (full sync)
            # Only delete if we actually imported records for that type
            if run_id:
                await run_log_service.log_event(
                    session, run_id, "INFO", "delete_missing",
                    "Deleting records not in import (full sync)"
                )

            # Delete opportunities first (no dependencies)
            if imported_opportunity_ids:
                deleted_opps = await salesforce_service.delete_opportunities_not_in(
                    session, organization_id, imported_opportunity_ids
                )
                result["opportunities"]["deleted"] = deleted_opps
                if deleted_opps > 0:
                    logger.info(f"Deleted {deleted_opps} opportunities not in import")

            # Delete contacts (no dependencies on other SF records)
            if imported_contact_ids:
                deleted_contacts = await salesforce_service.delete_contacts_not_in(
                    session, organization_id, imported_contact_ids
                )
                result["contacts"]["deleted"] = deleted_contacts
                if deleted_contacts > 0:
                    logger.info(f"Deleted {deleted_contacts} contacts not in import")

            # Delete accounts last (contacts/opportunities may reference them)
            if imported_account_ids:
                deleted_accounts = await salesforce_service.delete_accounts_not_in(
                    session, organization_id, imported_account_ids
                )
                result["accounts"]["deleted"] = deleted_accounts
                if deleted_accounts > 0:
                    logger.info(f"Deleted {deleted_accounts} accounts not in import")

            await session.commit()

            # Index records for search
            if run_id:
                await run_log_service.log_event(
                    session, run_id, "INFO", "indexing",
                    "Indexing records for search"
                )

            indexed_counts = await self._index_salesforce_records(
                session, organization_id
            )
            result["indexed"] = indexed_counts

            # Log completion
            if run_id:
                total_deleted = (
                    result["accounts"]["deleted"] +
                    result["contacts"]["deleted"] +
                    result["opportunities"]["deleted"]
                )
                await run_log_service.log_event(
                    session, run_id, "INFO", "import_complete",
                    f"Import complete: {result['accounts']['total']} accounts "
                    f"({result['accounts']['created']} new, {result['accounts']['updated']} updated, {result['accounts']['deleted']} deleted), "
                    f"{result['contacts']['total']} contacts "
                    f"({result['contacts']['created']} new, {result['contacts']['updated']} updated, {result['contacts']['deleted']} deleted), "
                    f"{result['opportunities']['total']} opportunities "
                    f"({result['opportunities']['created']} new, {result['opportunities']['updated']} updated, {result['opportunities']['deleted']} deleted). "
                    f"Indexed: {indexed_counts.get('accounts', 0)} accounts, "
                    f"{indexed_counts.get('contacts', 0)} contacts, "
                    f"{indexed_counts.get('opportunities', 0)} opportunities"
                )

            logger.info(f"Salesforce import complete: {result}")
            return result

        except Exception as e:
            logger.error(f"Salesforce import failed: {e}", exc_info=True)
            result["errors"].append(str(e))
            if run_id:
                await run_log_service.log_event(
                    session, run_id, "ERROR", "import_failed",
                    f"Import failed: {e}"
                )
            raise

    def _find_csv(self, file_list: List[str], object_name: str) -> Optional[str]:
        """Find a CSV file in the zip matching the object name."""
        for filename in file_list:
            # Match patterns like "Account.csv", "Accounts.csv", "account_export.csv"
            lower_name = filename.lower()
            if object_name.lower() in lower_name and lower_name.endswith('.csv'):
                return filename
        return None

    def _read_csv(self, zf: zipfile.ZipFile, filename: str) -> List[Dict[str, str]]:
        """Read a CSV file from the zip with proper encoding handling."""
        with zf.open(filename) as f:
            # Salesforce exports often use latin-1 encoding
            content = f.read()

            # Try UTF-8 first, fall back to latin-1
            try:
                text = content.decode('utf-8')
            except UnicodeDecodeError:
                text = content.decode('latin-1')

            reader = csv.DictReader(io.StringIO(text))
            return list(reader)

    async def _import_accounts(
        self,
        session: AsyncSession,
        organization_id: UUID,
        zf: zipfile.ZipFile,
        filename: str,
    ) -> Tuple[Dict[str, int], Set[str]]:
        """Import accounts from CSV.

        Returns:
            Tuple of (stats dict, set of imported Salesforce IDs)
        """
        rows = self._read_csv(zf, filename)
        created = 0
        updated = 0
        imported_ids: Set[str] = set()

        for row in rows:
            sf_id = row.get("Id", "").strip()
            if not sf_id:
                continue

            imported_ids.add(sf_id)

            # Check if existing
            existing = await salesforce_service.get_account_by_sf_id(
                session, organization_id, sf_id
            )

            # Build address dicts
            billing_address = self._build_address(row, "Billing")
            shipping_address = self._build_address(row, "Shipping")

            # Build small business flags
            small_business_flags = self._build_small_business_flags(row)

            # Upsert
            await salesforce_service.upsert_account(
                session=session,
                organization_id=organization_id,
                salesforce_id=sf_id,
                name=row.get("Name", "").strip() or "Unknown",
                parent_salesforce_id=row.get("ParentId", "").strip() or None,
                account_type=row.get("Type", "").strip() or None,
                industry=row.get("Industry", "").strip() or None,
                department=row.get("Department__c", "").strip() or None,
                description=row.get("Description", "").strip() or None,
                website=row.get("Website", "").strip() or None,
                phone=row.get("Phone", "").strip() or None,
                billing_address=billing_address,
                shipping_address=shipping_address,
                small_business_flags=small_business_flags,
                raw_data=dict(row),
            )

            if existing:
                updated += 1
            else:
                created += 1

        return {"created": created, "updated": updated, "total": created + updated}, imported_ids

    async def _import_contacts(
        self,
        session: AsyncSession,
        organization_id: UUID,
        zf: zipfile.ZipFile,
        filename: str,
    ) -> Tuple[Dict[str, int], Set[str]]:
        """Import contacts from CSV.

        Returns:
            Tuple of (stats dict, set of imported Salesforce IDs)
        """
        rows = self._read_csv(zf, filename)
        created = 0
        updated = 0
        imported_ids: Set[str] = set()

        for row in rows:
            sf_id = row.get("Id", "").strip()
            if not sf_id:
                continue

            imported_ids.add(sf_id)

            # Check if existing
            existing = await salesforce_service.get_contact_by_sf_id(
                session, organization_id, sf_id
            )

            # Build mailing address
            mailing_address = self._build_address(row, "Mailing")

            # Parse boolean
            is_current = self._parse_bool(row.get("Current_Employee__c", ""))

            # Upsert
            await salesforce_service.upsert_contact(
                session=session,
                organization_id=organization_id,
                salesforce_id=sf_id,
                last_name=row.get("LastName", "").strip() or "Unknown",
                first_name=row.get("FirstName", "").strip() or None,
                account_salesforce_id=row.get("AccountId", "").strip() or None,
                email=row.get("Email", "").strip() or None,
                title=row.get("Title", "").strip() or None,
                phone=row.get("Phone", "").strip() or None,
                mobile_phone=row.get("MobilePhone", "").strip() or None,
                department=row.get("Department", "").strip() or None,
                is_current_employee=is_current,
                mailing_address=mailing_address,
                raw_data=dict(row),
            )

            if existing:
                updated += 1
            else:
                created += 1

        return {"created": created, "updated": updated, "total": created + updated}, imported_ids

    async def _import_opportunities(
        self,
        session: AsyncSession,
        organization_id: UUID,
        zf: zipfile.ZipFile,
        filename: str,
    ) -> Tuple[Dict[str, int], Set[str]]:
        """Import opportunities from CSV.

        Returns:
            Tuple of (stats dict, set of imported Salesforce IDs)
        """
        rows = self._read_csv(zf, filename)
        created = 0
        updated = 0
        imported_ids: Set[str] = set()

        for row in rows:
            sf_id = row.get("Id", "").strip()
            if not sf_id:
                continue

            imported_ids.add(sf_id)

            # Check if existing
            existing = await salesforce_service.get_opportunity_by_sf_id(
                session, organization_id, sf_id
            )

            # Parse values
            amount = self._parse_float(row.get("Amount", ""))
            probability = self._parse_float(row.get("Probability", ""))
            close_date = self._parse_date(row.get("CloseDate", ""))
            is_closed = self._parse_bool(row.get("IsClosed", ""))
            is_won = self._parse_bool(row.get("IsWon", ""))

            # Collect custom dates if present
            custom_dates = {}
            for key, value in row.items():
                if "Date" in key and key not in ("CloseDate",) and value.strip():
                    parsed = self._parse_date(value)
                    if parsed:
                        custom_dates[key] = parsed.isoformat()
            if not custom_dates:
                custom_dates = None

            # Upsert
            await salesforce_service.upsert_opportunity(
                session=session,
                organization_id=organization_id,
                salesforce_id=sf_id,
                name=row.get("Name", "").strip() or "Unknown",
                account_salesforce_id=row.get("AccountId", "").strip() or None,
                stage_name=row.get("StageName", "").strip() or None,
                amount=amount,
                probability=probability,
                close_date=close_date,
                is_closed=is_closed,
                is_won=is_won,
                opportunity_type=row.get("Type", "").strip() or None,
                role=row.get("Role__c", "").strip() or None,
                lead_source=row.get("LeadSource", "").strip() or None,
                fiscal_year=row.get("FiscalYear", "").strip() or None,
                fiscal_quarter=row.get("FiscalQuarter", "").strip() or None,
                description=row.get("Description", "").strip() or None,
                custom_dates=custom_dates,
                raw_data=dict(row),
            )

            if existing:
                updated += 1
            else:
                created += 1

        return {"created": created, "updated": updated, "total": created + updated}, imported_ids

    def _build_address(self, row: Dict[str, str], prefix: str) -> Optional[Dict[str, str]]:
        """Build an address dict from CSV row fields."""
        street = row.get(f"{prefix}Street", "").strip()
        city = row.get(f"{prefix}City", "").strip()
        state = row.get(f"{prefix}State", "").strip()
        postal_code = row.get(f"{prefix}PostalCode", "").strip()
        country = row.get(f"{prefix}Country", "").strip()

        if any([street, city, state, postal_code, country]):
            return {
                "street": street or None,
                "city": city or None,
                "state": state or None,
                "postal_code": postal_code or None,
                "country": country or None,
            }
        return None

    def _build_small_business_flags(self, row: Dict[str, str]) -> Optional[Dict[str, bool]]:
        """Build small business certification flags from CSV row."""
        flags = {}

        flag_fields = [
            ("SBA_8_a__c", "sba_8a"),
            ("HubZone__c", "hubzone"),
            ("WOSB__c", "wosb"),
            ("SDVOSB__c", "sdvosb"),
            ("Small_Business__c", "small_business"),
            ("Small_Disadvantaged_Business__c", "small_disadvantaged"),
        ]

        for csv_field, flag_name in flag_fields:
            value = row.get(csv_field, "").strip()
            if value:
                flags[flag_name] = self._parse_bool(value)

        return flags if flags else None

    def _parse_bool(self, value: str) -> Optional[bool]:
        """Parse a boolean value from CSV."""
        if not value:
            return None
        value = value.strip().lower()
        if value in ("true", "1", "yes", "y"):
            return True
        if value in ("false", "0", "no", "n"):
            return False
        return None

    def _parse_date(self, value: str) -> Optional[date]:
        """Parse a date value from CSV."""
        if not value or not value.strip():
            return None
        value = value.strip()

        # Try common date formats
        formats = [
            "%Y-%m-%d",  # ISO format
            "%m/%d/%Y",  # US format
            "%d/%m/%Y",  # European format
            "%Y/%m/%d",  # Alternative ISO
        ]

        for fmt in formats:
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue

        logger.warning(f"Could not parse date: {value}")
        return None

    def _parse_float(self, value: str) -> Optional[float]:
        """Parse a float value from CSV."""
        if not value or not value.strip():
            return None
        try:
            # Remove currency symbols and commas
            clean = value.strip().replace("$", "").replace(",", "")
            return float(clean)
        except ValueError:
            logger.warning(f"Could not parse float: {value}")
            return None

    async def _index_salesforce_records(
        self,
        session: AsyncSession,
        organization_id: UUID,
    ) -> Dict[str, int]:
        """
        Index all Salesforce records for search.

        Args:
            session: Database session
            organization_id: Organization UUID

        Returns:
            Dict with count of indexed records by type
        """
        from sqlalchemy import select

        from app.core.database.models import (
            SalesforceAccount,
            SalesforceContact,
            SalesforceOpportunity,
        )

        counts = {"accounts": 0, "contacts": 0, "opportunities": 0}

        # Build account name lookup for contacts and opportunities
        account_names: Dict[UUID, str] = {}

        try:
            # Index accounts
            account_result = await session.execute(
                select(SalesforceAccount).where(
                    SalesforceAccount.organization_id == organization_id
                )
            )
            accounts = account_result.scalars().all()

            for account in accounts:
                account_names[account.id] = account.name
                try:
                    success = await pg_index_service.index_salesforce_account(
                        session=session,
                        organization_id=organization_id,
                        account_id=account.id,
                        salesforce_id=account.salesforce_id,
                        name=account.name,
                        account_type=account.account_type,
                        industry=account.industry,
                        description=account.description,
                        website=account.website,
                    )
                    if success:
                        counts["accounts"] += 1
                except Exception as e:
                    logger.warning(f"Failed to index account {account.id}: {e}")

            logger.info(f"Indexed {counts['accounts']} Salesforce accounts")

            # Index contacts
            contact_result = await session.execute(
                select(SalesforceContact).where(
                    SalesforceContact.organization_id == organization_id
                )
            )
            contacts = contact_result.scalars().all()

            for contact in contacts:
                account_name = account_names.get(contact.account_id) if contact.account_id else None
                try:
                    success = await pg_index_service.index_salesforce_contact(
                        session=session,
                        organization_id=organization_id,
                        contact_id=contact.id,
                        salesforce_id=contact.salesforce_id,
                        first_name=contact.first_name,
                        last_name=contact.last_name,
                        email=contact.email,
                        title=contact.title,
                        account_name=account_name,
                        department=contact.department,
                    )
                    if success:
                        counts["contacts"] += 1
                except Exception as e:
                    logger.warning(f"Failed to index contact {contact.id}: {e}")

            logger.info(f"Indexed {counts['contacts']} Salesforce contacts")

            # Index opportunities
            opp_result = await session.execute(
                select(SalesforceOpportunity).where(
                    SalesforceOpportunity.organization_id == organization_id
                )
            )
            opportunities = opp_result.scalars().all()

            for opp in opportunities:
                account_name = account_names.get(opp.account_id) if opp.account_id else None
                try:
                    success = await pg_index_service.index_salesforce_opportunity(
                        session=session,
                        organization_id=organization_id,
                        opportunity_id=opp.id,
                        salesforce_id=opp.salesforce_id,
                        name=opp.name,
                        stage_name=opp.stage_name,
                        amount=float(opp.amount) if opp.amount else None,
                        opportunity_type=opp.opportunity_type,
                        account_name=account_name,
                        description=opp.description,
                        close_date=opp.close_date,
                    )
                    if success:
                        counts["opportunities"] += 1
                except Exception as e:
                    logger.warning(f"Failed to index opportunity {opp.id}: {e}")

            logger.info(f"Indexed {counts['opportunities']} Salesforce opportunities")

        except Exception as e:
            logger.error(f"Error during Salesforce indexing: {e}")

        return counts


# Singleton instance
salesforce_import_service = SalesforceImportService()

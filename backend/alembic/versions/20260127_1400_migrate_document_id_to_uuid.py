"""Migrate document_id columns to UUID format (String(36))

This migration changes document_id columns from String(255) to String(36) in three tables:
- artifacts
- job_documents
- job_logs

The migration is safe and reversible. It validates existing data before making changes
and preserves all indexes. Supports both SQLite and PostgreSQL.

Revision ID: migrate_document_id_to_uuid
Revises: 20260126_1500
Create Date: 2026-01-27 14:00:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

# revision identifiers, used by Alembic.
revision = 'migrate_document_id_to_uuid'
down_revision = '9a7d4c2b3f1e'  # 20260126_1500_add_job_processed_folder
branch_labels = None
depends_on = None


def validate_document_ids(connection):
    """
    Validate that all document_id values are in valid format before migration.

    Raises:
        ValueError: If any invalid document_id format is found
    """
    import re

    # UUID pattern
    uuid_pattern = re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
        re.IGNORECASE
    )
    # Legacy doc_* pattern
    legacy_pattern = re.compile(r'^doc_[0-9a-f]{12}$', re.IGNORECASE)

    tables_to_check = [
        ('artifacts', 'document_id'),
        ('job_documents', 'document_id'),
        ('job_logs', 'document_id'),
    ]

    invalid_entries = []

    for table, column in tables_to_check:
        # Check if table exists
        inspector = inspect(connection)
        if table not in inspector.get_table_names():
            continue

        # Query all document_id values
        result = connection.execute(
            text(f"SELECT DISTINCT {column} FROM {table} WHERE {column} IS NOT NULL")
        )

        for row in result:
            doc_id = row[0]
            # Check if valid UUID or legacy format
            if not (uuid_pattern.match(doc_id) or legacy_pattern.match(doc_id)):
                invalid_entries.append((table, column, doc_id))

    if invalid_entries:
        error_msg = "Invalid document_id values found (must be UUID or doc_* format):\n"
        for table, column, value in invalid_entries[:10]:  # Show first 10
            error_msg += f"  - {table}.{column}: {value}\n"
        if len(invalid_entries) > 10:
            error_msg += f"  ... and {len(invalid_entries) - 10} more\n"
        raise ValueError(error_msg)


def get_database_type(connection):
    """Detect database type (sqlite or postgresql)."""
    dialect_name = connection.dialect.name
    return dialect_name


def upgrade():
    """Migrate document_id columns from String(255) to String(36)."""
    connection = op.get_bind()
    db_type = get_database_type(connection)

    print(f"Starting migration for {db_type} database...")

    # Step 1: Validate existing data
    print("Validating existing document_id values...")
    try:
        validate_document_ids(connection)
        print("✓ All document_id values are valid")
    except ValueError as e:
        print(f"✗ Validation failed: {e}")
        raise

    # Step 2: Migrate each table
    tables_to_migrate = [
        {
            'name': 'artifacts',
            'column': 'document_id',
            'indexes': [
                ('ix_artifacts_document_id', ['document_id']),
                ('ix_artifacts_org_doc', ['organization_id', 'document_id']),
                ('ix_artifacts_doc_type', ['document_id', 'artifact_type'])
            ]
        },
        {
            'name': 'job_documents',
            'column': 'document_id',
            'indexes': [
                ('ix_job_documents_document_id', ['document_id']),
                ('ix_job_docs_document', ['document_id'])
            ]
        },
        {
            'name': 'job_logs',
            'column': 'document_id',
            'indexes': [
                ('ix_job_logs_document_id', ['document_id'])
            ]
        }
    ]

    for table_info in tables_to_migrate:
        table_name = table_info['name']
        column_name = table_info['column']
        indexes = table_info['indexes']

        # Check if table exists
        inspector = inspect(connection)
        if table_name not in inspector.get_table_names():
            print(f"⊘ Table {table_name} does not exist, skipping")
            continue

        print(f"Migrating {table_name}.{column_name}...")

        if db_type == 'postgresql':
            # PostgreSQL: Use ALTER COLUMN
            # Drop indexes first
            for index_name, columns in indexes:
                try:
                    op.drop_index(index_name, table_name=table_name)
                    print(f"  ✓ Dropped index {index_name}")
                except Exception as e:
                    print(f"  ⊘ Index {index_name} doesn't exist or already dropped: {e}")

            # Alter column type
            op.alter_column(
                table_name,
                column_name,
                type_=sa.String(length=36),
                existing_type=sa.String(length=255),
                existing_nullable=True
            )
            print(f"  ✓ Changed {column_name} to String(36)")

            # Recreate indexes
            for index_name, columns in indexes:
                op.create_index(index_name, table_name, columns)
                print(f"  ✓ Recreated index {index_name}")

        else:  # SQLite
            # SQLite: Use temporary column approach (no ALTER COLUMN TYPE support)
            temp_column = f"{column_name}_new"

            # Drop indexes first
            for index_name, columns in indexes:
                try:
                    op.drop_index(index_name, table_name=table_name)
                    print(f"  ✓ Dropped index {index_name}")
                except Exception as e:
                    print(f"  ⊘ Index {index_name} doesn't exist or already dropped: {e}")

            # Add temporary column
            op.add_column(
                table_name,
                sa.Column(temp_column, sa.String(length=36), nullable=True)
            )
            print(f"  ✓ Added temporary column {temp_column}")

            # Copy data
            connection.execute(
                text(f"UPDATE {table_name} SET {temp_column} = {column_name}")
            )
            print(f"  ✓ Copied data to {temp_column}")

            # Drop old column
            op.drop_column(table_name, column_name)
            print(f"  ✓ Dropped old column {column_name}")

            # Rename temporary column
            op.alter_column(
                table_name,
                temp_column,
                new_column_name=column_name
            )
            print(f"  ✓ Renamed {temp_column} to {column_name}")

            # Recreate indexes
            for index_name, columns in indexes:
                op.create_index(index_name, table_name, columns)
                print(f"  ✓ Recreated index {index_name}")

    print("✓ Migration completed successfully")


def downgrade():
    """Revert document_id columns back to String(255)."""
    connection = op.get_bind()
    db_type = get_database_type(connection)

    print(f"Starting rollback for {db_type} database...")

    tables_to_migrate = [
        {
            'name': 'artifacts',
            'column': 'document_id',
            'indexes': [
                ('ix_artifacts_document_id', ['document_id']),
                ('ix_artifacts_org_doc', ['organization_id', 'document_id']),
                ('ix_artifacts_doc_type', ['document_id', 'artifact_type'])
            ]
        },
        {
            'name': 'job_documents',
            'column': 'document_id',
            'indexes': [
                ('ix_job_documents_document_id', ['document_id']),
                ('ix_job_docs_document', ['document_id'])
            ]
        },
        {
            'name': 'job_logs',
            'column': 'document_id',
            'indexes': [
                ('ix_job_logs_document_id', ['document_id'])
            ]
        }
    ]

    for table_info in tables_to_migrate:
        table_name = table_info['name']
        column_name = table_info['column']
        indexes = table_info['indexes']

        # Check if table exists
        inspector = inspect(connection)
        if table_name not in inspector.get_table_names():
            print(f"⊘ Table {table_name} does not exist, skipping")
            continue

        print(f"Rolling back {table_name}.{column_name}...")

        if db_type == 'postgresql':
            # PostgreSQL: Use ALTER COLUMN
            # Drop indexes first
            for index_name, columns in indexes:
                try:
                    op.drop_index(index_name, table_name=table_name)
                    print(f"  ✓ Dropped index {index_name}")
                except Exception as e:
                    print(f"  ⊘ Index {index_name} doesn't exist: {e}")

            # Alter column type back to String(255)
            op.alter_column(
                table_name,
                column_name,
                type_=sa.String(length=255),
                existing_type=sa.String(length=36),
                existing_nullable=True
            )
            print(f"  ✓ Changed {column_name} back to String(255)")

            # Recreate indexes
            for index_name, columns in indexes:
                op.create_index(index_name, table_name, columns)
                print(f"  ✓ Recreated index {index_name}")

        else:  # SQLite
            # SQLite: Use temporary column approach
            temp_column = f"{column_name}_old"

            # Drop indexes first
            for index_name, columns in indexes:
                try:
                    op.drop_index(index_name, table_name=table_name)
                    print(f"  ✓ Dropped index {index_name}")
                except Exception as e:
                    print(f"  ⊘ Index {index_name} doesn't exist: {e}")

            # Add temporary column
            op.add_column(
                table_name,
                sa.Column(temp_column, sa.String(length=255), nullable=True)
            )
            print(f"  ✓ Added temporary column {temp_column}")

            # Copy data
            connection.execute(
                text(f"UPDATE {table_name} SET {temp_column} = {column_name}")
            )
            print(f"  ✓ Copied data to {temp_column}")

            # Drop old column
            op.drop_column(table_name, column_name)
            print(f"  ✓ Dropped old column {column_name}")

            # Rename temporary column
            op.alter_column(
                table_name,
                temp_column,
                new_column_name=column_name
            )
            print(f"  ✓ Renamed {temp_column} to {column_name}")

            # Recreate indexes
            for index_name, columns in indexes:
                op.create_index(index_name, table_name, columns)
                print(f"  ✓ Recreated index {index_name}")

    print("✓ Rollback completed successfully")

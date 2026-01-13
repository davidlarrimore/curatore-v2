# backend/app/commands/__init__.py
"""
Command-line utilities for Curatore v2.

Provides management commands for database seeding, migrations, and maintenance.

Commands:
    - seed: Create initial organization and admin user
    - migrate: Migrate ENV-based config to database

Usage:
    python -m app.commands.seed --create-admin
    python -m app.commands.migrate --import-env-connections
"""

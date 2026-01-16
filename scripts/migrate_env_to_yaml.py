#!/usr/bin/env python3
"""
Migration script to convert .env configuration to config.yml.

This script reads environment variables from .env file and generates
a config.yml with appropriate structure and ${VAR_NAME} references
for sensitive values.

Usage:
    python scripts/migrate_env_to_yaml.py
    python scripts/migrate_env_to_yaml.py --env-file /path/to/.env
    python scripts/migrate_env_to_yaml.py --output /path/to/config.yml
    python scripts/migrate_env_to_yaml.py --dry-run
"""

import os
import argparse
import sys
from pathlib import Path
from typing import Dict, Optional


def load_env_file(env_path: str) -> Dict[str, str]:
    """
    Load environment variables from .env file.

    Args:
        env_path: Path to .env file

    Returns:
        Dictionary of environment variables
    """
    env_vars = {}

    if not os.path.exists(env_path):
        print(f"Warning: .env file not found at {env_path}")
        return env_vars

    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()

            # Skip comments and empty lines
            if not line or line.startswith('#'):
                continue

            # Parse KEY=VALUE
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()

                # Remove quotes if present
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]

                env_vars[key] = value

    return env_vars


def should_reference_env(key: str, value: str) -> bool:
    """
    Determine if a value should reference environment variable.

    Sensitive values (API keys, secrets) should reference ${VAR_NAME}
    instead of hardcoding in config.yml.

    Args:
        key: Environment variable name
        value: Environment variable value

    Returns:
        True if should use ${VAR_NAME} reference
    """
    sensitive_keywords = [
        'KEY', 'SECRET', 'PASSWORD', 'TOKEN',
        'CLIENT_ID', 'CLIENT_SECRET', 'TENANT_ID',
        'ACCESS_KEY', 'AWS'
    ]

    # Always reference sensitive values
    for keyword in sensitive_keywords:
        if keyword in key.upper():
            return True

    # Reference if value looks like a key or secret
    if len(value) > 20 and any(c in value for c in ['-', '_']):
        return True

    return False


def generate_config_yaml(env_vars: Dict[str, str]) -> str:
    """
    Generate config.yml content from environment variables.

    Args:
        env_vars: Dictionary of environment variables

    Returns:
        YAML configuration string
    """
    yaml_lines = []

    # Header
    yaml_lines.append("# ============================================================================")
    yaml_lines.append("# Curatore v2 - Service Configuration")
    yaml_lines.append("# ============================================================================")
    yaml_lines.append("# Generated from .env file by migrate_env_to_yaml.py")
    yaml_lines.append("#")
    yaml_lines.append("# Sensitive values are referenced from environment variables using ${VAR_NAME}")
    yaml_lines.append("# Keep these values in .env and do not commit them to version control.")
    yaml_lines.append("# ============================================================================")
    yaml_lines.append("")
    yaml_lines.append("version: \"2.0\"")
    yaml_lines.append("")

    # LLM Configuration
    if any(k.startswith('OPENAI_') for k in env_vars):
        yaml_lines.append("# ============================================================================")
        yaml_lines.append("# LLM Configuration")
        yaml_lines.append("# ============================================================================")
        yaml_lines.append("llm:")

        # Provider (infer from base_url)
        base_url = env_vars.get('OPENAI_BASE_URL', 'https://api.openai.com/v1')
        if 'ollama' in base_url.lower():
            provider = 'ollama'
        elif 'openwebui' in base_url.lower() or ':3000' in base_url:
            provider = 'openwebui'
        elif 'lmstudio' in base_url.lower() or ':1234' in base_url:
            provider = 'lmstudio'
        else:
            provider = 'openai'

        yaml_lines.append(f"  provider: {provider}")

        # API key
        if 'OPENAI_API_KEY' in env_vars:
            yaml_lines.append("  api_key: ${OPENAI_API_KEY}")

        # Base URL
        if 'OPENAI_BASE_URL' in env_vars:
            yaml_lines.append(f"  base_url: {base_url}")

        # Model
        if 'OPENAI_MODEL' in env_vars:
            yaml_lines.append(f"  model: {env_vars['OPENAI_MODEL']}")

        # Optional settings
        if 'OPENAI_TIMEOUT' in env_vars:
            yaml_lines.append(f"  timeout: {env_vars['OPENAI_TIMEOUT']}")

        if 'OPENAI_MAX_RETRIES' in env_vars:
            yaml_lines.append(f"  max_retries: {env_vars['OPENAI_MAX_RETRIES']}")

        if 'OPENAI_VERIFY_SSL' in env_vars:
            yaml_lines.append(f"  verify_ssl: {env_vars['OPENAI_VERIFY_SSL'].lower()}")

        yaml_lines.append("")

    # Extraction Configuration
    if any(k.startswith('EXTRACTION_') or k.startswith('DOCLING_') for k in env_vars):
        yaml_lines.append("# ============================================================================")
        yaml_lines.append("# Extraction Service Configuration")
        yaml_lines.append("# ============================================================================")
        yaml_lines.append("extraction:")

        yaml_lines.append("  services:")

        # Extraction service
        yaml_lines.append("    - name: extraction-service")
        extraction_url = env_vars.get('EXTRACTION_SERVICE_URL', 'http://extraction:8010')
        yaml_lines.append(f"      url: {extraction_url}")

        if 'EXTRACTION_SERVICE_TIMEOUT' in env_vars:
            yaml_lines.append(f"      timeout: {env_vars['EXTRACTION_SERVICE_TIMEOUT']}")

        yaml_lines.append("      enabled: true")
        yaml_lines.append("")

        # Docling service (if enabled)
        if env_vars.get('ENABLE_DOCLING_SERVICE', '').lower() == 'true':
            yaml_lines.append("    - name: docling")
            docling_url = env_vars.get('DOCLING_SERVICE_URL', 'http://docling:5001')
            yaml_lines.append(f"      url: {docling_url}")

            if 'DOCLING_TIMEOUT' in env_vars:
                yaml_lines.append(f"      timeout: {env_vars['DOCLING_TIMEOUT']}")

            yaml_lines.append("      enabled: true")

        yaml_lines.append("")

    # SharePoint Configuration
    if any(k.startswith('MS_') for k in env_vars):
        yaml_lines.append("# ============================================================================")
        yaml_lines.append("# Microsoft SharePoint Configuration")
        yaml_lines.append("# ============================================================================")
        yaml_lines.append("sharepoint:")
        yaml_lines.append("  enabled: true")

        if 'MS_TENANT_ID' in env_vars:
            yaml_lines.append("  tenant_id: ${MS_TENANT_ID}")

        if 'MS_CLIENT_ID' in env_vars:
            yaml_lines.append("  client_id: ${MS_CLIENT_ID}")

        if 'MS_CLIENT_SECRET' in env_vars:
            yaml_lines.append("  client_secret: ${MS_CLIENT_SECRET}")

        if 'MS_GRAPH_SCOPE' in env_vars:
            yaml_lines.append(f"  graph_scope: {env_vars['MS_GRAPH_SCOPE']}")

        if 'MS_GRAPH_BASE_URL' in env_vars:
            yaml_lines.append(f"  graph_base_url: {env_vars['MS_GRAPH_BASE_URL']}")

        yaml_lines.append("")

    # Email Configuration
    if any(k.startswith('EMAIL_') or k.startswith('SMTP_') or k.startswith('SENDGRID_') for k in env_vars):
        yaml_lines.append("# ============================================================================")
        yaml_lines.append("# Email Service Configuration")
        yaml_lines.append("# ============================================================================")
        yaml_lines.append("email:")

        backend = env_vars.get('EMAIL_BACKEND', 'console')
        yaml_lines.append(f"  backend: {backend}")

        if 'EMAIL_FROM_ADDRESS' in env_vars:
            yaml_lines.append(f"  from_address: {env_vars['EMAIL_FROM_ADDRESS']}")

        if 'EMAIL_FROM_NAME' in env_vars:
            yaml_lines.append(f"  from_name: {env_vars['EMAIL_FROM_NAME']}")

        # SMTP configuration
        if backend == 'smtp' and any(k.startswith('SMTP_') for k in env_vars):
            yaml_lines.append("  smtp:")

            if 'SMTP_HOST' in env_vars:
                yaml_lines.append("    host: ${SMTP_HOST}")

            if 'SMTP_PORT' in env_vars:
                yaml_lines.append(f"    port: {env_vars['SMTP_PORT']}")

            if 'SMTP_USERNAME' in env_vars:
                yaml_lines.append("    username: ${SMTP_USERNAME}")

            if 'SMTP_PASSWORD' in env_vars:
                yaml_lines.append("    password: ${SMTP_PASSWORD}")

            if 'SMTP_USE_TLS' in env_vars:
                yaml_lines.append(f"    use_tls: {env_vars['SMTP_USE_TLS'].lower()}")

        yaml_lines.append("")

    # Storage Configuration
    yaml_lines.append("# ============================================================================")
    yaml_lines.append("# Storage Configuration")
    yaml_lines.append("# ============================================================================")
    yaml_lines.append("storage:")

    if 'USE_HIERARCHICAL_STORAGE' in env_vars:
        yaml_lines.append(f"  hierarchical: {env_vars['USE_HIERARCHICAL_STORAGE'].lower()}")

    yaml_lines.append("  deduplication:")

    if 'FILE_DEDUPLICATION_ENABLED' in env_vars:
        yaml_lines.append(f"    enabled: {env_vars['FILE_DEDUPLICATION_ENABLED'].lower()}")

    if 'FILE_DEDUPLICATION_STRATEGY' in env_vars:
        yaml_lines.append(f"    strategy: {env_vars['FILE_DEDUPLICATION_STRATEGY']}")

    yaml_lines.append("  retention:")

    if 'FILE_RETENTION_UPLOADED_DAYS' in env_vars:
        yaml_lines.append(f"    uploaded_days: {env_vars['FILE_RETENTION_UPLOADED_DAYS']}")

    if 'FILE_RETENTION_PROCESSED_DAYS' in env_vars:
        yaml_lines.append(f"    processed_days: {env_vars['FILE_RETENTION_PROCESSED_DAYS']}")

    yaml_lines.append("  cleanup:")

    if 'FILE_CLEANUP_ENABLED' in env_vars:
        yaml_lines.append(f"    enabled: {env_vars['FILE_CLEANUP_ENABLED'].lower()}")

    if 'FILE_CLEANUP_SCHEDULE_CRON' in env_vars:
        yaml_lines.append(f"    schedule_cron: \"{env_vars['FILE_CLEANUP_SCHEDULE_CRON']}\"")

    yaml_lines.append("")

    # Queue Configuration
    yaml_lines.append("# ============================================================================")
    yaml_lines.append("# Queue Configuration")
    yaml_lines.append("# ============================================================================")
    yaml_lines.append("queue:")

    if 'CELERY_BROKER_URL' in env_vars:
        yaml_lines.append(f"  broker_url: {env_vars['CELERY_BROKER_URL']}")

    if 'CELERY_RESULT_BACKEND' in env_vars:
        yaml_lines.append(f"  result_backend: {env_vars['CELERY_RESULT_BACKEND']}")

    if 'CELERY_DEFAULT_QUEUE' in env_vars:
        yaml_lines.append(f"  default_queue: {env_vars['CELERY_DEFAULT_QUEUE']}")

    yaml_lines.append("")

    return '\n'.join(yaml_lines)


def main():
    """Main migration entry point."""
    parser = argparse.ArgumentParser(
        description='Migrate .env configuration to config.yml'
    )
    parser.add_argument(
        '--env-file',
        type=str,
        default='.env',
        help='Path to .env file (default: .env)'
    )
    parser.add_argument(
        '--output',
        type=str,
        default='config.yml',
        help='Output path for config.yml (default: config.yml)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Print config.yml to stdout without writing file'
    )

    args = parser.parse_args()

    print("Curatore v2 Configuration Migration Tool")
    print("=" * 50)
    print()

    # Load .env file
    print(f"Reading .env file: {args.env_file}")
    env_vars = load_env_file(args.env_file)

    if not env_vars:
        print("Error: No environment variables found in .env file")
        print("\nPlease ensure .env file exists and contains configuration.")
        sys.exit(1)

    print(f"Found {len(env_vars)} environment variables")
    print()

    # Generate config.yml
    print("Generating config.yml...")
    config_yaml = generate_config_yaml(env_vars)

    # Count detected services
    services = []
    if 'OPENAI_API_KEY' in env_vars:
        services.append("LLM configuration (OpenAI)")
    if 'EXTRACTION_SERVICE_URL' in env_vars:
        services.append(f"Extraction service ({len([k for k in env_vars if k.startswith('EXTRACTION_')])} settings)")
    if 'MS_TENANT_ID' in env_vars:
        services.append("SharePoint configuration")
    if 'EMAIL_BACKEND' in env_vars:
        backend = env_vars['EMAIL_BACKEND']
        services.append(f"Email configuration ({backend})")
    services.append("Storage configuration")
    services.append("Queue configuration")

    print(f"\nCreated config.yml with:")
    for service in services:
        print(f"  ✓ {service}")

    # Handle output
    if args.dry_run:
        print("\n" + "=" * 50)
        print("DRY RUN - config.yml content:")
        print("=" * 50)
        print(config_yaml)
        print("=" * 50)
        print("\nNo files were modified (--dry-run mode)")
    else:
        # Check if output file exists
        if os.path.exists(args.output):
            response = input(f"\n{args.output} already exists. Overwrite? (y/N): ")
            if response.lower() not in ['y', 'yes']:
                print("Migration cancelled.")
                sys.exit(0)

        # Write config.yml
        with open(args.output, 'w') as f:
            f.write(config_yaml)

        print(f"\nSuccessfully created {args.output}")
        print("\nNext steps:")
        print(f"  1. Review {args.output} and adjust as needed")
        print(f"  2. Validate configuration: python -m app.commands.validate_config")
        print(f"  3. Keep sensitive values in .env (referenced via ${{VAR_NAME}})")
        print(f"  4. Restart services to use new configuration")


if __name__ == '__main__':
    main()

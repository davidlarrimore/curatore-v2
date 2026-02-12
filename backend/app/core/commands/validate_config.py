"""
Configuration validation command.

Validates config.yml against Pydantic models, resolves environment variables,
and tests service connectivity.

Usage:
    python -m app.commands.validate_config
    python -m app.commands.validate_config --config-path /path/to/config.yml
    python -m app.commands.validate_config --skip-connectivity
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import List, Tuple

# Add backend directory to path for imports
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from app.core.models.config_models import AppConfig
from app.core.shared.config_loader import ConfigLoader

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)


class Colors:
    """ANSI color codes for terminal output."""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'


def print_success(message: str) -> None:
    """Print success message in green."""
    print(f"{Colors.GREEN}✓{Colors.END} {message}")


def print_error(message: str) -> None:
    """Print error message in red."""
    print(f"{Colors.RED}✗{Colors.END} {message}")


def print_warning(message: str) -> None:
    """Print warning message in yellow."""
    print(f"{Colors.YELLOW}⚠{Colors.END} {message}")


def print_info(message: str) -> None:
    """Print info message in blue."""
    print(f"{Colors.BLUE}ℹ{Colors.END} {message}")


def print_section(title: str) -> None:
    """Print section header."""
    print(f"\n{Colors.BOLD}{title}{Colors.END}")
    print("─" * len(title))


def validate_file_exists(config_path: str) -> Tuple[bool, List[str]]:
    """
    Validate that config file exists and is readable.

    Returns:
        Tuple of (success, errors)
    """
    errors = []

    if not os.path.exists(config_path):
        errors.append(f"Configuration file not found: {config_path}")
        return False, errors

    if not os.path.isfile(config_path):
        errors.append(f"Configuration path is not a file: {config_path}")
        return False, errors

    if not os.access(config_path, os.R_OK):
        errors.append(f"Configuration file is not readable: {config_path}")
        return False, errors

    return True, errors


def validate_yaml_syntax(config_path: str) -> Tuple[bool, List[str]]:
    """
    Validate YAML syntax.

    Returns:
        Tuple of (success, errors)
    """
    import yaml

    errors = []

    try:
        with open(config_path, 'r') as f:
            yaml.safe_load(f)
        return True, errors
    except yaml.YAMLError as e:
        errors.append(f"Invalid YAML syntax: {e}")
        return False, errors
    except Exception as e:
        errors.append(f"Failed to read YAML: {e}")
        return False, errors


def validate_schema(config_path: str) -> Tuple[bool, List[str], AppConfig]:
    """
    Validate configuration against Pydantic schema.

    Returns:
        Tuple of (success, errors, config)
    """
    errors = []
    config = None

    try:
        loader = ConfigLoader(config_path)
        config = loader.load()
        return True, errors, config
    except ValueError as e:
        errors.append(f"Schema validation failed: {e}")
        return False, errors, None
    except Exception as e:
        errors.append(f"Unexpected error: {e}")
        return False, errors, None


def validate_env_vars(config_path: str) -> Tuple[bool, List[str]]:
    """
    Validate that all referenced environment variables are set.

    Returns:
        Tuple of (success, errors)
    """
    import re

    errors = []
    missing_vars = set()

    try:
        with open(config_path, 'r') as f:
            raw_content = f.read()

        # Find all ${VAR_NAME} references
        env_var_pattern = r'\$\{([^}]+)\}'
        matches = re.findall(env_var_pattern, raw_content)

        for var_name in matches:
            if not os.getenv(var_name):
                missing_vars.add(var_name)

        if missing_vars:
            errors.append("Missing environment variables:")
            for var in sorted(missing_vars):
                errors.append(f"  - {var}")
            return False, errors

        return True, errors

    except Exception as e:
        errors.append(f"Failed to check environment variables: {e}")
        return False, errors


def test_service_connectivity(config: AppConfig, skip_connectivity: bool = False) -> Tuple[bool, List[str]]:
    """
    Test connectivity to configured services.

    Returns:
        Tuple of (success, warnings)
    """
    if skip_connectivity:
        print_info("Skipping connectivity tests (--skip-connectivity)")
        return True, []

    warnings = []

    # Test LLM connectivity
    if config.llm:
        try:
            import httpx
            response = httpx.get(
                config.llm.base_url.rstrip('/') + '/models',
                headers={'Authorization': f'Bearer {config.llm.api_key}'},
                timeout=5,
                verify=config.llm.verify_ssl
            )
            if response.status_code == 200:
                print_success(f"LLM service reachable: {config.llm.base_url}")
            else:
                warnings.append(f"LLM service returned status {response.status_code}")
        except Exception as e:
            warnings.append(f"LLM service unreachable: {e}")

    # Test extraction services
    if config.extraction:
        for service in config.extraction.services:
            if not service.enabled:
                continue
            try:
                import httpx
                response = httpx.get(
                    service.url.rstrip('/') + '/health',
                    timeout=5,
                    verify=service.verify_ssl
                )
                if response.status_code == 200:
                    print_success(f"Extraction service '{service.name}' reachable: {service.url}")
                else:
                    warnings.append(f"Extraction service '{service.name}' returned status {response.status_code}")
            except Exception as e:
                warnings.append(f"Extraction service '{service.name}' unreachable: {e}")

    # Test Microsoft Graph connectivity
    if config.microsoft_graph and config.microsoft_graph.enabled:
        try:
            # Just check if the Graph API endpoint is reachable
            import httpx
            response = httpx.get(
                config.microsoft_graph.graph_base_url,
                timeout=5
            )
            print_success(f"Microsoft Graph API reachable: {config.microsoft_graph.graph_base_url}")
        except Exception as e:
            warnings.append(f"Microsoft Graph API unreachable: {e}")

    return True, warnings


def main():
    """Main validation entry point."""
    parser = argparse.ArgumentParser(
        description='Validate Curatore v2 configuration file'
    )
    parser.add_argument(
        '--config-path',
        type=str,
        default=None,
        help='Path to config.yml (defaults to project root)'
    )
    parser.add_argument(
        '--skip-connectivity',
        action='store_true',
        help='Skip service connectivity tests'
    )

    args = parser.parse_args()

    # Determine config path
    if args.config_path:
        config_path = args.config_path
    else:
        # Default to project root
        project_root = Path(__file__).parent.parent.parent.parent
        config_path = str(project_root / 'config.yml')

    print(f"{Colors.BOLD}Curatore v2 Configuration Validator{Colors.END}")
    print(f"Config file: {config_path}\n")

    all_success = True
    total_errors = []

    # Step 1: Check file exists
    print_section("File Validation")
    success, errors = validate_file_exists(config_path)
    if success:
        print_success("config.yml found and readable")
    else:
        all_success = False
        total_errors.extend(errors)
        for error in errors:
            print_error(error)
        # Can't continue if file doesn't exist
        print(f"\n{Colors.BOLD}Validation failed!{Colors.END}")
        print("\nTo create a configuration file:")
        print("  cp config.yml.example config.yml")
        print("  # Edit config.yml with your settings")
        sys.exit(1)

    # Step 2: Validate YAML syntax
    print_section("YAML Syntax")
    success, errors = validate_yaml_syntax(config_path)
    if success:
        print_success("YAML syntax valid")
    else:
        all_success = False
        total_errors.extend(errors)
        for error in errors:
            print_error(error)

    # Step 3: Validate environment variables
    print_section("Environment Variables")
    success, errors = validate_env_vars(config_path)
    if success:
        print_success("All environment variables resolved")
    else:
        all_success = False
        total_errors.extend(errors)
        for error in errors:
            print_error(error)

    # Step 4: Validate schema
    print_section("Schema Validation")
    success, errors, config = validate_schema(config_path)
    if success:
        print_success("Schema validation passed")

        # Print configuration summary
        print("\nConfiguration Summary:")
        if config.llm:
            print(f"  LLM: {config.llm.provider} ({config.llm.model})")
        if config.extraction:
            enabled_services = [s.name for s in config.extraction.services if s.enabled]
            print(f"  Extraction: {', '.join(enabled_services)}")
        if config.microsoft_graph and config.microsoft_graph.enabled:
            print("  Microsoft Graph: Enabled")
        if config.email:
            print(f"  Email: {config.email.backend}")
        print(f"  Storage: Hierarchical={config.storage.hierarchical}, Dedup={config.storage.deduplication.enabled}")
        print(f"  Queue: {config.queue.default_queue}")
    else:
        all_success = False
        total_errors.extend(errors)
        for error in errors:
            print_error(error)

    # Step 5: Test connectivity (if schema validation passed)
    if config:
        print_section("Service Connectivity")
        success, warnings = test_service_connectivity(config, args.skip_connectivity)
        for warning in warnings:
            print_warning(warning)

    # Final summary
    print_section("Summary")
    if all_success and not total_errors:
        print_success("Configuration is valid!")
        print("\nYour configuration is ready to use.")
        print("Services will load settings from config.yml automatically.")
        sys.exit(0)
    else:
        print_error("Configuration validation failed!")
        print(f"\n{len(total_errors)} error(s) found:")
        for error in total_errors:
            print(f"  • {error}")
        print("\nPlease fix the errors above and run validation again.")
        sys.exit(1)


if __name__ == '__main__':
    main()

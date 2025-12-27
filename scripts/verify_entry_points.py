#!/usr/bin/env python3
"""Verify all extracted package entry points can be loaded."""
import os
import sys
import re
from pathlib import Path

# Prevent pydantic-settings from reading .env files
os.environ["STACHE_NO_ENV_FILE"] = "1"

# Clear environment variables that may cause Settings validation errors
# These are not relevant to testing import functionality
for key in list(os.environ.keys()):
    if key.upper() in ("ENABLE_DOCUMENT_INDEX", "DATA_DIR"):
        del os.environ[key]

# Change directory away from stache to avoid .env files
os.chdir("/tmp")

# Add stache-core and backend to path for base classes
sys.path.insert(0, "/mnt/devbuntu/dev/stache/packages/stache-core/src")
sys.path.insert(0, "/mnt/devbuntu/dev/stache/backend")

# Add packages to path for testing
packages_dir = Path("/mnt/devbuntu/dev/stache/packages")
for pkg in packages_dir.glob("stache-ai-*/src"):
    sys.path.insert(0, str(pkg))


def parse_entry_points_from_toml(toml_path: Path) -> dict:
    """Parse entry points from a pyproject.toml file."""
    content = toml_path.read_text()
    entry_points = {}

    # Find all entry point sections
    pattern = r'\[project\.entry-points\."([^"]+)"\]\s*\n([^\[]*)'
    for match in re.finditer(pattern, content):
        group = match.group(1)
        entries_text = match.group(2)

        # Parse individual entries
        entry_pattern = r'(\w+)\s*=\s*"([^"]+)"'
        for entry_match in re.finditer(entry_pattern, entries_text):
            name = entry_match.group(1)
            path = entry_match.group(2)
            if group not in entry_points:
                entry_points[group] = []
            entry_points[group].append((name, path))

    return entry_points


def main():
    # Collect all entry points from pyproject.toml files
    all_entry_points = {}

    for pyproject in packages_dir.glob("stache-ai-*/pyproject.toml"):
        # Skip the AWS metapackage
        if "stache-ai-aws" in str(pyproject):
            continue

        pkg_entry_points = parse_entry_points_from_toml(pyproject)
        for group, entries in pkg_entry_points.items():
            if group not in all_entry_points:
                all_entry_points[group] = []
            all_entry_points[group].extend(entries)

    errors = []
    success = []
    skipped = []

    # Known missing third-party dependencies
    missing_deps = {
        "anthropic": "anthropic",
        "openai": "openai",
        "cohere": "cohere",
        "mixedbread-ai-sdk": "mixedbread_ai",
    }

    for group, entries in sorted(all_entry_points.items()):
        for name, path in entries:
            try:
                module_path, class_name = path.split(":")
                module = __import__(module_path, fromlist=[class_name])
                cls = getattr(module, class_name)
                success.append(f"[OK] {group}:{name} -> {class_name}")
            except ImportError as e:
                error_msg = str(e)
                # Check if it's a missing third-party dependency
                is_third_party = False
                for dep, module_name in missing_deps.items():
                    if f"No module named '{module_name}'" in error_msg:
                        skipped.append(f"[SKIP] {group}:{name} - Missing optional dependency: {dep}")
                        is_third_party = True
                        break
                if not is_third_party:
                    errors.append(f"[FAIL] {group}:{name} - ImportError: {e}")
            except AttributeError as e:
                errors.append(f"[FAIL] {group}:{name} - AttributeError: {e}")
            except Exception as e:
                errors.append(f"[FAIL] {group}:{name} - {type(e).__name__}: {e}")

    print("\n=== Entry Point Verification ===\n")

    for s in success:
        print(s)

    if skipped:
        print("\n=== SKIPPED (missing optional dependencies) ===\n")
        for s in skipped:
            print(s)

    if errors:
        print("\n=== ERRORS ===\n")
        for e in errors:
            print(e)
        print(f"\nSummary: {len(success)} OK, {len(skipped)} skipped, {len(errors)} errors")
        sys.exit(1)
    else:
        print(f"\nAll {len(success)} entry points loaded successfully!")
        if skipped:
            print(f"({len(skipped)} skipped due to missing optional dependencies)")
        sys.exit(0)


if __name__ == "__main__":
    main()

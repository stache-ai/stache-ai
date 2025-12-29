"""CLI command for importing directories of documents"""

import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import click

# Supported file extensions
SUPPORTED_EXTENSIONS = {'.txt', '.md', '.markdown', '.pdf', '.epub', '.docx', '.pptx', '.vtt', '.srt'}


def setup_logging(verbose: bool):
    """Configure logging based on verbosity"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )


def get_files(path: Path, pattern: str, recursive: bool) -> list[Path]:
    """Get list of files matching pattern"""
    if recursive:
        files = list(path.glob(f"**/{pattern}"))
    else:
        files = list(path.glob(pattern))

    # Filter to supported extensions
    supported = [f for f in files if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS]
    return sorted(supported)


@click.command()
@click.argument('path', type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path))
@click.option('--namespace', '-n', required=True, help='Target namespace for imported documents')
@click.option('--pattern', '-p', default='*', help='Glob pattern for files (default: *)')
@click.option('--recursive', '-r', is_flag=True, help='Search subdirectories recursively')
@click.option('--chunking', '-c', default='recursive',
              type=click.Choice(['recursive', 'markdown', 'semantic', 'character', 'transcript']),
              help='Chunking strategy (default: recursive)')
@click.option('--dry-run', is_flag=True, help='Show what would be imported without actually importing')
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
@click.option('--skip-errors', is_flag=True, help='Continue on errors instead of stopping')
@click.option('--metadata', '-m', multiple=True, help='Add metadata as key=value pairs (can repeat)')
@click.option('--prepend-metadata', help='Comma-separated metadata keys to prepend to chunks')
@click.option('--parallel', '-P', default=1, type=int, help='Number of parallel file processors (default: 1)')
def import_directory(
    path: Path,
    namespace: str,
    pattern: str,
    recursive: bool,
    chunking: str,
    dry_run: bool,
    verbose: bool,
    skip_errors: bool,
    metadata: tuple,
    prepend_metadata: str | None,
    parallel: int
):
    """
    Import a directory of documents into Stache.

    PATH is the directory containing documents to import.

    Examples:

        # Import all supported files from a directory
        stache-import ./documents --namespace my-docs

        # Import only markdown files recursively
        stache-import ./notes -n notes -p "*.md" -r

        # Import with custom metadata
        stache-import ./talks -n church/talks -m speaker="Jane Doe" -m year=2024

        # Dry run to see what would be imported
        stache-import ./books -n books --dry-run

        # Use markdown chunking for markdown files
        stache-import ./docs -n docs -p "*.md" -c markdown

        # Import with 4 parallel workers for faster processing
        stache-import ./large-corpus -n corpus -P 4
    """
    setup_logging(verbose)
    logger = logging.getLogger(__name__)

    # Parse metadata key=value pairs
    meta_dict = {}
    for item in metadata:
        if '=' in item:
            key, value = item.split('=', 1)
            meta_dict[key.strip()] = value.strip()
        else:
            click.echo(f"Warning: Ignoring invalid metadata '{item}' (expected key=value)", err=True)

    # Parse prepend_metadata
    prepend_keys = None
    if prepend_metadata:
        prepend_keys = [k.strip() for k in prepend_metadata.split(',') if k.strip()]

    # Find files
    click.echo(f"Scanning {path} for files matching '{pattern}'...")
    files = get_files(path, pattern, recursive)

    if not files:
        click.echo("No supported files found.", err=True)
        click.echo(f"Supported extensions: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
        sys.exit(1)

    click.echo(f"Found {len(files)} file(s) to import:")
    for f in files[:10]:  # Show first 10
        click.echo(f"  - {f.relative_to(path)}")
    if len(files) > 10:
        click.echo(f"  ... and {len(files) - 10} more")

    if dry_run:
        click.echo("\n[DRY RUN] No files were imported.")
        click.echo(f"Would import {len(files)} files to namespace '{namespace}'")
        if meta_dict:
            click.echo(f"With metadata: {meta_dict}")
        if prepend_keys:
            click.echo(f"Prepending metadata keys: {prepend_keys}")
        sys.exit(0)

    # Confirm before proceeding
    parallel_msg = f" (parallel: {parallel})" if parallel > 1 else ""
    if not click.confirm(f"\nImport {len(files)} files to namespace '{namespace}'{parallel_msg}?"):
        click.echo("Aborted.")
        sys.exit(0)

    # Import the pipeline and loaders (lazy import to speed up --help)
    click.echo("\nInitializing pipeline...")
    from stache_ai.loaders import load_document
    from stache_ai.rag.pipeline import get_pipeline

    pipeline = get_pipeline()

    # Helper function for processing a single file
    def process_file(file_path: Path) -> dict:
        """Process a single file and return result dict"""
        try:
            # Load document
            text = load_document(str(file_path), file_path.name)

            if not text.strip():
                return {'status': 'skipped', 'file': file_path.name, 'reason': 'empty'}

            # Build file-specific metadata
            file_metadata = {
                **meta_dict,
                'filename': file_path.name,
                'source_path': str(file_path.relative_to(path)),
            }

            # Ingest into pipeline
            result = pipeline.ingest_text(
                text=text,
                metadata=file_metadata,
                chunking_strategy=chunking,
                namespace=namespace,
                prepend_metadata=prepend_keys
            )

            return {
                'status': 'success',
                'file': file_path.name,
                'chunks': result['chunks_created']
            }

        except Exception as e:
            return {'status': 'error', 'file': file_path.name, 'error': str(e)}

    # Process files
    success_count = 0
    error_count = 0
    total_chunks = 0

    if parallel > 1:
        # Parallel processing
        click.echo(f"Processing with {parallel} parallel workers...")
        completed = 0

        with ThreadPoolExecutor(max_workers=parallel) as executor:
            futures = {executor.submit(process_file, f): f for f in files}

            for future in as_completed(futures):
                completed += 1
                result = future.result()

                if result['status'] == 'success':
                    success_count += 1
                    total_chunks += result['chunks']
                    logger.debug(f"[{completed}/{len(files)}] Imported {result['file']}: {result['chunks']} chunks")
                elif result['status'] == 'skipped':
                    logger.warning(f"[{completed}/{len(files)}] Skipped {result['file']}: {result['reason']}")
                else:
                    error_count += 1
                    logger.error(f"[{completed}/{len(files)}] Failed {result['file']}: {result['error']}")
                    if not skip_errors:
                        click.echo(f"\nError importing {result['file']}: {result['error']}", err=True)
                        click.echo("Use --skip-errors to continue on failures.", err=True)
                        sys.exit(1)

                # Progress update every 10 files
                if completed % 10 == 0 or completed == len(files):
                    click.echo(f"Progress: {completed}/{len(files)} files processed")
    else:
        # Sequential processing with progress bar
        with click.progressbar(files, label='Importing', show_pos=True) as progress_files:
            for file_path in progress_files:
                result = process_file(file_path)

                if result['status'] == 'success':
                    success_count += 1
                    total_chunks += result['chunks']
                    logger.debug(f"Imported {result['file']}: {result['chunks']} chunks")
                elif result['status'] == 'skipped':
                    logger.warning(f"Skipped {result['file']}: {result['reason']}")
                else:
                    error_count += 1
                    logger.error(f"Failed {result['file']}: {result['error']}")
                    if not skip_errors:
                        click.echo(f"\nError importing {result['file']}: {result['error']}", err=True)
                        click.echo("Use --skip-errors to continue on failures.", err=True)
                        sys.exit(1)

    # Summary
    click.echo(f"\n{'='*50}")
    click.echo("Import complete!")
    click.echo(f"  Successful: {success_count} files")
    click.echo(f"  Failed: {error_count} files")
    click.echo(f"  Total chunks: {total_chunks}")
    click.echo(f"  Namespace: {namespace}")

    if error_count > 0:
        sys.exit(1)


if __name__ == '__main__':
    import_directory()

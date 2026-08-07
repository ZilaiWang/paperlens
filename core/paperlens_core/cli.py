"""PaperLens command line interface for reproducible parsing and evaluation."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .config import Settings
from .database import Database
from .ingestion import IngestionService
from .references import parse_references
from .retrieval import BM25Index
from .sections import section_metrics


def _runtime(settings: Settings) -> tuple[Database, IngestionService]:
    settings.ensure_dirs()
    database = Database(settings.database_path)
    return database, IngestionService(
        database,
        settings.uploads_dir,
        max_pdf_mb=settings.paperlens_max_pdf_mb,
    )


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def command_ingest(args: argparse.Namespace, settings: Settings) -> int:
    _, service = _runtime(settings)
    outcomes = []
    for file_name in args.pdf:
        outcome = service.ingest_file(file_name)
        outcomes.append(
            {
                "paper_id": outcome.result.paper.paper_id,
                "file_name": outcome.result.paper.file_name,
                "pages": outcome.result.paper.page_count,
                "sections": len(outcome.result.sections),
                "chunks": len(outcome.result.chunks),
                "deduplicated": outcome.deduplicated,
                "stored_path": str(outcome.stored_path),
            }
        )
    _print_json(outcomes)
    return 0


def command_list(args: argparse.Namespace, settings: Settings) -> int:
    database, _ = _runtime(settings)
    _print_json([paper.model_dump(mode="json") for paper in database.list_papers()])
    return 0


def command_inspect(args: argparse.Namespace, settings: Settings) -> int:
    database, _ = _runtime(settings)
    paper = database.get_paper(args.paper_id)
    if paper is None:
        raise SystemExit(f"paper not found: {args.paper_id}")
    _print_json(
        {
            "paper": paper.model_dump(mode="json"),
            "sections": [
                item.model_dump(mode="json") for item in database.get_sections(args.paper_id)
            ],
            "block_count": len(database.get_blocks(args.paper_id)),
            "chunk_count": len(database.get_chunks(args.paper_id)),
            "cleaning_events": [
                event.model_dump(mode="json")
                for event in database.get_cleaning_events(args.paper_id)
            ],
        }
    )
    return 0


def command_search(args: argparse.Namespace, settings: Settings) -> int:
    database, _ = _runtime(settings)
    hits = BM25Index(database.get_chunks(args.paper_id)).search(args.query, top_k=args.top_k)
    _print_json([hit.model_dump(mode="json") for hit in hits])
    return 0


def command_references(args: argparse.Namespace, settings: Settings) -> int:
    database, _ = _runtime(settings)
    text = "\n".join(
        block.text
        for block in database.get_blocks(args.paper_id)
        if "reference" in block.section_path.casefold()
    )
    _print_json([record.model_dump(mode="json") for record in parse_references(text)])
    return 0


def command_evaluate_sections(args: argparse.Namespace, settings: Settings) -> int:
    database, _ = _runtime(settings)
    gold = json.loads(Path(args.gold).read_text(encoding="utf-8"))
    semantic_paper_id = gold["paper_id"]
    paper = database.get_paper_by_sha256(gold["pdf_sha256"])
    if paper is None:
        raise SystemExit(f"gold paper not ingested: {semantic_paper_id}")
    if paper.file_sha256 != gold["pdf_sha256"]:
        raise SystemExit("PDF SHA-256 does not match gold; metric refused")
    records = [
        {
            "canonical_name": item["canonical_name"],
            "start_page": item["pdf_page"],
            "raw_title": item["raw_title"],
            "level": item["level"],
        }
        for item in gold["sections"]
        if item["include_in_metric"]
    ]
    result = section_metrics(database.get_sections(paper.paper_id), records)
    result["paper_id"] = semantic_paper_id
    result["pdf_sha256"] = paper.file_sha256
    _print_json(result)
    return 0


def command_validate_demo(args: argparse.Namespace, settings: Settings) -> int:
    script = Path(__file__).resolve().parents[2] / "scripts" / "validate_demo_assets.py"
    return subprocess.call([sys.executable, str(script)])


def command_import_demo(args: argparse.Namespace, settings: Settings) -> int:
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / "data" / "demo" / "manifest.json").read_text(encoding="utf-8"))
    database, service = _runtime(settings)
    imported = []
    for record in manifest["papers"]:
        outcome = service.ingest_file(root / "data" / "demo" / record["file"])
        imported.append(outcome.result.paper.paper_id)
    _print_json({"imported": imported, "database": str(database.path)})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paperlens", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    ingest = subparsers.add_parser("ingest", help="parse and persist PDF files")
    ingest.add_argument("pdf", nargs="+")
    ingest.set_defaults(handler=command_ingest)
    list_parser = subparsers.add_parser("list", help="list ingested papers")
    list_parser.set_defaults(handler=command_list)
    inspect = subparsers.add_parser("inspect", help="show deterministic paper structure")
    inspect.add_argument("paper_id")
    inspect.set_defaults(handler=command_inspect)
    search = subparsers.add_parser("search", help="run local BM25 retrieval")
    search.add_argument("paper_id")
    search.add_argument("query")
    search.add_argument("--top-k", type=int, default=8)
    search.set_defaults(handler=command_search)
    references = subparsers.add_parser("references", help="lint IEEE numeric references")
    references.add_argument("paper_id")
    references.set_defaults(handler=command_references)
    evaluate = subparsers.add_parser("evaluate-sections", help="evaluate a SHA-pinned section gold")
    evaluate.add_argument("gold")
    evaluate.set_defaults(handler=command_evaluate_sections)
    validate = subparsers.add_parser("validate-demo", help="run demo copyright/integrity gate")
    validate.set_defaults(handler=command_validate_demo)
    import_demo = subparsers.add_parser("import-demo", help="preparse the three packaged demo PDFs")
    import_demo.set_defaults(handler=command_import_demo)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args, Settings()))


if __name__ == "__main__":
    raise SystemExit(main())

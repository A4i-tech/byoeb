import argparse
import asyncio
import csv
from pathlib import Path
from typing import Dict, Iterable, List, Optional
import uuid

from byoeb.constants.user_enums import LanguageCode
from byoeb.models.dyk import DykEntry, DykLanguageEntry
from byoeb.repositories.repository_factory import get_repository_factory

GUID_COLUMN = "guid"
DEFAULT_INPUT_FILE = Path(__file__).resolve().parents[2] / "background_jobs" / "did_you_know" / "dyk.csv"

def load_entries(csv_path: Path) -> List[DykEntry]:
    if not csv_path.exists():
        raise FileNotFoundError(f"Input file not found: {csv_path}")

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("CSV file must have a header row.")

        guid_column, lang_columns = _parse_header(reader.fieldnames)
        if not lang_columns:
            raise ValueError("CSV file must include at least one supported language column.")

        entries: List[DykEntry] = []
        for row in reader:
            guid_value = (row.get(guid_column) or "").strip()
            if not guid_value:
                continue
            try:
                dyk_id = uuid.UUID(guid_value)
            except ValueError as exc:
                raise ValueError(f"Invalid GUID '{guid_value}' on line {reader.line_num}.") from exc

            languages: Dict[LanguageCode, DykLanguageEntry] = {}
            for column, lang in lang_columns.items():
                fact = (row.get(column) or "").strip()
                if not fact:
                    continue
                languages[lang] = DykLanguageEntry(fact=fact, related_questions=[])
            if not languages:
                continue

            entries.append(DykEntry(id=dyk_id, languages=languages))

    return entries


def _parse_header(columns: Iterable[str]) -> tuple[str, Dict[str, LanguageCode]]:
    guid_column: Optional[str] = None
    lang_columns: Dict[str, LanguageCode] = {}
    for column in columns:
        normalized = column.strip().lower()
        if normalized == GUID_COLUMN:
            guid_column = column
            continue
        try:
            lang_columns[column] = LanguageCode(normalized)
        except ValueError:
            continue

    if not guid_column:
        raise ValueError("CSV header must include a GUID column.")

    return guid_column, lang_columns


async def migrate(entries: List[DykEntry], skip_existing: bool) -> Dict[str, int]:
    factory = await get_repository_factory()
    repository = await factory.get_dyk_repository()

    written = 0
    skipped = 0
    for entry in entries:
        if skip_existing:
            existing = await repository.find(entry.id)
            if existing:
                skipped += 1
                continue
        else:
            await repository.delete(entry.id)

        try:
            await repository.add(entry)
        except Exception as exc:
            raise RuntimeError(f"Failed to persist DYK entry {entry.id}.") from exc
        written += 1

    return {"written": written, "skipped": skipped}


async def main() -> None:
    parser = argparse.ArgumentParser(description="Populate the Mongo DYK storage collection from a CSV file.")
    parser.add_argument("input_file", nargs="?", default=str(DEFAULT_INPUT_FILE), help=f"Path to the DYK CSV file (default: {DEFAULT_INPUT_FILE})")
    parser.add_argument("--skip-existing", action="store_true", help="Skip entries that already exist in storage instead of replacing them.")
    args = parser.parse_args()

    entries = load_entries(Path(args.input_file))
    print(f"Loaded {len(entries)} DYK entries from {args.input_file}")
    results = await migrate(entries, skip_existing=args.skip_existing)
    print(f"Migrated {results['written']} entries ({results['skipped']} skipped).")


if __name__ == "__main__":
    asyncio.run(main())
from __future__ import annotations

import argparse
from pathlib import Path

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stream a Parquet file to CSV or CSV.GZ without loading the full dataset into memory.")
    parser.add_argument("input_path", help="Input Parquet path.")
    parser.add_argument("output_path", help="Output CSV path. Use .csv.gz for gzip-compressed CSV.")
    parser.add_argument("--batch-size", type=int, default=250_000, help="Record batch size used during export.")
    parser.add_argument("--max-rows", type=int, default=0, help="Optional maximum number of rows to export. Use 0 for all rows.")
    return parser


def export_parquet_to_csv_streaming(
    input_path: str | Path,
    output_path: str | Path,
    *,
    batch_size: int = 250_000,
    max_rows: int = 0,
) -> dict[str, int | str]:
    source = Path(input_path).expanduser()
    target = Path(output_path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)

    parquet_file = pq.ParquetFile(source)
    rows_written = 0
    writer: pacsv.CSVWriter | None = None

    compression = "gzip" if target.name.endswith(".gz") else None
    with pa.output_stream(str(target), compression=compression) as sink:
        for batch in parquet_file.iter_batches(batch_size=batch_size):
            if max_rows > 0:
                remaining = max_rows - rows_written
                if remaining <= 0:
                    break
                if batch.num_rows > remaining:
                    batch = batch.slice(0, remaining)

            if writer is None:
                writer = pacsv.CSVWriter(sink, batch.schema)
            writer.write_batch(batch)
            rows_written += batch.num_rows

            if max_rows > 0 and rows_written >= max_rows:
                break

    if writer is not None:
        writer.close()

    return {
        "input_path": str(source),
        "output_path": str(target),
        "rows_written": int(rows_written),
        "source_rows": int(parquet_file.metadata.num_rows),
    }


def main() -> int:
    args = _build_parser().parse_args()
    result = export_parquet_to_csv_streaming(
        args.input_path,
        args.output_path,
        batch_size=int(args.batch_size),
        max_rows=int(args.max_rows),
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
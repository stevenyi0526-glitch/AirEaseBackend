"""
AirEase - Import OpenSky Aircraft Database into PostgreSQL

This script reads the OpenSky Network aircraft database CSV and imports
relevant aircraft data (registration, model, engines, operator, age)
into a PostgreSQL table for use in flight scoring and detail display.

Usage:
    python import_aircraft_db.py [--csv PATH] [--batch-size N] [--drop]

CSV Source: https://opensky-network.org/datasets/metadata/
File: aircraft-database-complete-2025-08.csv
"""

import csv
import os
import sys
import argparse
from datetime import datetime, date
from typing import Optional

import psycopg2
from psycopg2.extras import execute_values

# Add parent path so we can import app config
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


# ============================================================
# Database connection
# ============================================================

def get_db_connection():
    """Create a PostgreSQL connection using environment variables."""
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", 5432)),
        user=os.getenv("POSTGRES_USER", ""),
        password=os.getenv("POSTGRES_PASSWORD", ""),
        dbname=os.getenv("POSTGRES_DB", "airease"),
    )


# ============================================================
# Table DDL
# ============================================================

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS aircraft_database (
    id              SERIAL PRIMARY KEY,
    icao24          VARCHAR(10),
    registration    VARCHAR(25),
    typecode        VARCHAR(30),
    model           VARCHAR(100),
    manufacturer    VARCHAR(150),
    engines         VARCHAR(200),
    first_flight    DATE,
    built_year      INTEGER,
    operator        VARCHAR(100),
    operator_iata   VARCHAR(25),
    operator_icao   VARCHAR(40),
    owner           VARCHAR(150),
    country         VARCHAR(50),
    category        VARCHAR(60),
    serial_number   VARCHAR(40),
    status          VARCHAR(50),
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_aircraft_registration ON aircraft_database (registration);
CREATE INDEX IF NOT EXISTS idx_aircraft_typecode ON aircraft_database (typecode);
CREATE INDEX IF NOT EXISTS idx_aircraft_operator_iata ON aircraft_database (operator_iata);
CREATE INDEX IF NOT EXISTS idx_aircraft_operator_icao ON aircraft_database (operator_icao);
CREATE INDEX IF NOT EXISTS idx_aircraft_icao24 ON aircraft_database (icao24);
CREATE INDEX IF NOT EXISTS idx_aircraft_model ON aircraft_database (model);
"""

DROP_TABLE_SQL = "DROP TABLE IF EXISTS aircraft_database CASCADE;"

INSERT_SQL = """
INSERT INTO aircraft_database (
    icao24, registration, typecode, model, manufacturer,
    engines, first_flight, built_year, operator, operator_iata,
    operator_icao, owner, country, category, serial_number, status
) VALUES %s
ON CONFLICT DO NOTHING;
"""


# ============================================================
# CSV Parsing
# ============================================================

def clean_value(val: str) -> Optional[str]:
    """Strip quotes and whitespace; return None for empty strings."""
    val = val.strip().strip("'\"")
    return val if val else None


def parse_date(val: str) -> Optional[date]:
    """Parse a date string from the CSV. Returns None on failure."""
    val = clean_value(val)
    if not val:
        return None
    try:
        return datetime.strptime(val, "%Y-%m-%d").date()
    except ValueError:
        try:
            return datetime.strptime(val, "%Y-%m-%d %H:%M:%S").date()
        except ValueError:
            return None


def parse_built_year(val: str, first_flight_str: str) -> Optional[int]:
    """
    Extract the built year. If the 'built' column is empty,
    try to derive from firstFlightDate.
    """
    v = clean_value(val)
    if v:
        try:
            return int(v)
        except ValueError:
            # Try parsing as a date
            d = parse_date(v)
            if d:
                return d.year
    # Fallback: derive from first flight date
    d = parse_date(first_flight_str)
    if d:
        return d.year
    return None


def preprocess_csv(csv_path: str):
    """
    Phase 1: Read & filter the CSV in memory.
    Returns (header_col_map, filtered_records_list, total_rows, skipped_rows).
    Shows a real-time progress bar during reading.
    """
    import time

    if not os.path.exists(csv_path):
        print(f"❌ CSV file not found: {csv_path}")
        sys.exit(1)

    # Quick line count for progress bar
    print("� Counting rows …", end=" ", flush=True)
    with open(csv_path, "r", encoding="utf-8") as f:
        total_lines = sum(1 for _ in f) - 1  # minus header
    print(f"{total_lines:,} rows")

    print("� Pre-processing: reading & filtering …")
    records = []
    total_rows = 0
    skipped_rows = 0
    start = time.time()

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f, quotechar="'")
        header = next(reader)

        col_map = {}
        for i, col in enumerate(header):
            col_map[col.strip().strip("'")] = i

        def get(row, name):
            idx = col_map.get(name)
            if idx is not None and idx < len(row):
                return clean_value(row[idx])
            return None

        for row in reader:
            total_rows += 1

            # ---- real-time progress (overwrite same line) ----
            if total_rows % 20000 == 0 or total_rows == total_lines:
                pct = total_rows / total_lines * 100
                bar_len = 30
                filled = int(bar_len * total_rows / total_lines)
                bar = "█" * filled + "░" * (bar_len - filled)
                elapsed = time.time() - start
                rate = total_rows / elapsed if elapsed > 0 else 0
                print(
                    f"\r   [{bar}] {pct:5.1f}%  {total_rows:>7,}/{total_lines:,}  "
                    f"kept={len(records):,}  skip={skipped_rows:,}  "
                    f"({rate:,.0f} rows/s)",
                    end="", flush=True,
                )

            try:
                model = get(row, "model")
                engines = get(row, "engines")
                operator = get(row, "operator")
                manufacturer = get(row, "manufacturerName")
                owner = get(row, "owner")
                built_raw = get(row, "built")

                # Skip "unknow" models
                if model and model.lower() in ("unknow", "unknown"):
                    model = None

                # Only keep rows with at least one useful content column
                if not any([model, engines, operator, manufacturer, owner, built_raw]):
                    skipped_rows += 1
                    continue

                first_flight_str = get(row, "firstFlightDate") or ""
                built_str = built_raw or ""

                records.append((
                    get(row, "icao24"),
                    get(row, "registration"),
                    get(row, "typecode"),
                    model,
                    manufacturer,
                    engines,
                    parse_date(first_flight_str),
                    parse_built_year(built_str, first_flight_str),
                    operator,
                    get(row, "operatorIata"),
                    get(row, "operatorIcao"),
                    owner,
                    get(row, "country"),
                    get(row, "categoryDescription"),
                    get(row, "serialNumber"),
                    get(row, "status"),
                ))
            except Exception as e:
                skipped_rows += 1
                if skipped_rows <= 5:
                    print(f"\n  ⚠️ Row {total_rows}: {e}")

    elapsed = time.time() - start
    print(f"\n✅ Pre-processing done in {elapsed:.1f}s")
    print(f"   Total CSV rows: {total_rows:,}")
    print(f"   Rows kept:      {len(records):,}")
    print(f"   Rows skipped:   {skipped_rows:,}")
    return records, total_rows, skipped_rows


def import_to_db(records: list, batch_size: int = 5000, drop_first: bool = False):
    """
    Phase 2: Bulk-insert pre-processed records into PostgreSQL.
    Shows a real-time progress bar during insertion.
    """
    import time

    total = len(records)
    if total == 0:
        print("⚠️ No records to import.")
        return

    print(f"\n📤 Importing {total:,} records to PostgreSQL (batch={batch_size}) …")

    conn = get_db_connection()
    cur = conn.cursor()
    start = time.time()

    try:
        if drop_first:
            print("🗑️  Dropping existing table …")
            cur.execute(DROP_TABLE_SQL)
            conn.commit()

        print("🔨 Creating table …")
        cur.execute(CREATE_TABLE_SQL)
        conn.commit()

        inserted = 0
        for i in range(0, total, batch_size):
            batch = records[i : i + batch_size]
            execute_values(cur, INSERT_SQL, batch, page_size=batch_size)
            conn.commit()
            inserted += len(batch)

            # ---- real-time progress ----
            pct = inserted / total * 100
            bar_len = 30
            filled = int(bar_len * inserted / total)
            bar = "█" * filled + "░" * (bar_len - filled)
            elapsed = time.time() - start
            rate = inserted / elapsed if elapsed > 0 else 0
            print(
                f"\r   [{bar}] {pct:5.1f}%  {inserted:>7,}/{total:,}  ({rate:,.0f} rows/s)",
                end="", flush=True,
            )

        elapsed = time.time() - start
        print(f"\n✅ Import done in {elapsed:.1f}s ({inserted:,} rows)")

        # ---- Stats ----
        print("\n📊 Database stats:")
        cur.execute("SELECT COUNT(*) FROM aircraft_database;")
        print(f"   Total rows:        {cur.fetchone()[0]:,}")

        cur.execute("SELECT COUNT(DISTINCT typecode) FROM aircraft_database WHERE typecode IS NOT NULL;")
        print(f"   Unique typecodes:  {cur.fetchone()[0]:,}")

        cur.execute("SELECT COUNT(*) FROM aircraft_database WHERE engines IS NOT NULL AND engines != '';")
        print(f"   With engine data:  {cur.fetchone()[0]:,}")

        cur.execute("SELECT COUNT(*) FROM aircraft_database WHERE first_flight IS NOT NULL;")
        print(f"   With age data:     {cur.fetchone()[0]:,}")

        print("\n📊 Sample commercial aircraft:")
        cur.execute("""
            SELECT registration, typecode, model, engines,
                   first_flight, operator, operator_iata
            FROM aircraft_database
            WHERE typecode IN ('B738','B789','A359','A321','B77W','A388')
              AND engines IS NOT NULL AND engines != ''
            ORDER BY first_flight DESC NULLS LAST
            LIMIT 10;
        """)
        for r in cur.fetchall():
            reg, tc, mdl, eng, ff, op, iata = r
            if ff:
                age_val = datetime.now().year - ff.year
                if age_val < 1:
                    age = "less than 1 year"
                elif age_val == 1:
                    age = "1 year old"
                else:
                    age = f"{age_val} years old"
            else:
                age = "unknown"
            print(f"   {reg or '?':>8} | {tc or '?':>4} | {(mdl or '?')[:30]:30} | {(eng or '?')[:30]:30} | {age:>20} | {op or '?'} ({iata or '?'})")

    except Exception as e:
        conn.rollback()
        print(f"\n❌ Error: {e}")
        raise
    finally:
        cur.close()
        conn.close()


def process_csv(csv_path: str, batch_size: int = 5000, drop_first: bool = False):
    """Two-phase pipeline: pre-process → import."""
    records, _, _ = preprocess_csv(csv_path)
    import_to_db(records, batch_size, drop_first)


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import OpenSky aircraft database into PostgreSQL")
    parser.add_argument(
        "--csv",
        default=os.path.join(os.path.dirname(__file__), "..", "aircraft-database-complete-2025-08.csv"),
        help="Path to the OpenSky CSV file",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5000,
        help="Number of rows to insert per batch (default: 5000)",
    )
    parser.add_argument(
        "--drop",
        action="store_true",
        help="Drop and recreate the table before importing",
    )
    args = parser.parse_args()

    process_csv(args.csv, args.batch_size, args.drop)

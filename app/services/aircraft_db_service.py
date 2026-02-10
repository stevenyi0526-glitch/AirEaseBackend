"""
AirEase Backend - Aircraft Database Service

Provides lookup of aircraft engine type and age from the
OpenSky Network aircraft database stored in PostgreSQL.
"""

from typing import Optional, Dict, Any
from datetime import datetime, date
import logging

from sqlalchemy import text
from app.database import SessionLocal

logger = logging.getLogger(__name__)


class AircraftDatabaseService:
    """Service to query aircraft metadata (engines, age) from the database."""

    @staticmethod
    def lookup_by_registration(registration: str) -> Optional[Dict[str, Any]]:
        """
        Look up aircraft info by registration number (e.g., 'B-LRA', 'JA891A').
        Returns dict with engines, first_flight, built_year, model, etc.
        """
        if not registration:
            return None

        db = SessionLocal()
        try:
            result = db.execute(
                text("""
                    SELECT registration, typecode, model, manufacturer, engines, engine_type,
                           first_flight, built_year, operator, operator_iata,
                           country, serial_number
                    FROM aircraft_database
                    WHERE UPPER(registration) = UPPER(:reg)
                    LIMIT 1
                """),
                {"reg": registration.strip()}
            ).fetchone()

            if result:
                return _row_to_dict(result)
            return None
        except Exception as e:
            logger.error(f"Error looking up registration {registration}: {e}")
            return None
        finally:
            db.close()

    @staticmethod
    def lookup_by_typecode(typecode: str, operator_iata: str = None) -> Optional[Dict[str, Any]]:
        """
        Look up aircraft info by ICAO type code (e.g., 'B789', 'A359').
        Optionally filter by airline IATA code for more specific results.
        Returns the most recent aircraft of that type for the operator.
        
        Strategy:
        1. Try airline + typecode with engine data
        2. Try airline + typecode without engine filter, then fill engine from global
        3. Try typecode globally with engine data
        """
        if not typecode:
            return None

        db = SessionLocal()
        try:
            result = None

            if operator_iata:
                # Step 1: airline + typecode + engines
                result = db.execute(
                    text("""
                        SELECT registration, typecode, model, manufacturer, engines, engine_type,
                               first_flight, built_year, operator, operator_iata,
                               country, serial_number
                        FROM aircraft_database
                        WHERE UPPER(typecode) = UPPER(:tc)
                          AND UPPER(operator_iata) = UPPER(:iata)
                          AND engines IS NOT NULL AND engines != ''
                        ORDER BY first_flight DESC NULLS LAST
                        LIMIT 1
                    """),
                    {"tc": typecode.strip(), "iata": operator_iata.strip()}
                ).fetchone()

                if not result:
                    # Step 2: airline + typecode WITHOUT engine filter
                    result = db.execute(
                        text("""
                            SELECT registration, typecode, model, manufacturer, engines, engine_type,
                                   first_flight, built_year, operator, operator_iata,
                                   country, serial_number
                            FROM aircraft_database
                            WHERE UPPER(typecode) = UPPER(:tc)
                              AND UPPER(operator_iata) = UPPER(:iata)
                            ORDER BY first_flight DESC NULLS LAST
                            LIMIT 1
                        """),
                        {"tc": typecode.strip(), "iata": operator_iata.strip()}
                    ).fetchone()

            if not result:
                # Step 3: typecode globally with engines
                result = db.execute(
                    text("""
                        SELECT registration, typecode, model, manufacturer, engines, engine_type,
                               first_flight, built_year, operator, operator_iata,
                               country, serial_number
                        FROM aircraft_database
                        WHERE UPPER(typecode) = UPPER(:tc)
                          AND engines IS NOT NULL AND engines != ''
                        ORDER BY first_flight DESC NULLS LAST
                        LIMIT 1
                    """),
                    {"tc": typecode.strip()}
                ).fetchone()

            if result:
                info = _row_to_dict(result)
                # If we got a result but no engines, try to fill from global data
                if not info.get("engines"):
                    engine_row = db.execute(
                        text("""
                            SELECT engines FROM aircraft_database
                            WHERE UPPER(typecode) = UPPER(:tc)
                              AND engines IS NOT NULL AND engines != ''
                              AND engines NOT IN ('2', '4', 'JET')
                            LIMIT 1
                        """),
                        {"tc": typecode.strip()}
                    ).fetchone()
                    if engine_row and engine_row[0]:
                        info["engines"] = engine_row[0]
                return info
            return None
        except Exception as e:
            logger.error(f"Error looking up typecode {typecode}: {e}")
            return None
        finally:
            db.close()

    @staticmethod
    def get_fleet_stats(operator_iata: str, typecode: str = None) -> Optional[Dict[str, Any]]:
        """
        Get fleet statistics for an airline (optionally filtered by type).
        Returns average age, engine types, and fleet size.
        """
        if not operator_iata:
            return None

        db = SessionLocal()
        try:
            if typecode:
                result = db.execute(
                    text("""
                        SELECT 
                            COUNT(*) as fleet_size,
                            AVG(EXTRACT(YEAR FROM NOW()) - built_year) as avg_age,
                            MIN(built_year) as oldest_year,
                            MAX(built_year) as newest_year,
                            MODE() WITHIN GROUP (ORDER BY engines) as common_engine
                        FROM aircraft_database
                        WHERE UPPER(operator_iata) = UPPER(:iata)
                          AND UPPER(typecode) = UPPER(:tc)
                          AND built_year IS NOT NULL
                    """),
                    {"iata": operator_iata.strip(), "tc": typecode.strip()}
                ).fetchone()
            else:
                result = db.execute(
                    text("""
                        SELECT 
                            COUNT(*) as fleet_size,
                            AVG(EXTRACT(YEAR FROM NOW()) - built_year) as avg_age,
                            MIN(built_year) as oldest_year,
                            MAX(built_year) as newest_year,
                            MODE() WITHIN GROUP (ORDER BY engines) as common_engine
                        FROM aircraft_database
                        WHERE UPPER(operator_iata) = UPPER(:iata)
                          AND built_year IS NOT NULL
                    """),
                    {"iata": operator_iata.strip()}
                ).fetchone()

            if result and result[0] > 0:
                return {
                    "fleetSize": result[0],
                    "averageAge": round(result[1], 1) if result[1] else None,
                    "oldestYear": result[2],
                    "newestYear": result[3],
                    "commonEngine": result[4],
                }
            return None
        except Exception as e:
            logger.error(f"Error getting fleet stats for {operator_iata}: {e}")
            return None
        finally:
            db.close()

    @staticmethod
    def lookup_by_model_name(model_name: str, operator_iata: str = None) -> Optional[Dict[str, Any]]:
        """
        Look up aircraft info by model name (e.g., 'Boeing 787-9', 'Airbus A350-900').
        Uses fuzzy matching on the model column.
        """
        if not model_name:
            return None

        # Normalize common model names to typecodes for more reliable lookup
        typecode = _model_name_to_typecode(model_name)
        if typecode:
            result = AircraftDatabaseService.lookup_by_typecode(typecode, operator_iata)
            if result:
                return result

        db = SessionLocal()
        try:
            # Try direct ILIKE match
            query_params = {"model": f"%{model_name.strip()}%"}
            sql = """
                SELECT registration, typecode, model, manufacturer, engines, engine_type,
                       first_flight, built_year, operator, operator_iata,
                       country, serial_number
                FROM aircraft_database
                WHERE model ILIKE :model
                  AND engines IS NOT NULL AND engines != ''
            """
            if operator_iata:
                sql += " AND UPPER(operator_iata) = UPPER(:iata)"
                query_params["iata"] = operator_iata.strip()

            sql += " ORDER BY first_flight DESC NULLS LAST LIMIT 1"

            result = db.execute(text(sql), query_params).fetchone()
            if result:
                return _row_to_dict(result)
            return None
        except Exception as e:
            logger.error(f"Error looking up model {model_name}: {e}")
            return None
        finally:
            db.close()

    @staticmethod
    def admin_update(
        typecode: str,
        operator_iata: str = None,
        engines: str = None,
        engine_type: str = None,
        built_year: int = None,
    ) -> int:
        """
        Admin-only: Update aircraft records directly in the database.
        Updates ALL rows matching the typecode (and optionally operator).
        Returns number of rows affected.
        """
        if not typecode:
            return 0

        db = SessionLocal()
        try:
            set_clauses = []
            params: Dict[str, Any] = {"tc": typecode.strip().upper()}

            if engines is not None:
                set_clauses.append("engines = :engines")
                params["engines"] = engines
            if engine_type is not None:
                set_clauses.append("engine_type = :engine_type")
                params["engine_type"] = engine_type
            if built_year is not None:
                set_clauses.append("built_year = :built_year")
                params["built_year"] = built_year

            if not set_clauses:
                return 0

            where = "UPPER(typecode) = :tc"
            if operator_iata:
                where += " AND UPPER(operator_iata) = UPPER(:iata)"
                params["iata"] = operator_iata.strip()

            sql = f"UPDATE aircraft_database SET {', '.join(set_clauses)} WHERE {where}"
            result = db.execute(text(sql), params)
            db.commit()
            return result.rowcount
        except Exception as e:
            db.rollback()
            logger.error(f"Admin update error: {e}")
            return 0
        finally:
            db.close()


# ============================================================
# Helpers
# ============================================================

def _row_to_dict(row) -> Dict[str, Any]:
    """Convert a database row to a dict with computed fields."""
    registration, typecode, model, manufacturer, engines, engine_type, \
        first_flight, built_year, operator, operator_iata, \
        country, serial_number = row

    # Calculate aircraft age
    age_years = None
    if built_year:
        age_years = datetime.now().year - built_year
    elif first_flight:
        if isinstance(first_flight, date):
            age_years = datetime.now().year - first_flight.year
        else:
            try:
                ff = datetime.strptime(str(first_flight), "%Y-%m-%d")
                age_years = datetime.now().year - ff.year
            except Exception:
                pass

    # Format age as human-readable string
    if age_years is not None:
        if age_years < 1:
            age_label = "less than 1 year"
        elif age_years == 1:
            age_label = "1 year old"
        else:
            age_label = f"{age_years} years old"
    else:
        age_label = None

    # Clean up engine string (remove HTML tags, trim)
    if engines:
        engines = engines.replace("<br>", "").replace("<br/>", "").strip()

    return {
        "registration": registration,
        "typecode": typecode,
        "model": model,
        "manufacturer": manufacturer,
        "engines": engines if engines else None,
        "engineType": engine_type if engine_type else None,
        "firstFlight": str(first_flight) if first_flight else None,
        "builtYear": built_year,
        "aircraftAge": age_years,
        "aircraftAgeLabel": age_label,
        "operator": operator,
        "operatorIata": operator_iata,
        "country": country,
        "serialNumber": serial_number,
    }


# Common aircraft model name → ICAO typecode mapping
_MODEL_TYPECODE_MAP = {
    # Boeing
    "737-700": "B737",
    "737-800": "B738",
    "737-900": "B739",
    "737 max 8": "B38M",
    "737 max 9": "B39M",
    "747-400": "B744",
    "747-8": "B748",
    "757-200": "B752",
    "757-300": "B753",
    "767-300": "B763",
    "767-400": "B764",
    "777-200": "B772",
    "777-300": "B773",
    "777-300er": "B77W",
    "777-200lr": "B77L",
    "777-9": "B779",
    "787-8": "B788",
    "787-9": "B789",
    "787-10": "B78X",
    # Airbus
    "a220-100": "BCS1",
    "a220-300": "BCS3",
    "a318": "A318",
    "a319": "A319",
    "a320": "A320",
    "a320neo": "A20N",
    "a321": "A321",
    "a321neo": "A21N",
    "a330-200": "A332",
    "a330-300": "A333",
    "a330-900": "A339",
    "a340-300": "A343",
    "a340-600": "A346",
    "a350-900": "A359",
    "a350-1000": "A35K",
    "a380": "A388",
    "a380-800": "A388",
}


def _model_name_to_typecode(model_name: str) -> Optional[str]:
    """Try to convert a model name to an ICAO typecode."""
    name = model_name.lower().strip()

    # Direct lookup
    for key, code in _MODEL_TYPECODE_MAP.items():
        if key in name:
            return code

    # Try extracting just numbers (e.g., "Boeing 787-9 Dreamliner" → "787-9")
    import re
    match = re.search(r'(\d{3})-?(\d{1,2})?', name)
    if match:
        base = match.group(1)
        variant = match.group(2) or ""
        search = f"{base}-{variant}" if variant else base
        for key, code in _MODEL_TYPECODE_MAP.items():
            if search in key:
                return code

    return None

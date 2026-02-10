"""
AirEase Backend – Safety Profile Service

Resolves a flight code (e.g. "UA123") into a tail/registration number via
FlightRadar24, then queries the NTSB PostgreSQL tables (events, aircraft,
engines, narratives) to build a comprehensive safety profile.
"""

from typing import Optional, Dict, Any, List
from datetime import datetime
import logging

from sqlalchemy import text
from app.database import SessionLocal
from app.services.aircraft_db_service import AircraftDatabaseService

logger = logging.getLogger(__name__)

# ============================================================
# 1. FlightRadar24 Resolver
# ============================================================

def get_tail_number(flight_code: str) -> Optional[str]:
    """
    Resolve a flight code (e.g. 'UA123') to a registration / tail number
    using the FlightRadar24 API.
    Returns the registration string (e.g. 'N456UA') or None.
    """
    if not flight_code:
        return None
    try:
        from FlightRadar24.api import FlightRadar24API
        fr_api = FlightRadar24API()
        
        code = flight_code.strip().upper()
        
        # Extract airline ICAO code from flight code (e.g., "UA123" → "UAL")
        # FlightRadar24 get_flights(airline=...) uses ICAO codes
        # We try with the IATA prefix first by getting all flights for that airline
        import re
        match = re.match(r'^([A-Z]{2,3})(\d+)$', code)
        if not match:
            return None
        
        airline_prefix = match.group(1)
        flight_num = match.group(2)
        
        # Map common 2-letter IATA → 3-letter ICAO
        iata_to_icao = {
            "UA": "UAL", "AA": "AAL", "DL": "DAL", "WN": "SWA",
            "AS": "ASA", "B6": "JBU", "NK": "NKS", "F9": "FFT",
            "HA": "HAL", "SY": "SCX", "BA": "BAW", "LH": "DLH",
            "AF": "AFR", "KL": "KLM", "QF": "QFA", "SQ": "SIA",
            "CX": "CPA", "JL": "JAL", "NH": "ANA", "EK": "UAE",
            "QR": "QTR", "TK": "THY", "LX": "SWR", "AC": "ACA",
            "NZ": "ANZ", "CZ": "CSN", "CA": "CCA", "MU": "CES",
            "KE": "KAL", "OZ": "AAR", "BR": "EVA", "CI": "CAL",
            "HX": "CRK", "UO": "HKE", "5J": "CEB",
        }
        
        icao_code = iata_to_icao.get(airline_prefix, airline_prefix)
        
        # Fetch active flights for this airline
        flights = fr_api.get_flights(airline=icao_code)
        
        # Match by flight number (e.g., "UA123" or "UAL123")
        target_numbers = {code, f"{icao_code}{flight_num}"}
        
        for f in flights:
            fn = getattr(f, "number", "") or ""
            cs = getattr(f, "callsign", "") or ""
            if fn.upper() in target_numbers or cs.upper() in target_numbers:
                reg = getattr(f, "registration", None)
                if reg:
                    return reg.strip().upper()
        
        return None
    except Exception as e:
        logger.warning(f"FlightRadar24 lookup failed for {flight_code}: {e}")
        return None


# ============================================================
# 2. NTSB Database Queries
# ============================================================

def get_aircraft_specs(reg_no: str) -> Optional[Dict[str, Any]]:
    """
    Query NTSB aircraft + engines tables by registration number.
    Returns engine manufacturer, engine model, engine type, model, operator,
    and year_built (derived from ev_date of earliest event for this reg).
    """
    if not reg_no:
        return None

    db = SessionLocal()
    try:
        # Get aircraft info + engine info joined
        row = db.execute(
            text("""
                SELECT
                    a.ev_id,
                    a.reg_no,
                    a.oper_name,
                    a.mfr_make,
                    a.model,
                    e.eng_mfgr,
                    e.eng_model,
                    e.eng_type
                FROM aircraft a
                LEFT JOIN engines e
                    ON a.ev_id = e.ev_id AND a.aircraft_key = e.aircraft_key
                WHERE UPPER(TRIM(a.reg_no)) = UPPER(TRIM(:reg))
                ORDER BY a.ev_id DESC
                LIMIT 1
            """),
            {"reg": reg_no.strip()},
        ).fetchone()

        if not row:
            return None

        return {
            "ev_id": row[0],
            "reg_no": row[1],
            "operator": row[2],
            "mfr_make": row[3],
            "model": row[4],
            "eng_mfgr": row[5],
            "eng_model": row[6],
            "eng_type": row[7],
        }
    except Exception as e:
        logger.error(f"get_aircraft_specs error for {reg_no}: {e}")
        return None
    finally:
        db.close()


def get_plane_accidents(reg_no: str) -> List[Dict[str, Any]]:
    """
    Return accident history for a specific tail number from the NTSB database.
    Joins events ↔ aircraft ↔ narratives.
    """
    if not reg_no:
        return []

    db = SessionLocal()
    try:
        rows = db.execute(
            text("""
                SELECT
                    ev.ev_id,
                    ev.ev_date,
                    ev.ev_city,
                    ev.ev_state,
                    ev.ev_country,
                    ev.injury_severity,
                    n.narr_cause,
                    n.narr_acc_desc
                FROM events ev
                JOIN aircraft a ON ev.ev_id = a.ev_id
                LEFT JOIN narratives n ON ev.ev_id = n.ev_id
                WHERE UPPER(TRIM(a.reg_no)) = UPPER(TRIM(:reg))
                ORDER BY ev.ev_date DESC
            """),
            {"reg": reg_no.strip()},
        ).fetchall()

        return [
            {
                "ev_id": r[0],
                "date": r[1].strftime("%Y-%m-%d") if r[1] else None,
                "city": r[2],
                "state": r[3],
                "country": r[4],
                "injury_severity": r[5],
                "cause": _truncate(r[6], 300),
                "description": _truncate(r[7], 500),
            }
            for r in rows
        ]
    except Exception as e:
        logger.error(f"get_plane_accidents error for {reg_no}: {e}")
        return []
    finally:
        db.close()


def get_airline_accidents(operator_name: str, years: int = 10) -> int:
    """
    Count NTSB events for a given operator (airline) in the last *years* years.
    Uses ILIKE for fuzzy matching on oper_name.
    """
    if not operator_name:
        return 0

    db = SessionLocal()
    try:
        cutoff_year = datetime.now().year - years
        row = db.execute(
            text("""
                SELECT COUNT(DISTINCT ev.ev_id)
                FROM events ev
                JOIN aircraft a ON ev.ev_id = a.ev_id
                WHERE a.oper_name ILIKE :op
                  AND ev.ev_date >= :cutoff
            """),
            {
                "op": f"%{operator_name.strip()}%",
                "cutoff": f"{cutoff_year}-01-01",
            },
        ).fetchone()
        return row[0] if row else 0
    except Exception as e:
        logger.error(f"get_airline_accidents error for {operator_name}: {e}")
        return 0
    finally:
        db.close()


def get_model_accidents(model: str) -> int:
    """
    Count total NTSB events for a given aircraft model.
    Uses ILIKE for fuzzy matching.
    """
    if not model:
        return 0

    db = SessionLocal()
    try:
        row = db.execute(
            text("""
                SELECT COUNT(DISTINCT ev.ev_id)
                FROM events ev
                JOIN aircraft a ON ev.ev_id = a.ev_id
                WHERE a.model ILIKE :mdl
            """),
            {"mdl": f"%{model.strip()}%"},
        ).fetchone()
        return row[0] if row else 0
    except Exception as e:
        logger.error(f"get_model_accidents error for {model}: {e}")
        return 0
    finally:
        db.close()


# ============================================================
# 3. Orchestrator – Build Full Safety Profile
# ============================================================

def build_safety_profile(
    flight_code: Optional[str] = None,
    airline: Optional[str] = None,
    airline_iata: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    End-to-end safety profile builder.

    1. Resolve flight_code → tail_number via FlightRadar24.
    2. Query NTSB for aircraft specs, accident history.
    3. Query NTSB for airline-wide and model-wide accident stats.
    4. **Fallback**: If NTSB has no engine/age data (plane was never in an
       accident), use the OpenSky aircraft_database for engine & age.
    5. Return a unified JSON response.
    """

    # --- Step 1: Resolve tail number ---
    tail_number = None
    if flight_code:
        tail_number = get_tail_number(flight_code)

    # --- Step 2: Aircraft specs from NTSB (if tail found) ---
    specs = get_aircraft_specs(tail_number) if tail_number else None

    # Derive operator / model from specs or fall back to caller-supplied values
    resolved_airline = (specs or {}).get("operator") or airline
    resolved_model = (specs or {}).get("model") or model
    resolved_mfr = (specs or {}).get("mfr_make")

    # Engine string from NTSB
    eng_mfgr = (specs or {}).get("eng_mfgr")
    eng_model = (specs or {}).get("eng_model")
    eng_type = (specs or {}).get("eng_type")
    engine_str = None
    if eng_mfgr or eng_model:
        parts = [p for p in [eng_mfgr, eng_model] if p]
        engine_str = " ".join(parts)
        if eng_type:
            engine_str += f" ({eng_type})"

    # --- Step 3: OpenSky fallback for engine & age ---
    built_year: Optional[int] = None
    age_years: Optional[int] = None
    age_label: Optional[str] = None
    opensky_info: Optional[Dict[str, Any]] = None

    # Try OpenSky lookup: registration first, then model+airline
    if tail_number:
        opensky_info = AircraftDatabaseService.lookup_by_registration(tail_number)
    if not opensky_info and model:
        opensky_info = AircraftDatabaseService.lookup_by_model_name(model, airline_iata)

    if opensky_info:
        # Fill engine from OpenSky if NTSB didn't have it
        if not engine_str and opensky_info.get("engines"):
            engine_str = opensky_info["engines"]
            if opensky_info.get("engineType"):
                engine_str += f" ({opensky_info['engineType']})"
            eng_type = opensky_info.get("engineType") or eng_type
        # Fill age from OpenSky
        built_year = opensky_info.get("builtYear")
        age_years = opensky_info.get("aircraftAge")
        age_label = opensky_info.get("aircraftAgeLabel")
        # Fill model/manufacturer if still missing
        if not resolved_mfr:
            resolved_mfr = opensky_info.get("manufacturer")
        if not resolved_model:
            resolved_model = opensky_info.get("model")

    # --- Step 4: Accident queries ---
    plane_accidents = get_plane_accidents(tail_number) if tail_number else None
    airline_total = get_airline_accidents(resolved_airline, years=10) if resolved_airline else 0
    model_total = get_model_accidents(resolved_model) if resolved_model else 0

    # --- Step 5: Build response ---
    full_model_name = None
    if resolved_mfr and resolved_model:
        full_model_name = f"{resolved_mfr} {resolved_model}"
    elif resolved_model:
        full_model_name = resolved_model

    return {
        "flight_info": {
            "flight_code": flight_code,
            "tail_number": tail_number,
            "airline": resolved_airline,
            "model": full_model_name or model,
            "built_year": built_year,
            "age_years": age_years,
            "age_label": age_label,
        },
        "technical_specs": {
            "engine": engine_str,
            "eng_mfgr": eng_mfgr,
            "eng_model": eng_model,
            "eng_type": eng_type,
        },
        "safety_records": {
            "this_plane_accidents": plane_accidents,
            "airline_total_accidents": airline_total,
            "model_total_accidents": model_total,
        },
    }


# ============================================================
# Helpers
# ============================================================

def _truncate(text_val: Optional[str], max_len: int) -> Optional[str]:
    """Truncate a string to max_len, adding '…' if truncated."""
    if not text_val:
        return None
    text_val = str(text_val).strip()
    if len(text_val) <= max_len:
        return text_val
    return text_val[: max_len - 1] + "…"

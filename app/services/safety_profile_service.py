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
from app.services.aerodatabox_service import enrich_aircraft as aerodatabox_enrich

logger = logging.getLogger(__name__)


def _infer_engine_type_from_string(engine_str: Optional[str]) -> Optional[str]:
    """
    Infer engine type ('Jet', 'Turboprop', 'Piston') from the engine string.
    Known jet engine families help us correct wrong AeroDataBox data.
    """
    if not engine_str:
        return None

    upper = engine_str.upper()

    # Known JET engine families/keywords
    JET_KEYWORDS = [
        "TRENT", "GE90", "GENX", "GE9X", "CF6", "CF34", "CFM", "LEAP",
        "PW4000", "PW1000", "PW1100", "PW1500", "PW2000", "JT8D", "JT9D",
        "V2500", "GP7200", "RB211",
        "TURBOFAN",
    ]
    for kw in JET_KEYWORDS:
        if kw in upper:
            return "Jet"

    # Known TURBOPROP engine families
    TP_KEYWORDS = ["PW100", "PW150", "PT6", "CT7", "PW120", "PW127", "TPE331", "TURBOPROP"]
    for kw in TP_KEYWORDS:
        if kw in upper:
            return "Turboprop"

    return None


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


# ── Airline name → NTSB operator name mapping ──
# Short/brand names that would cause false-positive substring matches.
# Maps to a list of known NTSB oper_name patterns.
_AIRLINE_NAME_EXPANSIONS: Dict[str, List[str]] = {
    "ANA":          ["All Nippon%", "ANA%"],
    "JAL":          ["Japan Air%", "JAL%"],
    "SIA":          ["Singapore Airlines%"],
    "CX":           ["Cathay Pacific%"],
    "QF":           ["Qantas%"],
    "BA":           ["British Airways%"],
    "AF":           ["Air France%"],
    "LH":           ["Lufthansa%", "Deutsche Lufthansa%"],
    "KE":           ["Korean Air%"],
    "OZ":           ["Asiana%"],
    "TK":           ["Turkish Airlines%", "Turk Hava Yollari%"],
    "EK":           ["Emirates%"],
    "QR":           ["Qatar Airways%"],
    "SQ":           ["Singapore Airlines%"],
    "EVA":          ["EVA Air%"],
    "CI":           ["China Airlines%"],
}


def _airline_where_clause(airline_name: str) -> tuple:
    """
    Build a SQL WHERE clause + params for airline matching.
    Uses exact-prefix or known expansions for short names to avoid
    false positives (e.g. 'ANA' matching 'Ryanair').
    
    Returns (where_sql, params_dict).
    """
    name = airline_name.strip()
    upper = name.upper()

    # Check if we have a known expansion for this airline name
    if upper in _AIRLINE_NAME_EXPANSIONS:
        patterns = _AIRLINE_NAME_EXPANSIONS[upper]
        conditions = []
        params = {}
        for i, pat in enumerate(patterns):
            key = f"airline_{i}"
            conditions.append(f"a.oper_name ILIKE :{key}")
            params[key] = pat
        return " OR ".join(conditions), params

    # For longer names (>=5 chars), substring match is usually safe
    if len(name) >= 5:
        return "a.oper_name ILIKE :airline_0", {"airline_0": f"%{name}%"}

    # For short names (<5 chars), use word-boundary matching via regex
    # This ensures 'ANA' matches 'ANA' or 'ANA Wings' but not 'Ryanair'
    return "a.oper_name ~* :airline_0", {"airline_0": f"(^|\\W){name}($|\\W)"}


def get_airline_accidents(operator_name: str, years: int = 10) -> int:
    """
    Count NTSB events for a given operator (airline) in the last *years* years.
    Uses word-boundary-aware matching to avoid false positives
    (e.g. 'ANA' should not match 'Ryanair' or 'Air Canada').
    """
    if not operator_name:
        return 0

    db = SessionLocal()
    try:
        cutoff_year = datetime.now().year - years
        where, params = _airline_where_clause(operator_name.strip())
        params["cutoff"] = f"{cutoff_year}-01-01"
        row = db.execute(
            text(f"""
                SELECT COUNT(DISTINCT ev.ev_id)
                FROM events ev
                JOIN aircraft a ON ev.ev_id = a.ev_id
                WHERE ({where})
                  AND ev.ev_date >= :cutoff
            """),
            params,
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


def get_incidents_paginated(
    query_type: str,
    query_value: str,
    page: int = 1,
    per_page: int = 10,
) -> Dict[str, Any]:
    """
    Return paginated NTSB incident records with narratives.
    
    query_type: 'tail' | 'airline' | 'model'
    query_value: the tail number, airline name, or model name
    """
    if not query_value:
        return {"records": [], "total": 0, "page": page, "per_page": per_page, "total_pages": 0}

    db = SessionLocal()
    try:
        # Build WHERE clause based on query_type
        if query_type == "tail":
            where_clause = "UPPER(TRIM(a.reg_no)) = UPPER(TRIM(:val))"
            params = {"val": query_value.strip()}
        elif query_type == "airline":
            airline_where, params = _airline_where_clause(query_value.strip())
            cutoff_year = datetime.now().year - 10
            where_clause = f"({airline_where}) AND ev.ev_date >= :cutoff"
            params["cutoff"] = f"{cutoff_year}-01-01"
        elif query_type == "model":
            where_clause = "a.model ILIKE :val"
            params = {"val": f"%{query_value.strip()}%"}
        else:
            return {"records": [], "total": 0, "page": page, "per_page": per_page, "total_pages": 0}

        # Count total
        count_row = db.execute(
            text(f"""
                SELECT COUNT(DISTINCT ev.ev_id)
                FROM events ev
                JOIN aircraft a ON ev.ev_id = a.ev_id
                WHERE {where_clause}
            """),
            params,
        ).fetchone()
        total = count_row[0] if count_row else 0
        total_pages = max(1, (total + per_page - 1) // per_page)

        # Fetch page
        offset = (page - 1) * per_page
        page_params = {**params, "limit": per_page, "offset": offset}
        rows = db.execute(
            text(f"""
                SELECT DISTINCT ON (ev.ev_id)
                    ev.ev_id,
                    ev.ev_date,
                    ev.ev_city,
                    ev.ev_state,
                    ev.ev_country,
                    ev.injury_severity,
                    a.model,
                    a.oper_name,
                    a.reg_no,
                    n.narr_cause,
                    n.narr_acc_desc
                FROM events ev
                JOIN aircraft a ON ev.ev_id = a.ev_id
                LEFT JOIN narratives n ON ev.ev_id = n.ev_id
                WHERE {where_clause}
                ORDER BY ev.ev_id, ev.ev_date DESC
            """),
            params,
        ).fetchall()

        # Sort by date descending in Python, then paginate
        # (DISTINCT ON requires ORDER BY ev.ev_id first, so we sort afterwards)
        sorted_rows = sorted(rows, key=lambda r: r[1] or datetime.min, reverse=True)
        paged_rows = sorted_rows[offset:offset + per_page]

        records = []
        for r in paged_rows:
            records.append({
                "ev_id": r[0],
                "date": r[1].strftime("%Y-%m-%d") if r[1] else None,
                "city": r[2],
                "state": r[3],
                "country": r[4],
                "injury_severity": r[5],
                "model": r[6],
                "operator": r[7],
                "registration": r[8],
                "cause": r[9],
                "description": r[10],
            })

        return {
            "records": records,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
        }
    except Exception as e:
        logger.error(f"get_incidents_paginated error ({query_type}={query_value}): {e}")
        return {"records": [], "total": 0, "page": page, "per_page": per_page, "total_pages": 0}
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
    
    # If registration lookup returned no engine data, also try typecode for engine
    opensky_typecode_info: Optional[Dict[str, Any]] = None
    if opensky_info and not opensky_info.get("engines") and opensky_info.get("typecode"):
        opensky_typecode_info = AircraftDatabaseService.lookup_by_typecode(
            opensky_info["typecode"], airline_iata
        )

    if opensky_info:
        # Fill engine from OpenSky if NTSB didn't have it
        if not engine_str:
            # Prefer typecode engine (more specific, e.g. "RR Trent XWB") over registration
            engine_source = opensky_typecode_info if opensky_typecode_info and opensky_typecode_info.get("engines") else opensky_info
            if engine_source.get("engines"):
                engine_str = engine_source["engines"]
                if engine_source.get("engineType"):
                    engine_str += f" ({engine_source['engineType']})"
                eng_type = engine_source.get("engineType") or eng_type
        # Fill age from OpenSky
        built_year = opensky_info.get("builtYear")
        age_years = opensky_info.get("aircraftAge")
        age_label = opensky_info.get("aircraftAgeLabel")
        # Fill model/manufacturer if still missing
        if not resolved_mfr:
            resolved_mfr = opensky_info.get("manufacturer")
        if not resolved_model:
            resolved_model = opensky_info.get("model")

    # --- Step 4: AeroDataBox API fallback (engine, age, image) ---
    image_url: Optional[str] = None
    image_attribution: Optional[str] = None
    adb_info: Optional[Dict[str, Any]] = None
    num_seats: Optional[int] = None

    # Determine the best registration to use for AeroDataBox
    adb_reg = tail_number
    if not adb_reg and opensky_info and opensky_info.get("registration"):
        adb_reg = opensky_info["registration"]

    # Only call AeroDataBox if we still lack engine OR age data
    needs_engine = not engine_str
    needs_age = age_years is None
    needs_eng_type = not eng_type
    if (needs_engine or needs_age or needs_eng_type) and adb_reg:
        adb_info = aerodatabox_enrich(adb_reg)
    elif adb_reg:
        # Even if we have engine+age, still try to get image from cache (no API call)
        adb_info = aerodatabox_enrich(adb_reg)

    if adb_info:
        if not engine_str and adb_info.get("engineStr"):
            engine_str = adb_info["engineStr"]
            eng_type = adb_info.get("engineType") or eng_type
        if not eng_type and adb_info.get("engineType"):
            eng_type = adb_info["engineType"]
        if age_years is None and adb_info.get("ageYears") is not None:
            age_years = round(adb_info["ageYears"], 1)
            age_label = adb_info.get("ageLabel")
        if built_year is None and adb_info.get("builtYear"):
            built_year = adb_info["builtYear"]
        if not resolved_model and adb_info.get("typeName"):
            resolved_model = adb_info["typeName"]
        if adb_info.get("numSeats"):
            num_seats = adb_info["numSeats"]
        image_url = adb_info.get("imageUrl")
        image_attribution = adb_info.get("imageAttribution")

    # --- Step 4b: Cross-validate engine type ---
    # If we have a concrete engine string (e.g. "RR Trent XWB"), use it to
    # infer the correct engine type — this overrides potentially wrong
    # AeroDataBox data (e.g. "Turboprop" for an A350).
    inferred = _infer_engine_type_from_string(engine_str)
    if inferred and eng_type and inferred != eng_type:
        logger.info(f"🔧 Engine type override: '{eng_type}' → '{inferred}' (inferred from engine string '{engine_str}')")
        eng_type = inferred
    elif inferred and not eng_type:
        eng_type = inferred

    # --- Step 5: Accident queries ---
    plane_accidents = get_plane_accidents(tail_number) if tail_number else None
    airline_total = get_airline_accidents(resolved_airline, years=10) if resolved_airline else 0
    model_total = get_model_accidents(resolved_model) if resolved_model else 0

    # --- Step 6: Build response ---
    full_model_name = None
    if resolved_mfr and resolved_model:
        # Avoid duplication like "Boeing Boeing 787" when model already contains manufacturer
        if resolved_model.upper().startswith(resolved_mfr.upper()):
            full_model_name = resolved_model
        else:
            full_model_name = f"{resolved_mfr} {resolved_model}"
    elif resolved_model:
        full_model_name = resolved_model

    return {
        "flight_info": {
            "flight_code": flight_code,
            "tail_number": tail_number,
            "airline": resolved_airline,
            "model": full_model_name or model,
            "model_query": resolved_model or model,
            "built_year": built_year,
            "age_years": age_years,
            "age_label": age_label,
            "num_seats": num_seats,
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
        "aircraft_image": {
            "url": image_url,
            "attribution": image_attribution,
        } if image_url else None,
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

"""
AirEase Backend - AI Search API Routes
AI智能搜索API路由
"""

import re
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List

from app.models import AISearchRequest, AISearchResponse
from app.services.gemini_service import gemini_service
from app.services.airport_resolver import resolve_to_iata, _lookup_iata

router = APIRouter(prefix="/v1/ai", tags=["AI Search"])


class ChatRequest(BaseModel):
    """对话请求"""
    message: str
    persona: Optional[str] = None
    context: Optional[str] = None


class ChatResponse(BaseModel):
    """对话响应"""
    reply: str
    parsed_query: Optional[dict] = None


class ParseQueryRequest(BaseModel):
    """Natural language parse request (single-shot)"""
    query: str


class ConversationMessage(BaseModel):
    """A single message in the conversation"""
    role: str  # 'user' or 'assistant'
    content: str


class ChatConversationRequest(BaseModel):
    """Multi-turn conversation request"""
    message: str
    conversation_history: Optional[List[ConversationMessage]] = None


@router.post(
    "/search",
    response_model=AISearchResponse,
    summary="AI智能搜索",
    description="使用自然语言搜索航班，AI将自动解析查询意图"
)
async def ai_search(request: AISearchRequest):
    """
    AI智能搜索
    
    将自然语言转换为结构化搜索参数
    
    **示例输入:**
    - "下周三北京到上海的公务舱"
    - "明天去广州的航班"
    - "后天从深圳飞成都，经济舱"
    
    **返回:**
    - 解析后的搜索参数
    - 置信度分数
    - 原始查询
    """
    try:
        result = await gemini_service.parse_flight_query(request.query)
        
        parsed_query = result.get("parsed_query")
        
        return AISearchResponse(
            parsedQuery=parsed_query,
            confidence=result.get("confidence", 0.0),
            originalQuery=request.query,
            suggestions=result.get("suggestions", [])
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI解析失败: {str(e)}")


@router.post(
    "/explain",
    response_model=ChatResponse,
    summary="AI评分解释",
    description="使用AI生成航班评分的个性化解释"
)
async def ai_explain(request: ChatRequest):
    """
    生成AI评分解释
    
    根据用户画像生成个性化的航班评分解释
    """
    try:
        explanation = await gemini_service.generate_score_explanation(
            flight_info=request.message,
            score_info=request.context or "",
            persona=request.persona or "business"
        )
        
        return ChatResponse(reply=explanation)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI生成失败: {str(e)}")


@router.get(
    "/health",
    summary="AI服务健康检查",
    description="检查Gemini AI服务是否可用"
)
async def ai_health():
    """检查AI服务状态"""
    from app.config import settings
    
    has_key = bool(settings.gemini_api_key)
    
    return {
        "status": "ok" if has_key else "no_api_key",
        "service": "gemini",
        "model": "gemini-3.1-flash-lite",
        "api_key_configured": has_key
    }


@router.post(
    "/parse-query",
    summary="Parse natural language flight search",
    description="Single-shot parsing of a natural language query into structured search parameters"
)
async def parse_query(request: ParseQueryRequest):
    """
    Parse a natural language flight search query.
    
    This proxies the Gemini API call through the backend so the frontend
    doesn't need direct access to Google's API.
    
    **Example inputs:**
    - "fly to Tokyo next Friday morning"
    - "cheapest direct flight to Bangkok"
    - "去上海"
    """
    # Pre-check: detect flight-number lookup intent (e.g. "American AA 1313",
    # "flight UA 857", "航班号 CA1858"). The product doesn't support direct
    # flight-number lookup, so short-circuit with a structured signal that the
    # frontend can render in the user's locale.
    if _looks_like_flight_number_lookup(request.query):
        return _empty_parse_result(
            unsupported_intent="flight_number_lookup",
            error_code="FLIGHT_NUMBER_LOOKUP_NOT_SUPPORTED",
        )

    # Redact flight-property phrases from the query the LLM sees so it can't
    # mistake them for airport codes (e.g. 'red-eye' → 'RED'). The original
    # query is still used for downstream resolution heuristics.
    sanitized_query = _redact_property_phrases(request.query)

    try:
        result = await gemini_service.parse_natural_language_query(sanitized_query)
    except Exception as e:
        # Instead of returning 500, use local fallback parser
        print(f"AI parse_query falling back to local parser: {e}")
        result = gemini_service._local_parse_natural_language(sanitized_query)

    # Drop hallucinated IATA codes that don't exist in the airports DB.
    # Bug: Gemini sometimes invents codes like "RED" from phrases like
    # "no red-eye flights" or "US to Thailand". The downstream resolver
    # would otherwise pass the bogus code straight to the search API.
    _drop_hallucinated_codes(result)

    # Post-process: resolve any unresolved departure / destination by querying
    # the airports DB. Handles small/private airports (e.g. "palo alto airport"
    # → PAO), CJK city names (e.g. "舊金山" → SFO) and misspellings
    # (e.g. "francicso" → SFO) that the LLM either skipped or got wrong.
    _enrich_with_airport_resolver(request.query, result)

    # Bug ("5月21日北京飞伦敦"): Gemini intermittently shifts explicit Chinese
    # dates by ±1 day (timezone or "next occurrence" guesswork). When the user
    # spells out 「N月D日」 deterministically, override Gemini's date with the
    # parsed date in the current year (rolling to next year only if the date
    # has already passed this year).
    _override_explicit_cjk_date(request.query, result)
    return result


_CJK_MONTH_DAY_RE = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号號]")


def _override_explicit_cjk_date(query: str, result: dict) -> None:
    """If the query contains explicit "N月D日" dates, force them onto the
    result. The 1st match overrides `date`; the 2nd (if present) overrides
    `return_date`. Both anchor to the current year, rolling forward to next
    year only if the date has already passed; the return date is additionally
    forced to be >= the outbound date so a round-trip never produces an
    invalid (return < depart) pair across year boundaries.
    Idempotent / safe."""
    matches = list(_CJK_MONTH_DAY_RE.finditer(query))
    if not matches:
        return
    today = datetime.now().date()

    def _to_date(match):
        try:
            month = int(match.group(1))
            day = int(match.group(2))
            if not (1 <= month <= 12 and 1 <= day <= 31):
                return None
            candidate = today.replace(month=month, day=day)
        except (ValueError, TypeError):
            return None
        if candidate < today:
            try:
                candidate = candidate.replace(year=today.year + 1)
            except ValueError:
                return None
        return candidate

    depart = _to_date(matches[0])
    if depart is None:
        return
    result["date"] = depart.isoformat()

    if len(matches) >= 2:
        ret = _to_date(matches[1])
        if ret is None:
            return
        # Ensure round-trip consistency: return must be on or after departure.
        # If the natural-year resolution put return before depart (e.g. depart
        # rolled to next year but return stayed in this year), bump return to
        # depart's year (or +1 if still earlier).
        if ret < depart:
            try:
                ret = ret.replace(year=depart.year)
            except ValueError:
                return
            if ret < depart:
                try:
                    ret = ret.replace(year=depart.year + 1)
                except ValueError:
                    return
        result["return_date"] = ret.isoformat()


# Match "from X to Y" / "from X going to Y" / Chinese 从X到Y.
# Uses [^\s] sequences so any Unicode (incl. CJK) is captured without `regex` lib.
_FROM_TO_EN_RE = re.compile(
    r"\b(?:from|departing\s+from|leaving\s+from)\s+"
    r"([\S][\S\s]{0,40}?)"
    r"\s+(?:to|going\s+to|→|->)\s+"
    r"([\S][\S\s]{0,40}?)"
    r"(?:\s+(?:on|next|tomorrow|today|in|the)\b|[?.!,]|$)",
    re.IGNORECASE,
)
_FROM_TO_CN_RE = re.compile(
    # Bug 2548192: list multi-char verbs (飞往/飛往/飞去/飛去) BEFORE single-char
    # 飞/飛 so "从喀什飞往OSS" doesn't match 飞 first and capture 往 into the
    # destination group. Also require the destination CJK group to be 2+ chars,
    # since real city names are at least 2 chars and "往" alone is never a city.
    r"(?:从|從|出發於|出发于)\s*([\u4e00-\u9fff]+?)\s*"
    r"(?:飛往|飞往|飛去|飞去|到|至|往|去|飛|飞|→|->)\s*"
    r"([\u4e00-\u9fff]{2,})"
)
# Bug 2548250: Japanese sentence pattern "X から Y へ / X から Y まで / X から Y に".
# Without this the resolver only saw the standalone Kanji "北京" (matching as a
# CJK city via _TO_ONLY_CN_RE in some cases) and lost the destination.
_FROM_TO_JP_RE = re.compile(
    r"([\u3400-\u9fff]+)\s*(?:から|発)\s*([\u3400-\u9fff]+)\s*(?:へ|まで|に|行き)"
)
_TO_ONLY_EN_RE = re.compile(
    r"(?:^|\s)(?:to|going\s+to|fly\s+to)\s+"
    r"([A-Za-z][A-Za-z0-9\s'.\-]{1,40}?)"
    r"(?:\s+(?:on|next|tomorrow|today|in|the)\b|[?.!,]|$)",
    re.IGNORECASE,
)
_TO_ONLY_CN_RE = re.compile(
    # Match "去/到/往/至 + (CJK city name)" anywhere in the query, including
    # immediately after another CJK char (e.g. "明天去東京"). The captured
    # group is greedy CJK chars; the airport resolver does longest-substring
    # CJK→English mapping, so trailing modifiers like "最便宜的商務直飛航班"
    # are tolerated.
    r"(?:去|到|往|至|飛去|飞去|飛往|飞往)\s*([\u4e00-\u9fff]+)"
)

# Bug 2548171: bare-verb pattern "X飞Y" / "X飛Y" without a 从/從 prefix.
# e.g. "5月21日北京飞伦敦的头等舱" → origin=北京, destination=伦敦.
# Bug (Shanghai→Haikou same-city): also accept the bare 到/至/往/去 verb so
# queries like "上海到海口的航班" extract origin=上海, destination=海口
# instead of falling through to Gemini (which may leave the destination
# blank and let the geolocation default collide with the parsed origin).
_X_FLY_Y_CN_RE = re.compile(
    r"([\u4e00-\u9fff]{2,})\s*(?:飞往|飛往|飞去|飛去|飞|飛|到|至|往|去)\s*([\u4e00-\u9fff]{2,})"
)
# Bug 2548192: mixed CJK origin → Latin destination (often a 3-letter IATA),
# e.g. "喀什飞OSS" / "喀什 到 OSS" / "从喀什飞往OSS".
_CJK_TO_LATIN_RE = re.compile(
    r"(?:从|從|出發於|出发于)?\s*([\u4e00-\u9fff]{2,})\s*"
    r"(?:到|至|往|去|飛往|飞往|飛去|飞去|飛|飞|→|->)\s*"
    r"([A-Za-z]{3,}(?:[\s'\.\-][A-Za-z]+)*)"
)
# And the symmetric Latin → CJK case ("Tokyo 到 北京").
_LATIN_TO_CJK_RE = re.compile(
    r"([A-Za-z]{3,}(?:[\s'\.\-][A-Za-z]+)*)\s*"
    r"(?:到|至|往|去|飛往|飞往|飛去|飞去|飛|飞|→|->)\s*"
    r"([\u4e00-\u9fff]{2,})"
)


def _extract_from_to(query: str):
    """Pull user-typed origin/destination phrases out of the raw query.
    Returns (from_str | None, to_str | None)."""
    # Japanese "X から Y へ" first — must precede the generic CN pattern so
    # queries like "北京から休斯顿へ" are not partially captured by 去/到.
    m = _FROM_TO_JP_RE.search(query)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    # Chinese 从X到Y next (more specific)
    m = _FROM_TO_CN_RE.search(query)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    # Bug 2548171: bare "X飞Y" without 从 prefix.
    m = _X_FLY_Y_CN_RE.search(query)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    # Bug 2548192: mixed CJK + Latin (e.g. "喀什飞OSS").
    m = _CJK_TO_LATIN_RE.search(query)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    m = _LATIN_TO_CJK_RE.search(query)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    m = _FROM_TO_EN_RE.search(query)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    m = _TO_ONLY_CN_RE.search(query)
    if m:
        return None, m.group(1).strip()
    m = _TO_ONLY_EN_RE.search(query)
    if m:
        return None, m.group(1).strip()
    return None, None


# Common airline IATA codes used to recognise "<airline> <number>" flight-number
# lookups (e.g. "AA1313", "United UA 857"). This is intentionally curated to
# the major carriers — extending it is cheap, but false positives here would
# block legitimate searches.
_AIRLINE_IATA_CODES = frozenset({
    # North America
    "AA", "UA", "DL", "AS", "B6", "F9", "NK", "WN", "HA", "AC", "WS",
    # Europe
    "BA", "LH", "AF", "KL", "IB", "AY", "SK", "LX", "OS", "AZ", "TK",
    "EI", "VS", "DY", "FR", "U2", "VY", "TP", "LO", "SU",
    # Middle East / Africa
    "EK", "QR", "EY", "SV", "MS", "ET", "KQ", "RJ", "GF", "WY",
    # Asia / Oceania
    "CX", "KA", "SQ", "TG", "MH", "GA", "JL", "NH", "KE", "OZ", "BR",
    "CI", "MU", "CA", "CZ", "HU", "FM", "MF", "ZH", "9C", "NX", "QF",
    "VA", "NZ", "FJ", "PR", "5J", "VN", "TR", "AK", "AI", "6E", "UK",
})

# "American AA1313", "AA 1313", "United UA857", "flight number CA1858",
# "\u822a\u73ed\u53f7 CA1858" \u2192 detected as flight-number lookup.
_FLIGHT_NUMBER_RE = re.compile(r"\b([A-Z]{2})\s*(\d{1,5})\b")
_FLIGHT_NUMBER_KEYWORD_RE = re.compile(
    r"(flight\s*(?:number|no|num)?|\u822a\u73ed\u53f7|\u822a\u73ed\u865f|\u73ed\u6b21)\s*[:#]?\s*([A-Z]{2})?\s*(\d{1,5})",
    re.IGNORECASE,
)


def _looks_like_flight_number_lookup(query: str) -> bool:
    """Return True if the query is asking to look up a specific flight by its
    flight number rather than search for flight options."""
    if not query:
        return False
    q = query.strip()
    # Explicit "flight number ..." / "\u822a\u73ed\u53f7 ..." anywhere wins.
    if _FLIGHT_NUMBER_KEYWORD_RE.search(q):
        return True
    # Otherwise look for an airline IATA code immediately followed by digits.
    for m in _FLIGHT_NUMBER_RE.finditer(q):
        airline = m.group(1).upper()
        if airline in _AIRLINE_IATA_CODES:
            return True
    return False


def _empty_parse_result(unsupported_intent: Optional[str] = None,
                        error_code: Optional[str] = None) -> dict:
    """Return a parse-query response shaped exactly like the normal one but
    with all fields empty/defaulted, plus optional intent flags."""
    out = {
        "has_destination": False,
        "destination_city": "",
        "destination_code": "",
        "departure_city": "",
        "departure_code": "",
        "date": "",
        "return_date": None,
        "time_preference": "any",
        "passengers": {"adults": 1, "children": 0, "infants": 0},
        "cabin_class": "economy",
        "sort_by": "score",
        "stops": "any",
        "aircraft_type": "any",
        "alliance": "any",
        "max_price": None,
        "preferred_airlines": [],
    }
    if unsupported_intent:
        out["unsupported_intent"] = unsupported_intent
    if error_code:
        out["error_code"] = error_code
    return out


def _drop_hallucinated_codes(result: dict) -> None:
    """Validate AI-returned IATA codes and drop ones that are obviously wrong.

    Two failure modes are handled:
      1. The code doesn't exist as an IATA airport (e.g. invented gibberish).
      2. The code exists but the city Gemini paired it with is a country or
         region (e.g. departure_city='United States', departure_code='RED' —
         RED is a real tiny WV airport, but the user clearly wanted a US hub).
         When that happens we drop the code so the resolver can pick the
         country's primary hub via _PRIMARY_HUB.
    """
    for code_key, city_key in (
        ("departure_code", "departure_city"),
        ("destination_code", "destination_city"),
    ):
        code = (result.get(code_key) or "").strip().upper()
        if not code:
            continue
        # 1) shape + DB existence check
        if not re.fullmatch(r"[A-Z]{3}", code) or _lookup_iata(code) is None:
            result[code_key] = ""
            city = (result.get(city_key) or "").strip()
            if city.upper() == code:
                result[city_key] = ""
            if code_key == "destination_code":
                result["has_destination"] = False
            continue
        # 2) country/region check — don't trust a specific airport code if
        # the user's city term is actually a country or large region.
        city_norm = (result.get(city_key) or "").strip().lower()
        city_norm = re.sub(r"^the\s+", "", city_norm)
        if city_norm in _COUNTRY_OR_REGION_WORDS:
            result[code_key] = ""  # let resolver pick the hub for this country
            # leave city in place so resolver has something to work with


# Words that name a country / region rather than a city. When Gemini pairs an
# airport code with one of these, the code is almost certainly wrong (it'll be
# some random small airport rather than the country's main hub).
_COUNTRY_OR_REGION_WORDS = frozenset({
    "us", "usa", "u.s.", "u.s.a.", "united states", "america",
    "canada", "mexico",
    "uk", "u.k.", "united kingdom", "britain", "great britain", "england",
    "scotland", "wales", "ireland",
    "france", "germany", "italy", "spain", "portugal", "netherlands",
    "holland", "belgium", "switzerland", "austria", "poland", "greece",
    "sweden", "norway", "denmark", "finland", "czech republic", "hungary",
    "russia", "ukraine", "turkey",
    "china", "japan", "korea", "south korea", "north korea",
    "taiwan", "hong kong sar", "macau sar",
    "thailand", "vietnam", "singapore", "malaysia", "indonesia",
    "philippines", "cambodia", "laos", "myanmar", "burma",
    "india", "pakistan", "bangladesh", "sri lanka", "nepal",
    "australia", "new zealand",
    "uae", "u.a.e.", "united arab emirates", "saudi arabia", "qatar",
    "israel", "egypt", "south africa", "kenya", "nigeria", "morocco",
    "brazil", "argentina", "chile", "peru", "colombia",
    "europe", "asia", "africa", "north america", "south america",
    "middle east", "southeast asia", "east asia", "south asia",
    "中国", "日本", "韩国", "美国", "英国", "法国", "德国", "加拿大",
    "泰国", "澳大利亚", "新加坡", "印度", "印尼", "菲律宾", "越南",
    "台灣", "台湾",
})


# Phrases that describe flight properties (not airports). Gemini sometimes
# yanks the first 3-letter substring out of these and treats it as an IATA
# code (e.g. 'red-eye' → 'RED'). We redact them from the query before sending
# it to Gemini so the temptation never appears.
_REDACT_PHRASE_RE = re.compile(
    r"\b(?:no\s+)?(?:red[\s\-]?eye|red\s+eye|redeye|over[\s\-]?night|overnight)\s*(?:flights?)?\b",
    re.IGNORECASE,
)


def _redact_property_phrases(query: str) -> str:
    """Strip flight-property phrases that have tempted the LLM into inventing
    airport codes from substrings (e.g. 'red-eye' → 'RED')."""
    return _REDACT_PHRASE_RE.sub(" ", query)


def _enrich_with_airport_resolver(query: str, result: dict) -> None:
    """Mutates `result` in place. Tries to fill missing departure / destination
    codes using the airports DB."""
    user_from, user_to = _extract_from_to(query)

    # Departure
    if not result.get("departure_code"):
        candidate = user_from or result.get("departure_city") or ""
        if candidate.strip():
            resolved = resolve_to_iata(candidate)
            if resolved:
                result["departure_code"] = resolved[0]
                result["departure_city"] = resolved[1]

    # Destination
    if not result.get("destination_code"):
        candidate = user_to or result.get("destination_city") or ""
        if candidate.strip():
            resolved = resolve_to_iata(candidate)
            if resolved:
                result["destination_code"] = resolved[0]
                result["destination_city"] = resolved[1]
                result["has_destination"] = True


@router.post(
    "/chat",
    summary="Multi-turn AI flight search conversation",
    description="Send a message in a multi-turn conversation to progressively build flight search parameters"
)
async def chat_conversation(request: ChatConversationRequest):
    """
    Multi-turn conversational AI flight search.
    
    The AI assistant will ask clarifying questions and progressively
    build up the search parameters through conversation.
    
    **Returns:**
    - message: The AI's conversational response
    - search_params: Current state of extracted search parameters
    """
    try:
        history = None
        if request.conversation_history:
            history = [{"role": m.role, "content": m.content} for m in request.conversation_history]
        
        result = await gemini_service.chat_conversation(
            message=request.message,
            conversation_history=history
        )
        return result
    except Exception as e:
        # Return a friendly message instead of 500
        print(f"AI chat_conversation error, returning friendly fallback: {e}")
        return {
            "message": "I'm sorry, the AI assistant is temporarily unavailable. Please use the search form above to find your flight — just enter your departure, destination, and date!",
            "search_params": {
                "departure_city": "", "departure_city_code": "",
                "arrival_city": "", "arrival_city_code": "",
                "date": "", "return_date": None,
                "time_preference": "any",
                "passengers": {"adults": 1, "children": 0, "infants": 0},
                "cabin_class": "economy", "max_stops": None,
                "priority": "balanced", "additional_requirements": [],
                "is_complete": False, "missing_fields": ["ai_unavailable"],
            }
        }

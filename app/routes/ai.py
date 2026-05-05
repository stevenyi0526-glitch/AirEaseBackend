"""
AirEase Backend - AI Search API Routes
AI智能搜索API路由
"""

import re
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List

from app.models import AISearchRequest, AISearchResponse
from app.services.gemini_service import gemini_service
from app.services.airport_resolver import resolve_to_iata

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
        "model": "gemini-3.1-flash-lite-preview",
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
    try:
        result = await gemini_service.parse_natural_language_query(request.query)
    except Exception as e:
        # Instead of returning 500, use local fallback parser
        print(f"AI parse_query falling back to local parser: {e}")
        result = gemini_service._local_parse_natural_language(request.query)

    # Post-process: resolve any unresolved departure / destination by querying
    # the airports DB. Handles small/private airports (e.g. "palo alto airport"
    # → PAO), CJK city names (e.g. "舊金山" → SFO) and misspellings
    # (e.g. "francicso" → SFO) that the LLM either skipped or got wrong.
    _enrich_with_airport_resolver(request.query, result)
    return result


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
    r"(?:从|從|出發於|出发于)\s*([\u4e00-\u9fff]+?)\s*(?:到|至|往|去|飛|飞|→|->)\s*([\u4e00-\u9fff]+)"
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


def _extract_from_to(query: str):
    """Pull user-typed origin/destination phrases out of the raw query.
    Returns (from_str | None, to_str | None)."""
    # Chinese 从X到Y first (more specific)
    m = _FROM_TO_CN_RE.search(query)
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

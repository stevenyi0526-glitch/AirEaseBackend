"""
AirEase Backend - AI Search API Routes
AI智能搜索API路由
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List

from app.models import AISearchRequest, AISearchResponse
from app.services.gemini_service import gemini_service

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
        "model": "gemini-3-flash-preview",
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
        return result
    except Exception as e:
        # Instead of returning 500, use local fallback parser
        print(f"AI parse_query falling back to local parser: {e}")
        return gemini_service._local_parse_natural_language(request.query)


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

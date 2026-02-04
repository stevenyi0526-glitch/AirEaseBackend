"""
AirEase Backend - AI Search API Routes
AI智能搜索API路由
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

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
        "model": "gemini-3-flash-preview-exp",
        "api_key_configured": has_key
    }

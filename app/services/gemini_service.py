"""
AirEase Backend - Gemini AI Service
Gemini LLM 智能搜索服务
"""

import httpx
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from app.config import settings
from app.models import SearchQuery


class GeminiService:
    """Gemini AI 服务 - 自然语言解析"""
    
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
    MODEL = "gemini-3-flash-preview-exp"
    
    def __init__(self):
        self.api_key = settings.gemini_api_key
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def parse_flight_query(self, natural_language: str) -> Dict[str, Any]:
        """
        解析自然语言搜索请求
        
        例如: "下周三北京到上海的公务舱" -> SearchQuery
        """
        today = datetime.now().strftime("%Y-%m-%d")
        
        system_prompt = f"""你是一个航班搜索助手。用户会用自然语言描述他们想要搜索的航班。
请从用户输入中提取以下信息，以JSON格式返回：

{{
    "fromCity": "出发城市名称（如：北京、上海）",
    "toCity": "到达城市名称",
    "date": "日期，格式为YYYY-MM-DD。如果是相对日期如'明天'、'下周三'，请转换为具体日期。今天是{today}",
    "cabin": "舱位：经济舱、公务舱 或 头等舱，默认经济舱",
    "confidence": 0.0到1.0之间的置信度
}}

如果某个字段无法确定，请设为null。
只返回JSON，不要有其他文字。"""
        
        endpoint = f"{self.BASE_URL}/models/{self.MODEL}:generateContent?key={self.api_key}"
        
        request_body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": f"{system_prompt}\n\n用户输入: {natural_language}"}]
                }
            ],
            "generationConfig": {
                "temperature": 0.3,
                "topK": 40,
                "topP": 0.95,
                "maxOutputTokens": 512
            }
        }
        
        try:
            response = await self.client.post(
                endpoint,
                json=request_body,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code != 200:
                print(f"Gemini API error: {response.status_code} - {response.text}")
                return self._fallback_parse(natural_language)
            
            data = response.json()
            text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            
            # Clean markdown code blocks
            text = text.replace("```json", "").replace("```", "").strip()
            
            parsed = json.loads(text)
            return {
                "parsed_query": {
                    "from": parsed.get("fromCity"),
                    "to": parsed.get("toCity"),
                    "date": parsed.get("date"),
                    "cabin": self._map_cabin(parsed.get("cabin", "经济舱"))
                },
                "confidence": parsed.get("confidence", 0.8),
                "original_query": natural_language,
                "suggestions": []
            }
            
        except Exception as e:
            print(f"Gemini parse error: {e}")
            return self._fallback_parse(natural_language)
    
    async def generate_score_explanation(
        self,
        flight_info: str,
        score_info: str,
        persona: str = "business"
    ) -> str:
        """生成航班评分解释"""
        persona_map = {
            "business": "商务出行者",
            "family": "家庭出行者",
            "student": "学生旅客"
        }
        persona_name = persona_map.get(persona, "旅客")
        
        system_prompt = f"""你是AirEase航班体验评分系统的解说员。
请用简洁友好的语言解释这个航班的评分。
根据用户的{persona_name}身份，突出与他们最相关的信息。
限制在100字以内。"""
        
        endpoint = f"{self.BASE_URL}/models/{self.MODEL}:generateContent?key={self.api_key}"
        
        request_body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": f"{system_prompt}\n\n航班信息:\n{flight_info}\n\n评分信息:\n{score_info}"}]
                }
            ],
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 256
            }
        }
        
        try:
            response = await self.client.post(
                endpoint,
                json=request_body,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code != 200:
                return "暂无AI解释"
            
            data = response.json()
            text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            return text.strip()
            
        except Exception as e:
            print(f"Gemini explanation error: {e}")
            return "暂无AI解释"
    
    def _map_cabin(self, cabin: str) -> str:
        """映射舱位到英文"""
        mapping = {
            "经济舱": "economy",
            "公务舱": "business",
            "头等舱": "first",
            "economy": "economy",
            "business": "business",
            "first": "first"
        }
        return mapping.get(cabin, "economy")
    
    async def _generate_text(self, prompt: str, max_tokens: int = 256) -> str:
        """
        Generic text generation helper for any prompt.
        Used by recommendation service and other AI features.
        """
        endpoint = f"{self.BASE_URL}/models/{self.MODEL}:generateContent?key={self.api_key}"
        
        request_body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": max_tokens
            }
        }
        
        try:
            response = await self.client.post(
                endpoint,
                json=request_body,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code != 200:
                print(f"Gemini API error: {response.status_code}")
                return ""
            
            data = response.json()
            text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            return text.strip()
            
        except Exception as e:
            print(f"Gemini generate error: {e}")
            return ""
    
    def _fallback_parse(self, query: str) -> Dict[str, Any]:
        """后备解析 - 关键词匹配"""
        cities = ["北京", "上海", "广州", "深圳", "成都", "杭州", "武汉", "西安", "南京", "重庆"]
        
        from_city = None
        to_city = None
        cabin = "economy"
        date = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
        
        # 尝试匹配城市
        for city in cities:
            if city in query:
                if from_city is None:
                    from_city = city
                elif to_city is None and city != from_city:
                    to_city = city
        
        # 匹配舱位
        if "公务" in query or "商务" in query:
            cabin = "business"
        elif "头等" in query:
            cabin = "first"
        
        # 匹配日期关键词
        if "明天" in query:
            date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        elif "后天" in query:
            date = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
        elif "下周" in query:
            days_until_next_week = 7 - datetime.now().weekday()
            date = (datetime.now() + timedelta(days=days_until_next_week)).strftime("%Y-%m-%d")
        
        return {
            "parsed_query": {
                "from": from_city,
                "to": to_city,
                "date": date,
                "cabin": cabin
            } if from_city and to_city else None,
            "confidence": 0.5 if from_city and to_city else 0.0,
            "original_query": query,
            "suggestions": ["请输入出发城市和目的地城市"] if not (from_city and to_city) else []
        }
    
    async def close(self):
        """关闭HTTP客户端"""
        await self.client.aclose()


# Singleton instance
gemini_service = GeminiService()

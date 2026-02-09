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
    MODEL = "gemini-3-flash-preview"
    
    # Errors that indicate a geo-restriction or API-level block (not our fault)
    GEO_BLOCK_KEYWORDS = [
        "User location is not supported",
        "FAILED_PRECONDITION",
        "not available in your country",
        "not supported for the API use",
    ]
    
    def __init__(self):
        self.api_key = settings.gemini_api_key
        self.client = httpx.AsyncClient(timeout=30.0)
    
    def _is_geo_blocked(self, status_code: int, response_text: str) -> bool:
        """Check if a Gemini error is due to geo-restriction."""
        if status_code == 400 or status_code == 403:
            return any(kw.lower() in response_text.lower() for kw in self.GEO_BLOCK_KEYWORDS)
        return False
    
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
    
    def _local_parse_natural_language(self, query: str) -> Dict[str, Any]:
        """
        Local fallback parser for parse_natural_language_query.
        Used when Gemini is unavailable (geo-blocked, rate-limited, etc.).
        Handles common English and Chinese flight search patterns.
        """
        import re
        
        q = query.strip()
        q_lower = q.lower()
        today = datetime.now()
        
        # --- Airport/City code mapping ---
        CITY_CODES = {
            # English
            "hong kong": "HKG", "hongkong": "HKG", "hkg": "HKG",
            "tokyo": "NRT", "narita": "NRT", "haneda": "HND", "nrt": "NRT", "hnd": "HND",
            "osaka": "KIX", "kix": "KIX",
            "seoul": "ICN", "incheon": "ICN", "icn": "ICN",
            "singapore": "SIN", "sin": "SIN",
            "bangkok": "BKK", "bkk": "BKK",
            "taipei": "TPE", "tpe": "TPE",
            "shanghai": "PVG", "pvg": "PVG",
            "beijing": "PEK", "pek": "PEK",
            "new york": "JFK", "nyc": "JFK", "jfk": "JFK",
            "los angeles": "LAX", "la": "LAX", "lax": "LAX",
            "san francisco": "SFO", "sf": "SFO", "sfo": "SFO",
            "london": "LHR", "lhr": "LHR",
            "paris": "CDG", "cdg": "CDG",
            "dubai": "DXB", "dxb": "DXB",
            "sydney": "SYD", "syd": "SYD",
            "melbourne": "MEL", "mel": "MEL",
            "kuala lumpur": "KUL", "kl": "KUL", "kul": "KUL",
            "mumbai": "BOM", "bom": "BOM",
            "delhi": "DEL", "del": "DEL",
            "frankfurt": "FRA", "fra": "FRA",
            "amsterdam": "AMS", "ams": "AMS",
            "istanbul": "IST", "ist": "IST",
            "toronto": "YYZ", "yyz": "YYZ",
            "vancouver": "YVR", "yvr": "YVR",
            "madrid": "MAD", "mad": "MAD",
            "barcelona": "BCN", "bcn": "BCN",
            "rome": "FCO", "fco": "FCO",
            # Chinese
            "香港": "HKG", "东京": "NRT", "大阪": "KIX", "首尔": "ICN",
            "新加坡": "SIN", "曼谷": "BKK", "台北": "TPE",
            "上海": "PVG", "北京": "PEK", "广州": "CAN", "深圳": "SZX",
            "成都": "CTU", "杭州": "HGH", "武汉": "WUH", "西安": "XIY",
            "南京": "NKG", "重庆": "CKG", "纽约": "JFK", "伦敦": "LHR",
            "巴黎": "CDG", "悉尼": "SYD", "迪拜": "DXB", "吉隆坡": "KUL",
        }
        
        # Reverse: code → city name
        CODE_TO_CITY = {}
        for city, code in CITY_CODES.items():
            if code not in CODE_TO_CITY and len(city) > 2:
                CODE_TO_CITY[code] = city.title()
        
        destination_city = ""
        destination_code = ""
        departure_city = ""
        departure_code = ""
        
        # --- Extract destination: "to <city>" / "fly to <city>" / "去<city>" ---
        # Sort by length descending so "new york" matches before "new"
        sorted_cities = sorted(CITY_CODES.keys(), key=len, reverse=True)
        
        # Pattern: "to <city>"
        for city in sorted_cities:
            pattern_to = rf'\bto\s+{re.escape(city)}\b'
            if re.search(pattern_to, q_lower):
                destination_code = CITY_CODES[city]
                destination_city = CODE_TO_CITY.get(destination_code, city.title())
                break
        
        # Chinese: "去<city>" / "飞<city>" / "到<city>"
        if not destination_code:
            for city in sorted_cities:
                if any(f"{prefix}{city}" in q for prefix in ["去", "飞", "到"]):
                    destination_code = CITY_CODES[city]
                    destination_city = CODE_TO_CITY.get(destination_code, city.title())
                    break
        
        # Fallback: just find any city mentioned (last one = likely destination)
        if not destination_code:
            found = []
            for city in sorted_cities:
                if city in q_lower and len(city) > 2:  # skip 2-letter codes for fuzzy
                    found.append((city, CITY_CODES[city]))
            if found:
                destination_code = found[-1][1]
                destination_city = CODE_TO_CITY.get(destination_code, found[-1][0].title())
                if len(found) > 1:
                    departure_code = found[0][1]
                    departure_city = CODE_TO_CITY.get(departure_code, found[0][0].title())
        
        # --- Extract departure: "from <city>" / "从<city>" ---
        if not departure_code:
            for city in sorted_cities:
                pattern_from = rf'\bfrom\s+{re.escape(city)}\b'
                if re.search(pattern_from, q_lower):
                    departure_code = CITY_CODES[city]
                    departure_city = CODE_TO_CITY.get(departure_code, city.title())
                    break
            if not departure_code:
                for city in sorted_cities:
                    if f"从{city}" in q:
                        departure_code = CITY_CODES[city]
                        departure_city = CODE_TO_CITY.get(departure_code, city.title())
                        break
        
        # --- Date parsing ---
        date_str = ""
        day_names = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                     "friday": 4, "saturday": 5, "sunday": 6}
        
        if "today" in q_lower or "今天" in q:
            date_str = today.strftime("%Y-%m-%d")
        elif "tomorrow" in q_lower or "明天" in q:
            date_str = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        elif "后天" in q:
            date_str = (today + timedelta(days=2)).strftime("%Y-%m-%d")
        elif "this weekend" in q_lower or "这周末" in q:
            days_to_sat = (5 - today.weekday()) % 7
            if days_to_sat == 0:
                days_to_sat = 7
            date_str = (today + timedelta(days=days_to_sat)).strftime("%Y-%m-%d")
        else:
            # "next Friday" pattern
            next_match = re.search(r'next\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)', q_lower)
            if next_match:
                target_day = day_names[next_match.group(1)]
                days_ahead = (target_day - today.weekday()) % 7
                if days_ahead == 0:
                    days_ahead = 7
                date_str = (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
            else:
                # "下周X" pattern
                cn_day_match = re.search(r'下周([一二三四五六日天])', q)
                if cn_day_match:
                    cn_day_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
                    target_day = cn_day_map.get(cn_day_match.group(1), 0)
                    days_ahead = (target_day - today.weekday()) % 7
                    if days_ahead <= 0:
                        days_ahead += 7
                    date_str = (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
        
        # --- Cabin class ---
        cabin_class = "economy"
        if any(w in q_lower for w in ["business", "商务", "公务"]):
            cabin_class = "business"
        elif any(w in q_lower for w in ["first class", "first", "头等"]):
            cabin_class = "first"
        elif any(w in q_lower for w in ["premium", "premium economy", "超级经济"]):
            cabin_class = "premium_economy"
        
        # --- Sort preference ---
        sort_by = "score"
        if any(w in q_lower for w in ["cheap", "cheapest", "budget", "便宜", "最便宜"]):
            sort_by = "price"
        elif any(w in q_lower for w in ["fast", "fastest", "quickest", "最快", "快"]):
            sort_by = "duration"
        elif any(w in q_lower for w in ["comfort", "comfortable", "舒适", "舒服"]):
            sort_by = "comfort"
        
        # --- Stops ---
        stops = "any"
        if any(w in q_lower for w in ["direct", "nonstop", "non-stop", "直飞"]):
            stops = "0"
        elif "1 stop" in q_lower or "one stop" in q_lower:
            stops = "1"
        
        # --- Time preference ---
        time_pref = "any"
        if any(w in q_lower for w in ["morning", "早上", "早班"]):
            time_pref = "morning"
        elif any(w in q_lower for w in ["afternoon", "下午"]):
            time_pref = "afternoon"
        elif any(w in q_lower for w in ["evening", "晚上", "傍晚"]):
            time_pref = "evening"
        elif any(w in q_lower for w in ["night", "red-eye", "red eye", "凌晨"]):
            time_pref = "night"
        
        return {
            "has_destination": bool(destination_code),
            "destination_city": destination_city,
            "destination_code": destination_code,
            "departure_city": departure_city,
            "departure_code": departure_code,
            "date": date_str,
            "time_preference": time_pref,
            "passengers": 1,
            "cabin_class": cabin_class,
            "sort_by": sort_by,
            "stops": stops,
            "aircraft_type": "any",
            "alliance": "any",
            "max_price": None,
            "preferred_airlines": [],
        }

    async def parse_natural_language_query(self, query: str) -> Dict[str, Any]:
        """
        Parse a natural language flight search query (single-shot).
        Used by the AI search bar on the frontend.
        Returns structured search parameters.
        """
        today = datetime.now().strftime("%Y-%m-%d")

        prompt = f"""You are an AI flight search parser. Parse the user's natural language query and extract flight search parameters.

IMPORTANT: Always respond in English. Always use English city names in your response.

## Your Task:
Extract the following from the user's query:
1. **destination** (REQUIRED) - The arrival city/airport (must be provided by user)
2. **departure** (optional) - The departure city/airport (if not provided, will be auto-detected)
3. **date** (optional) - Travel date (if not provided, defaults to today)
4. **time_preference** (optional) - morning(6-12), afternoon(12-18), evening(18-22), night(22-6)
5. **passengers** (optional) - Number of passengers (defaults to 1)
6. **cabin_class** (optional) - economy, premium_economy, business, first (defaults to economy)
7. **sort_preference** (optional) - What to prioritize: comfort, price, duration, or balanced
8. **stops** (optional) - Number of stops: "0" for direct/nonstop, "1" for 1 stop, "2+" for 2+ stops, "any" if not mentioned
9. **aircraft_type** (optional) - "widebody" or "narrowbody" or "any"
10. **alliance** (optional) - "star", "oneworld", "skyteam" or "any"
11. **max_price** (optional) - Maximum price budget in USD if mentioned, null if not
12. **preferred_airlines** (optional) - Specific airline IATA codes if mentioned

## Airport Code Reference:
- Hong Kong: HKG
- Shanghai: PVG (Pudong), SHA (Hongqiao) - use PVG as default
- Beijing: PEK (Capital), PKX (Daxing) - use PEK as default
- Tokyo: NRT (Narita), HND (Haneda) - use NRT as default
- Singapore: SIN
- Seoul: ICN (Incheon)
- Bangkok: BKK
- Taipei: TPE
- New York: JFK
- Los Angeles: LAX
- London: LHR
- Paris: CDG
- Dubai: DXB
- Osaka: KIX
- Sydney: SYD
- Melbourne: MEL

## Date Interpretation (Today is {today}):
- "today" → {today}
- "tomorrow" → calculate actual date
- "next Friday" / "下周五" → calculate actual date
- "this weekend" → coming Saturday

## Time Interpretation:
- "morning flight" / "早班机" / "早上" → morning
- "afternoon" / "下午" → afternoon
- "evening" / "晚上" / "傍晚" → evening
- "red-eye" / "night" / "凌晨" → night

## Sort Preference Interpretation:
- "most comfortable" / "舒服" / "舒适" → comfort
- "cheapest" / "cheap" / "便宜" / "budget" → price
- "fastest" / "quickest" / "快" → duration
- No preference mentioned → score (balanced)

## Stops Interpretation:
- "direct" / "nonstop" / "non-stop" / "直飞" → 0
- "1 stop" / "one stop" / "转一次" → 1
- "2 stops" / "multiple stops" → 2+
- Not mentioned → any

## Aircraft Type Interpretation:
- "widebody" / "large plane" / "777" / "A350" / "787" / "大飞机" → widebody
- "narrowbody" / "small plane" / "A320" / "737" / "小飞机" → narrowbody
- Not mentioned → any

## Alliance Interpretation:
- "Star Alliance" / "星空联盟" → star
- "Oneworld" / "寰宇一家" → oneworld
- "SkyTeam" / "天合联盟" → skyteam
- Not mentioned → any

## Airline Interpretation:
- "Cathay Pacific" / "CX" / "国泰" → CX
- "Singapore Airlines" / "SQ" / "新航" → SQ
- "Emirates" / "EK" / "阿联酋" → EK
- "ANA" / "NH" / "全日空" → NH
- "JAL" / "JL" / "日航" → JL
- "Korean Air" / "KE" / "大韩" → KE
- "China Airlines" / "CI" / "华航" → CI
- "EVA Air" / "BR" / "长荣" → BR
- "Delta" / "DL" → DL
- "United" / "UA" → UA
- "American" / "AA" → AA
- "British Airways" / "BA" → BA
- "Lufthansa" / "LH" → LH
- "Qantas" / "QF" → QF
- "Thai Airways" / "TG" / "泰航" → TG
- Use IATA 2-letter codes in the array

## Price Budget Interpretation:
- "under $500" / "less than 500" / "budget 500" → max_price: 500
- "500以下" / "五百以内" → max_price: 500
- Not mentioned → max_price: null

## Response Format (JSON only, no markdown):
{{
  "has_destination": true/false,
  "destination_city": "City name or empty",
  "destination_code": "IATA code or empty",
  "departure_city": "City name or empty",
  "departure_code": "IATA code or empty",
  "date": "YYYY-MM-DD or empty",
  "time_preference": "morning|afternoon|evening|night|any",
  "passengers": 1,
  "cabin_class": "economy|premium_economy|business|first",
  "sort_by": "score|price|duration|comfort",
  "stops": "any|0|1|2+",
  "aircraft_type": "any|widebody|narrowbody",
  "alliance": "any|star|oneworld|skyteam",
  "max_price": null,
  "preferred_airlines": []
}}

User Query: "{query}"

Respond with JSON only, no explanation:"""

        endpoint = f"{self.BASE_URL}/models/{self.MODEL}:generateContent?key={self.api_key}"

        request_body = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 2048,
            }
        }

        try:
            response = await self.client.post(
                endpoint,
                json=request_body,
                headers={"Content-Type": "application/json"}
            )

            if response.status_code == 429 or response.status_code == 503:
                # Retry once after a short delay
                import asyncio
                await asyncio.sleep(1)
                response = await self.client.post(
                    endpoint,
                    json=request_body,
                    headers={"Content-Type": "application/json"}
                )

            if response.status_code != 200:
                error_text = response.text
                print(f"Gemini API error: {response.status_code} - {error_text}")
                if self._is_geo_blocked(response.status_code, error_text):
                    print("⚠️  Gemini geo-blocked — using local NLP fallback for parse_natural_language_query")
                    return self._local_parse_natural_language(query)
                raise Exception(f"Gemini API error: {response.status_code}")

            data = response.json()
            candidates = data.get("candidates", [])
            if not candidates:
                raise Exception("Empty response from AI")

            # Check for truncation
            finish_reason = candidates[0].get("finishReason", "")
            if finish_reason == "MAX_TOKENS":
                raise Exception("AI response truncated")

            # Extract text from parts (skip thoughtSignature parts)
            parts = candidates[0].get("content", {}).get("parts", [])
            text = "".join(
                p.get("text", "") for p in parts
                if p.get("text") and len(p.get("text", "")) > 0
            )

            if not text:
                raise Exception("Empty text in response")

            # Clean and parse JSON
            text = text.strip()
            # Remove markdown code blocks if present
            import re
            code_block = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
            if code_block:
                text = code_block.group(1).strip()

            json_match = re.search(r'\{[\s\S]*\}', text)
            if not json_match:
                raise Exception("No JSON found in response")

            parsed = json.loads(json_match.group(0))
            return parsed

        except Exception as e:
            print(f"Gemini parse_natural_language_query error: {e}")
            # If any Gemini error, try local fallback instead of crashing
            if "geo" in str(e).lower() or "location" in str(e).lower() or "FAILED_PRECONDITION" in str(e):
                return self._local_parse_natural_language(query)
            raise

    async def chat_conversation(
        self,
        message: str,
        conversation_history: list = None
    ) -> Dict[str, Any]:
        """
        Multi-turn conversational AI flight search.
        Used by the AI chat dialog on the frontend.
        Returns a message and structured search parameters.
        """
        today = datetime.now().strftime("%Y-%m-%d")

        system_prompt = f"""You are AirEase AI, an intelligent flight search assistant. Your job is to help users find the perfect flight by understanding their natural language requests and extracting structured search parameters.

## YOUR CAPABILITIES:
1. Parse natural language flight search queries
2. Ask clarifying questions when information is missing
3. Understand time preferences (morning = 6am-12pm, afternoon = 12pm-6pm, evening = 6pm-10pm, night = 10pm-6am)
4. Understand priority preferences (cheapest, fastest, most comfortable, best value)
5. Handle complex requirements like layover preferences, airline preferences, etc.

## REQUIRED INFORMATION FOR A COMPLETE SEARCH:
1. **Departure City** - Where the user is flying from (REQUIRED)
2. **Arrival City** - Where the user is flying to (REQUIRED)
3. **Date** - The departure date (REQUIRED)
4. **Passengers** - Number of adults, children, infants (default: 1 adult if not specified)
5. **Time Preference** - morning/afternoon/evening/night/any (default: any)
6. **Cabin Class** - economy/premium_economy/business/first (default: economy)
7. **Stops** - direct only, 1 stop max, 2 stops max, or any (default: any)
8. **Priority** - what matters most: cheapest/fastest/most_comfortable/best_value/balanced

## AIRPORT CODE REFERENCE:
- Hong Kong: HKG
- Shanghai: PVG (Pudong), SHA (Hongqiao)
- Beijing: PEK (Capital), PKX (Daxing)
- Tokyo: NRT (Narita), HND (Haneda)
- Singapore: SIN
- Seoul: ICN (Incheon)
- Bangkok: BKK
- Sydney: SYD
- Melbourne: MEL
- London: LHR (Heathrow), LGW (Gatwick)
- Paris: CDG
- New York: JFK, EWR, LGA
- Los Angeles: LAX
- San Francisco: SFO
- Dubai: DXB
- Taipei: TPE
- Kuala Lumpur: KUL
- Mumbai: BOM
- Delhi: DEL
- Frankfurt: FRA
- Amsterdam: AMS
- Madrid: MAD
- Barcelona: BCN
- Rome: FCO
- Zurich: ZRH
- Vienna: VIE
- Istanbul: IST
- Toronto: YYZ
- Vancouver: YVR

## DATE HANDLING:
- "next Friday" - calculate the actual date
- "tomorrow" - calculate the actual date
- "next week" - ask for specific day
- "January 15" - use the year appropriately
- Today's date is: {today}

## RESPONSE FORMAT:
You MUST respond with a valid JSON object in this exact format:
{{
  "message": "Your conversational response to the user",
  "search_params": {{
    "departure_city": "City name or empty string",
    "departure_city_code": "3-letter code or empty string",
    "arrival_city": "City name or empty string",
    "arrival_city_code": "3-letter code or empty string",
    "date": "YYYY-MM-DD format or empty string",
    "return_date": "YYYY-MM-DD format or null for one-way",
    "time_preference": "morning|afternoon|evening|night|any",
    "passengers": {{
      "adults": 1,
      "children": 0,
      "infants": 0
    }},
    "cabin_class": "economy|premium_economy|business|first",
    "max_stops": null or 0 or 1 or 2,
    "priority": "cheapest|fastest|most_comfortable|best_value|balanced",
    "additional_requirements": ["list of any special requirements"],
    "is_complete": true or false,
    "missing_fields": ["list of missing required fields"]
  }}
}}

## CONVERSATION GUIDELINES:
1. Be friendly and helpful
2. If information is missing, ask for it naturally in your message
3. Confirm the search parameters before marking is_complete as true
4. When all required info is gathered, summarize and ask for confirmation
5. Handle ambiguous requests by asking clarifying questions
6. Always provide the search_params object, even if incomplete"""

        # Build conversation context
        conversation_context = ""
        if conversation_history:
            parts = []
            for msg in conversation_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                parts.append(f"{'User' if role == 'user' else 'Assistant'}: {content}")
            conversation_context = "\n\n".join(parts)

        full_prompt = system_prompt
        if conversation_context:
            full_prompt += f"\n\n## PREVIOUS CONVERSATION:\n{conversation_context}\n"
        full_prompt += f"\n## CURRENT USER MESSAGE:\n{message}\n\nRemember to respond with a valid JSON object containing \"message\" and \"search_params\" fields."

        endpoint = f"{self.BASE_URL}/models/{self.MODEL}:generateContent?key={self.api_key}"

        request_body = {
            "contents": [{
                "parts": [{"text": full_prompt}]
            }],
            "generationConfig": {
                "temperature": 0.7,
                "topK": 40,
                "topP": 0.95,
                "maxOutputTokens": 2048
            }
        }

        try:
            response = await self.client.post(
                endpoint,
                json=request_body,
                headers={"Content-Type": "application/json"}
            )

            if response.status_code != 200:
                error_text = response.text
                print(f"Gemini API error: {response.status_code} - {error_text}")
                if self._is_geo_blocked(response.status_code, error_text):
                    print("⚠️  Gemini geo-blocked — returning friendly error for chat")
                    return {
                        "message": "I'm sorry, the AI service is temporarily unavailable. Please try using the manual search form to find your flight — it works just as well!",
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
                raise Exception(f"Gemini API error: {response.status_code}")

            data = response.json()
            ai_text = (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
            )

            if not ai_text:
                raise Exception("No response from Gemini")

            # Extract JSON from response
            import re
            json_match = re.search(r'\{[\s\S]*\}', ai_text)
            if not json_match:
                raise Exception("No JSON found in response")

            parsed = json.loads(json_match.group(0))

            # Ensure required structure
            result = {
                "message": parsed.get("message", "I apologize, but I had trouble understanding. Could you please rephrase your request?"),
                "search_params": {
                    "departure_city": parsed.get("search_params", {}).get("departure_city", ""),
                    "departure_city_code": parsed.get("search_params", {}).get("departure_city_code", ""),
                    "arrival_city": parsed.get("search_params", {}).get("arrival_city", ""),
                    "arrival_city_code": parsed.get("search_params", {}).get("arrival_city_code", ""),
                    "date": parsed.get("search_params", {}).get("date", ""),
                    "return_date": parsed.get("search_params", {}).get("return_date"),
                    "time_preference": parsed.get("search_params", {}).get("time_preference", "any"),
                    "passengers": parsed.get("search_params", {}).get("passengers", {"adults": 1, "children": 0, "infants": 0}),
                    "cabin_class": parsed.get("search_params", {}).get("cabin_class", "economy"),
                    "max_stops": parsed.get("search_params", {}).get("max_stops"),
                    "priority": parsed.get("search_params", {}).get("priority", "balanced"),
                    "additional_requirements": parsed.get("search_params", {}).get("additional_requirements", []),
                    "is_complete": parsed.get("search_params", {}).get("is_complete", False),
                    "missing_fields": parsed.get("search_params", {}).get("missing_fields", []),
                }
            }

            return result

        except Exception as e:
            print(f"Gemini chat_conversation error: {e}")
            raise

    async def close(self):
        """关闭HTTP客户端"""
        await self.client.aclose()


# Singleton instance
gemini_service = GeminiService()

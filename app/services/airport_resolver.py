"""
Airport resolver — convert a free-form city/airport string into an IATA code
using the same `airports` table the classic search uses.

Handles:
  • exact IATA codes (e.g. "PAO", "HKG")
  • full or partial English airport / city names (e.g. "palo alto airport")
  • Simplified & Traditional CJK city names (e.g. "香港", "舊金山")
  • common misspellings via fuzzy matching (e.g. "spanish" -> Spain isn't an
    airport; "francicso" -> "San Francisco" SFO)

Single helper: resolve_to_iata(query) -> (iata_code, display_name) | None.
Used by the /v1/ai/parse-query route to fix departure/destination codes that
Gemini failed to identify.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Optional, Tuple

import psycopg2

from app.config import settings


# CJK city/airport name → English. Includes both Simplified and Traditional
# variants of every major hub. Keep alphabetised by region for maintenance.
_CJK_TO_EN = {
    # Greater China
    "香港": "Hong Kong", "香港國際機場": "Hong Kong", "香港国际机场": "Hong Kong",
    "上海": "Shanghai", "浦東": "Pudong", "浦东": "Pudong",
    "虹橋": "Hongqiao", "虹桥": "Hongqiao",
    "北京": "Beijing",
    "廣州": "Guangzhou", "广州": "Guangzhou",
    "深圳": "Shenzhen",
    "成都": "Chengdu", "杭州": "Hangzhou",
    "武漢": "Wuhan", "武汉": "Wuhan",
    "西安": "Xi'an", "南京": "Nanjing",
    "重慶": "Chongqing", "重庆": "Chongqing",
    "厦门": "Xiamen", "廈門": "Xiamen",
    "青岛": "Qingdao", "青島": "Qingdao",
    "天津": "Tianjin",
    "沈阳": "Shenyang", "瀋陽": "Shenyang", "沈陽": "Shenyang",
    "大连": "Dalian", "大連": "Dalian",
    "郑州": "Zhengzhou", "鄭州": "Zhengzhou",
    "长沙": "Changsha", "長沙": "Changsha",
    "昆明": "Kunming",
    "贵阳": "Guiyang", "貴陽": "Guiyang",
    "南宁": "Nanning", "南寧": "Nanning",
    "海口": "Haikou",
    "三亚": "Sanya", "三亞": "Sanya",
    "烟台": "Yantai", "煙台": "Yantai",
    "济南": "Jinan", "濟南": "Jinan",
    "福州": "Fuzhou", "合肥": "Hefei", "南昌": "Nanchang",
    "哈尔滨": "Harbin", "哈爾濱": "Harbin",
    "长春": "Changchun", "長春": "Changchun",
    "兰州": "Lanzhou", "蘭州": "Lanzhou",
    "乌鲁木齐": "Urumqi", "烏魯木齊": "Urumqi",
    "拉萨": "Lhasa", "拉薩": "Lhasa",
    "呼和浩特": "Hohhot",
    "台北": "Taipei", "桃園": "Taoyuan", "桃园": "Taoyuan",
    "高雄": "Kaohsiung", "台中": "Taichung",
    "台南": "Tainan", "花蓮": "Hualien", "花莲": "Hualien",
    "澳门": "Macau", "澳門": "Macau",

    # Japan
    "東京": "Tokyo", "东京": "Tokyo",
    "成田": "Narita", "羽田": "Haneda",
    "大阪": "Osaka", "關西": "Kansai", "关西": "Kansai",
    "京都": "Kyoto",
    "名古屋": "Nagoya", "中部": "Chubu",
    "札幌": "Sapporo", "新千歲": "New Chitose", "新千岁": "New Chitose",
    "福岡": "Fukuoka", "福冈": "Fukuoka",
    "沖繩": "Okinawa", "冲绳": "Okinawa", "那霸": "Naha", "那覇": "Naha",
    "廣島": "Hiroshima", "广岛": "Hiroshima",
    "仙台": "Sendai", "神戶": "Kobe", "神户": "Kobe",

    # Korea
    "首爾": "Seoul", "首尔": "Seoul", "仁川": "Incheon", "金浦": "Gimpo",
    "釜山": "Busan", "济州": "Jeju", "濟州": "Jeju",

    # Southeast Asia
    "新加坡": "Singapore",
    "曼谷": "Bangkok", "蘇瓦那普": "Suvarnabhumi", "苏瓦那普": "Suvarnabhumi",
    "普吉": "Phuket", "普吉島": "Phuket", "普吉岛": "Phuket",
    "清邁": "Chiang Mai", "清迈": "Chiang Mai",
    "吉隆坡": "Kuala Lumpur",
    "雅加達": "Jakarta", "雅加达": "Jakarta",
    "峇里": "Bali", "巴厘": "Bali", "巴厘島": "Bali", "巴厘岛": "Bali",
    "登巴薩": "Denpasar", "登巴萨": "Denpasar",
    "馬尼拉": "Manila", "马尼拉": "Manila",
    "胡志明市": "Ho Chi Minh", "河內": "Hanoi", "河内": "Hanoi",
    "金邊": "Phnom Penh", "金边": "Phnom Penh",
    "仰光": "Yangon", "永珍": "Vientiane", "万象": "Vientiane",

    # South Asia / Middle East
    "孟買": "Mumbai", "孟买": "Mumbai",
    "德里": "Delhi", "新德里": "New Delhi",
    "班加羅爾": "Bangalore", "班加罗尔": "Bangalore",
    "加爾各答": "Kolkata", "加尔各答": "Kolkata",
    "金奈": "Chennai", "海德拉巴": "Hyderabad",
    "迪拜": "Dubai", "杜拜": "Dubai",
    "阿布扎比": "Abu Dhabi", "阿布達比": "Abu Dhabi",
    "多哈": "Doha", "科威特": "Kuwait",
    "利雅得": "Riyadh", "吉達": "Jeddah", "吉达": "Jeddah",
    "德黑蘭": "Tehran", "德黑兰": "Tehran",
    "特拉維夫": "Tel Aviv", "特拉维夫": "Tel Aviv",
    "伊斯坦堡": "Istanbul", "伊斯坦布尔": "Istanbul",

    # Europe
    "倫敦": "London", "伦敦": "London",
    "希思羅": "Heathrow", "希思罗": "Heathrow",
    "巴黎": "Paris", "戴高樂": "Charles de Gaulle", "戴高乐": "Charles de Gaulle",
    "法蘭克福": "Frankfurt", "法兰克福": "Frankfurt",
    "慕尼黑": "Munich",
    "柏林": "Berlin",
    "漢堡": "Hamburg", "汉堡": "Hamburg",
    "杜塞爾多夫": "Dusseldorf", "杜塞尔多夫": "Dusseldorf",
    "阿姆斯特丹": "Amsterdam",
    "布魯塞爾": "Brussels", "布鲁塞尔": "Brussels",
    "蘇黎世": "Zurich", "苏黎世": "Zurich",
    "日內瓦": "Geneva", "日内瓦": "Geneva",
    "維也納": "Vienna", "维也纳": "Vienna",
    "馬德里": "Madrid", "马德里": "Madrid",
    "巴塞隆納": "Barcelona", "巴塞罗那": "Barcelona",
    "羅馬": "Rome", "罗马": "Rome",
    "米蘭": "Milan", "米兰": "Milan",
    "威尼斯": "Venice", "佛羅倫斯": "Florence", "佛罗伦萨": "Florence",
    "那不勒斯": "Naples",
    "里斯本": "Lisbon",
    "雅典": "Athens",
    "都柏林": "Dublin",
    "愛丁堡": "Edinburgh", "爱丁堡": "Edinburgh",
    "格拉斯哥": "Glasgow", "曼徹斯特": "Manchester", "曼彻斯特": "Manchester",
    "哥本哈根": "Copenhagen",
    "斯德哥爾摩": "Stockholm", "斯德哥尔摩": "Stockholm",
    "奧斯陸": "Oslo", "奥斯陆": "Oslo",
    "赫爾辛基": "Helsinki", "赫尔辛基": "Helsinki",
    "華沙": "Warsaw", "华沙": "Warsaw",
    "布拉格": "Prague",
    "布達佩斯": "Budapest", "布达佩斯": "Budapest",
    "莫斯科": "Moscow",

    # North America
    "紐約": "New York", "纽约": "New York", "曼哈頓": "New York", "曼哈顿": "New York",
    "洛杉磯": "Los Angeles", "洛杉矶": "Los Angeles",
    "舊金山": "San Francisco", "旧金山": "San Francisco", "三藩市": "San Francisco",
    "帕羅奧圖": "Palo Alto", "帕罗奥图": "Palo Alto",
    "西雅圖": "Seattle", "西雅图": "Seattle",
    "芝加哥": "Chicago",
    "波士頓": "Boston", "波士顿": "Boston",
    "邁阿密": "Miami", "迈阿密": "Miami",
    "華盛頓": "Washington", "华盛顿": "Washington",
    "休士頓": "Houston", "休斯顿": "Houston", "休斯敦": "Houston",
    "達拉斯": "Dallas", "达拉斯": "Dallas",
    "亞特蘭大": "Atlanta", "亚特兰大": "Atlanta",
    "拉斯維加斯": "Las Vegas", "拉斯维加斯": "Las Vegas",
    "丹佛": "Denver",
    "費城": "Philadelphia", "费城": "Philadelphia",
    "底特律": "Detroit", "明尼阿波利斯": "Minneapolis",
    "鳳凰城": "Phoenix", "凤凰城": "Phoenix",
    "聖地牙哥": "San Diego", "圣地亚哥": "San Diego",
    "波特蘭": "Portland", "波特兰": "Portland",
    "奧蘭多": "Orlando", "奥兰多": "Orlando",
    "夏威夷": "Honolulu", "檀香山": "Honolulu",
    "多倫多": "Toronto", "多伦多": "Toronto",
    "溫哥華": "Vancouver", "温哥华": "Vancouver",
    "蒙特利爾": "Montreal", "蒙特利尔": "Montreal", "蒙特婁": "Montreal", "蒙特娄": "Montreal",
    "卡爾加里": "Calgary", "卡尔加里": "Calgary",
    "渥太華": "Ottawa", "渥太华": "Ottawa",
    "墨西哥城": "Mexico City", "坎昆": "Cancun",

    # Oceania
    "悉尼": "Sydney", "雪梨": "Sydney",
    "墨爾本": "Melbourne", "墨尔本": "Melbourne",
    "布里斯本": "Brisbane", "布里斯班": "Brisbane",
    "珀斯": "Perth", "柏斯": "Perth",
    "阿德萊德": "Adelaide", "阿德莱德": "Adelaide",
    "奧克蘭": "Auckland", "奥克兰": "Auckland",
    "惠靈頓": "Wellington", "惠灵顿": "Wellington",

    # South America / Africa
    "聖保羅": "São Paulo", "圣保罗": "São Paulo",
    "里約熱內盧": "Rio de Janeiro", "里约热内卢": "Rio de Janeiro",
    "布宜諾斯艾利斯": "Buenos Aires", "布宜诺斯艾利斯": "Buenos Aires",
    "聖地亞哥智利": "Santiago", "利馬": "Lima", "利马": "Lima",
    "波哥大": "Bogota",
    "開羅": "Cairo", "开罗": "Cairo",
    "約翰內斯堡": "Johannesburg", "约翰内斯堡": "Johannesburg",
    "開普敦": "Cape Town", "开普敦": "Cape Town",
    "奈洛比": "Nairobi", "内罗毕": "Nairobi",
    "拉哥斯": "Lagos", "拉各斯": "Lagos",
    "卡薩布蘭卡": "Casablanca", "卡萨布兰卡": "Casablanca",
}


# Major-hub override: map normalized lowercase city / common name → primary
# IATA. Used to disambiguate when DB has many airports matching the same
# substring (e.g. "London" → LHR, not London Ontario YXU).
_PRIMARY_HUB = {
    "new york": "JFK", "manhattan": "JFK",
    "london": "LHR", "paris": "CDG", "moscow": "SVO",
    "tokyo": "HND", "osaka": "KIX", "seoul": "ICN",
    "shanghai": "PVG", "beijing": "PEK",
    "los angeles": "LAX", "san francisco": "SFO", "chicago": "ORD",
    "washington": "IAD", "washington dc": "IAD",
    "houston": "IAH", "dallas": "DFW",
    "miami": "MIA", "boston": "BOS", "seattle": "SEA",
    "atlanta": "ATL", "denver": "DEN", "phoenix": "PHX",
    "las vegas": "LAS", "orlando": "MCO", "philadelphia": "PHL",
    "san diego": "SAN", "portland": "PDX", "minneapolis": "MSP",
    "detroit": "DTW", "newark": "EWR",
    "toronto": "YYZ", "montreal": "YUL", "vancouver": "YVR",
    "calgary": "YYC", "ottawa": "YOW",
    "mexico city": "MEX", "cancun": "CUN",
    "berlin": "BER", "munich": "MUC", "frankfurt": "FRA", "hamburg": "HAM",
    "amsterdam": "AMS", "brussels": "BRU", "zurich": "ZRH", "geneva": "GVA",
    "vienna": "VIE", "rome": "FCO", "milan": "MXP", "naples": "NAP",
    "madrid": "MAD", "barcelona": "BCN", "lisbon": "LIS",
    "athens": "ATH", "istanbul": "IST",
    "dublin": "DUB", "edinburgh": "EDI", "manchester": "MAN", "glasgow": "GLA",
    "copenhagen": "CPH", "stockholm": "ARN", "oslo": "OSL", "helsinki": "HEL",
    "warsaw": "WAW", "prague": "PRG", "budapest": "BUD",
    "dubai": "DXB", "abu dhabi": "AUH", "doha": "DOH",
    "kuwait": "KWI", "riyadh": "RUH", "jeddah": "JED",
    "tehran": "IKA", "tel aviv": "TLV", "cairo": "CAI",
    "johannesburg": "JNB", "cape town": "CPT", "nairobi": "NBO",
    "lagos": "LOS", "casablanca": "CMN",
    "bangkok": "BKK", "phuket": "HKT", "chiang mai": "CNX",
    "singapore": "SIN", "kuala lumpur": "KUL",
    "jakarta": "CGK", "bali": "DPS", "denpasar": "DPS",
    "manila": "MNL", "ho chi minh": "SGN", "hanoi": "HAN",
    "phnom penh": "PNH", "yangon": "RGN",
    "mumbai": "BOM", "delhi": "DEL", "new delhi": "DEL",
    "bangalore": "BLR", "bengaluru": "BLR",
    "kolkata": "CCU", "chennai": "MAA", "hyderabad": "HYD",
    "sydney": "SYD", "melbourne": "MEL", "brisbane": "BNE",
    "perth": "PER", "adelaide": "ADL",
    "auckland": "AKL", "wellington": "WLG",
    "são paulo": "GRU", "sao paulo": "GRU",
    "rio de janeiro": "GIG", "buenos aires": "EZE",
    "santiago": "SCL", "lima": "LIM", "bogota": "BOG",
    "guangzhou": "CAN", "shenzhen": "SZX",
    "chengdu": "CTU", "hangzhou": "HGH", "xi'an": "XIY", "xian": "XIY",
    "wuhan": "WUH", "nanjing": "NKG", "chongqing": "CKG",
    "xiamen": "XMN", "qingdao": "TAO", "tianjin": "TSN",
    "shenyang": "SHE", "dalian": "DLC", "zhengzhou": "CGO",
    "changsha": "CSX", "kunming": "KMG", "guiyang": "KWE",
    "nanning": "NNG", "haikou": "HAK", "sanya": "SYX",
    "yantai": "YNT", "jinan": "TNA", "fuzhou": "FOC",
    "hefei": "HFE", "nanchang": "KHN", "harbin": "HRB",
    "changchun": "CGQ", "lanzhou": "LHW", "urumqi": "URC",
    "lhasa": "LXA", "hohhot": "HET",
    "taipei": "TPE", "taoyuan": "TPE", "kaohsiung": "KHH", "taichung": "RMQ",
    "macau": "MFM", "hong kong": "HKG",
    "kyoto": "KIX", "nagoya": "NGO", "sapporo": "CTS",
    "fukuoka": "FUK", "okinawa": "OKA", "naha": "OKA",
    "hiroshima": "HIJ",
    "busan": "PUS", "jeju": "CJU", "gimpo": "GMP", "incheon": "ICN",
    "maui": "OGG", "kahului": "OGG", "kona": "KOA",
}


def _fold_diacritics(s: str) -> str:
    """Strip combining marks so 'Kraków' → 'Krakow'."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", s)
        if not unicodedata.combining(c)
    )


def _normalize(s: str) -> str:
    """Lowercase + fold diacritics + strip noise words for fuzzy comparison."""
    s = _fold_diacritics(s).lower()
    s = re.sub(r"\b(international|intl|airport|airfield|field|airpark|regional)\b", "", s)
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _lookup_iata(code: str) -> Optional[Tuple[str, str]]:
    """Direct IATA lookup. Returns (code, display) or None."""
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT iata_code, COALESCE(municipality, name) FROM airports "
            "WHERE UPPER(iata_code) = %s LIMIT 1",
            (code.upper(),),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return (row[0], row[1] or row[0])
    except Exception:
        pass
    return None


def _translate_cjk(q: str) -> str:
    """Translate CJK city/airport name to English; return original if no CJK."""
    if not any("\u4e00" <= ch <= "\u9fff" for ch in q):
        return q
    if q in _CJK_TO_EN:
        return _CJK_TO_EN[q]
    for cjk in sorted(_CJK_TO_EN.keys(), key=len, reverse=True):
        if cjk in q:
            return _CJK_TO_EN[cjk]
    return q


def _get_conn():
    return psycopg2.connect(
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
        host=settings.postgres_host,
        port=str(settings.postgres_port),
    )


def resolve_to_iata(query: str) -> Optional[Tuple[str, str]]:
    """
    Resolve a free-form location string to (iata_code, display_name).

    Resolution order (fast → expensive):
      1. Empty / whitespace → None
      2. Looks like a 3-letter IATA code → look it up directly
      3. CJK input → translate to English, then continue
      4. Exact substring search on iata_code, name, municipality
         (limited to large/medium airports). The classic /search endpoint
         uses the same query.
      5. Fuzzy fallback (difflib) over candidate airports/cities for
         misspellings like "francicso" → "San Francisco".

    Returns None if no reasonable match is found.
    """
    if not query or not query.strip():
        return None

    q = query.strip()

    # 2. Direct IATA code
    if re.fullmatch(r"[A-Za-z]{3}", q):
        hit = _lookup_iata(q)
        if hit:
            return hit

    # 3. CJK → English
    q_en = _translate_cjk(q)

    # 3b. Major-hub override (after CJK translation). Strip noise words like
    # "airport", normalize, and check against the curated primary-hub map.
    # This guarantees "London"/"伦敦" → LHR (not London Ontario), "Paris" →
    # CDG (not Le Bourget), "Seattle" → SEA (not Boeing Field), etc.
    hub_key = re.sub(
        r"\b(international|intl|airport|airfield|field|airpark|regional)\b",
        "",
        _fold_diacritics(q_en).lower(),
    ).strip()
    hub_key = re.sub(r"\s+", " ", hub_key)
    if hub_key in _PRIMARY_HUB:
        hit = _lookup_iata(_PRIMARY_HUB[hub_key])
        if hit:
            return hit

    # 4 + 5. DB search
    try:
        conn = _get_conn()
        cur = conn.cursor()

        like = f"%{q_en.upper()}%"
        # Also try diacritic-folded form so "Krakow" matches "Kraków".
        like_folded = f"%{_fold_diacritics(q_en).upper()}%"
        cur.execute(
            """
            SELECT iata_code, name, municipality, type
            FROM airports
            WHERE iata_code IS NOT NULL AND iata_code != ''
              AND (
                UPPER(iata_code) = %s
                OR UPPER(municipality) LIKE %s
                OR UPPER(name) LIKE %s
                OR UPPER(municipality) LIKE %s
                OR UPPER(name) LIKE %s
              )
            ORDER BY
              CASE
                WHEN UPPER(iata_code) = %s THEN 0
                ELSE 1
              END,
              CASE
                WHEN type = 'large_airport' THEN 0
                WHEN type = 'medium_airport' THEN 1
                ELSE 2
              END,
              CASE WHEN scheduled_service = 'yes' THEN 0 ELSE 1 END,
              CASE
                WHEN UPPER(municipality) = %s THEN 0
                ELSE 1
              END
            LIMIT 1
            """,
            (q_en.upper(), like, like, like_folded, like_folded, q_en.upper(), q_en.upper()),
        )
        row = cur.fetchone()
        if row:
            cur.close()
            conn.close()
            return (row[0], row[2] or row[1])

        # 5. Fuzzy match. Pull a candidate set of public airports and pick the
        # best-scoring match by normalized SequenceMatcher. Restricted to
        # large/medium airports to avoid mapping a misspelling onto an
        # obscure airfield.
        norm_query = _normalize(q_en)
        if len(norm_query) < 4:
            cur.close()
            conn.close()
            return None

        cur.execute(
            """
            SELECT iata_code, name, municipality, type
            FROM airports
            WHERE iata_code IS NOT NULL AND iata_code != ''
              AND type IN ('large_airport', 'medium_airport')
              AND scheduled_service = 'yes'
              AND (municipality IS NOT NULL OR name IS NOT NULL)
            """
        )
        candidates = cur.fetchall()
        cur.close()
        conn.close()

        type_bonus = {"large_airport": 0.04, "medium_airport": 0.0}
        best: Optional[Tuple[float, str, str]] = None
        first_char = norm_query[0]
        for iata, name, muni, atype in candidates:
            for label in (muni, name):
                if not label:
                    continue
                norm_label = _normalize(label)
                if not norm_label or norm_label[0] != first_char:
                    # Require same first letter to avoid wild jumps
                    continue
                ratio = SequenceMatcher(None, norm_query, norm_label).ratio()
                if norm_query in norm_label or norm_label in norm_query:
                    ratio = max(ratio, 0.9)
                ratio += type_bonus.get(atype, 0.0)
                if best is None or ratio > best[0]:
                    best = (ratio, iata, muni or name)

        if best and best[0] >= 0.85:
            return (best[1], best[2])
    except Exception:
        return None

    return None

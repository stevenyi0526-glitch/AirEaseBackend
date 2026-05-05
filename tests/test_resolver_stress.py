"""
Stress test for app.services.airport_resolver.resolve_to_iata().

Covers:
  - 100 common city / airport names in English  (expected: high accuracy)
  - 100 common city / airport names in Chinese  (expected: high accuracy)
  - 30  uncommon / regional / small cities      (expected: best-effort)

Each test entry is (query, expected_iata_set). The test passes if the
resolver returns any IATA code in the expected set, OR returns one of the
city's other valid airport codes.

Run from backend/:  python tests/test_resolver_stress.py
"""
from __future__ import annotations

import sys
import time
from typing import Iterable, List, Tuple

# Make `app` importable when run as a script from backend/
sys.path.insert(0, ".")

from app.services.airport_resolver import resolve_to_iata


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------
# Each city maps to ANY valid IATA code (city codes or airport codes both OK).
# A query is a "pass" if the resolver returns any code in the set.

COMMON_EN: List[Tuple[str, set]] = [
    ("Hong Kong",            {"HKG"}),
    ("Tokyo",                {"NRT", "HND", "TYO"}),
    ("Narita",               {"NRT"}),
    ("Haneda",               {"HND"}),
    ("Osaka",                {"KIX", "ITM", "OSA"}),
    ("Kansai",               {"KIX"}),
    ("Seoul",                {"ICN", "GMP", "SEL"}),
    ("Incheon",              {"ICN"}),
    ("Singapore",            {"SIN"}),
    ("Bangkok",              {"BKK", "DMK"}),
    ("Suvarnabhumi",         {"BKK"}),
    ("Taipei",               {"TPE", "TSA"}),
    ("Taoyuan",              {"TPE"}),
    ("Shanghai",             {"PVG", "SHA"}),
    ("Pudong",               {"PVG"}),
    ("Hongqiao",             {"SHA"}),
    ("Beijing",              {"PEK", "PKX", "BJS"}),
    ("Guangzhou",            {"CAN"}),
    ("Shenzhen",             {"SZX"}),
    ("Chengdu",              {"CTU", "TFU"}),
    ("Hangzhou",             {"HGH"}),
    ("Xiamen",               {"XMN"}),
    ("Wuhan",                {"WUH"}),
    ("Xi'an",                {"XIY"}),
    ("Xian",                 {"XIY"}),
    ("Nanjing",              {"NKG"}),
    ("Chongqing",            {"CKG"}),
    ("Qingdao",              {"TAO"}),
    ("New York",             {"JFK", "LGA", "EWR", "NYC"}),
    ("JFK",                  {"JFK"}),
    ("LaGuardia",            {"LGA"}),
    ("Newark",               {"EWR"}),
    ("Los Angeles",          {"LAX"}),
    ("San Francisco",        {"SFO"}),
    ("Oakland",              {"OAK"}),
    ("San Jose",             {"SJC"}),
    ("Palo Alto",            {"PAO"}),
    ("Seattle",              {"SEA"}),
    ("Boston",               {"BOS"}),
    ("Chicago",              {"ORD", "MDW", "CHI"}),
    ("Miami",                {"MIA"}),
    ("Houston",              {"IAH", "HOU"}),
    ("Dallas",               {"DFW", "DAL"}),
    ("Atlanta",              {"ATL"}),
    ("Washington",           {"IAD", "DCA", "WAS"}),
    ("Denver",               {"DEN"}),
    ("Las Vegas",            {"LAS"}),
    ("Phoenix",              {"PHX"}),
    ("Philadelphia",         {"PHL"}),
    ("Detroit",              {"DTW"}),
    ("Minneapolis",          {"MSP"}),
    ("Orlando",              {"MCO"}),
    ("Toronto",              {"YYZ", "YTZ"}),
    ("Vancouver",            {"YVR"}),
    ("Montreal",             {"YUL"}),
    ("Calgary",              {"YYC"}),
    ("Mexico City",          {"MEX"}),
    ("São Paulo",            {"GRU", "CGH", "SAO"}),
    ("Sao Paulo",            {"GRU", "CGH", "SAO"}),
    ("Rio de Janeiro",       {"GIG", "SDU", "RIO"}),
    ("Buenos Aires",         {"EZE", "AEP", "BUE"}),
    ("Lima",                 {"LIM"}),
    ("Bogota",               {"BOG"}),
    ("London",               {"LHR", "LGW", "STN", "LCY", "LON"}),
    ("Heathrow",             {"LHR"}),
    ("Gatwick",              {"LGW"}),
    ("Paris",                {"CDG", "ORY", "PAR"}),
    ("Charles de Gaulle",    {"CDG"}),
    ("Frankfurt",            {"FRA"}),
    ("Munich",               {"MUC"}),
    ("Berlin",               {"BER"}),
    ("Amsterdam",            {"AMS"}),
    ("Brussels",             {"BRU"}),
    ("Zurich",               {"ZRH"}),
    ("Geneva",               {"GVA"}),
    ("Vienna",               {"VIE"}),
    ("Madrid",               {"MAD"}),
    ("Barcelona",            {"BCN"}),
    ("Lisbon",               {"LIS"}),
    ("Rome",                 {"FCO", "CIA", "ROM"}),
    ("Milan",                {"MXP", "LIN", "MIL"}),
    ("Athens",               {"ATH"}),
    ("Istanbul",             {"IST", "SAW"}),
    ("Moscow",               {"SVO", "DME", "VKO", "MOW"}),
    ("Saint Petersburg",     {"LED"}),
    ("Dubai",                {"DXB", "DWC"}),
    ("Abu Dhabi",            {"AUH"}),
    ("Doha",                 {"DOH"}),
    ("Riyadh",               {"RUH"}),
    ("Tel Aviv",             {"TLV"}),
    ("Cairo",                {"CAI"}),
    ("Johannesburg",         {"JNB"}),
    ("Cape Town",            {"CPT"}),
    ("Nairobi",              {"NBO"}),
    ("Lagos",                {"LOS"}),
    ("Mumbai",               {"BOM"}),
    ("Delhi",                {"DEL"}),
    ("Bangalore",            {"BLR"}),
    ("Chennai",              {"MAA"}),
    ("Kolkata",              {"CCU"}),
    ("Hyderabad",            {"HYD"}),
    ("Sydney",               {"SYD"}),
    ("Melbourne",            {"MEL", "AVV"}),
    ("Brisbane",             {"BNE"}),
    ("Perth",                {"PER"}),
    ("Auckland",             {"AKL"}),
]
assert len(COMMON_EN) >= 100, f"Need 100 EN, have {len(COMMON_EN)}"

COMMON_CN: List[Tuple[str, set]] = [
    ("香港",          {"HKG"}),
    ("香港国际机场",   {"HKG"}),
    ("香港國際機場",   {"HKG"}),
    ("东京",          {"NRT", "HND", "TYO"}),
    ("東京",          {"NRT", "HND", "TYO"}),
    ("成田",          {"NRT"}),
    ("羽田",          {"HND"}),
    ("大阪",          {"KIX", "ITM", "OSA"}),
    ("关西",          {"KIX"}),
    ("關西",          {"KIX"}),
    ("首尔",          {"ICN", "GMP", "SEL"}),
    ("首爾",          {"ICN", "GMP", "SEL"}),
    ("仁川",          {"ICN"}),
    ("新加坡",         {"SIN"}),
    ("曼谷",          {"BKK", "DMK"}),
    ("台北",          {"TPE", "TSA"}),
    ("桃园",          {"TPE"}),
    ("桃園",          {"TPE"}),
    ("上海",          {"PVG", "SHA"}),
    ("浦东",          {"PVG"}),
    ("浦東",          {"PVG"}),
    ("虹桥",          {"SHA"}),
    ("虹橋",          {"SHA"}),
    ("北京",          {"PEK", "PKX", "BJS"}),
    ("广州",          {"CAN"}),
    ("廣州",          {"CAN"}),
    ("深圳",          {"SZX"}),
    ("成都",          {"CTU", "TFU"}),
    ("杭州",          {"HGH"}),
    ("厦门",          {"XMN"}),
    ("廈門",          {"XMN"}),
    ("武汉",          {"WUH"}),
    ("武漢",          {"WUH"}),
    ("西安",          {"XIY"}),
    ("南京",          {"NKG"}),
    ("重庆",          {"CKG"}),
    ("重慶",          {"CKG"}),
    ("青岛",          {"TAO"}),
    ("青島",          {"TAO"}),
    ("天津",          {"TSN"}),
    ("沈阳",          {"SHE"}),
    ("瀋陽",          {"SHE"}),
    ("大连",          {"DLC"}),
    ("大連",          {"DLC"}),
    ("郑州",          {"CGO"}),
    ("鄭州",          {"CGO"}),
    ("长沙",          {"CSX"}),
    ("長沙",          {"CSX"}),
    ("昆明",          {"KMG"}),
    ("贵阳",          {"KWE"}),
    ("貴陽",          {"KWE"}),
    ("南宁",          {"NNG"}),
    ("南寧",          {"NNG"}),
    ("海口",          {"HAK"}),
    ("三亚",          {"SYX"}),
    ("三亞",          {"SYX"}),
    ("纽约",          {"JFK", "LGA", "EWR", "NYC"}),
    ("紐約",          {"JFK", "LGA", "EWR", "NYC"}),
    ("洛杉矶",         {"LAX"}),
    ("洛杉磯",         {"LAX"}),
    ("旧金山",         {"SFO"}),
    ("舊金山",         {"SFO"}),
    ("三藩市",         {"SFO"}),
    ("西雅图",         {"SEA"}),
    ("西雅圖",         {"SEA"}),
    ("芝加哥",         {"ORD", "MDW", "CHI"}),
    ("波士顿",         {"BOS"}),
    ("波士頓",         {"BOS"}),
    ("迈阿密",         {"MIA"}),
    ("邁阿密",         {"MIA"}),
    ("华盛顿",         {"IAD", "DCA", "WAS"}),
    ("華盛頓",         {"IAD", "DCA", "WAS"}),
    ("休斯顿",         {"IAH", "HOU"}),
    ("休士頓",         {"IAH", "HOU"}),
    ("达拉斯",         {"DFW", "DAL"}),
    ("達拉斯",         {"DFW", "DAL"}),
    ("亚特兰大",        {"ATL"}),
    ("亞特蘭大",        {"ATL"}),
    ("拉斯维加斯",      {"LAS"}),
    ("拉斯維加斯",      {"LAS"}),
    ("丹佛",          {"DEN"}),
    ("多伦多",         {"YYZ", "YTZ"}),
    ("多倫多",         {"YYZ", "YTZ"}),
    ("温哥华",         {"YVR"}),
    ("溫哥華",         {"YVR"}),
    ("墨西哥城",        {"MEX"}),
    ("伦敦",          {"LHR", "LGW", "STN", "LON"}),
    ("倫敦",          {"LHR", "LGW", "STN", "LON"}),
    ("巴黎",          {"CDG", "ORY", "PAR"}),
    ("法兰克福",        {"FRA"}),
    ("法蘭克福",        {"FRA"}),
    ("慕尼黑",         {"MUC"}),
    ("柏林",          {"BER"}),
    ("阿姆斯特丹",      {"AMS"}),
    ("布鲁塞尔",        {"BRU"}),
    ("布魯塞爾",        {"BRU"}),
    ("苏黎世",         {"ZRH"}),
    ("蘇黎世",         {"ZRH"}),
    ("罗马",          {"FCO", "CIA", "ROM"}),
    ("羅馬",          {"FCO", "CIA", "ROM"}),
    ("米兰",          {"MXP", "LIN", "MIL"}),
    ("米蘭",          {"MXP", "LIN", "MIL"}),
    ("马德里",         {"MAD"}),
    ("馬德里",         {"MAD"}),
    ("巴塞罗那",        {"BCN"}),
    ("巴塞隆納",        {"BCN"}),
    ("迪拜",          {"DXB", "DWC"}),
    ("杜拜",          {"DXB", "DWC"}),
    ("多哈",          {"DOH"}),
    ("孟买",          {"BOM"}),
    ("孟買",          {"BOM"}),
    ("德里",          {"DEL"}),
    ("悉尼",          {"SYD"}),
    ("墨尔本",         {"MEL", "AVV"}),
    ("墨爾本",         {"MEL", "AVV"}),
    ("吉隆坡",         {"KUL"}),
]
assert len(COMMON_CN) >= 100, f"Need 100 CN, have {len(COMMON_CN)}"

UNCOMMON: List[Tuple[str, set]] = [
    # Small / regional / less-known but real airports
    ("Palo Alto airport",       {"PAO"}),
    ("Burbank",                 {"BUR"}),
    ("Long Beach",              {"LGB"}),
    ("Santa Barbara",           {"SBA"}),
    ("Reno",                    {"RNO"}),
    ("Boise",                   {"BOI"}),
    ("Tucson",                  {"TUS"}),
    ("Albuquerque",             {"ABQ"}),
    ("Anchorage",               {"ANC"}),
    ("Honolulu",                {"HNL"}),
    ("Maui",                    {"OGG"}),
    ("Kona",                    {"KOA"}),
    ("Halifax",                 {"YHZ"}),
    ("Quebec City",             {"YQB"}),
    ("Edinburgh",               {"EDI"}),
    ("Glasgow",                 {"GLA"}),
    ("Manchester UK",           {"MAN"}),
    ("Dublin",                  {"DUB"}),
    ("Reykjavik",               {"KEF", "RKV"}),
    ("Helsinki",                {"HEL"}),
    ("Oslo",                    {"OSL"}),
    ("Stockholm",               {"ARN", "BMA", "STO"}),
    ("Copenhagen",              {"CPH"}),
    ("Warsaw",                  {"WAW"}),
    ("Prague",                  {"PRG"}),
    ("Budapest",                {"BUD"}),
    ("Krakow",                  {"KRK"}),
    ("Tbilisi",                 {"TBS"}),
    ("Almaty",                  {"ALA"}),
    ("Tashkent",                {"TAS"}),
    # Chinese smaller cities
    ("烟台",                     {"YNT"}),
    ("煙台",                     {"YNT"}),
]
assert len(UNCOMMON) >= 30, f"Need 30 uncommon, have {len(UNCOMMON)}"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

GREEN = "\033[92m"
RED   = "\033[91m"
YEL   = "\033[93m"
DIM   = "\033[2m"
END   = "\033[0m"


def run_section(title: str, cases: Iterable[Tuple[str, set]]):
    cases = list(cases)
    print(f"\n{'='*78}")
    print(f"  {title}  ({len(cases)} cases)")
    print(f"{'='*78}")
    passed = 0
    failed: list[Tuple[str, set, object, float]] = []
    t0 = time.time()
    for query, expected in cases:
        t_q = time.time()
        result = resolve_to_iata(query)
        elapsed = (time.time() - t_q) * 1000
        got = result[0] if result else None
        ok = got in expected
        if ok:
            passed += 1
            mark = f"{GREEN}✓{END}"
        else:
            mark = f"{RED}✗{END}"
            failed.append((query, expected, result, elapsed))
        exp_str = "/".join(sorted(expected))
        got_str = f"{result[0]:3s} {result[1]}" if result else "(none)"
        print(f"  {mark} {query:30s} expected {exp_str:20s} got {got_str}  {DIM}{elapsed:6.1f}ms{END}")
    elapsed_total = time.time() - t0
    pct = 100.0 * passed / len(cases) if cases else 0
    color = GREEN if pct >= 90 else (YEL if pct >= 75 else RED)
    print(f"\n  Result: {color}{passed}/{len(cases)} ({pct:.1f}%){END}   total {elapsed_total*1000:.0f}ms"
          f"  avg {(elapsed_total/len(cases))*1000:.1f}ms")
    return passed, len(cases), failed


def main():
    print("\nAirport resolver stress test")
    print("Tests against the live `airports` table via app.services.airport_resolver\n")

    sections = [
        ("100 common cities / airports — English", COMMON_EN),
        ("100 common cities / airports — Chinese", COMMON_CN),
        ("30 uncommon / regional cities",          UNCOMMON),
    ]

    summary = []
    all_failures = []
    for title, cases in sections:
        p, t, fails = run_section(title, cases)
        summary.append((title, p, t))
        all_failures.extend((title, *f) for f in fails)

    print("\n" + "="*78)
    print("  SUMMARY")
    print("="*78)
    total_p = total_t = 0
    for title, p, t in summary:
        pct = 100.0 * p / t
        color = GREEN if pct >= 90 else (YEL if pct >= 75 else RED)
        print(f"  {title:55s} {color}{p:3d}/{t:3d}  ({pct:5.1f}%){END}")
        total_p += p
        total_t += t
    overall = 100.0 * total_p / total_t
    color = GREEN if overall >= 85 else (YEL if overall >= 70 else RED)
    print(f"  {'OVERALL':55s} {color}{total_p:3d}/{total_t:3d}  ({overall:5.1f}%){END}")

    if all_failures:
        print(f"\n{RED}Failures ({len(all_failures)}):{END}")
        for section, query, expected, result, _ms in all_failures:
            exp_str = "/".join(sorted(expected))
            got_str = f"{result[0]} {result[1]}" if result else "(none)"
            print(f"  [{section[:30]}] {query!r:30s} expected {exp_str}, got {got_str}")

    return 0 if overall >= 85 else 1


if __name__ == "__main__":
    sys.exit(main())

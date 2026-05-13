"""
International Airports Service
==============================

A curated mapping of IATA codes recognised as international airports
(those that have customs/immigration facilities and operate scheduled
international service). The list is sourced from the Wikipedia article
"List of international airports by country"
(https://en.wikipedia.org/wiki/List_of_international_airports_by_country).

This module is used by the "nearest airport" lookup so that when a user's
GPS coordinates resolve to a small/regional airport (e.g. Palo Alto KPAO),
we promote them to the closest *international* airport — which is what a
flight search engine actually needs.

Also exposes HARDCODED_REMAP for fixed mappings that should always apply
(e.g. PAO -> SFO).
"""

from __future__ import annotations
from typing import Optional, Tuple


# ---------------------------------------------------------------------------
# Hardcoded remap: applied BEFORE international-airport snapping.
# Useful for tiny/private airports next to a well-known hub where the
# great-circle distance computation might otherwise pick a different one.
# ---------------------------------------------------------------------------
HARDCODED_REMAP: dict[str, str] = {
    "PAO": "SFO",  # Palo Alto Airport -> San Francisco International
}


# ---------------------------------------------------------------------------
# IATA codes of international airports, grouped (informally) by region for
# maintainability. Membership in this set is what matters at runtime.
# ---------------------------------------------------------------------------
INTERNATIONAL_IATA_CODES: frozenset[str] = frozenset({
    # ---------------- Africa ----------------
    # Northern
    "ALG", "AAE", "BLJ", "BJA", "CFK", "CZL", "GHA", "GJL", "ORN", "BSK", "QSF", "TLM",
    "HBE", "ATZ", "ASW", "CAI", "SPX", "AAC", "DBB", "HRG", "LXR", "RMF", "MUH", "SKV",
    "SSH", "HMB", "TCP", "BEN", "SEB", "TIP", "MJI", "AGA", "BEM", "CMN", "ESU", "FEZ",
    "RAK", "NDR", "OZZ", "OUD", "RBA", "TNG", "TTU", "VIL", "EUN", "KRT", "PZU", "DJE",
    "NBE", "MIR", "SFA", "TBJ", "TOE", "TUN",
    # Western
    "COO", "BOY", "OUA", "BVC", "SID", "RAI", "VXE", "BJL", "ACC", "KMS", "TKD", "NYI",
    "HZO", "WZA", "TML", "CKY", "OXB", "ABJ", "ROB", "BKO", "NKC", "NDB", "ATR", "NIM",
    "ABV", "CBQ", "ABB", "KAN", "LOS", "PHC", "ENU", "SKO", "HLE", "DSS", "FNA", "LFW",
    # Central
    "CBT", "LAD", "SDD", "DLA", "NSI", "BGF", "NDJ", "GOM", "FIH", "FKI", "FBM", "SSG",
    "MVB", "LBV", "POG", "BZV", "PNR", "TMS",
    # Southern
    "GBE", "MUB", "FRW", "BBK", "SHO", "MSU", "WDH", "WVB", "BFN", "CPT", "DUR", "ELS",
    "JNB", "HLA", "MQP", "PTG",
    # Eastern
    "BJM", "HAH", "JIB", "ASM", "ADD", "DIR", "EDL", "MBA", "KIS", "NBO", "TNR", "DIE",
    "MJN", "NOS", "TMM", "FTU", "TLE", "BLZ", "LLW", "MRU", "DZA", "MPM", "BEW", "INH",
    "APL", "POL", "TET", "VNX", "RUN", "KGL", "SEZ", "BSA", "GLK", "GGR", "HGA", "KMU",
    "MGQ", "JUB", "MAK", "ARK", "DAR", "JRO", "MWZ", "TGT", "ZNZ", "RUA", "EBB", "ULU",
    "LVI", "LUN", "MFU", "NLA", "HRE", "VFA", "BUQ",

    # ---------------- Americas ----------------
    # Caribbean
    "AXA", "ANU", "AUA", "NAS", "CCZ", "GGT", "FPO", "ELH", "RSD", "MHH", "BGI", "EIS",
    "BON", "EUX", "SAB", "CYB", "GCM", "CMW", "CCC", "CYO", "CFG", "HAV", "HOG", "SNU",
    "SCU", "VRA", "CUR", "DOM", "BRX", "LRM", "PUJ", "AZS", "POP", "STI", "SDQ", "GND",
    "PTP", "CAP", "PAP", "KIN", "MBJ", "FDF", "MNI", "BQN", "PSE", "SIG", "SJU", "SBH",
    "SKB", "UVF", "SVD", "CIW", "SXM", "POS", "TAB", "PLS", "STT", "STX",
    # Central America
    "BZE", "LIR", "SJO", "SAL", "FRS", "GUA", "LCE", "RTB", "SAP", "TGU", "XPL", "MGA",
    "BEF", "RNI", "BOC", "DAV", "PAC", "BLB", "PTY", "RIH", "BDA",
    # Canada
    "YXX", "YLK", "YYC", "YYG", "YDA", "YEG", "YFC", "YQX", "YHZ", "YHM", "YKA", "YLW",
    "YGK", "YKF", "YXU", "YQM", "YUL", "YOW", "YQB", "YQR", "YSJ", "YYT", "YQY", "YQT",
    "YYZ", "YTZ", "YVR", "YYJ", "YXY", "YQG", "YWG",
    # Greenland & Saint Pierre
    "SFJ", "GOH", "JAV", "UAK", "FSP",
    # Mexico
    "ACA", "AGU", "CUN", "CUU", "CME", "CZM", "CUL", "DGO", "GDL", "HMO", "HUX", "ZIH",
    "BJX", "LTO", "CSL", "SJD", "ZLO", "MZT", "MID", "MXL", "MEX", "NLU", "MTY", "MLM",
    "OAX", "PBC", "PXM", "PVR", "QRO", "REX", "SLW", "SLP", "TAM", "TPQ", "TIJ", "TLC",
    "TRC", "TQO", "UPN", "TGZ", "VER", "VSA", "ZCL",
    # United States
    "AKC", "ALB", "ABQ", "AMA", "ANC", "ATW", "ATL", "ACY", "AUS", "BWI", "BGR", "BDE",
    "BLI", "BHM", "BOI", "BOS", "BRO", "BUF", "CXL", "CLT", "CHS", "MDW", "ORD", "CVG",
    "CLE", "CAE", "CMH", "LCK", "CRP", "DAL", "DFW", "DAY", "DEN", "DSM", "DTW", "DLH",
    "ELP", "ERI", "FAI", "FLL", "RSW", "FAT", "GYY", "GRR", "GRB", "GSO", "GSP", "GPT",
    "HRL", "MDT", "BDL", "ITO", "HNL", "IAH", "HOU", "HSV", "IND", "INL", "JAN", "JAX",
    "JNU", "KOA", "MCI", "KTN", "EYW", "ISM", "TYS", "LAL", "LAN", "LAS", "LIT", "LAX",
    "SDF", "LBB", "MSN", "MFE", "MLB", "MEM", "MIA", "MAF", "MKE", "MSP", "MYR", "BNA",
    "MSY", "JFK", "LGA", "EWR", "SWF", "PHF", "IAG", "ORF", "OAK", "OKC", "OMA", "ONT",
    "SNA", "MCO", "PSP", "ECP", "PNS", "PHL", "PHX", "AZA", "PIT", "PWM", "PDX", "PVD",
    "RAC", "RDU", "RNO", "RIC", "RST", "ROC", "RFD", "SMF", "SLC", "SAT", "SBD", "SAN",
    "SFO", "SJC", "SFB", "SRQ", "SAV", "LKE", "BFI", "SEA", "SBM", "PAE", "GEG", "STL",
    "PIE", "SYR", "TLH", "TPA", "TUS", "TUL", "DCA", "IAD", "PBI", "AVP", "ILM",
    # South America
    "EZE", "AEP", "BRC", "CRD", "COR", "CNQ", "FTE", "EPA", "EQS", "FMA", "MDQ", "MDZ",
    "NQN", "PSS", "IGR", "RES", "RGL", "RGA", "ROS", "SLA", "TUC", "JUJ", "RLO", "RHD",
    "REL", "USH", "LPB", "VVI", "CBB", "AJU", "BEL", "CNF", "BVB", "BSB", "VCP", "CGR",
    "CGB", "CWB", "FLN", "FOR", "IGU", "GYN", "JPA", "MCZ", "MAO", "NAT", "PNZ", "POA",
    "PVH", "REC", "RBR", "GIG", "SDU", "SSA", "SLZ", "CGH", "GRU", "THE", "UDI", "VIX",
    "ANF", "CCP", "PMC", "PUQ", "SCL", "AXM", "BAQ", "BOG", "BGA", "BUN", "CLO", "CTG",
    "CUC", "IBE", "IPI", "FLA", "LET", "MCJ", "MZL", "MDE", "MVP", "MTR", "NVA", "PSO",
    "PEI", "PPN", "PVA", "UIB", "RCH", "ADZ", "TLU", "TCO", "SMR", "CZU", "VUP", "VVC",
    "EYP", "CUE", "ESM", "GYE", "ETR", "MEC", "UIO", "TUA", "MPN", "CAY", "GEO", "ASU",
    "AGT", "AQP", "CIX", "CUZ", "LIM", "TRU", "PBM", "MVD", "PDP", "RVY", "CCS", "MAR",
    "VLN",

    # ---------------- Asia ----------------
    # Central Asia
    "SCO", "AKX", "ALA", "NQZ", "GUW", "KGF", "KOV", "KSN", "KZO", "URA", "UKK", "PWQ",
    "PPK", "PLX", "CIT", "DMB", "FRU", "IKU", "IKG", "OSS", "KQT", "DYU", "LBD", "TJU",
    "ASB", "TAZ", "MYP", "CRZ", "KRW", "AZN", "BHK", "FEG", "KSQ", "NMA", "NVI", "NCU",
    "SKD", "TAS", "TMJ", "UGC",
    # Eastern Asia – China
    "BAV", "BHY", "PEK", "PKX", "CGQ", "CSX", "CZX", "CTU", "TFU", "CKG", "DLC", "DDG",
    "DAT", "DNH", "ENH", "FOC", "KOW", "CAN", "KWL", "KWE", "HAK", "HGH", "HRB", "HFE",
    "HEK", "HET", "HIA", "TXN", "HLD", "JMU", "SWA", "TNA", "KMG", "LHW", "LXA", "LYG",
    "LJG", "LYI", "LYA", "LUM", "NZH", "MDG", "KHN", "NKG", "NNG", "NTG", "NGB", "DSN",
    "TAO", "BPE", "BAR", "NDG", "JJN", "SYX", "SHA", "PVG", "SHE", "SZX", "SJW", "TYN",
    "TSN", "UCB", "URC", "WXN", "WEH", "WNZ", "WUH", "WUX", "WUS", "XMN", "XIY", "XNN",
    "WUT", "JHG", "XUZ", "YNZ", "YTY", "YNJ", "YNT", "YIH", "INC", "YIW", "YCU", "DYG",
    "ZHA", "CGO", "ZUH", "ZYI",
    # Eastern Asia – Other
    "HKG", "AXT", "AOJ", "FUK", "HKD", "HIJ", "KOJ", "KKJ", "KMQ", "NGS", "NGO", "OKA",
    "KIJ", "OIT", "OKJ", "KIX", "CTS", "SDJ", "FSZ", "HND", "NRT", "MFM", "ULG", "UBN",
    "FNJ", "PUS", "CJJ", "TAE", "CJU", "MWX", "GMP", "ICN", "YNY", "HUN", "KHH", "RMQ",
    "TNN", "TSA", "TPE",
    # Southern Asia
    "BZL", "CGP", "CXB", "DAC", "KLN", "RJH", "SPD", "ZYL", "PBH", "IXA", "AMD", "ATQ",
    "AYJ", "BLR", "BHO", "BBI", "MAA", "CJB", "DEL", "RDP", "GAY", "GAU", "HYD", "IMF",
    "IDR", "JAI", "IXJ", "CNN", "COK", "CCU", "CCJ", "LKO", "IXM", "IXE", "BOM", "NAG",
    "ISK", "NMI", "DXN", "GOX", "PNQ", "IXR", "IXB", "GOI", "SXR", "STV", "TRV", "TRZ",
    "TIR", "BDQ", "VNS", "VGA", "VTZ", "GAN", "HAQ", "MLE", "NMF", "VAM", "KTM", "PKR",
    "BWA", "BHV", "LYP", "GWD", "ISB", "KHI", "LHE", "MUX", "PEW", "UET", "RYK", "SKT",
    "TUK", "BTC", "CMB", "RML", "HRI", "JAF",
    # Southeast Asia
    "BWN", "KTI", "PNH", "REP", "KOS", "AMQ", "BPN", "BTJ", "TKG", "KJT", "BDJ", "BTH",
    "DPS", "HLP", "CGK", "DJJ", "LBJ", "UPG", "MDC", "LOP", "KNO", "PDG", "PLM", "PKU",
    "AAP", "SRG", "SOQ", "SUB", "SOC", "TJQ", "YIA", "BOR", "LPQ", "PKZ", "ZVK", "VTE",
    "AOR", "IPH", "JHB", "KBR", "BKI", "KUL", "SZB", "TGG", "KUA", "KCH", "LBU", "LGK",
    "PEN", "MDL", "NYT", "RGN", "DRP", "LLC", "CEB", "CRK", "DVO", "GES", "ILO", "KLO",
    "CGY", "LAO", "MNL", "TAG", "PPS", "SFS", "ZAM", "SIN", "XSP", "BKK", "DMK", "CNX",
    "CEI", "HDY", "USM", "KBV", "HKT", "UTP", "URT", "UTH", "DIL", "VCA", "DAD", "HPH",
    "HAN", "SGN", "HUI", "CXR", "PQC", "VCL", "VDO",
    # Middle East / Southwest Asia
    "HEA", "KBL", "KDH", "MZR", "LWN", "YUK", "EVN", "GYD", "FZL", "KVD", "LHL", "LLK",
    "NAJ", "GBB", "ZZE", "ZTU", "BAH", "LCA", "ECN", "PFO", "BUS", "KUT", "SUI", "TBS",
    "ABD", "AWZ", "AJK", "ADU", "PGU", "BND", "XBJ", "BUZ", "GBT", "HDM", "IIL", "IFN",
    "KER", "KSH", "KIH", "ZBR", "LFM", "LRR", "MHD", "GSM", "RAS", "SRY", "SYZ", "TBZ",
    "IKA", "THR", "OMH", "AZD", "ZAH", "NJF", "BGW", "BSR", "EBL", "OSM", "XNH", "ISU",
    "ETM", "HFA", "TLV", "AQJ", "AMM", "KWI", "BEY", "MCT", "SLL", "OHS", "DOH", "AHB",
    "HOF", "AJF", "ULH", "ELQ", "DMM", "AQI", "HAS", "RSI", "JED", "GIZ", "MED", "EAM",
    "NUM", "RUH", "TUU", "TIF", "YNB", "ALP", "DAM", "LTK", "KAC", "ADA", "GZP", "ESB",
    "AYT", "BJV", "YEI", "DLM", "DNZ", "DIY", "EZS", "GZT", "IST", "SAW", "ADB", "ASR",
    "KYA", "KZR", "MLX", "NAV", "SZF", "TZX", "ONQ", "AUH", "AAN", "DWC", "DXB", "RKT",
    "SHJ", "ADE", "RIY", "SAH", "GXF", "SCT",

    # ---------------- Europe ----------------
    # Western
    "ANR", "BRU", "CRL", "LGG", "OST", "AMS", "EIN", "GRQ", "MST", "RTM", "LUX", "AJA",
    "BIA", "BVA", "EGC", "BZR", "BIQ", "BOD", "BES", "CCF", "XCR", "CMF", "DNR", "FSC",
    "GNB", "LRH", "LIL", "LIG", "LYS", "MRS", "BSL", "NTE", "NCE", "FNI", "CDG", "ORY",
    "PUF", "PGF", "PIS", "RDZ", "EBU", "SXB", "TLN", "TLS", "TUF", "ORK", "DUB", "KIR",
    "NOC", "SNN", "BHX", "BOH", "BRS", "EXT", "HUY", "LBA", "LPL", "LGW", "LHR", "LCY",
    "SEN", "STN", "LTN", "MAN", "MME", "NCL", "NQY", "NWI", "EMA", "SOU", "ABZ", "BFS",
    "BHD", "CWL", "LDY", "EDI", "GLA", "PIK", "INV", "ACI", "IOM", "GIB", "GCI", "JER",
    # Central
    "GRZ", "KLU", "INN", "LNZ", "SZG", "VIE", "BRQ", "JCL", "KLV", "OSR", "PED", "PRG",
    "FKB", "BER", "BRE", "CGN", "DTM", "DUS", "FRA", "HHN", "FDH", "HAM", "HAJ", "LEJ",
    "LBC", "FMM", "MUC", "NUE", "STR", "NRN", "BUD", "DEB", "QGY", "SOB", "QPJ", "BZG",
    "GDN", "KTW", "KRK", "LUZ", "LCJ", "SZY", "POZ", "RZE", "SZZ", "WAW", "WMI", "RDO",
    "WRO", "BTS", "KSC", "PZY", "TAT", "ILZ", "BRN", "GVA", "LUG", "ACH", "ZRH",
    # Southern
    "BWK", "DBV", "LSZ", "OSI", "PUY", "RJK", "SPU", "ZAD", "ZAG", "ATH", "EFL", "CHQ",
    "JKH", "CFU", "HER", "KLX", "AOK", "KVA", "KGS", "JMK", "MJT", "PVK", "RHO", "SMI",
    "JTR", "JSI", "SKU", "SKG", "VOL", "ZTH", "AHO", "AOI", "BRI", "BGY", "BLQ", "VBS",
    "BDS", "CAG", "CTA", "CUF", "FLR", "GOA", "SUF", "LIN", "MXP", "NAP", "OLB", "PMO",
    "PMF", "PEG", "PSR", "PSA", "RMI", "FCO", "CIA", "QSR", "TPS", "TRS", "TRN", "VCE",
    "VRN", "MLA", "BYJ", "FAO", "FNC", "LIS", "PDL", "OPO", "PXO", "TER", "LJU", "MBX",
    "POW", "LCG", "ALC", "LEI", "OVD", "BCN", "BIO", "CDT", "FUE", "GRO", "LPA", "GRX",
    "HSK", "IBZ", "XRY", "SPC", "ACE", "ILD", "MAD", "AGP", "MAH", "RMU", "PMI", "PNA",
    "REU", "SDR", "SCQ", "SVQ", "TFN", "TFS", "VLC", "VLL", "VGO", "VIT", "ZAZ",
    # Eastern
    "KFZ", "TIA", "GNA", "GME", "MSQ", "BNX", "OMO", "SJJ", "TZL", "BOJ", "PDV", "SOF",
    "VAR", "PRN", "RMO", "ARW", "BCM", "BAY", "GHV", "OTP", "BBU", "CLJ", "CND", "CRA",
    "IAS", "OMR", "SUJ", "SBZ", "SCV", "TGM", "TSR", "TGD", "TIV", "OHD", "SKP", "ABA",
    "DYR", "AAQ", "ARH", "ASF", "BAX", "EGO", "BQS", "BTK", "BZK", "CSY", "CEK", "CEE",
    "HTA", "ESL", "GRV", "IKT", "KGD", "KZN", "KHV", "KXK", "KRR", "KJA", "URS", "GDX",
    "MQF", "MCX", "MRV", "DME", "ZIA", "SVO", "VKO", "MMK", "NAL", "NBC", "NJC", "GOJ",
    "NOZ", "OVB", "OMS", "REN", "OSW", "PEE", "PES", "PVS", "PKC", "PKV", "ROV", "LED",
    "KUF", "GSV", "AER", "STW", "SGC", "SCW", "TOF", "TJM", "UUD", "ULV", "UFA", "VVO",
    "OGZ", "VOG", "VOZ", "YKS", "IAR", "SVX", "UUS", "BEG", "KVO", "INI", "CWC", "IFO",
    "HRK", "KWG", "KBP", "IEV", "LWO", "NLV", "ODS", "PLV", "SIP", "UDJ", "OZH",
    # Nordic / Baltics
    "EPU", "TLL", "TAY", "RIX", "VNT", "KUN", "PLQ", "SQQ", "VNO", "AAL", "AAR", "BLL",
    "CPH", "FAE", "MHQ", "HEL", "KTT", "KUO", "KAO", "LPP", "OUL", "RVN", "SVL", "TMP",
    "TKU", "VAA", "AEY", "EGS", "KEF", "RKV", "AES", "BGO", "BOO", "HAU", "KRS", "KSU",
    "OSL", "TRF", "SVG", "TOS", "TRD", "GOT", "LLA", "MMX", "NRK", "OSD", "ARN", "BMA",
    "NYO", "VST", "SDL", "UME", "VXO", "VBY",

    # ---------------- Oceania ----------------
    "PPG", "ADL", "BNE", "BME", "CNS", "CBR", "DRW", "OOL", "HBA", "HID", "MEL", "NTL",
    "PER", "MCY", "SYD", "XCH", "CCK", "RAR", "IPC", "NAN", "SUV", "PPT", "GUM", "CXI",
    "TRW", "KWA", "MAJ", "TKK", "KSA", "PNI", "YAP", "INU", "NOU", "AKL", "CHC", "DUD",
    "HLZ", "ZQN", "WLG", "IUE", "NLK", "ROP", "SPN", "TIQ", "ROR", "DAU", "HGU", "POM",
    "APW", "HIR", "TBU", "VAV", "FUN", "SON", "VLI", "FUT", "WLS",
})


def is_international(iata_code: Optional[str]) -> bool:
    """Return True if the given IATA code is in the international airports set."""
    if not iata_code:
        return False
    return iata_code.upper() in INTERNATIONAL_IATA_CODES


def apply_hardcoded_remap(iata_code: Optional[str]) -> Optional[str]:
    """Apply hardcoded IATA remapping (e.g. PAO -> SFO). Returns the (possibly
    remapped) IATA code, or the original input if no remap applies."""
    if not iata_code:
        return iata_code
    return HARDCODED_REMAP.get(iata_code.upper(), iata_code.upper())


def find_nearest_international_airport_sql() -> str:
    """SQL fragment that finds the nearest international airport to a given
    (lat, lng) pair. Uses Haversine in SQL. The %s placeholders are, in order:
    lat, lng, lat, then a tuple of all international IATA codes.

    Returns ordered rows: (iata_code, name, municipality, iso_country,
    latitude_deg, longitude_deg, distance_km).
    """
    return """
        SELECT
            iata_code, name, municipality, iso_country,
            latitude_deg, longitude_deg,
            (6371 * acos(
                cos(radians(%s)) * cos(radians(latitude_deg)) *
                cos(radians(longitude_deg) - radians(%s)) +
                sin(radians(%s)) * sin(radians(latitude_deg))
            )) AS distance_km
        FROM airports
        WHERE iata_code = ANY(%s)
          AND latitude_deg IS NOT NULL
          AND longitude_deg IS NOT NULL
        ORDER BY distance_km
        LIMIT 1
    """


def international_iata_list() -> Tuple[str, ...]:
    """Return international IATA codes as a sorted tuple (for SQL ANY(%s))."""
    return tuple(sorted(INTERNATIONAL_IATA_CODES))

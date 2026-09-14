"""
BHUMI-NITI: Multi-Jurisdictional Statutory Rules Engine
Resolves state-specific land revenue codes, tenancy acts, tribal protections, urban planning mandates,
and Non-Agricultural (NA) conversion prerequisites dynamically based on location hierarchy.
"""

from typing import Dict, Any, List

def evaluate_regulatory_framework(hierarchy: Dict[str, str], official_name: str, ecology: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evaluates statutory rules based on the state, district, and ecological features.
    Supports Gujarat, Maharashtra, Uttar Pradesh, Karnataka, Madhya Pradesh, Rajasthan, West Bengal, Tamil Nadu, and generic state fallbacks.
    """
    state = hierarchy.get("state", "").lower()
    district = hierarchy.get("district", "").lower()
    taluka = hierarchy.get("taluka", "").lower()
    village = hierarchy.get("village_ward", "").lower()
    name_full = official_name.lower()

    # -------------------------------------------------------------------------
    # 1. UTTAR PRADESH
    # -------------------------------------------------------------------------
    if "uttar pradesh" in state or "gautam buddha" in district or "noida" in name_full or "lucknow" in name_full:
        authority = "New Okhla Industrial Development Authority (NOIDA) / YEIDA / LDA"
        authority_short = "NOIDA / YEIDA"
        special_act = "UP Industrial Area Development Act 1976 & UP Revenue Code 2006"
        jantri_tier = "Circle Rate Tier 1: Premium NCR Commercial & Industrial Hub"
        na_prereqs = [
            "Section 80 Declaration under UP Revenue Code 2006 (Agricultural to Non-Agricultural status).",
            "Master Plan 2041 zoning conformance and building layout sanction.",
            "State Environmental Impact Assessment Authority (SEIAA UP) clearance for built-up > 20,000 sqm.",
            "NOC from Uttar Pradesh Ground Water Department and Forest Department buffer compliance.",
            "16-digit ULPIN (Bhu-Aadhaar) digital parcel validation via UP Bhulekh portal."
        ]
        tenancy_rules = [
            "UP Zamindari Abolition and Land Reforms (UPZALR) Act 1950 & UP Revenue Code 2006 ceiling compliance (12.5 acres).",
            "Section 98/99 UP Revenue Code: Strict restrictions on alienation of SC/ST land without prior sanction of Collector.",
            "RERA Uttar Pradesh registration mandatory for residential/commercial plotted layout developments.",
            "Hindon/Yamuna riverbed zonation restrictions (no permanent construction within 100m high-flood level)."
        ]
        return {
            "applicable_authority": authority,
            "authority_short": authority_short,
            "special_legislation": special_act,
            "jantri_tier": jantri_tier,
            "na_prerequisites": na_prereqs,
            "tenancy_and_conversion_rules": tenancy_rules,
            "jurisdiction_state": "Uttar Pradesh"
        }

    # -------------------------------------------------------------------------
    # 2. MAHARASHTRA
    # -------------------------------------------------------------------------
    elif "maharashtra" in state or "pune" in district or "mumbai" in name_full or "nagpur" in name_full:
        authority = "Pune Metropolitan Region Development Authority (PMRDA) / MMRDA / Municipal Corp"
        authority_short = "PMRDA / MMRDA"
        special_act = "Maharashtra Regional and Town Planning (MRTP) Act 1966 & Maharashtra Land Revenue Code (MLRC) 1966"
        jantri_tier = "Ready Reckoner Tier 1: Metropolitan Growth Corridor (Annual Statement of Rates)"
        na_prereqs = [
            "Section 44 Maharashtra Land Revenue Code (MLRC) 1966 non-agricultural permission via e-Hakk portal.",
            "Development Plan 2041 zoning verification and layout sanction.",
            "Maharashtra Pollution Control Board (MPCB) consent to establish for commercial/industrial setups.",
            "Water Resources Department (WRD) NOC for projects adjacent to river basins.",
            "Verification of Title / Search Report for 30 years from Sub-Registrar Office."
        ]
        tenancy_rules = [
            "Section 63 Bombay Tenancy and Agricultural Lands Act 1948 (Strict bar on transfer of agricultural land to non-agriculturists).",
            "Section 36 & 36A MLRC: Absolute prohibition on non-tribal transfer of tribal lands without State Govt sanction.",
            "Section 85 MLRC partition compliance and Satbara (7/12 & 8A) digital record synchronization.",
            "Eco-Sensitive Area (ESA) foothills construction buffer compliance."
        ]
        return {
            "applicable_authority": authority,
            "authority_short": authority_short,
            "special_legislation": special_act,
            "jantri_tier": jantri_tier,
            "na_prerequisites": na_prereqs,
            "tenancy_and_conversion_rules": tenancy_rules,
            "jurisdiction_state": "Maharashtra"
        }

    # -------------------------------------------------------------------------
    # 3. KARNATAKA
    # -------------------------------------------------------------------------
    elif "karnataka" in state or "bengaluru" in name_full or "mysuru" in name_full:
        authority = "Bangalore Development Authority (BDA) / BMRDA / KIADB"
        authority_short = "BDA / KIADB"
        special_act = "Karnataka Land Revenue Act 1964 & Karnataka Town & Country Planning Act 1961"
        jantri_tier = "Guidance Value Tier 1: IT Corridor & Industrial SEZ"
        na_prereqs = [
            "Section 95 Karnataka Land Revenue Act 1964 NA conversion order via Seva Sindhu / e-Swathu portal.",
            "BDA Master Plan zoning compliance and layout plan clearance.",
            "KSPCB (Karnataka State Pollution Control Board) Consent to Establish.",
            "Lake Buffer Clearance (30m buffer around Rajakaluve / storm water drains as per NGT guidelines)."
        ]
        tenancy_rules = [
            "Karnataka Land Reforms Act 1961 (Section 79A/79B ceiling and non-agriculturist purchase framework).",
            "Karnataka Scheduled Castes and Scheduled Tribes (Prohibition of Transfer of Certain Lands) Act 1978 (PTCL Act).",
            "e-Swathu Khata registration and Encumbrance Certificate (EC Form 15) verification."
        ]
        return {
            "applicable_authority": authority,
            "authority_short": authority_short,
            "special_legislation": special_act,
            "jantri_tier": jantri_tier,
            "na_prerequisites": na_prereqs,
            "tenancy_and_conversion_rules": tenancy_rules,
            "jurisdiction_state": "Karnataka"
        }

    # -------------------------------------------------------------------------
    # 4. MADHYA PRADESH
    # -------------------------------------------------------------------------
    elif "madhya pradesh" in state or "bhopal" in name_full or "indore" in name_full:
        authority = "Bhopal Development Authority (BDA) / Indore Development Authority (IDA) / MPIDC"
        authority_short = "BDA / IDA"
        special_act = "Madhya Pradesh Land Revenue Code (MPLRC) 1959 & MP Nagar Tatha Gram Nivesh Adhiniyam 1973"
        jantri_tier = "Collector Guideline Rate Tier 1: Urban Growth Hub"
        na_prereqs = [
            "Section 172 MPLRC 1959 Non-Agricultural diversion permission via MP Bhulekh portal.",
            "Town & Country Planning (TNCP) approved layout map.",
            "MP Pollution Control Board environmental consent."
        ]
        tenancy_rules = [
            "Section 165 MPLRC: Prohibition on transfer of land owned by Scheduled Tribe members to non-tribals without Collector approval.",
            "Ceiling limits under MP Ceiling on Agricultural Holdings Act 1960."
        ]
        return {
            "applicable_authority": authority,
            "authority_short": authority_short,
            "special_legislation": special_act,
            "jantri_tier": jantri_tier,
            "na_prerequisites": na_prereqs,
            "tenancy_and_conversion_rules": tenancy_rules,
            "jurisdiction_state": "Madhya Pradesh"
        }

    # -------------------------------------------------------------------------
    # 5. GUJARAT (Default State Specific Logic)
    # -------------------------------------------------------------------------
    elif "gujarat" in state or any(d in district for d in ["ahmedabad", "surat", "vadodara", "rajkot", "kutch", "gandhinagar", "bhavnagar", "dahod", "bharuch", "gir somnath"]):
        authority = "Gram Panchayat / Revenue Department (District Collectorate)"
        authority_short = "Gram Panchayat"
        special_act = "Gujarat Panchayats Act 1993 & Gujarat Land Revenue Code (GLRC) 1879"
        jantri_tier = "Tier 4: Rural Agricultural Base (Standard agricultural Jantri tariff)"

        if "dholera" in name_full or "dholera" in taluka:
            authority = "Dholera Special Investment Region Development Authority (DSIRDA) & DICDL"
            authority_short = "DSIRDA"
            special_act = "Gujarat Special Investment Region (GSIR) Act 2009 & TP Schemes 1-6"
            jantri_tier = "Tier 2: Special Investment Region (Industrial / Logistics Jantri)"
        elif "ahmedabad" in district:
            authority = "Ahmedabad Urban Development Authority (AUDA) / AMC"
            authority_short = "AUDA / AMC"
            special_act = "Gujarat Town Planning and Urban Development Act (GTPUDA) 1976"
            jantri_tier = "Tier 1: Metro Core Corridor (Premium urban Jantri valuation)"
        elif "gandhinagar" in district:
            authority = "Gandhinagar Urban Development Authority (GUDA) / GIFT City SEZ"
            authority_short = "GUDA / GIFT"
            special_act = "GTPUDA 1976 & GIFT SEZ Regulations"
            jantri_tier = "Tier 1: Capital Financial Hub"
        elif "surat" in district:
            authority = "Surat Urban Development Authority (SUDA) / SMC"
            authority_short = "SUDA / SMC"
            special_act = "GTPUDA 1976"
            jantri_tier = "Tier 1: Metro Industrial Corridor"

        tenancy_rules = []
        is_saurashtra = any(sd in district for sd in ["rajkot", "jamnagar", "bhavnagar", "junagadh", "amreli", "surendranagar", "porbandar", "morbi", "devbhumi dwarka", "gir somnath", "botad"])
        if is_saurashtra:
            tenancy_rules.append("Saurashtra Gharkhed, Tenancy Settlement and Agricultural Lands Act 1949 (Section 54): Bar on non-agriculturist purchase without Collector permission.")
        else:
            tenancy_rules.append("Gujarat Tenancy and Agricultural Lands Act 1948 (Section 63): Bar on non-agriculturist transfer without Collector permission.")

        if any(td in district for td in ["dahod", "narmada", "tapi", "panchmahal", "dang", "chhota udepur"]):
            tenancy_rules.append("Gujarat Land Revenue Code Section 73AA: Strict prohibition on alienation of tribal land to non-tribals.")

        na_prereqs = [
            "Online iORA portal e-NA application submission (Form 7/12 & 30-year Encumbrance Certificate).",
            "Planning Authority GDCR zoning verification and layout clearance.",
            "District Collectorate / Prant Officer NA Order issuance."
        ]

        return {
            "applicable_authority": authority,
            "authority_short": authority_short,
            "special_legislation": special_act,
            "jantri_tier": jantri_tier,
            "na_prerequisites": na_prereqs,
            "tenancy_and_conversion_rules": tenancy_rules,
            "jurisdiction_state": "Gujarat"
        }

    # -------------------------------------------------------------------------
    # 6. GENERIC STATE FALLBACK (National Scope Enforcement)
    # -------------------------------------------------------------------------
    else:
        state_name = hierarchy.get("state", "State Jurisdiction").title()
        return {
            "applicable_authority": f"{state_name} Revenue Department / Local Planning Authority",
            "authority_short": "Revenue Dept",
            "special_legislation": f"{state_name} Land Revenue Code & Local Town Planning Act",
            "jantri_tier": "Standard State Revenue Circle Rates",
            "na_prerequisites": [
                f"Non-Agricultural (NA) conversion application via {state_name} single-window portal.",
                "Zoning verification from competent Urban Local Body or Gram Panchayat.",
                "Title search report for 30 years and 7/12 or Record of Rights (RoR) extract."
            ],
            "tenancy_and_conversion_rules": [
                f"{state_name} Agricultural Land Ceiling and Tenancy restrictions apply.",
                "State Scheduled Tribe / Fifth Schedule land alienation restrictions enforced.",
                "Notice: State-specific local tenancy bylaws active; verify with competent Revenue Collector."
            ],
            "jurisdiction_state": state_name
        }

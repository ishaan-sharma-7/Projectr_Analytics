"""Zoning GIS adapter — fetches municipal zoning polygon data from ArcGIS REST APIs.

Supported universities / cities (16 active):
  Virginia Tech            / Blacksburg, VA    tobmaps.blacksburg.gov
  University of Virginia   / Charlottesville   services.arcgis.com  (no-spatial-filter)
  University of Tennessee  / Knoxville, TN     services1.arcgis.com
  UNC Chapel Hill          / Chapel Hill, NC   gis-portal.townofchapelhill.org
  University of Georgia    / Athens, GA        enigma.accgov.com
  NC State University      / Raleigh, NC       maps.raleighnc.gov
  University of Alabama    / Tuscaloosa, AL    services1.arcgis.com
  University of S Carolina / Columbia, SC      gis.columbiasc.gov
  Ohio State University    / Columbus, OH      gis.columbus.gov
  Michigan State Univ.     / East Lansing, MI  gis2.cityofeastlansing.com (HTTPS)
  Texas A&M University     / College Station   gis.cstx.gov
  Penn State University    / State College, PA services8.arcgis.com
  Indiana University       / Bloomington, IN   bloomington.in.gov
  University of Kentucky   / Lexington, KY     services1.arcgis.com
  Mississippi State Univ.  / Starkville, MS    services1.arcgis.com
  Arizona State Univ.      / Tempe, AZ         gis.tempe.gov  (may 403)

Zone PBSH signal values:
  positive    — multi-family explicitly allowed; PBSH is by-right
  neutral     — mixed/commercial; residential possible w/ conditions
  restrictive — single-family/low-density only; rezoning required
  constrained — university/institutional land
  negative    — industrial/R&D; residential not a permitted use

Config keys:
  url               ArcGIS REST query URL
  code_field        property key holding zone code in returned features
  label_field       property key holding full zone name (defaults to code_field)
  code_field_alt    alternative key to try if code_field absent
  zone_map          dict: code → (pbsh_signal, rationale)
  signal_patterns   [(prefix, signal), ...] fallback when code not in zone_map
  no_spatial_filter if True, fetches all features without bbox (client-side PiP)
"""

from __future__ import annotations

import math
from typing import TypedDict

import httpx

# ── Zone maps (corrected from live data) ──────────────────────────────────────

_BLACKSBURG_ZONE_MAP: dict[str, tuple[str, str]] = {
    "RM-48": ("positive",    "Medium-density multiunit — PBSH by-right"),
    "RM-27": ("positive",    "Low-density multiunit — apartments by-right"),
    "MXD":   ("positive",    "Mixed-Use Development"),
    "PR":    ("positive",    "Planned Residential"),
    "R-5":   ("neutral",     "Transitional Residential"),
    "OTR":   ("neutral",     "Old Town Residential"),
    "DC":    ("neutral",     "Downtown Commercial"),
    "GC":    ("neutral",     "General Commercial"),
    "PC":    ("neutral",     "Planned Commercial"),
    "O":     ("neutral",     "Office"),
    "R-4":   ("restrictive", "Low Density Residential — single-family only"),
    "RR-1":  ("restrictive", "Rural Residential 1"),
    "RR-2":  ("restrictive", "Rural Residential 2"),
    "PMH":   ("restrictive", "Planned Manufactured Home"),
    "UNIV":  ("constrained", "University campus land"),
    "IN":    ("negative",    "Industrial"),
    "RD":    ("negative",    "Research & Development"),
}

# Charlottesville VA — actual codes from live service (no_spatial_filter=True)
_CHARLOTTESVILLE_ZONE_MAP: dict[str, tuple[str, str]] = {
    "GU-1":  ("positive",    "General Urban 1 — medium density mixed use"),
    "GU-2":  ("positive",    "General Urban 2"),
    "MF":    ("positive",    "Multi-Family — PBSH by-right"),
    "MFO":   ("positive",    "Multi-Family Office — residential explicitly allowed"),
    "DT":    ("positive",    "Downtown — highest density mixed use"),
    "TF":    ("neutral",     "Two-Family residential"),
    "OR":    ("neutral",     "Office-Residential — limited residential"),
    "GC":    ("neutral",     "General Commercial"),
    "NCC":   ("positive",    "North Carlton Commons — mixed use"),
    "RE-1":  ("restrictive", "Residential Estate 1-acre"),
    "RE-2":  ("restrictive", "Residential Estate 2-acre"),
    "RE-4":  ("restrictive", "Residential Estate 4-acre"),
    "RR":    ("restrictive", "Rural Residential"),
    "RA-5":  ("restrictive", "Residential Agricultural 5-acre"),
    "RA-10": ("restrictive", "Residential Agricultural 10-acre"),
    # Single-family lot-size variants (post-2023 Cville zoning)
    "SF-5":  ("restrictive", "Single-Family 5k sq ft"),
    "SF-10": ("restrictive", "Single-Family 10k sq ft"),
    "SF-15": ("restrictive", "Single-Family 15k sq ft"),
    "SF-20": ("restrictive", "Single-Family 20k sq ft"),
    "RF-2":  ("constrained", "Residential Floodplain 2-acre"),
    "RF-4":  ("constrained", "Residential Floodplain 4-acre"),
    # Commercial / other
    "LC":    ("neutral",     "Local Commercial"),
    "CBD":   ("positive",    "Community Business District"),
    "HI":    ("negative",    "Heavy Industrial"),
    "OSB":   ("constrained", "Open Space Buffer"),
    "ML":    ("negative",    "Manufacturing/Light Industrial"),
    "RRS":   ("restrictive", "Rural Residential Special"),
    "LI":    ("negative",    "Light Industrial"),
    "P":     ("constrained", "Public/Institutional"),
    "UVA":   ("constrained", "University of Virginia land"),
}

# Knoxville TN — actual codes (RN series, not R-1/R-2)
_KNOXVILLE_ZONE_MAP: dict[str, tuple[str, str]] = {
    "RN-1":  ("restrictive", "Residential Neighborhood 1 — low density SFR"),
    "RN-2":  ("restrictive", "Residential Neighborhood 2 — low-medium density"),
    "RN-3":  ("neutral",     "Residential Neighborhood 3 — moderate density"),
    "RN-4":  ("neutral",     "Residential Neighborhood 4 — medium density"),
    "RN-5":  ("neutral",     "Residential Neighborhood 5 — medium-high density"),
    "RN-6":  ("positive",    "Residential Neighborhood 6 — high density / multi-family"),
    "O":     ("neutral",     "Office"),
    "C-N":   ("neutral",     "Neighborhood Commercial"),
    "C-G":   ("neutral",     "General Commercial"),
    "C-G-1": ("neutral",     "General Commercial 1"),
    "C-G-2": ("neutral",     "General Commercial 2"),
    "C-H":   ("neutral",     "Highway Commercial"),
    "DK-G":  ("positive",    "Downtown Knoxville General — mixed use"),
    "DK-R":  ("positive",    "Downtown Knoxville Residential"),
    "I-MU":  ("neutral",     "Industrial Mixed-Use — some residential viable"),
    "I-G":   ("negative",    "General Industrial"),
    "I-L":   ("negative",    "Light Industrial"),
    "I-H":   ("negative",    "Heavy Industrial"),
    "INST":  ("constrained", "Institutional"),
    "OS":    ("constrained", "Open Space"),
    "ROW":   ("constrained", "Right of Way"),
    "RA":    ("restrictive", "Rural Agricultural"),
    "TC":    ("positive",    "Town Center"),
    # Southwest Knoxville / Cumberland University area codes
    "SW-1":  ("restrictive", "Southwest 1 — low density residential"),
    "SW-2":  ("restrictive", "Southwest 2"),
    "SW-3":  ("neutral",     "Southwest 3 — medium density"),
    "SW-4":  ("neutral",     "Southwest 4"),
    "SW-5":  ("neutral",     "Southwest 5"),
    "SW-6":  ("positive",    "Southwest 6 — multi-family"),
    "SW-7":  ("positive",    "Southwest 7 — mixed use"),
    "CU-1":  ("neutral",     "Cumberland University 1"),
    "CU-2":  ("neutral",     "Cumberland University 2"),
    "CU-3":  ("neutral",     "Cumberland University 3"),
    "CU-4":  ("neutral",     "Cumberland University 4"),
    "CU-5":  ("neutral",     "Cumberland University 5"),
    "AG":    ("restrictive", "Agricultural"),
    "A":     ("restrictive", "Agricultural"),
    "OP":    ("neutral",     "Office Park"),
    "OB":    ("neutral",     "Office/Business"),
    "RB":    ("neutral",     "Retail/Business"),
    "PR":    ("constrained", "Parks and Recreation"),
    "LI":    ("negative",    "Light Industrial"),
    "NA":    ("constrained", "Natural Area"),
    "WATER": ("constrained", "Water"),
}

# Chapel Hill NC — actual codes (OI-1 not O&I-1)
_CHAPEL_HILL_ZONE_MAP: dict[str, tuple[str, str]] = {
    "R-1":      ("restrictive", "Single-family"),
    "R-1A":     ("restrictive", "Single-family A"),
    "R-2":      ("restrictive", "Single-family moderate"),
    "R-2A":     ("restrictive", ""),
    "R-3":      ("neutral",     "Multi-family (conditional)"),
    "R-3A":     ("neutral",     ""),
    "R-4":      ("positive",    "Multi-family residential"),
    "R-4A":     ("positive",    ""),
    "R-5":      ("positive",    "High-density residential"),
    "R-6":      ("positive",    "High-density residential"),
    "R-LD1":    ("restrictive", "Residential Low Density 1"),
    "R-SS-CZD": ("restrictive", "Single-family Small Scale conditional"),
    "OI-1":     ("neutral",     "Office-Institutional"),
    "OI-2":     ("neutral",     "Office-Institutional 2"),
    "OI-1-CZD": ("neutral",     "Office-Institutional conditional"),
    "TC-1":     ("positive",    "Town Center 1"),
    "TC-2":     ("positive",    "Town Center 2"),
    "TC-3":     ("positive",    "Town Center 3"),
    "TC-2-CZD": ("positive",    "Town Center 2 conditional"),
    "TC-3-CZD": ("positive",    "Town Center 3 conditional"),
    "CC":       ("neutral",     "Community Commercial"),
    "NC":       ("neutral",     "Neighborhood Commercial"),
    "MHP":      ("restrictive", "Mobile Home Park"),
    "PL":       ("constrained", "Public Land/Institutional"),
    "MP":       ("neutral",     "Master Plan"),
    "MU-V":     ("positive",    "Mixed-Use Village"),
    "MU-V-CZD": ("positive",    "Mixed-Use Village conditional"),
    "DA-1":     ("positive",    "Downtown Area 1"),
    "IND":      ("negative",    "Industrial"),
    "R-LD5":    ("restrictive", "Residential Low Density 5"),
    "R-CP-CZD": ("restrictive", "Residential Country Place conditional"),
}

# Athens-Clarke County GA — actual codes from live service
_ATHENS_ZONE_MAP: dict[str, tuple[str, str]] = {
    "RE":    ("restrictive", "Rural Estate"),
    "RS-60": ("restrictive", "Single-family large lot"),
    "RS-40": ("restrictive", "Single-family"),
    "RS-25": ("restrictive", "Single-family"),
    "RS-15": ("restrictive", "Single-family moderate"),
    "RS-8":  ("restrictive", "Single-family small lot"),
    "RS-5":  ("neutral",     "Small-lot residential — townhomes viable"),
    "RR":    ("restrictive", "Rural Residential"),
    "MH":    ("restrictive", "Mobile Home"),
    "RM-1":  ("positive",    "Multi-family low density"),
    "RM-2":  ("positive",    "Multi-family medium density"),
    "RM-3":  ("positive",    "Multi-family high density"),
    "C-N":   ("neutral",     "Neighborhood Commercial"),
    "C-O":   ("neutral",     "Commercial Office"),
    "C-D":   ("positive",    "Commercial Downtown — mixed use"),
    "C-P":   ("neutral",     "Professional Commercial"),
    "C-G":   ("neutral",     "General Commercial"),
    "HC":    ("neutral",     "Highway Commercial"),
    "G":     ("neutral",     "General commercial"),
    "E-I":   ("negative",    "Employment-Industrial"),
    "I-1":   ("negative",    "Light Industrial"),
    "I-2":   ("negative",    "General Industrial"),
    "PD":    ("neutral",     "Planned Development"),
    "P-ID":  ("constrained", "Public Institutional District"),
    "AG":    ("restrictive", "Agricultural"),
}

# Raleigh NC — actual codes have trailing "-" (OX-, DX- etc.)
# _get_pbsh_signal strips trailing "-" before lookup
_RALEIGH_ZONE_MAP: dict[str, tuple[str, str]] = {
    "R-1":  ("restrictive", "Single-family"),
    "R-2":  ("restrictive", "Single-family"),
    "R-4":  ("restrictive", "Low-density residential"),
    "R-6":  ("neutral",     "Duplex/small multi-family"),
    "R-10": ("positive",    "Multi-family"),
    "RX":   ("positive",    "Residential Mixed-Use"),
    "OX":   ("neutral",     "Office Mixed-Use"),
    "NX":   ("positive",    "Neighborhood Mixed-Use"),
    "DX":   ("positive",    "Downtown Mixed-Use"),
    "CX":   ("neutral",     "Commercial Mixed-Use"),
    "MX":   ("positive",    "Mixed-Use"),
    "IX":   ("negative",    "Industrial Mixed"),
    "NB":   ("neutral",     "Neighborhood Business"),
    "CB":   ("neutral",     "Community Business"),
    "OB":   ("neutral",     "Office Business"),
    "HB":   ("neutral",     "Highway Business"),
    "OP":   ("neutral",     "Office Park"),
    "CM":   ("neutral",     "Commercial Mixed"),
    "IH":   ("negative",    "Heavy Industrial"),
    "IL":   ("negative",    "Light Industrial"),
    "RR":   ("restrictive", "Rural Residential"),
    "RPA":  ("neutral",     "Residential Planned Area"),
    "RAR":  ("restrictive", "Rural Area Residential"),
    "PD":   ("neutral",     "Planned Development"),
    "P":    ("constrained", "Public/Institutional"),
}

# Tuscaloosa AL — actual codes from live service
_TUSCALOOSA_ZONE_MAP: dict[str, tuple[str, str]] = {
    "R-1":   ("restrictive", "Single-family residential"),
    "R-2":   ("restrictive", "Single-family"),
    "R-3":   ("restrictive", "Single-family small lot"),
    "R-4":   ("neutral",     "Two-family / duplex"),
    "RMF-1": ("positive",    "Residential Multi-Family 1 — low density"),
    "RMF-2": ("positive",    "Residential Multi-Family 2 — higher density"),
    "BN":    ("neutral",     "Neighborhood Business"),
    "BGO":   ("neutral",     "General Business Outparcel"),
    "BC":    ("neutral",     "Community Business"),
    "B-1":   ("neutral",     "Limited Business"),
    "B-2":   ("neutral",     "General Business"),
    "B-3":   ("neutral",     "Highway Business"),
    "O-1":   ("neutral",     "Office"),
    "I":     ("negative",    "Industrial"),
    "MG":    ("negative",    "Manufacturing General"),
    "ML":    ("negative",    "Manufacturing Light"),
    "MH":    ("restrictive", "Mobile Home"),
    "RD":    ("restrictive", "Residential District"),
    "RD-1":  ("restrictive", "Residential District 1"),
    "RA-1":  ("restrictive", "Residential Agricultural 1"),
    "RA-2":  ("restrictive", "Residential Agricultural 2"),
    "MX-1":  ("positive",    "Mixed Use 1"),
    "MX-2":  ("positive",    "Mixed Use 2"),
    "MX-3":  ("positive",    "Mixed Use 3"),
    "MX-4":  ("positive",    "Mixed Use 4"),
    "MX-5":  ("positive",    "Mixed Use 5"),
    "PJ":    ("neutral",     "Planned Jurisdiction"),
    "PUD":   ("neutral",     "Planned Unit Development"),
    "UNIV":  ("constrained", "University"),
    "INST":  ("constrained", "Institutional"),
    "RA":    ("restrictive", "Residential Agricultural"),
}

# Columbia SC — actual codes from live service (RSF not RS)
_COLUMBIA_SC_ZONE_MAP: dict[str, tuple[str, str]] = {
    "RSF-1":  ("restrictive", "Single-family low density"),
    "RSF-2":  ("restrictive", "Single-family"),
    "RSF-3":  ("restrictive", "Single-family high density"),
    "RM-1":   ("positive",    "Multi-family low density"),
    "RM-2":   ("positive",    "Multi-family medium density"),
    "RM-3":   ("positive",    "Multi-family high density"),
    "RD":     ("neutral",     "Residential Duplex"),
    "RD-MV":  ("neutral",     "Residential Duplex Multi-vehicle"),
    "NAC":    ("neutral",     "Neighborhood Activity Center"),
    "CAC":    ("neutral",     "Community Activity Center"),
    "EC":     ("neutral",     "Employment Center"),
    "MC":     ("positive",    "Mixed Corridor — multi-family viable"),
    "MU-1":   ("positive",    "Mixed Use 1"),
    "MU-2":   ("positive",    "Mixed Use 2"),
    "MU-3":   ("positive",    "Mixed Use 3"),
    "GC":     ("neutral",     "General Commercial"),
    "LC":     ("neutral",     "Limited Commercial"),
    "NC":     ("neutral",     "Neighborhood Commercial"),
    "I":      ("negative",    "Industrial"),
    "IP":     ("negative",    "Industrial Park"),
    "P-1":    ("constrained", "Public/Institutional"),
    "PD":     ("neutral",     "Planned Development"),
}

# Columbus OH — actual codes from live service (no hyphens)
_COLUMBUS_ZONE_MAP: dict[str, tuple[str, str]] = {
    "R2F":    ("neutral",     "Two-family residential"),
    "R3":     ("neutral",     "Three-family residential"),
    "R4":     ("neutral",     "Four-family residential"),
    "AR1":    ("positive",    "Apartment Residential 1 — low density"),
    "AR2":    ("positive",    "Apartment Residential 2"),
    "AR3":    ("positive",    "Apartment Residential 3 — high density"),
    "AR4":    ("positive",    "Apartment Residential 4 — highest density"),
    "UCT":    ("neutral",     "Urban Commercial Transitional"),
    "UCR":    ("neutral",     "Urban Commercial Residential"),
    "UGN-1":  ("neutral",     "Urban General Neighborhood"),
    "UGN-2":  ("neutral",     "Urban General Neighborhood 2"),
    "C4":     ("neutral",     "Commercial 4"),
    "C3":     ("neutral",     "Commercial 3"),
    "C2":     ("neutral",     "Commercial 2"),
    "C1":     ("neutral",     "Commercial 1"),
    "LUCRPD": ("neutral",     "Land Use Commercial Residential Planned Dev"),
    "SR":     ("restrictive", "Single Residence"),
    "LR":     ("restrictive", "Limited Residence"),
    "RMF":    ("positive",    "Residential Multi-Family"),
    "M1":     ("negative",    "Manufacturing 1"),
    "M2":     ("negative",    "Manufacturing 2"),
    "M3":     ("negative",    "Manufacturing 3"),
    "I":      ("constrained", "Institutional"),
    "PD":     ("neutral",     "Planned Development"),
    "CBD":    ("positive",    "Central Business District"),
    "R1":     ("restrictive", "Residential 1 — single family"),
    "R2":     ("neutral",     "Residential 2"),
    "R3":     ("neutral",     "Residential 3"),
    "RURAL":  ("restrictive", "Rural"),
    "RRR":    ("restrictive", "Rural Residential Reserve"),
    "RAC":    ("neutral",     "Residential Arterial Corridor"),
    "P1":     ("constrained", "Park 1 / Public Park"),
    "LP1":    ("constrained", "Limited Park 1"),
    "LM":     ("negative",    "Light Manufacturing"),
    "LM2":    ("negative",    "Light Manufacturing 2"),
    "LAR1":   ("restrictive", "Limited Apartment Residential 1"),
    "LAR12":  ("restrictive", "Limited Apartment Residential 1-2"),
    "LARLD":  ("restrictive", "Limited Apartment Residential Low Density"),
}

# East Lansing MI — actual codes from live service
_EAST_LANSING_ZONE_MAP: dict[str, tuple[str, str]] = {
    "U":           ("constrained", "University — MSU institutional land"),
    "R1":          ("restrictive", "Single-family"),
    "R2":          ("neutral",     "Two-family / moderate residential"),
    "R3":          ("positive",    "Multi-family"),
    "RM08":        ("positive",    "Residential Multi — 8 units/acre"),
    "RM14":        ("positive",    "Residential Multi — 14 units/acre"),
    "RM22":        ("positive",    "Residential Multi — 22 units/acre"),
    "RM32":        ("positive",    "Residential Multi — 32 units/acre"),
    "EAST VILLAGE":("positive",    "East Village mixed-use district"),
    "B1":          ("neutral",     "General Office Business"),
    "B2":          ("neutral",     "Retail Business"),
    "B3":          ("neutral",     "City Center Commercial"),
    "B4":          ("neutral",     "Restricted Office Business"),
    "B5":          ("neutral",     "Community Retail"),
    "C":           ("constrained", "Community Facilities"),
    "RA":          ("constrained", "Restricted Area"),
    "M1":          ("negative",    "Manufacturing"),
    "OIP":         ("neutral",     "Office Industrial Park"),
}

# College Station TX — Description field returns FULL TEXT, not codes
_COLLEGE_STATION_ZONE_MAP: dict[str, tuple[str, str]] = {
    "General Commercial":           ("neutral",     ""),
    "General Suburban":             ("restrictive", "Single-family suburban"),
    "High Density Multi-Family":    ("positive",    ""),
    "Multi-Family":                 ("positive",    ""),
    "Middle Housing":               ("neutral",     "Transitional density"),
    "Planned Development District": ("neutral",     ""),
    "Office":                       ("neutral",     ""),
    "Townhouse":                    ("positive",    ""),
    "Duplex":                       ("neutral",     ""),
    "Light Commercial":             ("neutral",     ""),
    "Commercial Industrial":        ("negative",    ""),
    "College and University":       ("constrained", ""),
    "Single-Family Residential":    ("restrictive", ""),
    "Restricted Suburban":          ("restrictive", ""),
    "Natural Areas Protected":      ("constrained", ""),
    "Business Park":                ("neutral",     ""),
    "Wellborn Commercial":          ("neutral",     ""),
    "Northgate":                    ("positive",    "Mixed-use near A&M"),
    "Core Northgate":               ("positive",    "Core Northgate mixed-use district"),
    "Transitional Northgate":       ("positive",    "Transitional Northgate"),
    "Residential Northgate":        ("positive",    "Residential Northgate"),
    "Wolf Pen Creek":               ("neutral",     ""),
    "Wolf Pen Creek Dev Corridor":  ("neutral",     "Wolf Pen Creek development corridor"),
    "Redevelopment District":       ("positive",    "Redevelopment district"),
    "Planned Mixed-Use Development":("positive",    "Planned mixed-use development"),
    "Neighborhood Conservation":    ("restrictive", "Neighborhood conservation — infill rules"),
    "Neighborhood Prevaling Overlay":("restrictive","Neighborhood Prevailing Overlay"),
    "Corridor Overlay":             ("neutral",     "Corridor Overlay"),
    "Rural":                        ("restrictive", "Rural"),
}

# State College PA — actual codes from live service
_STATE_COLLEGE_ZONE_MAP: dict[str, tuple[str, str]] = {
    "R1":  ("restrictive", "Low Density Residential"),
    "R2":  ("neutral",     "Medium Density Residential"),
    "R3":  ("positive",    "High Density Residential"),
    "R3B": ("positive",    "High Density Residential B"),
    "R4":  ("positive",    "High Density Multi-family"),
    "RO":  ("neutral",     "Residential-Office"),
    "H":   ("constrained", "Historic/Conservation district"),
    "B1":  ("neutral",     "Business"),
    "B2":  ("neutral",     "Business 2"),
    "C":   ("neutral",     "Commercial"),
    "CP2": ("neutral",     "Commercial Plaza 2"),
    "CG":  ("neutral",     "Commercial General"),
    "CID": ("positive",    "Commercial Incentive District — mixed use"),
    "HC":  ("neutral",     "Highway Commercial"),
    "I-1": ("negative",    "Industrial"),
    "IO":  ("negative",    "Industrial Overlay"),
    "UV":  ("positive",    "Urban Village — mixed use"),
    "UPD": ("constrained", "University Planned Development"),
    "PK":  ("constrained", "Parking"),
    "PA":  ("constrained", "Parking Authority"),
    "P":   ("constrained", "Public/Open Space"),
    "PO":  ("constrained", "Public/Open Space"),
    "SB":  ("constrained", "Stream Buffer"),
}

# Bloomington IN — actual codes from live service (UDO zones)
_BLOOMINGTON_ZONE_MAP: dict[str, tuple[str, str]] = {
    "RM":    ("positive",    "Residential Multi-family"),
    "RH":    ("positive",    "Residential High density"),
    "R4":    ("positive",    "Residential 4 — multi-family"),
    "R3":    ("neutral",     "Residential 3 — medium density"),
    "R1":    ("restrictive", "Residential 1 — single-family"),
    "MN":    ("positive",    "Mixed-use Neighborhood"),
    "MC":    ("positive",    "Mixed-use Community"),
    "MS":    ("positive",    "Mixed-use Station area"),
    "ME":    ("neutral",     "Mixed-use Employment"),
    "R2":    ("neutral",     "Residential 2 — two-family"),
    "PO":    ("neutral",     "Professional Office"),
    "PUD":   ("neutral",     "Planned Unit Development"),
    # MD-* = Mixed-use District codes (various sub-districts)
    "MD-DE": ("positive",    "Mixed-use District — Downtown East"),
    "MD-DG": ("positive",    "Mixed-use District — Downtown General"),
    "MD-ST": ("positive",    "Mixed-use District — Station"),
    "MD-UV": ("positive",    "Mixed-use District — University Village"),
    "MD-DC": ("positive",    "Mixed-use District — Downtown Core"),
    "MD-CS": ("positive",    "Mixed-use District — Community Scale"),
    "MM":    ("negative",    "Mixed Manufacturing"),
    "MI":    ("negative",    "Mixed Industrial"),
    "PF":    ("constrained", "Public Facility"),
}

# Lexington KY — actual codes (R-1T, R-1D, R-1E variants)
_LEXINGTON_ZONE_MAP: dict[str, tuple[str, str]] = {
    "A-1":  ("restrictive", "Agricultural"),
    "A-2":  ("restrictive", "Agricultural-Residential"),
    "R-1A": ("restrictive", "Single-family large lot"),
    "R-1B": ("restrictive", "Single-family"),
    "R-1C": ("restrictive", "Single-family small lot"),
    "R-1D": ("restrictive", "Single-family"),
    "R-1E": ("restrictive", "Single-family"),
    "R-1T": ("restrictive", "Single-family transitional"),
    "R-2":  ("neutral",     "Low-density multi-family"),
    "R-3":  ("neutral",     "Multi-family low — conditional PBSH"),
    "R-4":  ("neutral",     "Medium-density residential"),
    "R-5":  ("positive",    "High-density multi-family"),
    "B-1":  ("neutral",     "Neighborhood Business"),
    "B-2":  ("neutral",     "Neighborhood Business 2"),
    "B-2A": ("neutral",     "Business 2A"),
    "B-3":  ("neutral",     "General Business"),
    "B-4":  ("neutral",     "Highway Business"),
    "B-5":  ("neutral",     "General Business Service"),
    "B-6":  ("neutral",     "General Retail"),
    "B-6P": ("neutral",     "Planned General Retail"),
    "I-1":  ("negative",    "Light Industrial"),
    "I-2":  ("negative",    "General Industrial"),
    "EP":   ("negative",    "Extractive Production"),
    "P-1":  ("neutral",     "Professional Office"),
    "P-2":  ("neutral",     "General Professional"),
    "RM":   ("positive",    "Residential Mixed"),
    "PD":   ("neutral",     "Planned Development"),
}

# Starkville MS — actual codes (Form Based Code + MDU zones)
_STARKVILLE_ZONE_MAP: dict[str, tuple[str, str]] = {
    "S-E":   ("restrictive", "Suburban Estate"),
    "S-1":   ("restrictive", "Suburban Standard"),
    "S-2":   ("neutral",     "Suburban Mixed"),
    "TN-E":  ("restrictive", "Traditional Neighborhood Estate"),
    "TN-1":  ("restrictive", "Traditional Neighborhood 1"),
    "T-3":   ("neutral",     "Transitional Neighborhood"),
    "T-4":   ("neutral",     "Traditional Neighborhood"),
    "T-4U":  ("positive",    "Traditional Neighborhood Urban — mixed use"),
    "T-5C":  ("neutral",     "Urban Core Commercial"),
    "T-5U":  ("positive",    "Urban Core — mixed use"),
    "T-5D":  ("positive",    "Urban Core Downtown"),
    "T-6":   ("positive",    "Downtown Core"),
    "MDU-9": ("positive",    "Multi-Dwelling Unit — 9 units/acre"),
    "MDU-20":("positive",    "Multi-Dwelling Unit — 20 units/acre"),
    "SD-2":  ("neutral",     "Special District 2"),
    "SD-6":  ("neutral",     "Special District 6"),
    "C":     ("neutral",     "Commercial"),
    "C-S":   ("neutral",     "Commercial Special"),
    "I-1":   ("negative",    "Light Industrial"),
    "I-2":   ("negative",    "General Industrial"),
    "U":     ("constrained", "University District"),
    "PUD":   ("neutral",     "Planned Unit Development"),
}

# Tempe AZ — may fail with 403 (Cloudflare); handled gracefully
_TEMPE_ZONE_MAP: dict[str, tuple[str, str]] = {
    "R1-6":  ("restrictive", "Single-family"),
    "R1-7":  ("restrictive", "Single-family"),
    "R1-8":  ("restrictive", "Single-family"),
    "R1-9":  ("restrictive", "Single-family"),
    "R2":    ("neutral",     "Two-family"),
    "R3":    ("positive",    "Multi-family low"),
    "R4":    ("positive",    "Multi-family high"),
    "PAD":   ("neutral",     "Planned Area Development"),
    "PUD":   ("neutral",     "Planned Unit Development"),
    "NCO":   ("neutral",     "Neighborhood Commercial Office"),
    "MU":    ("positive",    "Mixed Use"),
    "GC":    ("neutral",     "General Commercial"),
    "O":     ("neutral",     "Office"),
    "I-1":   ("negative",    "Light Industrial"),
    "I-2":   ("negative",    "General Industrial"),
    "IRI":   ("negative",    "Industrial Research"),
    "ASU":   ("constrained", "Arizona State University"),
    "OS":    ("constrained", "Open Space"),
}

# ── GIS endpoint registry ─────────────────────────────────────────────────────

_VT_CONFIG = {
    "url": "https://tobmaps.blacksburg.gov/server/rest/services/Planning/TownZoningLayers/MapServer/8/query",
    "code_field": "Labels",
    "label_field": "Zoning",
    "zone_map": _BLACKSBURG_ZONE_MAP,
    "signal_patterns": [("RM-", "positive"), ("R-", "restrictive")],
}

_UVA_CONFIG = {
    "url": "https://services.arcgis.com/f4rR7WnIfGBdVYFd/arcgis/rest/services/Zoning_Districts/FeatureServer/0/query",
    "code_field": "ZONE",
    "label_field": "ZONE",
    # Server CRS mismatch with lat/lng bbox — fetch all 1120 features, filter client-side
    "no_spatial_filter": True,
    "zone_map": _CHARLOTTESVILLE_ZONE_MAP,
    "signal_patterns": [("GU-", "positive"), ("MF", "positive"), ("RE-", "restrictive"), ("RA-", "restrictive"), ("SF-", "restrictive"), ("RF-", "constrained"), ("LI", "negative"), ("HI", "negative")],
}

_UTK_CONFIG = {
    "url": "https://services1.arcgis.com/QWaOgwdmpqI9HUzf/arcgis/rest/services/KnoxvilleKnoxCountyZoning/FeatureServer/2/query",
    "code_field": "ZONE1",
    "label_field": "ZONE1",
    "zone_map": _KNOXVILLE_ZONE_MAP,
    "signal_patterns": [("RN-6", "positive"), ("RN-5", "neutral"), ("RN-", "restrictive"), ("DK-", "positive"), ("I-", "negative"), ("C-", "neutral")],
}

_UNC_CONFIG = {
    "url": "https://gis-portal.townofchapelhill.org/server/rest/services/OpenData/Zoning_Districts/MapServer/0/query",
    "code_field": "ZONING",
    "label_field": "NAME",
    "zone_map": _CHAPEL_HILL_ZONE_MAP,
    "signal_patterns": [("TC-", "positive"), ("R-4", "positive"), ("R-5", "positive"), ("R-6", "positive"), ("R-3", "neutral"), ("R-1", "restrictive"), ("R-2", "restrictive"), ("OI-", "neutral")],
}

_UGA_CONFIG = {
    "url": "https://enigma.accgov.com/server/rest/services/Parcel_Zoning_Types/FeatureServer/0/query",
    "code_field": "CurrentZn",
    "label_field": "CurrentZn",
    "zone_map": _ATHENS_ZONE_MAP,
    "signal_patterns": [("RM-", "positive"), ("RS-", "restrictive"), ("I-", "negative"), ("C-", "neutral")],
}

_NCSTATE_CONFIG = {
    "url": "https://maps.raleighnc.gov/arcgis/rest/services/Planning/Zoning/MapServer/0/query",
    "code_field": "ZONE_TYPE",
    "label_field": "ZONE_TYPE_DECODE",
    "zone_map": _RALEIGH_ZONE_MAP,
    # Raleigh appends "-" to codes (e.g. "OX-"); _get_pbsh_signal strips it
    "signal_patterns": [("DX", "positive"), ("RX", "positive"), ("NX", "positive"), ("MX", "positive"), ("IX", "negative"), ("OX", "neutral"), ("CX", "neutral"), ("R-10", "positive"), ("R-6", "neutral"), ("R-4", "restrictive"), ("R-2", "restrictive"), ("R-1", "restrictive"), ("IL", "negative"), ("IH", "negative")],
}

_ALABAMA_CONFIG = {
    "url": "https://services1.arcgis.com/DADyRNMb7tdzKmmq/arcgis/rest/services/Tuscaloosa_City_Zoning/FeatureServer/3/query",
    "code_field": "zone_class",
    "label_field": "zone_descript",
    "zone_map": _TUSCALOOSA_ZONE_MAP,
    "signal_patterns": [("RMF-", "positive"), ("R-1", "restrictive"), ("R-2", "restrictive"), ("R-3", "restrictive"), ("R-4", "neutral"), ("B", "neutral"), ("MG", "negative"), ("ML", "negative"), ("I", "negative")],
}

_USC_CONFIG = {
    "url": "https://gis.columbiasc.gov/cola/rest/services/Public/CoCInfoLand/MapServer/2/query",
    "code_field": "ZoningDistrict",
    "label_field": "ZoningDescription",
    "zone_map": _COLUMBIA_SC_ZONE_MAP,
    "signal_patterns": [("RSF-", "restrictive"), ("RM-", "positive"), ("MU-", "positive"), ("MC", "positive"), ("EC", "neutral"), ("NAC", "neutral"), ("CAC", "neutral"), ("GC", "neutral"), ("I", "negative")],
}

_OSU_CONFIG = {
    "url": "https://gis.columbus.gov/arcgis/rest/services/Applications/Zoning/MapServer/20/query",
    "code_field": "CLASSIFICATION",
    "label_field": "GENERAL_ZONING_CATEGORY",
    "zone_map": _COLUMBUS_ZONE_MAP,
    "signal_patterns": [("AR", "positive"), ("R2F", "neutral"), ("R3", "neutral"), ("R4", "neutral"), ("RMF", "positive"), ("SR", "restrictive"), ("LR", "restrictive"), ("UC", "neutral"), ("CBD", "positive"), ("M", "negative"), ("C", "neutral")],
}

_MSU_CONFIG = {
    # HTTPS required — HTTP returns proxy error
    "url": "https://gis2.cityofeastlansing.com/arcgis/rest/services/ZONING/MapServer/1/query",
    "code_field": "ZONING",
    "label_field": "ZONING",
    "zone_map": _EAST_LANSING_ZONE_MAP,
    "signal_patterns": [("RM", "positive"), ("R3", "positive"), ("R2", "neutral"), ("R1", "restrictive"), ("B", "neutral"), ("M1", "negative")],
}

_TAMU_CONFIG = {
    "url": "https://gis.cstx.gov/csgis/rest/services/_OpenData/OpenData_PDS/MapServer/17/query",
    "code_field": "Description",
    "label_field": "Description",
    # Full-text descriptions — zone_map keys are exact description strings
    "zone_map": _COLLEGE_STATION_ZONE_MAP,
    "signal_patterns": [
        ("High Density", "positive"), ("Multi-Family", "positive"), ("Townhouse", "positive"),
        ("Northgate", "positive"), ("Duplex", "neutral"), ("Office", "neutral"),
        ("Commercial", "neutral"), ("Industrial", "negative"), ("Suburban", "restrictive"),
        ("Single-Family", "restrictive"),
    ],
}

_PSU_CONFIG = {
    "url": "https://services8.arcgis.com/5EsWsFkU1FzqtfTb/arcgis/rest/services/Zoning_Overlay/FeatureServer/3/query",
    "code_field": "Symbol",
    "label_field": "Zoning",
    "zone_map": _STATE_COLLEGE_ZONE_MAP,
    "signal_patterns": [("UV", "positive"), ("CID", "positive"), ("R3", "positive"), ("R4", "positive"), ("R2", "neutral"), ("R1", "restrictive"), ("B", "neutral"), ("C", "neutral"), ("I", "negative"), ("P", "constrained"), ("U", "constrained")],
}

_IU_CONFIG = {
    "url": "https://bloomington.in.gov/arcgis-server/rest/services/DataPortal/DataPortal_PlanningZoning/MapServer/1/query",
    # SDE-prefixed field — try full name first, then short alias
    "code_field": "geodb.sde.ZoningDistricts.zone_code",
    "code_field_alt": "zone_code",
    "label_field": "geodb.sde.ZoningDistricts.zone_description",
    "zone_map": _BLOOMINGTON_ZONE_MAP,
    "signal_patterns": [("RM", "positive"), ("RH", "positive"), ("MN", "positive"), ("MC", "positive"), ("MS", "positive"), ("ME", "neutral"), ("R4", "positive"), ("R2", "neutral"), ("MM", "negative"), ("MI", "negative"), ("PF", "constrained"), ("PO", "neutral")],
}

_UK_CONFIG = {
    "url": "https://services1.arcgis.com/Mg7DLdfYcSWIaDnu/arcgis/rest/services/Zoning/FeatureServer/0/query",
    "code_field": "ZONING",
    "label_field": "ZONING",
    "zone_map": _LEXINGTON_ZONE_MAP,
    "signal_patterns": [("R-5", "positive"), ("R-4", "neutral"), ("R-3", "neutral"), ("R-2", "neutral"), ("R-1", "restrictive"), ("A-", "restrictive"), ("B-", "neutral"), ("I-", "negative")],
}

_MSSTATE_CONFIG = {
    "url": "https://services1.arcgis.com/RTaez8fHeIiDRbgb/arcgis/rest/services/Zoning_District/FeatureServer/0/query",
    "code_field": "Zoning",
    "label_field": "Zoning",
    "zone_map": _STARKVILLE_ZONE_MAP,
    "signal_patterns": [("MDU-", "positive"), ("T-5D", "positive"), ("T-5U", "positive"), ("T-6", "positive"), ("T-4U", "positive"), ("T-5C", "neutral"), ("T-4", "neutral"), ("T-3", "neutral"), ("T-", "neutral"), ("TN-", "restrictive"), ("S-E", "restrictive"), ("S-", "restrictive"), ("I-", "negative")],
}

# Boise ID — actual codes from services1.arcgis.com layer 191
# Overlay suffixes (/DA, /HD-O, /CD-O, /NC-O, /BC-O, /SC-O, /AI-O) stripped by _get_pbsh_signal
_BOISE_ZONE_MAP: dict[str, tuple[str, str]] = {
    "A-1":  ("restrictive", "Rural Residential / Agricultural"),
    "A-2":  ("restrictive", "Large Lot Agricultural"),
    "R-1A": ("restrictive", "Single-Family Low Density"),
    "R-1B": ("restrictive", "Single-Family Medium Density"),
    "R-1C": ("restrictive", "Single-Family Compact"),
    "R-2":  ("neutral",     "Medium-Density Residential — duplexes / townhomes"),
    "R-3":  ("positive",    "Multi-Family Residential"),
    "MX-1": ("neutral",     "Mixed-Use Neighborhood"),
    "MX-2": ("positive",    "Mixed-Use Community"),
    "MX-3": ("positive",    "Mixed-Use Urban"),
    "MX-4": ("positive",    "Mixed-Use Downtown"),
    "MX-5": ("positive",    "Mixed-Use High Intensity"),
    "MX-H": ("positive",    "Mixed-Use High Rise"),
    "MX-U": ("positive",    "Mixed-Use University"),
    "I-1":  ("negative",    "Limited Industrial"),
    "I-2":  ("negative",    "General Industrial"),
    "I-3":  ("negative",    "Heavy Industrial"),
    "SP-01":("constrained", "Special Purpose 01"),
    "SP-02":("constrained", "Special Purpose 02"),
    "SP-03":("constrained", "Special Purpose 03"),
    "SP-04":("constrained", "Special Purpose 04"),
}

_BSU_CONFIG = {
    "url": "https://services1.arcgis.com/WHM6qC35aMtyAAlN/arcgis/rest/services/BoiseZoning/FeatureServer/191/query",
    "code_field": "ZONING",
    "label_field": "ZONING",
    "zone_map": _BOISE_ZONE_MAP,
    "signal_patterns": [("MX-", "positive"), ("R-3", "positive"), ("R-2", "neutral"), ("R-1", "restrictive"), ("A-", "restrictive"), ("I-", "negative"), ("SP-", "constrained")],
}

_ASU_CONFIG = {
    "url": "https://gis.tempe.gov/arcgis/rest/services/Open_Data/Zoning_Districts/FeatureServer/0/query",
    "code_field": "ZONING_DISTRICT",
    "code_field_alt": "ZoningDistrict",
    "label_field": "LONG_NAME",
    "zone_map": _TEMPE_ZONE_MAP,
    "signal_patterns": [("R3", "positive"), ("R4", "positive"), ("MU", "positive"), ("R2", "neutral"), ("R1", "restrictive"), ("PAD", "neutral"), ("PUD", "neutral"), ("I-", "negative"), ("GC", "neutral"), ("O", "neutral")],
}

_GIS_CONFIGS: dict[str, dict] = {
    # Virginia Tech
    "virginia polytechnic institute and state university": _VT_CONFIG,
    "virginia tech": _VT_CONFIG,

    # University of Virginia
    "university of virginia": _UVA_CONFIG,
    "university of virginia main campus": _UVA_CONFIG,

    # University of Tennessee Knoxville
    "university of tennessee knoxville": _UTK_CONFIG,
    "university of tennessee": _UTK_CONFIG,

    # UNC Chapel Hill
    "university of north carolina chapel hill": _UNC_CONFIG,
    "university of north carolina at chapel hill": _UNC_CONFIG,

    # University of Georgia
    "university of georgia": _UGA_CONFIG,

    # NC State
    "north carolina state university": _NCSTATE_CONFIG,
    "north carolina state university at raleigh": _NCSTATE_CONFIG,

    # University of Alabama
    "university of alabama": _ALABAMA_CONFIG,

    # University of South Carolina
    "university of south carolina": _USC_CONFIG,
    "university of south carolina columbia": _USC_CONFIG,

    # Ohio State University
    "ohio state university": _OSU_CONFIG,
    "ohio state university main campus": _OSU_CONFIG,
    "the ohio state university": _OSU_CONFIG,

    # Michigan State University
    "michigan state university": _MSU_CONFIG,

    # Texas A&M University
    "texas a&m university": _TAMU_CONFIG,

    # Pennsylvania State University
    "pennsylvania state university": _PSU_CONFIG,
    "pennsylvania state university main campus": _PSU_CONFIG,
    "penn state university": _PSU_CONFIG,

    # Indiana University Bloomington
    "indiana university bloomington": _IU_CONFIG,

    # University of Kentucky
    "university of kentucky": _UK_CONFIG,

    # Mississippi State University
    "mississippi state university": _MSSTATE_CONFIG,

    # Boise State University
    "boise state university": _BSU_CONFIG,

    # Arizona State University (Tempe) — may get 403; fails gracefully
    "arizona state university": _ASU_CONFIG,
}

LAYER_DATA_VERSION = "zoning_gis_v5_17schools_final_2026"

# In-memory cache keyed by (uni_name, rounded_lat, rounded_lng, radius_miles)
_CACHE: dict[tuple, list[dict]] = {}


class ZoneFeature(TypedDict):
    zone_code: str
    zone_label: str
    pbsh_signal: str                               # positive|neutral|restrictive|constrained|negative
    polygon_rings: list[list[tuple[float, float]]] # outer + inner rings, each (lat, lng)


def _normalize_name(name: str) -> str:
    return " ".join(name.strip().lower().replace("-", " ").split())


def _bbox_envelope(lat: float, lng: float, radius_miles: float) -> str:
    dlat = radius_miles / 69.0
    dlng = radius_miles / max(1e-6, 69.172 * max(0.2, abs(math.cos(math.radians(lat)))))
    return f"{lng - dlng},{lat - dlat},{lng + dlng},{lat + dlat}"


def _parse_geojson_rings(geometry: dict) -> list[list[tuple[float, float]]]:
    gtype = geometry.get("type", "")
    coords = geometry.get("coordinates", [])
    rings: list[list[tuple[float, float]]] = []
    if gtype == "Polygon":
        for ring in coords:
            rings.append([(float(pt[1]), float(pt[0])) for pt in ring if len(pt) >= 2])
    elif gtype == "MultiPolygon":
        for polygon in coords:
            for ring in polygon:
                rings.append([(float(pt[1]), float(pt[0])) for pt in ring if len(pt) >= 2])
    return [r for r in rings if len(r) >= 3]


def _get_pbsh_signal(zone_code: str, config: dict) -> str:
    """Exact lookup → strip trailing '-'/overlay suffix → prefix patterns."""
    zone_map: dict = config.get("zone_map", {})

    result = zone_map.get(zone_code)
    if result:
        return result[0]

    # Raleigh (and similar) appends trailing "-" to codes (e.g. "OX-")
    stripped = zone_code.rstrip("- ")
    if stripped != zone_code:
        result = zone_map.get(stripped)
        if result:
            return result[0]

    # Charlottesville (and similar) uses overlay suffixes like "GC/GWP", "RR/WS"
    # Strip everything from "/" onward and look up the base code
    if "/" in zone_code:
        base = zone_code.split("/")[0]
        result = zone_map.get(base)
        if result:
            return result[0]
        # Also try stripped base
        base_stripped = base.rstrip("- ")
        if base_stripped != base:
            result = zone_map.get(base_stripped)
            if result:
                return result[0]

    for prefix, signal in config.get("signal_patterns", []):
        if zone_code.startswith(prefix):
            return signal

    return "unknown"


async def fetch_zoning_polygons(
    lat: float,
    lng: float,
    radius_miles: float,
    university_name: str,
) -> list[ZoneFeature]:
    """Fetch zoning polygons around campus from the city GIS.

    Returns empty list if university has no config or service is unreachable.
    Never raises — callers treat empty list as "no data."
    Results are cached in-memory per (university, location, radius).
    """
    config = _GIS_CONFIGS.get(_normalize_name(university_name))
    if not config:
        return []

    cache_key = (university_name, round(lat, 3), round(lng, 3), radius_miles)
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    code_field: str = config["code_field"]
    code_field_alt: str | None = config.get("code_field_alt")
    label_field: str = config.get("label_field", code_field)
    no_spatial_filter: bool = config.get("no_spatial_filter", False)

    params: dict = {
        "where": "1=1",
        "outSR": "4326",
        "outFields": f"{code_field},{label_field}",
        "returnGeometry": "true",
        "resultRecordCount": "2000",
        "f": "geojson",
    }
    if not no_spatial_filter:
        params.update({
            "geometry": _bbox_envelope(lat, lng, radius_miles),
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
        })

    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            resp = await client.get(config["url"], params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        print(f"[zoning_gis] fetch failed for {university_name}: {exc}")
        return []

    features: list[ZoneFeature] = []
    for feat in data.get("features", []):
        props = feat.get("properties") or {}
        geom = feat.get("geometry")
        if not geom:
            continue

        raw_code = (props.get(code_field) or "").strip()
        if not raw_code and code_field_alt:
            raw_code = (props.get(code_field_alt) or "").strip()
        if not raw_code:
            continue

        zone_label = (props.get(label_field) or raw_code).strip()
        pbsh_signal = _get_pbsh_signal(raw_code, config)
        rings = _parse_geojson_rings(geom)
        if not rings:
            continue

        features.append(ZoneFeature(
            zone_code=raw_code,
            zone_label=zone_label,
            pbsh_signal=pbsh_signal,
            polygon_rings=rings,
        ))

    print(f"[zoning_gis] {len(features)} zone polygons for {university_name}")
    _CACHE[cache_key] = features
    return features


def has_gis_support(university_name: str) -> bool:
    return _normalize_name(university_name) in _GIS_CONFIGS

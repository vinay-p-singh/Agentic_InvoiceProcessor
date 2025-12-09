"""
Invoice Models - Core data structures for invoice processing with Azure AI Foundry agents
"""

from typing import List
from enum import Enum


class InvoiceCategory(Enum):
    """
    Invoice categories based on 2-step classification:
    1. CapEx vs Revenue/Revex (Revenue and Revex are the same)
    2. Material vs Service vs Service-Connectivity
    """
    CAPEX_MATERIAL = "Capex-Material"
    CAPEX_SERVICE = "Capex-Service"
    REVENUE_MATERIAL = "Revenue-Material"  # Note: Revenue = Revex
    REVENUE_SERVICE = "Revenue-Service"    # Note: Revenue = Revex
    REVENUE_SERVICE_CONNECTIVITY = "Revenue-Service-Connectivity"  # Note: Revenue = Revex


# Field name mappings for reference data lookup consistency
FIELD_NAME_MAPPINGS = {
    "BandWidth": "BandWidth(B/W)"
}


# =============================================================================
# BUSINESS CONSTANTS AND FIELD DEFINITIONS
# =============================================================================

# Confidence scoring thresholds (moved from _get_confidence_from_percentage)
CONFIDENCE_THRESHOLDS = {
    "EXCELLENT": {"threshold": 0.005, "score": 0.98},  # Within 0.5%
    "VERY_GOOD": {"threshold": 0.01, "score": 0.93},   # Within 1%
    "ACCEPTABLE": {"threshold": 0.02, "score": 0.85},  # Within 2%
    "NEEDS_ATTENTION": {"threshold": 0.05, "score": 0.75},  # Within 5%
    "SIGNIFICANT_DIFFERENCE": {"score": 0.50}  # Above 5%
}

# Comparison status thresholds
COMPARISON_STATUS_THRESHOLDS = {
    "MATCHED": 0.95,
    "PARTIALLY_MATCHED": 0.70,
    "MISMATCHED": 0.0
}

# Date comparison confidence scores
DATE_CONFIDENCE_SCORES = {
    "EXACT_MATCH": 1.0,
    "ONE_DAY_OFF": 0.95,  # Possible OCR error in day field
    "WITHIN_WEEK": 0.50,  # Possible month boundary error
    "WITHIN_MONTH": 0.30,  # Possible month error
    "SIGNIFICANT_DIFFERENCE": 0.20  # Major date difference
}

# String similarity adjustments
STRING_SIMILARITY_ADJUSTMENTS = {
    "HIGH_SIMILARITY_BOOST": 0.05,
    "LOW_SIMILARITY_PENALTY": 0.1,
    "CHAR_SIMILARITY_WEIGHT": 0.8,
    "MIN_CHAR_SIMILARITY": 0.2
}

# Field definitions for processing
INVOICE_FIELDS = [
    "InvoiceNumber", "InvoiceDate", "InvoiceServicePeriod",
    "InvoiceBaseAmount", "InvoiceWithTaxAmount", "BuyerGSTNumber",
    "SellerGSTNumber", "CKT_ID", "BandWidth"
]

# Line item fields by category
LINE_ITEM_FIELDS = {
    "CONNECTIVITY": ["LineItemNo", "Product", "HSN_SAC_Code", "Amount"],
    "SERVICE": ["LineItemNo", "Product", "HSN_SAC_Code", "Amount"],
    "MATERIAL": ["LineItemNo", "Product", "Quantity", "UnitPrice", "HSN_SAC_Code", "Amount"]
}

# Amount fields that require special integer-only comparison
AMOUNT_FIELDS = ["invoicebaseamount", "invoicewithtaxamount", "unitprice", "amount"]

# Fields that support prefix/suffix matching for formatting variations
PREFIX_SUFFIX_MATCH_FIELDS = ["invoicenumber", "purchaseordernumber"]

# Prefix/suffix matching confidence score
PREFIX_SUFFIX_CONFIDENCE = 0.9

# Line item field mappings for comparison
LINE_ITEM_FIELD_MAPPINGS = {
    "LineItemNo": "LineItemNo",
    "Product": "Product",
    "Quantity": "Quantity",
    "UnitPrice": "UnitPrice",
    "HSN_SAC_Code": "HSN_SAC_Code",
    "Amount": "Amount"
}


def normalize_field_name(field_name: str) -> str:
    """
    Get canonical field name for reference data lookup.
    
    Handles field name variations between extraction and reference data:
    - BandWidth → BandWidth(B/W)
    
    Args:
        field_name: Field name from extraction
        
    Returns:
        Canonical field name for reference data lookup
    """
    return FIELD_NAME_MAPPINGS.get(field_name, field_name)


def parse_category_string(category_string: str) -> InvoiceCategory:
    """
    Robust category parser with multiple format support.
    
    Handles:
    - Plain strings: "Capex-Material"
    - Structured strings: "CATEGORY: Capex-Material\\nREASONING: ..."
    - Case variations: "CAPEX-MATERIAL", "capex-material"
    - Whitespace issues: " Capex-Material "
    
    Args:
        category_string: Category in any supported format
        
    Returns:
        InvoiceCategory enum value
        
    Raises:
        ValueError: If category is invalid/unsupported
        
    Examples:
        >>> parse_category_string("Capex-Material")
        InvoiceCategory.CAPEX_MATERIAL
        >>> parse_category_string("CATEGORY: Capex-Material\\nREASONING: WBS code...")
        InvoiceCategory.CAPEX_MATERIAL
        >>> parse_category_string("CAPEX-MATERIAL")
        InvoiceCategory.CAPEX_MATERIAL
    """
    import re
    
    # Step 1: Extract category name if structured format
    category_name = category_string.strip()
    if "CATEGORY:" in category_name:
        match = re.search(r'CATEGORY:\s*([^\n]+)', category_name)
        if match:
            category_name = match.group(1).strip()
    
    # Step 2: Normalize whitespace and hyphens
    # Remove extra spaces, ensure single hyphen
    category_name = category_name.strip().replace(" ", "-")
    
    # Step 3: Case-insensitive enum lookup
    for category_enum in InvoiceCategory:
        if category_enum.value.lower() == category_name.lower():
            return category_enum
    
    # Step 4: Fail with helpful error
    valid_values = [c.value for c in InvoiceCategory]
    raise ValueError(
        f"Invalid invoice category: '{category_string}'. "
        f"Must be one of: {valid_values}"
    )


def format_category_for_agent(category: InvoiceCategory, reasoning: str = "") -> str:
    """
    Format category for agent consumption (Step 1 output format).
    
    Args:
        category: InvoiceCategory enum
        reasoning: Optional reasoning text
        
    Returns:
        Formatted string for agent with proper capitalization
        
    Examples:
        >>> format_category_for_agent(InvoiceCategory.CAPEX_MATERIAL, "WBS code indicates CapEx")
        "CATEGORY: Capex-Material\\nREASONING: WBS code indicates CapEx\\nSTATUS: SUCCESS"
        >>> format_category_for_agent(InvoiceCategory.CAPEX_MATERIAL)
        "Capex-Material"
    """
    if reasoning:
        return f"CATEGORY: {category.value}\nREASONING: {reasoning}\nSTATUS: SUCCESS"
    else:
        return category.value  # Plain format


# =============================================================================
# HELPER FUNCTIONS FOR CONSTANTS
# =============================================================================

def get_line_item_fields(category: InvoiceCategory) -> List[str]:
    """
    Get line item fields based on invoice category.
    
    Args:
        category: Invoice category enum
        
    Returns:
        List of line item field names for the category
    """
    if category == InvoiceCategory.REVENUE_SERVICE_CONNECTIVITY:
        return LINE_ITEM_FIELDS["CONNECTIVITY"]
    elif category in [InvoiceCategory.CAPEX_SERVICE, InvoiceCategory.REVENUE_SERVICE]:
        return LINE_ITEM_FIELDS["SERVICE"]
    else:
        return LINE_ITEM_FIELDS["MATERIAL"]


def is_amount_field(field_name: str) -> bool:
    """
    Check if a field requires integer-only comparison (amount fields).
    
    Args:
        field_name: Field name to check
        
    Returns:
        True if field should use integer-only comparison
    """
    return field_name.lower() in AMOUNT_FIELDS


def supports_prefix_suffix_matching(field_name: str) -> bool:
    """
    Check if a field supports prefix/suffix matching for formatting variations.
    
    Args:
        field_name: Field name to check
        
    Returns:
        True if field supports prefix/suffix matching
    """
    return field_name.lower() in PREFIX_SUFFIX_MATCH_FIELDS


def get_comparison_status(match_confidence: float) -> str:
    """
    Convert match confidence to comparison status string.
    
    Args:
        match_confidence: Confidence score (0.0-1.0)
        
    Returns:
        Comparison status string
    """
    if match_confidence >= COMPARISON_STATUS_THRESHOLDS["MATCHED"]:
        return "Matched"
    elif match_confidence >= COMPARISON_STATUS_THRESHOLDS["PARTIALLY_MATCHED"]:
        return "Partially Matched"
    else:
        return "Mismatched"


def get_confidence_from_percentage(diff_percent: float) -> float:
    """
    Convert percentage difference to confidence score using standardized thresholds.
    
    Provides consistent confidence scoring across all numeric field comparisons,
    using centralized business thresholds.
    
    Args:
        diff_percent: Absolute percentage difference (0.0-1.0+)
        
    Returns:
        float: Confidence score based on standardized business thresholds
    """
    thresholds = CONFIDENCE_THRESHOLDS
    
    if diff_percent <= thresholds["EXCELLENT"]["threshold"]:
        return thresholds["EXCELLENT"]["score"]
    elif diff_percent <= thresholds["VERY_GOOD"]["threshold"]:
        return thresholds["VERY_GOOD"]["score"]
    elif diff_percent <= thresholds["ACCEPTABLE"]["threshold"]:
        return thresholds["ACCEPTABLE"]["score"]
    elif diff_percent <= thresholds["NEEDS_ATTENTION"]["threshold"]:
        return thresholds["NEEDS_ATTENTION"]["score"]
    else:
        return thresholds["SIGNIFICANT_DIFFERENCE"]["score"]


def get_date_confidence_from_day_difference(day_diff: int) -> float:
    """
    Private helper: Convert day difference to confidence score using centralized thresholds.
   
    Args:
        day_diff: Absolute difference in days between two dates
       
    Returns:
        float: Confidence score based on day difference
    """
    from .invoice_models import DATE_CONFIDENCE_SCORES
   
    if day_diff == 0:
        return DATE_CONFIDENCE_SCORES["EXACT_MATCH"]
    elif day_diff == 1:
        return DATE_CONFIDENCE_SCORES["ONE_DAY_OFF"]
    elif day_diff <= 7:
        return DATE_CONFIDENCE_SCORES["WITHIN_WEEK"]
    elif day_diff <= 31:
        return DATE_CONFIDENCE_SCORES["WITHIN_MONTH"]
    else:
        return DATE_CONFIDENCE_SCORES["SIGNIFICANT_DIFFERENCE"]
 
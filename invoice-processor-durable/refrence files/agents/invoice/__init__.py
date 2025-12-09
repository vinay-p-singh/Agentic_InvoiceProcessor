"""
Invoice Processing Package - Auto Function Calling Pattern

Following the audit agent pattern with auto function calling.
"""

from .invoice_agent import InvoiceAgent
from .invoice_prompts import InvoicePrompts
from .invoice_models import InvoiceCategory
from .invoice_functions import (
    identify_invoice_category,
    extract_invoice_fields,
    compare_invoice_fields,
    invoice_functions_set
)

__all__ = [
    "InvoiceAgent",
    "InvoicePrompts",
    "InvoiceCategory",
    "identify_invoice_category",
    "extract_invoice_fields",
    "compare_invoice_fields",
    "invoice_functions_set"
]
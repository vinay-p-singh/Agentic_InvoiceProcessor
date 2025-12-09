"""
Invoice Processing Functions for Azure AI Foundry Agent Integration

This module provides a streamlined 3-step invoice processing workflow designed
for Azure AI Foundry agents following the auto function calling pattern.

Public AI Agent Flow (3 Steps):
    1. identify_invoice_category - Business rule-based category classification
    2. extract_invoice_fields - Field extraction with internal prompt retrieval
    3. compare_invoice_fields - Comprehensive validation and comparison

Public AI Agent Flow Note:
    Agentic flow - expects structured dict input, returns structured dict output.
    Category-specific extraction prompts are retrieved internally in step 2 
    (more reliable than separate function call - eliminates prompt loss risk).
    
    Example:
        >>> category = identify_invoice_category(wbs_code="HOCP.MTRV.MT.4A.IT.001")
        >>> attachments = {"FileUrl": "https://example.com/capex Q4.pdf", "FileName": "capex_Q4.pdf"}
        >>> result = extract_invoice_fields(category, attachments)  # Prompt retrieved internally
        >>> result["Invoice"]["InvoiceNumber"]["Value"]
        "CAP-MAT-2024-001"

Private Helper Methods:
    - _calculate_match_confidence - Field matching confidence calculation
    - _extract_reference_values - Reference value extraction from structured data

Architecture: 
- Follows Azure AI Foundry auto function calling pattern (synchronous)
- Uses FunctionTool integration via invoice_functions_set
- Implements agentic programming principles with clean interfaces
- Structured error handling and comprehensive logging
- No JSON parsing/dumping, pure agentic data flow
"""

# Standard library imports
import asyncio
import base64
import json
from datetime import datetime
from typing import Annotated, Any, Callable, Set, Optional
from utilities.logger import get_logger

# Local imports
from .invoice_models import (
    InvoiceCategory, 
    get_confidence_from_percentage,
    get_comparison_status,
    get_line_item_fields,
    is_amount_field,
    supports_prefix_suffix_matching,
    INVOICE_FIELDS,
    PREFIX_SUFFIX_CONFIDENCE,
    get_date_confidence_from_day_difference
)
from .invoice_prompts import InvoicePrompts

# Initialize module logger
logger = get_logger(__name__)


# =============================================================================
# PUBLIC AI AGENT FUNCTIONS (3-Step Workflow)
# =============================================================================

async def identify_invoice_category(
    wbs_code: Annotated[str, "WBS code from Accounting section (e.g., 'HOCP.MTRV.MT.4A.IT.001', 'HORG.24IT.PF.OT.004')"] = "",
    cost_center: Annotated[str, "Cost center from Accounting section (e.g., '610000', '0', '#N/A')"] = "",
    service_confirmation: Annotated[str, "ServiceConfirmationNumber(SC/SES) from Identifiers → Service type"] = "",
    advance_shipment: Annotated[str, "AdvanceShipmentNotice(ASN/IBD) from Identifiers → Material type"] = "",
    ckt_id: Annotated[str, "Circuit ID(CKD_ID) from Invoice section for connectivity services"] = "",
    bandwidth: Annotated[str, "Bandwidth(B/W) from Invoice section for connectivity services"] = ""
) -> str:
    """
    Step 1 of 3: Identify the invoice category based on business rules.
    
    AI Agent Function: Analyzes individual field parameters to classify invoice
    into one of 5 categories (CapEx/Revenue × Material/Service + Connectivity)
    for downstream category-specific processing.
    
    Args:
        wbs_code: WBS code from Accounting section (e.g., 'HOCP.MTRV.MT.4A.IT.001', 'HORG.24IT.PF.OT.004')
        cost_center: Cost center from Accounting section (e.g., '610000', '0', '#N/A')
        service_confirmation: ServiceConfirmationNumber(SC/SES) from Identifiers → Service type
        advance_shipment: AdvanceShipmentNotice(ASN/IBD) from Identifiers → Material type
        ckt_id: Circuit ID for connectivity services
        bandwidth: Bandwidth specification for connectivity services
    
    Returns:
        str: Category classification result in structured text format:
             "CATEGORY: {category}\\nREASONING: {reasoning}\\nSTATUS: SUCCESS|ERROR"
    
    Raises:
        ValueError: If WBS code format is invalid (3rd character must be 'C' or 'R')
    
    Business Rules:
        Step 1 - CapEx vs Revenue/Revex Classification:
        - WBS code 3rd letter: 'C' = CapEx, 'R' = Revenue/Revex (e.g., 'HOCP.*' = CapEx, 'HORG.*' = Revenue/Revex)
        - WBS blank/null + cost center present = Revenue/Revex (business rule)
        - WBS blank/null + cost center blank/null = Revenue/Revex (default)
        
        Step 2 - Material/Service/Connectivity Classification:
        - AdvanceShipmentNotice(ASN/IBD) present → Material type
        - ServiceConfirmationNumber(SC/SES) present → Service type  
        - Revenue Service + CKT_ID + Bandwidth → Connectivity service type
        - Null values: '0', '#N/A', 'NA', blank treated as null
    
    Example:
        >>> result = await identify_invoice_category(
        ...     wbs_code="HOCP.MTRV.MT.4A.IT.001", 
        ...     service_confirmation="SC-2024-001"
        ... )
        >>> print(result)
        CATEGORY: Capex-Service
        REASONING: WBS code 'HOCP.MTRV.MT.4A.IT.001' (3rd letter='C') indicates CapEx; Service type: Service
        STATUS: SUCCESS
    """
    try:
        # Helper function to check if value is null/empty
        def _is_null(value: str) -> bool:
            """Check if value is considered null according to business rules"""
            if not value:
                return True
            value_upper = value.upper().strip()
            return value_upper in ['0', '#N/A', 'NA', '']
        
        # Step 1: Determine CapEx vs Revenue/Revex based on WBS code and cost center
        is_capex = False
        
        if not _is_null(wbs_code):
            # Look for 'C' or 'R' at 3rd character position (index 2) according to business rules
            wbs_upper = wbs_code.upper()
            if len(wbs_upper) >= 3:
                type_char = wbs_upper[2]  # 3rd character (index 2)
                if type_char == 'C':
                    is_capex = True
                elif type_char == 'R':
                    is_capex = False
                else:
                    # 3rd character is neither 'C' nor 'R' - this is an error
                    raise ValueError(f"Invalid WBS code format: '{wbs_code}'. 3rd character must be 'C' (CapEx) or 'R' (Revenue)")
            else:
                # WBS code too short - this is an error
                raise ValueError(f"Invalid WBS code format: '{wbs_code}'. WBS code must be at least 3 characters with 'C' or 'R' at 3rd position")
        else:
            # WBS code is blank/null - check cost center rules
            if not _is_null(cost_center):
                # WBS blank/null + cost center present = Revenue/Revex (business rule)
                is_capex = False
            else:
                # WBS blank/null + cost center blank/null = Revenue/Revex (default)
                is_capex = False
        
        # Step 2: Determine Material/Service/Connectivity Classification
        is_service = False
        is_connectivity = False
        
        # Priority order: ASN/IBD → SC/SES → Connectivity check
        if not _is_null(advance_shipment):
            # AdvanceShipmentNotice(ASN/IBD) present → Material type
            is_service = False
        elif not _is_null(service_confirmation):
            # ServiceConfirmationNumber(SC/SES) present → Service type
            is_service = True
            
            # Check for connectivity: Revenue Service + CKT_ID + Bandwidth → Connectivity service type
            if not is_capex and not _is_null(ckt_id) and not _is_null(bandwidth):
                is_connectivity = True
        else:
            # Default behavior when both are null - default to Material type
            is_service = False
        
        # Determine final category
        if is_capex:
            category = InvoiceCategory.CAPEX_SERVICE if is_service else InvoiceCategory.CAPEX_MATERIAL
        else:  # Revenue/Revex
            if is_connectivity:
                category = InvoiceCategory.REVENUE_SERVICE_CONNECTIVITY
            elif is_service:
                category = InvoiceCategory.REVENUE_SERVICE
            else:
                category = InvoiceCategory.REVENUE_MATERIAL

        
        # Build reasoning based on business rules
        reasoning_parts = []
        
        # 1. CapEx vs Revenue/Revex reasoning
        if not _is_null(wbs_code):
            # Check 3rd character for reasoning
            wbs_upper = wbs_code.upper()
            if len(wbs_upper) >= 3:
                type_char = wbs_upper[2]  # 3rd character (index 2)
                if type_char == 'C':
                    wbs_type = "CapEx"
                    reasoning_parts.append(f"WBS code '{wbs_code}' (3rd letter='{type_char}') indicates {wbs_type}")
                elif type_char == 'R':
                    wbs_type = "Revenue/Revex"
                    reasoning_parts.append(f"WBS code '{wbs_code}' (3rd letter='{type_char}') indicates {wbs_type}")
        else:
            # WBS code is blank/null - apply business rules
            if not _is_null(cost_center):
                reasoning_parts.append(f"WBS code blank/null, cost center '{cost_center}' present → Revenue/Revex (business rule)")
            else:
                reasoning_parts.append("WBS code blank/null, cost center blank/null → Revenue/Revex (business rule default)")
        
        # 2. Material/Service/Connectivity reasoning
        if not _is_null(advance_shipment):
            reasoning_parts.append(f"AdvanceShipmentNotice(ASN/IBD) '{advance_shipment}' present → Material type")
        elif not _is_null(service_confirmation):
            reasoning_parts.append(f"ServiceConfirmationNumber(SC/SES) '{service_confirmation}' present → Service type")
            
            # Check connectivity for Revenue-Service
            if not is_capex and not _is_null(ckt_id) and not _is_null(bandwidth):
                reasoning_parts.append(f"Revenue Service + CKT_ID '{ckt_id}' + Bandwidth '{bandwidth}' → Connectivity service type")
            elif not is_capex and is_service:
                reasoning_parts.append("Revenue Service but missing CKT_ID/Bandwidth → Standard Service type")
        else:
            reasoning_parts.append("No AdvanceShipmentNotice or ServiceConfirmationNumber → default to Material type")
        
        # Use centralized formatter for consistent output
        from .invoice_models import format_category_for_agent
        result_text = format_category_for_agent(category, '; '.join(reasoning_parts))
        
        logger.info(f"Invoice categorized as: {category.value}")
        return result_text
        
    except Exception as e:
        logger.error(f"Error identifying invoice category: {str(e)}")
        return f"CATEGORY: INVALID\nREASONING: {str(e)}\nSTATUS: ERROR"


def _is_empty_line_item(item: dict, category_enum) -> bool:
    """
    Check if all fields in a line item are empty.
    
    Args:
        item: Line item dict with field structure {"FieldName": {"Value": "", "ConfidenceScore": 0.0, ...}}
        category_enum: InvoiceCategory enum to determine which fields to check
        
    Returns:
        True if ALL field Values are empty (empty string or whitespace only), False otherwise
    """
    from .invoice_models import InvoiceCategory
    
    # Get fields to check from centralized definition
    required_fields = get_line_item_fields(category_enum)
    
    # Check if ALL fields are empty
    for field in required_fields:
        if field in item:
            field_data = item[field]
            if isinstance(field_data, dict) and "Value" in field_data:
                value = field_data["Value"]
                # Non-empty value found (not empty string and not just whitespace)
                if value and str(value).strip():
                    return False
    
    # All fields are empty
    return True


async def extract_invoice_fields(
    category: Annotated[str, "Category string in any format (will be parsed to enum internally)"],
    attachments_data: Annotated[dict, "Complete attachments dict with FileUrl (required) and optional FileName"]
) -> dict:
    """
    Step 2 of 3: Extract fields from invoice using category and attachments.
    
    AI Agent Function: Takes category and complete attachment data to perform intelligent 
    field extraction. Gets category-specific extraction prompt INTERNALLY (no separate 
    step needed). Uses DocumentAPI for extraction.
    
    Args:
        category: Invoice category from step 1 (e.g., 'Capex-Material', 'Revenue-Service')
                 Prompt is retrieved internally based on this category
        attachments_data: Complete attachments dict (agentic flow):
                         - FileUrl (required): HTTP URL or local file path to invoice document
                         - FileName (optional): Override filename for the document
                         - FileType (optional): File type hint (defaults to "PDF")
                         - Line items are extracted from this dict structure
                         
                         Note: Filename sanitization (spaces → underscores) happens automatically
                               during FileUrl processing for DocumentAPI compatibility
    
    Returns:
        dict: Invoice/PurchaseOrder structure with Value/ConfidenceScore/FieldStatus format:
              - Invoice section with main invoice fields
              - PurchaseOrder section with PO fields and InvoiceDeliveryLineItems array
    
    Raises:
        ValueError: If attachments_data is not dict, invalid category, or extraction fails
        KeyError: If required FileUrl field missing from attachments_data
        DocumentAPIException: If DocumentAPI fails
        IOError: If FileUrl cannot be accessed or converted to base64
        
    Note:
        Returns structured dict (not JSON string) for agentic workflows.
        FileUrl input is converted to base64 internally for DocumentAPI compatibility.
        Category-specific prompt is retrieved internally (more reliable than separate step).
    
    Example (FileURL format - HTTP):
        >>> category = "Capex-Material"
        >>> attachments = {"FileUrl": "https://example.com/invoice Q4.pdf", "FileName": "capex_invoice.pdf"}
        >>> result = await extract_invoice_fields(category, attachments)
        >>> result["Invoice"]["InvoiceNumber"]["Value"]
        "CAP-MAT-2024-001"
        
    Example (DocumentAPI):
        >>> attachments = {"FileUrl": "https://example.com/invoice with spaces.pdf"}
        >>> result = await extract_invoice_fields(category, attachments)  # Uses DocumentAPI + automatic sanitization
        >>> result["Invoice"]["InvoiceNumber"]["Value"]
        "REAL-INVOICE-001"
    """
    try:
        logger.info(f"Step 2: Starting field extraction for category: {category}")
        logger.info(f"Step 2: Received attachments_data type: {type(attachments_data)}")
        
        # Use centralized parser for robust category extraction
        from .invoice_models import parse_category_string
        category_enum = parse_category_string(category)
        category_name = category_enum.value  # Use canonical value
        logger.info(f"Step 2: Parsed category to enum: {category_name}")
        
        # Get category-specific prompt INTERNALLY (eliminates Step 2 function call risk)
        from .invoice_prompts import get_category_prompt
        category_prompt = get_category_prompt(category_enum)
        
        # Validate that prompt is not empty
        if not category_prompt or len(category_prompt.strip()) == 0:
            error_msg = f"No extraction prompt defined for category: {category_enum.value}. Please check invoice_prompts.py configuration."
            logger.error(f"Step 2: {error_msg}")
            raise ValueError(error_msg)
        
        logger.info(f"Step 2: Retrieved category-specific prompt internally (length: {len(category_prompt)} chars)")
        logger.info(f"Step 2: Using category-specific prompt for extraction")
        
        # Handle Azure AI agent framework string conversion issue
        # Sometimes the AI agent framework converts dict inputs to JSON strings
        if isinstance(attachments_data, str):
            logger.info("Step 2: Converting attachments_data from JSON string to dict")
            try:
                attachments_data = json.loads(attachments_data)
                logger.info("Step 2: Successfully converted attachments_data to dict")
            except json.JSONDecodeError as e:
                logger.error(f"Step 2: Failed to parse attachments_data JSON string: {str(e)}")
                raise ValueError(f"Agent error: attachments_data string is not valid JSON. Got: {attachments_data[:200]}...")
        
        # Validate parameter types after conversion
        if not isinstance(attachments_data, dict):
            logger.error(f"Step 2: attachments_data must be dict object, got {type(attachments_data)}")
            logger.error("Step 2: Agent should pass structured data object, not string")
            raise ValueError(f"Agent error: attachments_data must be dict object with FileUrl. Got {type(attachments_data)}")
        
        logger.info(f"Step 2: attachments_data has keys: {list(attachments_data.keys())}")
        
        # Handle FileUrl format only - convert to base64 internally for DocumentAPI compatibility
        if "FileUrl" in attachments_data:
            # FileUrl approach - convert to base64 for DocumentAPI compatibility
            from sap.file_to_base64_converter import convert_fileurl_to_base64
            from config.configuration import AppConfig
            
            config = AppConfig()
            file_url = attachments_data["FileUrl"]
            provided_filename = attachments_data.get("FileName")
            
            logger.info(f"Step 2.1: Converting FileUrl to base64: {file_url}")
            
            # Filename sanitization (spaces to underscores) happens automatically in convert_fileurl_to_base64()
            # File converter automatically detects URLs vs local paths
            base64_data, filename = convert_fileurl_to_base64(
                file_url, 
                provided_filename
            )
            file_type = attachments_data.get("FileType", "PDF")
            
            logger.info(f"Step 2: FileUrl converted - filename: {filename}, type: {file_type}")
            
        else:
            # Structured invoice data approach (agentic flow)
            filename = "structured_invoice_data.json"
            file_type = "application/json"
            base64_data = "structured_data"  # Mock value for structured data
            logger.info(f"Step 2: Processing structured invoice data with {len(attachments_data)} fields")
        
        # Integration point: category (from step 1) + category_prompt (retrieved internally) + attachments_data
        logger.info("Step 2: Integrating category, prompt (internal), and attachments with DocumentAPI")
        
        # Use DocumentAPI for invoice extraction
        from config.configuration import AppConfig
        config = AppConfig()
        
        logger.info("Step 2: Using DocumentAPI for invoice extraction")
        logger.info(f"Step 2: DocumentAPI endpoint: {config.meka_api_endpoint}")
        
        # Call DocumentAPI for extraction
        extraction_result = await _extract_via_document_api(
            base64_content=base64_data,
            filename=filename,
            category_name=category_name,
            category_prompt=category_prompt
        )
        logger.info("Step 2: DocumentAPI extraction completed successfully")
        
        # Filter out empty line items (Python enforcement - backup to prompt instruction)
        try:
            if extraction_result:
                po_section = extraction_result.get("PurchaseOrder", {})
                line_items = po_section.get("InvoiceDeliveryLineItems", [])
                
                if line_items:
                    original_count = len(line_items)
                    # Filter out line items where ALL fields are empty
                    filtered_items = [
                        item for item in line_items 
                        if not _is_empty_line_item(item, category_enum)
                    ]
                    filtered_count = len(filtered_items)
                    
                    # Update extraction result with filtered line items
                    extraction_result["PurchaseOrder"]["InvoiceDeliveryLineItems"] = filtered_items
                    
                    if original_count != filtered_count:
                        removed_count = original_count - filtered_count
                        logger.info(f"Step 2: Filtered out {removed_count} empty line item(s) - kept {filtered_count} out of {original_count} total")
                    else:
                        logger.info(f"Step 2: All {original_count} line item(s) have data - no empty items filtered")
                else:
                    logger.info("Step 2: No line items to filter")
                
        except Exception as filter_error:
            logger.warning(f"Step 2: Line item filtering failed, continuing with unfiltered data: {str(filter_error)}")
            # Continue with unfiltered data rather than failing the entire extraction
        
        # Return the Invoice/PurchaseOrder structure directly for agentic workflow
        logger.info(f"Step 2: Generated Invoice/PurchaseOrder structure for {category}")

        # Safety check before accessing dict keys
        if extraction_result and isinstance(extraction_result, dict):
            invoice_count = len(extraction_result.get('Invoice', {}))
            po_count = len(extraction_result.get('PurchaseOrder', {}))
            logger.info(f"Invoice fields: {invoice_count}")
            logger.info(f"PurchaseOrder fields: {po_count}")
        else:
            logger.warning(f"Step 2: extraction_result structure validation skipped (type: {type(extraction_result)})")
 
        return extraction_result
        
    except Exception as e:
        logger.error(f"Error extracting invoice fields: {str(e)}")
        # Agentic flow - raise error instead of returning error dict
        raise


async def compare_invoice_fields(
    extraction_results: Annotated[dict, "Extraction results from step 2 with Invoice/PurchaseOrder structure"],
    reference_data: Annotated[dict, "Complete structured data(original User input for agnet) (except Accounting, Identifiers and attachments section) containing reference SAP values"]
) -> dict:
    """
    Step 3 of 3: Compare extracted fields with reference values and generate validation results.
    
    AI Agent Function: Takes extraction results from step 2 and user input to generate 
    complete validation with ExtractedInvoiceValue/ExtractConfidenceScore/ReferenceSAPValue/
    MatchConfidenceScore/ComparisonStatus structure.
    
    Args:
        extraction_results: Dict from extract_invoice_fields (step 3) with Invoice/PurchaseOrder structure
        reference_data: Structured data containing Invoice and PurchaseOrder sections with reference SAP values
    
    Returns:
        dict: Validation results in Invoice/PurchaseOrder structure with comparison fields:
              - ExtractedInvoiceValue: Value from OCR extraction
              - ExtractConfidenceScore: OCR extraction confidence (0.0-1.0) 
              - ReferenceSAPValue: Reference value from user input
              - MatchConfidenceScore: Match confidence between extracted and reference (0.0-1.0)
              - ComparisonStatus: "Matched", "Mismatched", or "Missing"
    
    Note:
        InvoiceServicePeriod (from extraction) is compared against PurchaseOrderPeriod (from reference input)
        to validate that the invoice service period matches the PO's authorized period.
    
    Example:
        >>> extraction = {"Invoice": {"InvoiceNumber": {"Value": "INV-001", "ConfidenceScore": 0.98}}}
        >>> reference_data = {"Invoice": {"InvoiceNumber": "INV-001", "InvoiceBaseAmount": "1000.00"}}
        >>> result = await compare_invoice_fields(extraction, reference_data)
        >>> result["Invoice"]["InvoiceNumber"]["ComparisonStatus"]
        "Matched"
    """
    try:
        logger.info("Step 3: Starting field comparison with new structure")
        logger.info(f"Step 3: Received extraction_results type: {type(extraction_results)}")
        logger.info(f"Step 3: Received reference_data type: {type(reference_data)}")
        
        # Handle Azure AI agent framework string conversion issue
        # Sometimes the AI agent framework converts dict returns to JSON strings
        if isinstance(extraction_results, str):
            logger.info("Step 3: Converting extraction_results from JSON string to dict")
            try:
                extraction_results = json.loads(extraction_results)
                logger.info("Step 3: Successfully converted extraction_results to dict")
            except json.JSONDecodeError as e:
                logger.error(f"Step 3: Failed to parse extraction_results JSON string: {str(e)}")
                raise ValueError(f"Agent error: extraction_results string is not valid JSON. Got: {extraction_results[:200]}...")
        
        if isinstance(reference_data, str):
            logger.info("Step 3: Converting reference_data from JSON string to dict")
            try:
                reference_data = json.loads(reference_data)
                logger.info("Step 3: Successfully converted reference_data to dict")
            except json.JSONDecodeError as e:
                logger.error(f"Step 3: Failed to parse reference_data JSON string: {str(e)}")
                raise ValueError(f"Agent error: reference_data string is not valid JSON. Got: {reference_data[:200]}...")
        
        # Validate parameter types after conversion
        if not isinstance(extraction_results, dict):
            logger.error(f"Step 3: extraction_results must be dict object from step 2, got {type(extraction_results)}")
            logger.error("Step 3: Agent should pass the complete dict result from extract_invoice_fields")
            raise ValueError(f"Agent error: extraction_results must be the complete dict object returned from step 2 extract_invoice_fields. Got {type(extraction_results)}")
        
        if not isinstance(reference_data, dict):
            logger.error(f"Step 3: reference_data must be dict object, got {type(reference_data)}")
            logger.error("Step 3: Agent should pass the structured user input data as dict object")
            raise ValueError(f"Agent error: reference_data must be the structured user input dict object with Invoice and PurchaseOrder sections. Got {type(reference_data)}")
        
        # Log structure details for debugging
        logger.info(f"Step 3: extraction_results has keys: {list(extraction_results.keys())}")
        logger.info(f"Step 3: reference_data has keys: {list(reference_data.keys())}")
        
        # Check if Invoice section exists in extraction_results
        if "Invoice" not in extraction_results:
            logger.error("Step 3: No 'Invoice' section found in extraction_results")
            raise ValueError("extraction_results must contain 'Invoice' section from step 2")
        
        # Check if reference_data has expected sections
        if "Invoice" not in reference_data and "PurchaseOrder" not in reference_data:
            logger.warning("Step 3: reference_data missing expected Invoice/PurchaseOrder sections")
            logger.info(f"Step 3: Available reference_data keys: {list(reference_data.keys())}")
        
        # Extract reference values from structured data (except attachments)
        # Use the existing helper function that was designed for this purpose
        reference_values = _extract_reference_values(reference_data)
        
        # Import comparison status function from models for consistency
        # get_comparison_status already imported at top of file
        
        # Build Invoice section validation (agentic flow - expect structured data)
        invoice_validation = {}
        invoice_section = extraction_results["Invoice"]  # Expect Invoice section exists
        
        # Use centralized invoice fields definition
        invoice_fields = INVOICE_FIELDS
        
        for field_name in invoice_fields:
            # Agentic flow - expect field structure exists
            if field_name in invoice_section:
                extracted_field = invoice_section[field_name]
                extracted_value = extracted_field["Value"]
                extract_confidence = extracted_field["ConfidenceScore"]
            else:
                # Field not present in extraction
                extracted_value = ""
                extract_confidence = 0.0
            
            # Get reference value (use centralized field name normalization)
            from .invoice_models import normalize_field_name
            reference_key = normalize_field_name(field_name)
            
            # Special case: InvoiceServicePeriod should be compared against PurchaseOrderPeriod
            if field_name == "InvoiceServicePeriod":
                reference_value = reference_values.get("PurchaseOrderPeriod", "")
                logger.info(f"Step 3: Comparing InvoiceServicePeriod (extracted: '{extracted_value}') against PurchaseOrderPeriod (reference: '{reference_value}')")
            else:
                reference_value = reference_values.get(reference_key, "")
            
            # Calculate match confidence
            match_confidence = _calculate_match_confidence(extracted_value, reference_value, field_name)
            comparison_status = get_comparison_status(match_confidence)
            
            # Create validation entry (use normalized key for output)
            invoice_validation[reference_key] = {
                "ExtractedInvoiceValue": extracted_value,
                "ExtractConfidenceScore": extract_confidence,
                "ReferenceSAPValue": reference_value,
                "MatchConfidenceScore": match_confidence,
                "ComparisonStatus": comparison_status
            }
        
        # Build PurchaseOrder section validation (agentic flow)
        po_validation = {}
        po_section = extraction_results["PurchaseOrder"]  # Expect PurchaseOrder section exists
        
        # Handle PurchaseOrderNumber
        if "PurchaseOrderNumber" in po_section:
            po_number_field = po_section["PurchaseOrderNumber"]
            po_extracted_value = po_number_field["Value"]
            po_extract_confidence = po_number_field["ConfidenceScore"]
        else:
            po_extracted_value = ""
            po_extract_confidence = 0.0
        
        po_reference_value = reference_values.get("PurchaseOrderNumber", "")
        po_match_confidence = _calculate_match_confidence(po_extracted_value, po_reference_value, "PurchaseOrderNumber")
        
        po_validation["PurchaseOrderNumber"] = {
            "ExtractedInvoiceValue": po_extracted_value,
            "ExtractConfidenceScore": po_extract_confidence,
            "ReferenceSAPValue": po_reference_value,
            "MatchConfidenceScore": po_match_confidence,
            "ComparisonStatus": get_comparison_status(po_match_confidence)
        }
        
        # Handle line items (agentic flow)
        extracted_line_items = po_section.get("InvoiceDeliveryLineItems", [])  # Keep .get() for optional line items
        reference_line_items = reference_values.get("LineItems", [])  # Keep .get() for optional reference
        
        line_items_validation = []
        max_items = max(len(extracted_line_items), len(reference_line_items))
        
        for idx in range(max_items):
            # Get extracted line item (agentic - expect structure if present)
            extracted_item = extracted_line_items[idx] if idx < len(extracted_line_items) else {}
            
            # Get reference line item (agentic - expect structure if present)
            reference_item = reference_line_items[idx] if idx < len(reference_line_items) else {}
            
            # Line item field mapping - determine fields based on invoice structure
            line_item_fields = {}
            
            # Determine field set dynamically based on extracted line item structure
            # Service types have 4 fields: LineItemNo, Product, HSN_SAC_Code, Amount
            # Material types have 6 fields: LineItemNo, Product, Quantity, UnitPrice, HSN_SAC_Code, Amount
            sample_extracted_item = extracted_line_items[0] if extracted_line_items else {}
            
            # Check if this is a service type (no Quantity/UnitPrice) or material type
            has_quantity = "Quantity" in sample_extracted_item
            has_unit_price = "UnitPrice" in sample_extracted_item
            is_connectivity = "CKT_ID" in extraction_results.get("Invoice", {}) or "BandWidth" in extraction_results.get("Invoice", {})
            
            if is_connectivity:
                # Revenue-Service-Connectivity: 4 fields
                field_keys = ["LineItemNo", "Product", "HSN_SAC_Code", "Amount"]
            elif not has_quantity and not has_unit_price:
                # Service types (Capex-Service, Revenue-Service): 4 fields
                field_keys = ["LineItemNo", "Product", "HSN_SAC_Code", "Amount"]
            else:
                # Material types (Capex-Material, Revenue-Material): 6 fields
                field_keys = ["LineItemNo", "Product", "Quantity", "UnitPrice", "HSN_SAC_Code", "Amount"]
            
            # Create field mapping for reference lookup
            field_mappings = {key: key for key in field_keys}
            
            for field_key, ref_key in field_mappings.items():
                # Get extracted values (agentic flow - expect structure)
                if field_key in extracted_item:
                    extracted_field_data = extracted_item[field_key]
                    extracted_value = extracted_field_data["Value"]
                    extract_confidence = extracted_field_data["ConfidenceScore"]
                else:
                    extracted_value = ""
                    extract_confidence = 0.0
                
                # Get reference value (keep .get() for optional reference data)
                reference_value = reference_item.get(ref_key, "")
                
                # Calculate match confidence
                match_confidence = _calculate_match_confidence(extracted_value, reference_value, field_key)
                comparison_status = get_comparison_status(match_confidence)
                
                line_item_fields[field_key] = {
                    "ExtractedInvoiceValue": extracted_value,
                    "ExtractConfidenceScore": extract_confidence,
                    "ReferenceSAPValue": reference_value,
                    "MatchConfidenceScore": match_confidence,
                    "ComparisonStatus": comparison_status
                }
            
            line_items_validation.append(line_item_fields)
        
        po_validation["PurchaseOrderDeliveryLineItems"] = line_items_validation
        
        # Create final result structure
        result = {
            "Invoice": invoice_validation,
            "PurchaseOrder": po_validation
        }
        
        logger.info(f"Step 3: Validation completed - Invoice fields: {len(invoice_validation)}, Line items: {len(line_items_validation)}")
        return result
        
    except Exception as e:
        logger.error(f"Error in field comparison: {str(e)}")
        return {
            "Invoice": {},
            "PurchaseOrder": {},
            "error": f"Field comparison failed: {str(e)}"
        }

# =============================================================================
# PRIVATE HELPER METHODS (Internal Implementation)
# =============================================================================

async def _extract_via_document_api(
    base64_content: str,
    filename: str,
    category_name: str, 
    category_prompt: str
) -> dict:
    """
    Private method: Extract invoice fields using DocumentAPI client.
    
    Args:
        base64_content: Base64 encoded file content (converted internally from FileUrl)
        filename: Sanitized filename (spaces → underscores, extracted from FileUrl or provided)
        category_name: Invoice category (e.g., "Capex-Material")
        category_prompt: Category-specific extraction prompt
        
    Returns:
        Dict in Invoice/PurchaseOrder structure format
        
    Raises:
        Various DocumentAPIException subclasses
    """
    try:
        # Import DocumentAPI components with detailed error logging
        logger.info("DocumentAPI: About to import document_api module...")
        
        try:
            from document_api import DocumentAPIClient, DocumentProcessingRequest
            logger.info("DocumentAPI: Successfully imported DocumentAPIClient and DocumentProcessingRequest")
        except Exception as import_error:
            logger.error(f"DocumentAPI: CRITICAL - Failed to import document_api module")
            logger.error(f"DocumentAPI: Import error type: {type(import_error).__name__}")
            logger.error(f"DocumentAPI: Import error message: {str(import_error)}")
            logger.error(f"DocumentAPI: Import error details: {repr(import_error)}")
            import traceback
            logger.error(f"DocumentAPI: Full traceback:\n{traceback.format_exc()}")
            raise ValueError(f"Cannot import document_api module: {type(import_error).__name__}: {str(import_error)}")
        
        try:
            from document_api.exceptions import (
                DocumentAPIException, AuthenticationError, NetworkError,
                ProcessingError, ValidationError, DocumentExistsError
            )
            logger.info("DocumentAPI: Successfully imported exception classes")
        except Exception as exc_import_error:
            logger.error(f"DocumentAPI: Failed to import exception classes: {str(exc_import_error)}")
            raise ValueError(f"Cannot import document_api exceptions: {str(exc_import_error)}")
        
        # Validate required fields with detailed logging
        logger.info("DocumentAPI: Validating file content and parameters")
        if not base64_content or base64_content == "structured_data":
            raise ValueError("DocumentAPI requires actual base64 file content")
        
        # === VALIDATION CHECKPOINT 3: Pre-DocumentAPI Validation ===
        
        # 1. Validate base64 size constraints
        max_base64_size = 100 * 1024 * 1024  # 100MB base64 limit
        if len(base64_content) > max_base64_size:
            raise ValueError(f"Base64 content too large: {len(base64_content)} bytes > {max_base64_size} limit")
        
        min_base64_size = 100  # ~75 bytes original
        if len(base64_content) < min_base64_size:
            raise ValueError(f"Base64 content too small: {len(base64_content)} bytes < {min_base64_size} minimum")
        
        # 2. Validate base64 format and decode to verify PDF
        try:
            decoded_content = base64.b64decode(base64_content)
            
            # Check PDF magic number
            if not decoded_content.startswith(b'%PDF'):
                logger.error(f"Decoded content is not a valid PDF file")
                logger.error(f"First 20 bytes (hex): {decoded_content[:20].hex()}")
                logger.error(f"First 20 bytes (repr): {repr(decoded_content[:20])}")
                raise ValueError("Base64 content does not decode to a valid PDF file")
            
            logger.info(f"[VALIDATION] PDF validation passed - decoded size: {len(decoded_content)} bytes")
            
        except base64.binascii.Error as e:
            raise ValueError(f"Base64 content is malformed: {str(e)}")
        except Exception as e:
            raise ValueError(f"Base64 content validation failed: {str(e)}")
        
        base64_size = len(base64_content)
        logger.info(f"DocumentAPI: Processing file '{filename}' (Base64 size: {base64_size} chars, Decoded: {len(decoded_content)} bytes)")
            
        # Create DocumentAPI request with comprehensive parameters
        request = DocumentProcessingRequest(
            file_content=base64_content,  # Updated parameter name
            filename=filename,
            userid=1,  # Default user ID for invoice processing
            category=category_name,
            extraction_prompt=category_prompt,
            skip_persistence=True,  # Don't store in database for invoice processing
            is_analytical=False,    # Standard document processing
            doc_description=f"Invoice processing for category: {category_name}"
        )
        
        logger.info(f"DocumentAPI: Created request for category '{category_name}', skip_persistence=True")
        logger.info(f"DocumentAPI: Extraction prompt length: {len(category_prompt)} characters")
        
        # Process document via API with proper async context management
        logger.info("DocumentAPI: Initializing client and processing document")
        async with DocumentAPIClient() as client:
            api_response = await client.add_document(request)
        
        logger.info(f"DocumentAPI: Received response with status {api_response.status_code}")
        
        extraction_result = api_response.extracted_json

        # Validate that extracted_json is not None
        if extraction_result is None:
            error_msg = (
                f"DocumentAPI returned no extraction data. "
                f"Status: {api_response.status_code}, Message: {api_response.message}"
            )
            logger.error(f"DocumentAPI: {error_msg}")
            raise ProcessingError(
                error_msg,
                status_code=api_response.status_code,
                details={'response': api_response.model_dump() if hasattr(api_response, 'model_dump') else {}}
            )
        
        logger.info(f"DocumentAPI: Successfully extracted data for category '{category_name}'")
        return extraction_result
        
    except AuthenticationError as e:
        logger.error(f"DocumentAPI: Authentication failed - check credentials and token")
        raise AuthenticationError(f"DocumentAPI authentication error: {str(e)}")
    except NetworkError as e:
        logger.error(f"DocumentAPI: Network error - check endpoint connectivity")
        raise NetworkError(f"DocumentAPI network error: {str(e)}")
    except ProcessingError as e:
        logger.error(f"DocumentAPI: Processing error - document may be invalid or unsupported")
        raise ProcessingError(f"DocumentAPI processing error: {str(e)}")
    except ValidationError as e:
        logger.error(f"DocumentAPI: Validation error - request parameters may be invalid")
        raise ValidationError(f"DocumentAPI validation error: {str(e)}")
    except DocumentExistsError as e:
        logger.warning(f"DocumentAPI: Document already exists - may be acceptable for invoice processing")
        # For skip_persistence=True, this might be recoverable
        raise DocumentExistsError(f"DocumentAPI document exists: {str(e)}")
    except DocumentAPIException as e:
        logger.error(f"DocumentAPI: General API exception")
        raise DocumentAPIException(f"DocumentAPI error: {str(e)}")
    except Exception as e:
        logger.error(f"DocumentAPI: Unexpected error - {type(e).__name__}: {str(e)}")
        raise ValueError(f"DocumentAPI unexpected error: {str(e)}")


def _try_parse_date(date_str: str) -> Optional[datetime]:
    """
    Private helper: Attempt to parse string as date using common formats.
    
    Handles multiple date formats commonly found in invoices and SAP systems:
    - ISO format: 2025-03-31
    - Invoice format: 31-Mar-2025, 31-March-2025, 17-Apr-25 (2-digit year)
    - Numeric formats: 31-03-2025, 31/03/2025, 17/04/25 (2-digit year)
    - US format: 03/31/2025
    - European format: 31.03.2025, 17.04.25 (2-digit year)
    
    Args:
        date_str: String to parse as date (normalized lowercase)
        
    Returns:
        datetime.date object if parsing succeeds, None otherwise
    """
    if not date_str or len(date_str) < 6:  # Minimum date string length
        return None
    
    # Common date formats (order matters - most specific first)
    # 4-digit year formats first (more specific), then 2-digit year formats
    date_formats = [
        "%Y-%m-%d",           # 2025-03-31 (ISO 8601, SAP format)
        "%d-%b-%Y",           # 31-mar-2025 (invoice format - short month, 4-digit year)
        "%d-%B-%Y",           # 31-march-2025 (invoice format - full month, 4-digit year)
        "%d-%m-%Y",           # 31-03-2025 (numeric with dash, 4-digit year)
        "%d/%m/%Y",           # 31/03/2025 (numeric with slash, 4-digit year)
        "%Y/%m/%d",           # 2025/03/31 (ISO with slash)
        "%m/%d/%Y",           # 03/31/2025 (US format, 4-digit year)
        "%d.%m.%Y",           # 31.03.2025 (European format, 4-digit year)
        "%Y.%m.%d",           # 2025.03.31 (ISO with dot)
        "%m.%d.%Y",           # 03.31.2025 (US format with dot, 4-digit year)
        "%d %b %Y",           # 31 mar 2025 (space separator - short month, 4-digit year)
        "%d %B %Y",           # 31 march 2025 (space separator - full month, 4-digit year)
        "%b %d, %Y",          # mar 31, 2025 (US format - short month, 4-digit year)
        "%B %d, %Y",          # march 31, 2025 (US format - full month, 4-digit year)
        "%Y%m%d",             # 20250331 (compact format, 4-digit year)
        # 2-digit year formats (less specific, try after 4-digit year formats)
        "%d-%b-%y",           # 17-apr-25 (invoice format - short month, 2-digit year)
        "%d-%B-%y",           # 17-april-25 (invoice format - full month, 2-digit year)
        "%d-%m-%y",           # 17-04-25 (numeric with dash, 2-digit year)
        "%d/%m/%y",           # 17/04/25 (numeric with slash, 2-digit year)
        "%y/%m/%d",           # 25/04/17 (ISO with slash, 2-digit year)
        "%m/%d/%y",           # 04/17/25 (US format, 2-digit year)
        "%d.%m.%y",           # 17.04.25 (European format, 2-digit year)
        "%y.%m.%d",           # 25.04.17 (ISO with dot, 2-digit year)
        "%m.%d.%y",           # 04.17.25 (US format with dot, 2-digit year)
        "%d %b %y",           # 17 apr 25 (space separator - short month, 2-digit year)
        "%d %B %y",           # 17 april 25 (space separator - full month, 2-digit year)
        "%y%m%d",             # 250417 (compact format, 2-digit year)
    ]
    
    for fmt in date_formats:
        try:
            parsed = datetime.strptime(date_str, fmt)
            return parsed.date()
        except ValueError:
            continue
    
    return None  # Not a recognizable date

def _parse_date_range(date_range_str: str) -> Optional[tuple]:
    """
    Private helper: Parse service period date range in "date to date" format.
   
    Handles formats like:
    - "2025-01-01 to 2025-03-31"
    - "01-Jan-2025 to 31-Mar-2025"
    - "January 1, 2025 to March 31, 2025"
   
    Args:
        date_range_str: String containing date range (normalized lowercase)
       
    Returns:
        Tuple of (start_date, end_date) as datetime.date objects, or None if parsing fails
    """
    if not date_range_str or " to " not in date_range_str:
        return None
   
    try:
        # Split on " to " separator
        parts = date_range_str.split(" to ")
        if len(parts) != 2:
            return None
       
        start_str = parts[0].strip()
        end_str = parts[1].strip()
       
        # Try to parse both parts as dates
        start_date = _try_parse_date(start_str)
        end_date = _try_parse_date(end_str)
       
        if start_date and end_date:
            return (start_date, end_date)
       
    except Exception:
        pass
   
    return None

def _try_parse_month_year(date_str: str) -> Optional[tuple]:
    """
    Private helper: Parse month-year format and infer full month date range.
    
    Handles formats like:
    - "April 2025" → (2025-04-01, 2025-04-30)
    - "Apr 2025" → (2025-04-01, 2025-04-30)
    - "2025-04" → (2025-04-01, 2025-04-30)
    
    Args:
        date_str: String containing month-year (normalized lowercase)
        
    Returns:
        Tuple of (start_date, end_date) representing the full month range,
        or None if parsing fails
    """
    if not date_str:
        return None
    
    # Month-year formats to try
    month_year_formats = [
        "%B %Y",          # "april 2025" (full month name)
        "%b %Y",          # "apr 2025" (abbreviated month name)
        "%Y-%m",          # "2025-04" (ISO year-month)
        "%m-%Y",          # "04-2025" (month-year numeric)
        "%m/%Y",          # "04/2025" (month/year numeric)
    ]
    
    for fmt in month_year_formats:
        try:
            parsed = datetime.strptime(date_str, fmt)
            
            # Calculate first day of month
            start_date = parsed.replace(day=1).date()
            
            # Calculate last day of month
            if parsed.month == 12:
                # December - last day is 31
                last_day = 31
            else:
                # Get first day of next month, then subtract 1 day
                from calendar import monthrange
                last_day = monthrange(parsed.year, parsed.month)[1]
            
            end_date = parsed.replace(day=last_day).date()
            
            return (start_date, end_date)
            
        except ValueError:
            continue
    
    return None

def _check_prefix_suffix_match(extracted_clean: str, reference_clean: str) -> float:
    """
    Private helper: Check for prefix/suffix matching in invoice/PO numbers
    
    Handles cases where extracted values have additional formatting like:
    - Extracted: "INV-001-2024" vs Reference: "001-2024" 
    - Extracted: "PO-ABC-123" vs Reference: "ABC-123"
    - Extracted: "DOC-INV-456" vs Reference: "INV-456"
    
    Args:
        extracted_clean: Normalized extracted value (lowercase, trimmed)
        reference_clean: Normalized reference value (lowercase, trimmed)
        
    Returns:
        float: 0.9 if prefix/suffix match found, 0.0 otherwise
    """
    if not extracted_clean or not reference_clean:
        return 0.0
    
    # Remove common separators for core matching
    separators = ['-', '_', '/', '.', ' ']
    
    # Check if reference is contained within extracted (prefix case)
    if reference_clean in extracted_clean:
        # Ensure it's a meaningful match, not just partial substring
        # Check if reference appears as complete segments
        for sep in separators:
            extracted_parts = extracted_clean.split(sep)
            reference_parts = reference_clean.split(sep)
            
            # Check if all reference parts are found in extracted parts
            if all(ref_part in extracted_parts for ref_part in reference_parts if ref_part):
                return 0.9
    
    # Check if extracted is contained within reference (suffix case)
    if extracted_clean in reference_clean:
        # Similar logic for reverse case
        for sep in separators:
            extracted_parts = extracted_clean.split(sep)
            reference_parts = reference_clean.split(sep)
            
            # Check if all extracted parts are found in reference parts
            if all(ext_part in reference_parts for ext_part in extracted_parts if ext_part):
                return 0.9
    
    # Check for significant overlap in number sequences
    # Extract numeric sequences from both values
    import re
    ext_numbers = re.findall(r'\d+', extracted_clean)
    ref_numbers = re.findall(r'\d+', reference_clean)
    
    if ext_numbers and ref_numbers:
        # Check if the longest number sequences match
        ext_longest = max(ext_numbers, key=len) if ext_numbers else ""
        ref_longest = max(ref_numbers, key=len) if ref_numbers else ""
        
        if len(ext_longest) >= 4 and len(ref_longest) >= 4:  # Meaningful number sequences
            if ext_longest == ref_longest:
                return 0.9
            # Check if one contains the other
            if ext_longest in ref_longest or ref_longest in ext_longest:
                return 0.9
    
    # Check for alphanumeric core matching
    # Remove all separators and check for core match
    ext_core = ''.join(c for c in extracted_clean if c.isalnum())
    ref_core = ''.join(c for c in reference_clean if c.isalnum())
    
    if len(ext_core) >= 6 and len(ref_core) >= 6:  # Meaningful alphanumeric sequences
        if ext_core in ref_core or ref_core in ext_core:
            # Calculate overlap ratio
            min_len = min(len(ext_core), len(ref_core))
            max_len = max(len(ext_core), len(ref_core))
            if min_len / max_len >= 0.7:  # At least 70% overlap
                return 0.9
    
    return 0.0

def _calculate_match_confidence(extracted_value: str, reference_value: str, field_name: str = "") -> float:
    """
    Private method: Calculate confidence score for field matching between OCR and reference values
    Optimized for AI agent processing with business context awareness
    
    Args:
        extracted_value: Value extracted from invoice OCR
        reference_value: Reference value from input data
        field_name: Name of the field being compared (for specialized logic)
        
    Returns:
        Confidence score between 0.0 and 1.0
    """
    try:
        # Handle empty values - both empty is a match, one empty is a mismatch
        if not extracted_value and not reference_value:
            return 1.0  # Both empty = perfect match (consistent state)
        if not extracted_value or not reference_value:
            return 0.0  # One empty = mismatch (inconsistent state)
        
        # Normalize values for comparison
        ext_clean = extracted_value.strip().lower()
        ref_clean = reference_value.strip().lower()
        
        # Exact match
        if ext_clean == ref_clean:
            return 1.0
        
        # Special handling for fields that support prefix/suffix matching
        if supports_prefix_suffix_matching(field_name):
            prefix_suffix_confidence = _check_prefix_suffix_match(ext_clean, ref_clean)
            if prefix_suffix_confidence > 0:
                return prefix_suffix_confidence
        
        # Numeric comparison for amounts and numeric identifiers
        try:
            ext_num = float(ext_clean.replace(",", "").replace("$", "").replace("₹", ""))
            ref_num = float(ref_clean.replace(",", "").replace("$", "").replace("₹", ""))
            
            # Special handling for amount fields - compare only integer part (ignore decimals)
            if is_amount_field(field_name):
                ext_int = int(ext_num)  # Get integer part only
                ref_int = int(ref_num)  # Get integer part only
                
                if ref_int == 0:
                    return 1.0 if ext_int == 0 else 0.0
                
                # Compare integer parts only
                if ext_int == ref_int:
                    return 1.0  # Perfect match on integer part
                else:
                    # Calculate percentage difference on integer parts
                    diff_percent = abs(ext_int - ref_int) / ref_int
                    
                    # Use standardized confidence mapping
                    return get_confidence_from_percentage(diff_percent)
            
            # Standard numeric comparison for non-amount fields
            if ref_num == 0:
                return 1.0 if ext_num == 0 else 0.0
            
            diff_percent = abs(ext_num - ref_num) / ref_num
            
            # Use standardized confidence mapping for consistent scoring
            return get_confidence_from_percentage(diff_percent)
                
        except ValueError:
            pass
        
        # Date comparison - handle both single dates and service period ranges
        # Try parsing both values as dates before falling back to string similarity
        try:
            # Special handling for service period "date to date" format
            if field_name.lower() in ["invoiceserviceperiod", "purchaseorderperiod", "serviceperiod"] or " to " in ext_clean or " to " in ref_clean:
                # Parse date ranges for service periods
                ext_range = _parse_date_range(ext_clean)
                ref_range = _parse_date_range(ref_clean)
                
                # If date range parsing fails, try month-year inference (e.g., "April 2025")
                if not ext_range:
                    ext_range = _try_parse_month_year(ext_clean)
                if not ref_range:
                    ref_range = _try_parse_month_year(ref_clean)
               
                if ext_range and ref_range:
                    ext_start, ext_end = ext_range
                    ref_start, ref_end = ref_range
                   
                    # Perfect match: both start and end dates match
                    if ext_start == ref_start and ext_end == ref_end:
                        return 1.0
                   
                    # Partial match: calculate overlap and proximity
                    # Check for date range overlap or proximity
                    start_diff = abs((ext_start - ref_start).days) if ext_start and ref_start else 999
                    end_diff = abs((ext_end - ref_end).days) if ext_end and ref_end else 999
                   
                    # Use centralized date confidence scoring for date range comparison
                    max_diff = max(start_diff, end_diff)
                    return get_date_confidence_from_day_difference(max_diff)
           
            # Single date parsing (existing logic)
            parsed_ext_date = _try_parse_date(ext_clean)
            parsed_ref_date = _try_parse_date(ref_clean)
            
            if parsed_ext_date and parsed_ref_date:
                # Both successfully parsed as dates - compare as dates
                if parsed_ext_date == parsed_ref_date:
                    return 1.0  # Exact date match (same date, different format)
                else:
                    # Different dates - calculate day difference for partial match scoring
                    day_diff = abs((parsed_ext_date - parsed_ref_date).days)
                    
                    # Use centralized date confidence scoring
                    return get_date_confidence_from_day_difference(day_diff)
                    
        except Exception as date_error:
            # Date parsing failed - continue with string comparison
            logger.debug(f"Date parsing failed for '{ext_clean}' vs '{ref_clean}': {date_error}")
            pass
        
        # Enhanced string similarity for text fields
        # Split on common separators for better matching
        ext_tokens = set(ext_clean.replace("-", " ").replace("_", " ").replace("/", " ").split())
        ref_tokens = set(ref_clean.replace("-", " ").replace("_", " ").replace("/", " ").split())
        
        if ext_tokens or ref_tokens:
            # Jaccard similarity
            intersection = len(ext_tokens & ref_tokens)
            union = len(ext_tokens | ref_tokens)
            jaccard_sim = intersection / union if union > 0 else 0.0
            
            # Business context adjustment using centralized constants
            from .invoice_models import STRING_SIMILARITY_ADJUSTMENTS
            
            if jaccard_sim > 0.7:
                boost = STRING_SIMILARITY_ADJUSTMENTS["HIGH_SIMILARITY_BOOST"]
                return round(min(jaccard_sim + boost, 1.0), 2)  # Boost high similarity
            elif jaccard_sim > 0.5:
                return round(jaccard_sim, 2)
            else:
                penalty = STRING_SIMILARITY_ADJUSTMENTS["LOW_SIMILARITY_PENALTY"]
                return round(max(jaccard_sim - penalty, 0.3), 2)  # Penalty for low similarity
        
        # Character-level fallback
        common_chars = set(ext_clean) & set(ref_clean)
        total_chars = set(ext_clean) | set(ref_clean)
        
        if total_chars:
            from .invoice_models import STRING_SIMILARITY_ADJUSTMENTS
            char_sim = len(common_chars) / len(total_chars)
            weight = STRING_SIMILARITY_ADJUSTMENTS["CHAR_SIMILARITY_WEIGHT"]
            min_score = STRING_SIMILARITY_ADJUSTMENTS["MIN_CHAR_SIMILARITY"]
            return round(max(char_sim * weight, min_score), 2)  # Reduced weight for char similarity
        
        return 0.0
                
    except Exception as e:
        logger.error(f"Error calculating match confidence: {str(e)}")
        return 0.0


def _extract_reference_values(invoice_data: dict) -> dict:
    """
    Private method: Extract reference values from Invoice and PurchaseOrder sections for comparison
    Only extracts fields that are actually part of the invoice processing workflow
    
    Args:
        invoice_data: Complete invoice input structure with Invoice and PurchaseOrder sections
        
    Returns:
        Dictionary with reference field values from Invoice and PurchaseOrder sections only
    """
    try:
        reference_values = {}
        
        # Extract from Invoice section
        invoice_section = invoice_data.get("Invoice", {})
        reference_values.update({
            "InvoiceNumber": invoice_section.get("InvoiceNumber", ""),
            "InvoiceDate": invoice_section.get("InvoiceDate", ""),
            "PurchaseOrderPeriod": invoice_section.get("PurchaseOrderPeriod", ""),
            "InvoiceBaseAmount": invoice_section.get("InvoiceBaseAmount", ""),
            "InvoiceWithTaxAmount": invoice_section.get("InvoiceWithTaxAmount", ""),
            "BuyerGSTNumber": invoice_section.get("BuyerGSTNumber", ""),
            "SellerGSTNumber": invoice_section.get("SellerGSTNumber", ""),
            "CKT_ID": invoice_section.get("CKT_ID", ""),
            # Handle field name variations for BandWidth
            "BandWidth": invoice_section.get("BandWidth", "") or invoice_section.get("BandWidth(B/W)", "")
        })
        
        # Extract from PurchaseOrder section
        po_section = invoice_data.get("PurchaseOrder", {})
        reference_values.update({
            "PurchaseOrderNumber": po_section.get("PurchaseOrderNumber", "")            
        })
        
        # Extract line items from PurchaseOrder section
        line_items_raw = po_section.get("PurchaseOrderDeliveryLineItems", [])
        if line_items_raw:
            line_items = []
            for item in line_items_raw:
                # Convert line item structure to match expected format
                line_item = {
                    "LineItemNo": item.get("LineItemNo", ""),
                    "Product": item.get("Product", ""),
                    "Quantity": item.get("Quantity", ""),
                    "UnitPrice": item.get("Unit", "") or item.get("UnitPrice", ""),  # Handle field name variation
                    "HSN_SAC_Code": item.get("Item HSN SAC", "") or item.get("HSN_SAC_Code", ""),  # Handle field name variation
                    "Amount": item.get("Amount", "")
                }
                line_items.append(line_item)
            reference_values["LineItems"] = line_items
        
        # Note: Accounting and Identifiers sections are not included as they are used for 
        # category identification (step 1) but not for field extraction comparison (step 4)
        
        # Log details about extracted values
        line_items_count = len(reference_values.get("LineItems", []))
        logger.info(f"Extracted {len(reference_values)} reference values from Invoice and PurchaseOrder sections")
        logger.info(f"Reference values include: Invoice fields, PO fields, and {line_items_count} line items")
        
        return reference_values
        
    except Exception as e:
        logger.error(f"Error extracting reference values: {str(e)}")
        return {}


# =============================================================================
# AZURE AI FOUNDRY AGENT FUNCTION SET EXPORT
# =============================================================================

# Function set for Azure AI Foundry agent integration via AsyncFunctionTool
# Usage pattern:
#   from azure.ai.agents.models import AsyncFunctionTool, AsyncToolSet
#   functions = AsyncFunctionTool(invoice_functions_set)
#   toolset = AsyncToolSet()
#   toolset.add(functions)
#   agents_client.enable_auto_function_calls(toolset)
#
# All functions are asynchronous (async def) for AsyncFunctionTool compatibility:
# - async def signatures for auto function calling in async context
# - Annotated type hints for parameter descriptions
# - Structured error handling (raise exceptions, no fallbacks)
# - Agentic data flow (dict-to-dict, no JSON parsing)
invoice_functions_set: Set[Callable[..., Any]] = {
    identify_invoice_category,      # Step 1: Business rule-based category classification
    extract_invoice_fields,         # Step 2: Field extraction with internal prompt retrieval
    compare_invoice_fields,         # Step 3: Comprehensive field validation and comparison
}


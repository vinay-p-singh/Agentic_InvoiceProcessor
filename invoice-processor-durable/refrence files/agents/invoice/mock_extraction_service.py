"""
Mock Invoice Extraction Service
Provides signature-compatible interface for external invoice extraction utility
Returns realistic mock data until the actual service becomes available
"""

from typing import Dict, Any, List
import json
import random
from .invoice_models import (
    InvoiceCategory, 
    get_required_fields,
    get_optional_fields
)


class MockExtractionService:
    """
    Mock implementation of external invoice extraction service
    Compatible with future real service interface
    """
    
    def __init__(self):
        self.confidence_base = 0.85  # Base confidence for mock extractions
        
    def _generate_mock_field_value(self, field_name: str, category: InvoiceCategory) -> tuple[str, float]:
        """
        Generate realistic mock values for specific fields
        
        Args:
            field_name: Name of the field to generate
            category: Invoice category for context
            
        Returns:
            Tuple of (mock_value, confidence_score)
        """
        confidence = self.confidence_base + random.uniform(-0.1, 0.1)
        confidence = max(0.7, min(0.98, confidence))  # Keep within realistic range
        
        # Field-specific mock values
        mock_values = {
            "PurchaseOrderNumber": f"PO-{random.randint(100000, 999999)}",
            "InvoiceNumber": f"INV-ACME-{random.randint(2024, 2025)}-{random.randint(100, 999):03d}",
            "InvoiceDate": "2024-10-03",
            "InvoiceServicePeriod": "2024-Q4",
            "InvoiceBaseAmount": f"{random.randint(5000, 50000)}.00",
            "InvoiceWithTaxAmount": f"{random.randint(6000, 60000)}.00",
            "BuyerGSTNumber": f"{random.randint(10, 35):02d}ABCDE{random.randint(1000, 9999)}F{random.randint(1, 9)}Z{random.randint(1, 9)}",
            "SellerGSTNumber": f"{random.randint(10, 35):02d}XYZAB{random.randint(1000, 9999)}C{random.randint(1, 9)}D{random.randint(1, 9)}",
            "HSNCode": f"{random.randint(10000, 99999)}{random.randint(100, 999)}",
            "Supportingdocument": f"DOC-{random.randint(1000, 9999)}.pdf",
            "InvoiceQuantity": str(random.randint(1, 10)),
            "InvoiceUnitRate": f"{random.randint(1000, 5000)}.00",
            "CKT_ID": f"CKT-{random.choice(['VHAN', 'MUMH', 'DELH'])}-{random.randint(100, 999)}",
            "BandWidth": f"{random.choice(['10', '50', '100', '500'])}Mbps"
        }
        
        # Return mock value or default
        mock_value = mock_values.get(field_name, f"MOCK_{field_name}_{random.randint(100, 999)}")
        
        # Add some variation to confidence based on field type
        if field_name in ["InvoiceBaseAmt", "InvoiceWithTaxAmt"]:
            confidence *= 0.95  # Slightly lower for amounts
        elif field_name in ["HSNCode", "BuyerGSTNO", "SellerGSTNO"]:
            confidence *= 0.90  # Lower for complex codes
        
        return mock_value, confidence
    
    def _generate_mock_line_items(self, category: InvoiceCategory) -> List[Dict[str, Any]]:
        """
        Generate mock line items based on category
        
        Args:
            category: Invoice category
            
        Returns:
            List of mock line item dictionaries
        """
        num_items = random.randint(1, 3)
        line_items = []
        
        for i in range(num_items):
            line_item = {
                "LineItemNo": f"{(i + 1) * 10:02d}",
                "Product": self._get_mock_product_name(category),
                "Quantity": str(random.randint(1, 10)),
                "UnitPrice": f"{random.randint(1000, 5000)}.00",
                "HSN_SAC_Code": f"{random.randint(10000, 99999)}{random.randint(100, 999)}",
                "Amount": f"{random.randint(2000, 10000)}.00"
            }
            line_items.append(line_item)
        
        return line_items
    
    def extract_fields(self, file_data: dict, category: str, extraction_prompt: str) -> dict:
        """
        New method for agentic workflow - returns Invoice/PurchaseOrder structure
        
        Args:
            file_data: Dictionary with file information from attachments_data
            category: Invoice category string
            extraction_prompt: Category-specific extraction prompt
            
        Returns:
            Dictionary with Invoice/PurchaseOrder structure using Value/ConfidenceScore/FieldStatus format
        """
        try:
            # Convert category string to enum
            category_enum = InvoiceCategory(category)
            
            # Generate Invoice section fields
            invoice_fields = {}
            
            # Core invoice fields that go in Invoice section
            invoice_field_names = [
                "InvoiceNumber", "InvoiceDate", "InvoiceServicePeriod", 
                "InvoiceBaseAmount", "InvoiceWithTaxAmount", "BuyerGSTNumber", 
                "SellerGSTNumber", "CKT_ID", "BandWidth", "InvoiceQuantity", "InvoiceUnitRate"
            ]
            
            for field_name in invoice_field_names:
                mock_value, confidence = self._generate_mock_field_value(field_name, category_enum)
                
                # Determine if field should be missing based on category
                should_include = self._should_include_field(field_name, category_enum)
                
                if should_include:
                    invoice_fields[field_name] = {
                        "Value": mock_value,
                        "ConfidenceScore": confidence,
                        "FieldStatus": "Extracted"
                    }
                else:
                    invoice_fields[field_name] = {
                        "Value": "",
                        "ConfidenceScore": 0.0,
                        "FieldStatus": "Missing"
                    }
            
            # Generate PurchaseOrder section
            purchase_order_fields = {}
            
            # PO Number
            po_value, po_confidence = self._generate_mock_field_value("PurchaseOrderNumber", category_enum)
            purchase_order_fields["PurchaseOrderNumber"] = {
                "Value": po_value,
                "ConfidenceScore": po_confidence,
                "FieldStatus": "Extracted"
            }
            
            # Generate line items in the new format
            line_items = self._generate_agentic_line_items(category_enum)
            purchase_order_fields["InvoiceDeliveryLineItems"] = line_items
            
            result = {
                "Invoice": invoice_fields,
                "PurchaseOrder": purchase_order_fields,
                "status": "completed",
                "processing_notes": [
                    f"Mock extraction completed for {category}",
                    f"Used category-specific prompt: {len(extraction_prompt)} characters",
                    f"Generated {len(line_items)} line items"
                ]
            }
            
            return result
            
        except Exception as e:
            return {
                "Invoice": {},
                "PurchaseOrder": {},
                "status": "error",
                "processing_notes": [f"Mock extraction failed: {str(e)}"]
            }
    
    def _should_include_field(self, field_name: str, category: InvoiceCategory) -> bool:
        """Check if a field should be included based on category"""
        # Category-specific field inclusion rules
        category_fields = {
            InvoiceCategory.CAPEX_MATERIAL: ["InvoiceQuantity", "InvoiceUnitRate"],
            InvoiceCategory.CAPEX_SERVICE: ["InvoiceServicePeriod"],
            InvoiceCategory.REVENUE_MATERIAL: ["InvoiceQuantity", "InvoiceUnitRate"],
            InvoiceCategory.REVENUE_SERVICE: ["InvoiceServicePeriod"],
            InvoiceCategory.REVENUE_SERVICE_CONNECTIVITY: ["InvoiceServicePeriod", "CKT_ID", "BandWidth"]
        }
        
        # Core fields always included
        core_fields = ["InvoiceNumber", "InvoiceDate", "InvoiceBaseAmount", "InvoiceWithTaxAmount", "BuyerGSTNumber", "SellerGSTNumber"]
        
        if field_name in core_fields:
            return True
            
        # Check category-specific fields
        category_specific = category_fields.get(category, [])
        return field_name in category_specific
    
    def _generate_agentic_line_items(self, category: InvoiceCategory) -> List[Dict[str, Any]]:
        """
        Generate line items in the new agentic format with Value/ConfidenceScore/FieldStatus
        Category-specific: Service types exclude Quantity/UnitPrice, Material types include them
        """
        from .invoice_models import get_line_item_fields
        
        num_items = random.randint(1, 3)
        line_items = []
        
        # Get category-specific fields
        field_list = get_line_item_fields(category)
        
        for i in range(num_items):
            line_item = {}
            
            # Always include core fields
            line_item["LineItemNo"] = {
                "Value": f"{(i + 1) * 10}",
                "ConfidenceScore": round(random.uniform(0.95, 0.99), 2),
                "FieldStatus": "Extracted"
            }
            
            line_item["Product"] = {
                "Value": self._get_mock_product_name(category),
                "ConfidenceScore": round(random.uniform(0.90, 0.96), 2),
                "FieldStatus": "Extracted"
            }
            
            # Add Quantity and UnitPrice only for material categories
            if "Quantity" in field_list:
                line_item["Quantity"] = {
                    "Value": str(random.randint(1, 10)),
                    "ConfidenceScore": round(random.uniform(0.92, 0.95), 2),
                    "FieldStatus": "Extracted"
                }
            
            if "UnitPrice" in field_list:
                line_item["UnitPrice"] = {
                    "Value": f"{random.randint(1000, 5000)}.00",
                    "ConfidenceScore": round(random.uniform(0.88, 0.94), 2),
                    "FieldStatus": "Extracted"
                }
            
            # Always include HSN_SAC_Code and Amount
            line_item["HSN_SAC_Code"] = {
                "Value": f"{random.randint(10000, 99999)}{random.randint(100, 999)}",
                "ConfidenceScore": round(random.uniform(0.90, 0.97), 2),
                "FieldStatus": "Extracted"
            }
            
            line_item["Amount"] = {
                "Value": f"{random.randint(2000, 15000)}.00",
                "ConfidenceScore": round(random.uniform(0.91, 0.95), 2),
                "FieldStatus": "Extracted"
            }
            
            line_items.append(line_item)
        
        return line_items
    
    def _get_mock_product_name(self, category: InvoiceCategory) -> str:
        """
        Get category-appropriate mock product names
        
        Args:
            category: Invoice category
            
        Returns:
            Mock product name string
        """
        products = {
            InvoiceCategory.CAPEX_MATERIAL: [
                "Industrial Pump Model X200",
                "Control System Module Y150",
                "Heavy Duty Motor Z300",
                "Safety Equipment Kit A100"
            ],
            InvoiceCategory.CAPEX_SERVICE: [
                "Installation Service Package",
                "System Integration Service",
                "Equipment Maintenance Service",
                "Technical Consulting Service"
            ],
            InvoiceCategory.REVENUE_MATERIAL: [
                "Material Supply Package",
                "Component Replacement Kit",
                "Standard Equipment Unit",
                "Operational Supply Item"
            ],
            InvoiceCategory.REVENUE_SERVICE: [
                "Monthly Maintenance Service",
                "Support Service Package",
                "Operational Service Contract",
                "Technical Support Service"
            ],
            InvoiceCategory.REVENUE_SERVICE_CONNECTIVITY: [
                "Network Connectivity Service",
                "Bandwidth Service Package",
                "Data Communication Service",
                "Network Infrastructure Service"
            ]
        }
        
        category_products = products.get(category, ["Generic Service Item"])
        return random.choice(category_products)


# Service instance for use in orchestrator functions
mock_extraction_service = MockExtractionService()


def get_extraction_prompt(category: InvoiceCategory) -> str:
    """
    Generate category-specific extraction prompt for external service
    
    Args:
        category: Invoice category
        
    Returns:
        Formatted extraction prompt string
    """
    required_fields = get_required_fields(category)
    optional_fields = get_optional_fields(category)
    
    prompt = f"""
INVOICE FIELD EXTRACTION - {category.value}

Extract the following fields from the invoice document:

REQUIRED FIELDS:
{chr(10).join([f"- {field}" for field in required_fields])}

OPTIONAL FIELDS:
{chr(10).join([f"- {field}" for field in optional_fields])}

SPECIAL INSTRUCTIONS:
- For line items, extract all available line item details
- Maintain high accuracy for monetary amounts
- Use exact text extraction for GST numbers and codes
- Return confidence scores for each extracted field
- Handle multiple line items separately

RESPONSE FORMAT:
Return structured JSON with extracted field values and confidence scores.
"""
    
    return prompt.strip()
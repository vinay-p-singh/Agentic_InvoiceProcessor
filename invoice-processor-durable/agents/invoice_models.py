from typing import List, Optional, Any, Dict, Union
from pydantic import BaseModel, Field, ConfigDict

class InvoiceLineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    Description: str = Field(..., description="Description of the line item")
    Quantity: float = Field(..., description="Quantity of the item")
    UnitPrice: float = Field(..., description="Unit price of the item")
    Amount: float = Field(..., description="Total amount for the line item")

class InvoiceData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    InvoiceNumber: Union[str, None] = Field(..., description="The invoice number")
    OrderNumber: Union[str, None] = Field(..., description="The order number")
    InvoiceDate: Union[str, None] = Field(..., description="The date of the invoice")
    InvoiceBaseAmount: Union[float, None] = Field(..., description="The base amount of the invoice")
    InvoiceWithTaxAmount: Union[float, None] = Field(..., description="The total amount with tax")
    LineItems: List[InvoiceLineItem] = Field(..., description="List of line items")

class FieldValidationDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(..., description="Status: MATCH, MISMATCH, MISSING_IN_EXTRACTION, or NOT_CHECKED")
    # Use Union[str, float, int, bool, None] instead of Any to be explicit for JSON Schema
    # IMPORTANT: For strict JSON Schema, all fields must be required. 
    # We use Union[..., None] to allow nulls, but the field itself must be present.
    expected: Union[str, float, int, bool, None] = Field(..., description="The expected value")
    actual: Union[str, float, int, bool, None] = Field(..., description="The actual extracted value")

class NamedFieldValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field_name: str = Field(..., description="The name of the field being validated")
    details: FieldValidationDetail = Field(...)

class LineItemValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    line_number: int = Field(..., description="The line item number (1-based)")
    status: str = Field(..., description="Overall status for this line item: MATCH or MISMATCH")
    field_analysis: List[NamedFieldValidation] = Field(..., description="Validation details for specific line item fields (Description, Quantity, etc.)")

class ValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_valid: bool = Field(..., description="Whether the invoice is valid based on expected fields")
    field_analysis: List[NamedFieldValidation] = Field(..., description="Detailed validation status for header fields")
    line_items_analysis: List[LineItemValidation] = Field(..., description="Detailed validation for line items")
    summary: str = Field(..., description="A brief summary of the validation result")

class AgentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    Extraction: InvoiceData = Field(...)
    Validation: ValidationResult = Field(...)

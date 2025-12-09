import os
import json
import requests
import logging
from typing import Annotated
from .invoice_prompts import InvoicePrompts

logger = logging.getLogger(__name__)

def extract_invoice_text(
    pdf_path: Annotated[str, "The local file path to the PDF invoice to be processed."]
) -> str:
    """
    Extracts raw text from a PDF invoice using the PDF Extractor API.
    """
    api_url = os.environ.get("PDF_EXTRACTOR_API_URL")
    if not api_url:
        return "Error: PDF_EXTRACTOR_API_URL environment variable is not set."

    if not os.path.exists(pdf_path):
        return f"Error: PDF file not found at: {pdf_path}"

    try:
        with open(pdf_path, 'rb') as f:
            files = {'file': (os.path.basename(pdf_path), f, 'application/pdf')}
            data = {'prompt': InvoicePrompts.EXTRACTION_PROMPT}
            
            response = requests.post(api_url, files=files, data=data)
            response.raise_for_status()

            result = response.json()
            return json.dumps(result)
            
    except Exception as e:
        logger.error(f"Error calling extraction API: {e}")
        return f"Error calling extraction API: {str(e)}"

import io
from pypdf import PdfReader
from typing import List

def extract_text_from_pdf(file_content: bytes) -> List[str]:
    """
    Extracts text from a PDF file content, page by page.
    
    Args:
        file_content (bytes): The raw bytes of the PDF file.
        
    Returns:
        List[str]: A list of strings, where each string is the text content of a page.
    """
    pdf_file = io.BytesIO(file_content)
    reader = PdfReader(pdf_file)
    
    pages_text = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages_text.append(text)
        else:
            pages_text.append("") # Append empty string if no text found on page
            
    return pages_text

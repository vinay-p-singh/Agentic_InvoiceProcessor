import asyncio
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from typing import List
from pdf_utils import extract_text_from_pdf
from ai_utils import analyze_page

app = FastAPI(title="PDF Data Extractor API")

@app.post("/extract")
async def extract_data(
    file: UploadFile = File(...),
    prompt: str = Form(...)
):
    """
    Upload a PDF file and a prompt to extract data from it using Azure OpenAI.
    """
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="File must be a PDF.")
    
    try:
        # Read file content
        content = await file.read()
        
        # Extract text from PDF pages
        pages_text = extract_text_from_pdf(content)
        
        if not pages_text:
            return {"message": "No text could be extracted from the PDF."}

        # Process pages
        # We can process them in parallel for speed, or sequentially if order matters strictly or to avoid rate limits.
        # Let's do parallel for now, but be mindful of rate limits in a real production scenario.
        tasks = []
        for i, text in enumerate(pages_text):
            if text.strip(): # Only process pages with text
                tasks.append(analyze_page(text, prompt))
            else:
                # Handle empty pages if necessary, or just skip
                pass
                
        results = await asyncio.gather(*tasks)
        
        # Structure the response
        response_data = {
            "filename": file.filename,
            "total_pages": len(pages_text),
            "extracted_data": results
        }
        
        return response_data

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

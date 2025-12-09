# PDF Data Extractor API

This is a simple FastAPI application that takes a PDF file and a prompt, extracts text from the PDF page by page, and uses Azure OpenAI to extract structured data based on the prompt.

## Setup

1.  **Install Dependencies:**

    ```bash
    pip install -r requirements.txt
    ```

2.  **Configure Environment:**
    Open `.env` and fill in your Azure OpenAI credentials:
    ```env
    AZURE_OPENAI_ENDPOINT="https://your-resource-name.openai.azure.com/"
    AZURE_OPENAI_API_KEY="your-api-key"
    AZURE_OPENAI_DEPLOYMENT_NAME="gpt-4" # or your deployment name
    AZURE_OPENAI_API_VERSION="2024-02-15-preview"
    ```

## Running the API

Run the application using uvicorn:

```bash
uvicorn main:app --reload
```

The API will be available at `http://localhost:8000`.

## Usage

You can use the interactive Swagger UI at `http://localhost:8000/docs` to test the API.

**Endpoint:** `POST /extract`

**Parameters:**

- `file`: The PDF file to upload.
- `prompt`: The instruction for what data to extract (e.g., "Extract the invoice number and total amount").

**Response:**
Returns a JSON object containing the extracted data for each page.

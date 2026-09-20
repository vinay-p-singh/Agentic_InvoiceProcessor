# Agentic Invoice Processor

Reference implementation of an agentic invoice-processing pipeline on Azure — a
FastAPI extraction service paired with a Durable Functions orchestration driven by
Azure AI Foundry agents.

Built as a personal reference project to explore how agent reasoning, durable
orchestration and document extraction fit together for a document-heavy workflow.

## Architecture

Two independent services:

### 1. `pdf-extractor-api` — extraction service

FastAPI app that accepts a PDF and a natural-language prompt, extracts text page
by page with `pypdf`, and uses Azure OpenAI to return structured data per page.

- `POST /extract` — multipart upload (`file`) plus a `prompt` describing the fields to extract
- Swagger UI at `/docs`
- Stack: FastAPI · uvicorn · pypdf · Azure OpenAI

### 2. `invoice-processor-durable` — agent orchestration

Azure Functions app using Durable Functions to orchestrate invoice processing,
with agent logic built on Azure AI Foundry (`azure-ai-projects`, `azure-ai-agents`).

- `function_app.py` — Durable Functions entry point
- `agents/` — agent definition, tool functions, typed models and prompts
- `activities/` — durable activity functions
- Auth via `azure-identity`
- Stack: Azure Functions · Durable Functions · Azure AI Foundry Agent Service · Azure OpenAI

## Getting started

Each service runs independently.

### PDF extractor API

```bash
cd pdf-extractor-api
pip install -r requirements.txt
uvicorn main:app --reload
```

Configure `.env`:

```env
AZURE_OPENAI_ENDPOINT="https://<resource>.openai.azure.com/"
AZURE_OPENAI_API_KEY="<key>"
AZURE_OPENAI_DEPLOYMENT_NAME="gpt-4"
AZURE_OPENAI_API_VERSION="2024-02-15-preview"
```

The API is then available at `http://localhost:8000`.

### Durable orchestration

```bash
cd invoice-processor-durable
pip install -r requirements.txt
func start
```

Requires Azure Functions Core Tools and an Azure AI Foundry project.
`test_invoice.http` contains sample requests; `sample-invoices/` has test PDFs.

## Notes

- Sample invoices are synthetic and contain no real data.
- This is a personal learning/reference project, not production software and not
  affiliated with any employer or client engagement.

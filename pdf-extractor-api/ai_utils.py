import os
import json
from openai import AsyncAzureOpenAI
from dotenv import load_dotenv

load_dotenv()

endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
api_key = os.getenv("AZURE_OPENAI_API_KEY")
deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
api_version = os.getenv("AZURE_OPENAI_API_VERSION")

client = AsyncAzureOpenAI(
    azure_endpoint=endpoint,
    api_key=api_key,
    api_version=api_version
)

async def analyze_page(page_text: str, user_prompt: str) -> dict:
    """
    Sends a page of text and a prompt to Azure OpenAI to extract data.
    
    Args:
        page_text (str): The text content of the page.
        user_prompt (str): The user's instruction for extraction.
        
    Returns:
        dict: The extracted data as a dictionary.
    """
    
    system_message = "You are a helpful assistant that extracts data from documents. Return ONLY valid JSON."
    
    full_prompt = f"""
    {user_prompt}
    
    Here is the text from the document page:
    ----------------------------------------
    {page_text}
    ----------------------------------------
    
    Return the output in valid JSON format. Do not include markdown formatting like ```json ... ```.
    """
    
    try:
        response = await client.chat.completions.create(
            model=deployment_name,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": full_prompt}
            ],
            response_format={ "type": "json_object" }
        )
        
        content = response.choices[0].message.content
        return json.loads(content)
    except Exception as e:
        return {"error": str(e), "page_text_snippet": page_text[:100]}

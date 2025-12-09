import os
import json
import asyncio
import logging
from typing import Optional, Dict, Any, Set
from azure.ai.projects.aio import AIProjectClient
from azure.ai.agents.models import AsyncFunctionTool, AsyncToolSet, MessageRole
from azure.identity.aio import DefaultAzureCredential
from config import AppConfig
from .invoice_prompts import InvoicePrompts
from .invoice_functions import extract_invoice_text
from .invoice_models import AgentResponse

class InvoiceAgent:
    def __init__(self, project_client: AIProjectClient, model: str):
        self.project_client = project_client
        self.agents_client = project_client.agents
        self.model = model
        self.logger = logging.getLogger(__name__)
        self.agent = None

    @classmethod
    async def create_and_process(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        config = AppConfig.get_instance()
        credential = DefaultAzureCredential()
        
        async with credential:
            project_client = AIProjectClient(
                endpoint=config.project_endpoint,
                credential=credential
            )
            
            async with project_client:
                agent_instance = cls(
                    project_client=project_client,
                    model=config.azure_openai_deployment_name
                )
                
                try:
                    await agent_instance.initialize()
                    return await agent_instance.process(data)
                finally:
                    await agent_instance.cleanup()

    async def initialize(self):
        """
        Initialize agent with auto function calling.
        """
        # Define functions set
        functions_set = {extract_invoice_text}
        
        # Create AsyncFunctionTool
        functions = AsyncFunctionTool(functions_set)
        
        # Create ToolSet and add functions
        toolset = AsyncToolSet()
        toolset.add(functions)
        
        # Enable auto function calling
        # This allows the SDK to automatically execute tools when the model requests them
        # Note: This modifies the agents_client behavior for this instance
        if hasattr(self.agents_client, "enable_auto_function_calls"):
             self.agents_client.enable_auto_function_calls(toolset)
        
        # Create agent
        self.agent = await self.agents_client.create_agent(
            model=self.model,
            name="invoice-processing-agent-temp",
            instructions=InvoicePrompts.SYSTEM_INSTRUCTION,
            tools=functions.definitions,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "invoice_response",
                    "schema": AgentResponse.model_json_schema(),
                    "strict": True
                }
            }
        )
        self.logger.info(f"Created temporary agent: {self.agent.id}")

    async def cleanup(self):
        """
        Delete the temporary agent.
        """
        if self.agent:
            try:
                await self.agents_client.delete_agent(self.agent.id)
                self.logger.info(f"Deleted agent: {self.agent.id}")
            except Exception as e:
                self.logger.warning(f"Failed to delete agent: {e}")

    async def process(self, data: Dict[str, Any]) -> Dict[str, Any]:
        pdf_path = data.get("pdf_path")
        expected_fields = data.get("expected_fields")

        # Create Thread
        thread = await self.agents_client.threads.create()

        # Add User Message
        user_content = f"""
        Please process this invoice.
        
        PDF Path: {pdf_path}
        
        Expected Fields for Validation:
        {json.dumps(expected_fields, indent=2)}
        """

        await self.agents_client.messages.create(
            thread_id=thread.id,
            role=MessageRole.USER,
            content=user_content
        )

        # Run with auto function calling
        # create_and_process handles the polling and tool execution loop
        run = await self.agents_client.runs.create_and_process(
            thread_id=thread.id,
            agent_id=self.agent.id
        )

        if run.status != "completed":
            raise Exception(f"Run failed with status: {run.status}")

        # Retrieve Messages
        messages = self.agents_client.messages.list(thread_id=thread.id)
        
        # Iterate to find the latest assistant message
        async for message in messages:
            if message.role == MessageRole.AGENT:
                content_text = message.content[0].text.value
                
                try:
                    # Since we used response_format, the output is guaranteed to be valid JSON
                    # We just need to parse the string into our Pydantic model
                    return AgentResponse.model_validate_json(content_text).model_dump()
                except Exception as e:
                    self.logger.error(f"Failed to parse agent response: {e}")
                    return {"raw_response": content_text}
        
        raise Exception("No response from assistant")


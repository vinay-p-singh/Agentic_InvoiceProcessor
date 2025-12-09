"""
Invoice Agent - Async Auto Function Calling Implementation

Following the official Azure SDK async pattern with proper async/await usage.
Refactored to follow Single Responsibility Principle (SRP).
"""

import os
from typing import Dict, Any, Optional, Tuple, TYPE_CHECKING
from utilities.logger import get_logger

from azure.ai.projects.aio import AIProjectClient
from azure.ai.agents.models import (
    AgentThread, 
    MessageRole, 
    AsyncFunctionTool, 
    ListSortOrder, 
    AsyncToolSet,
    RunStepToolCallDetails,
    RunStepFunctionToolCall
)
from azure.identity.aio import DefaultAzureCredential, ManagedIdentityCredential, ChainedTokenCredential
from config import AppConfig
from .invoice_functions import invoice_functions_set
from .invoice_prompts import InvoicePrompts

# Import TokenTracker for type hints only (avoid circular import)
if TYPE_CHECKING:
    from utilities.token_tracking import TokenTracker

class InvoiceAgent:
    """
    Invoice Processing Agent with Auto Function Calling (Async)
    
    Uses proper async pattern from official Azure SDK documentation:
    - Receives AIProjectClient from caller (like official sample pattern)
    - All methods are async def
    - Uses await for all agent operations
    - Caller manages context with async with
    - Handles instruction selection and message formatting internally
    
    Workflow:
    - AI receives invoice processing request
    - AI automatically calls the 3 invoice functions as needed:
      1. identify_invoice_category
      2. extract_invoice_fields
      3. compare_invoice_fields
    - Returns structured data extracted from step-level outputs
    """
    
    def __init__(
        self, 
        project_client: AIProjectClient, 
        config: AppConfig, 
        data: Optional[Dict[str, Any]] = None,
        instructions: Optional[str] = None,
        token_tracker: Optional['TokenTracker'] = None
    ):
        """
        Initialize Invoice Agent with smart instruction selection.
        
        Following official pattern: Receives project_client from caller who manages 
        the async with context. Agent encapsulates all agent-specific logic including
        instruction selection based on data type.
        
        Args:
            project_client: AIProjectClient instance (managed by caller with async with)
            config: Application configuration
            data: Optional dict containing user_input and request_body. 
                  If provided, automatically determines structured vs text mode.
            instructions: Optional custom instructions. If not provided, instructions
                         are automatically selected based on data parameter.
            token_tracker: Optional TokenTracker instance for tracking token usage.
                          If None, no token tracking occurs (default).
        """
        self.logger = get_logger(__name__)
        self.project_client = project_client
        self.agents_client = project_client.agents
        self.config = config
        self.agent = None
        self.token_tracker = token_tracker
        
        # Smart instruction and message handling
        if data:
            self.user_input = data.get("user_input", "")
            self.request_body = data.get("request_body", {})
            self.has_structured_data = bool(self.request_body)

            # Build processing message            
            self.instructions = InvoicePrompts.get_agent_function_prompt()   

            # Build processing message
            self.processing_message = InvoicePrompts.format_structured_processing_message(self.request_body)
        
        self.logger.info("Invoice Agent initialized with project client")
    
    # =========================================================================
    # FACTORY METHOD
    # =========================================================================
    
    @classmethod
    async def create_and_process(
        cls, 
        data: Dict[str, Any],
        token_tracker: Optional['TokenTracker'] = None
    ) -> Tuple[Dict[str, Any], str, Dict[str, Any]]:
        """
        Factory method for complete invoice processing workflow.
        
        Creates AIProjectClient, processes invoice through 3-step workflow,
        and returns structured results with metadata.
        
        Args:
            data: Dict containing 'user_input' and optional 'request_body'
            token_tracker: Optional TokenTracker instance for tracking token usage
            
        Returns:
            tuple: (structured_results, run_status, metadata)
        """
        config = AppConfig.get_instance()
        
        # Create credential with User-Assigned Managed Identity priority
        credential = ChainedTokenCredential(
            ManagedIdentityCredential(client_id=config.user_assigned_managed_identity),
            DefaultAzureCredential()
        )
        
        # Use async with for credential cleanup
        async with credential:
            # Create AIProjectClient at this level (official pattern)
            project_client = AIProjectClient(
                endpoint=config.project_endpoint,
                credential=credential
            )
            
            # Use async with for entire processing (official pattern)
            async with project_client:
                # Create agent with smart instruction selection
                agent = cls(
                    project_client=project_client,
                    config=config,
                    data=data,
                    token_tracker=token_tracker
                )
                
                # Step 1: Run the agent (execution only)
                thread, run = await agent.run(agent.processing_message)
                
                # Step 2: Extract structured results from step-level outputs
                structured_results = await agent.extract_structured_results(thread, run)
                
                # Step 3: Analyze and log workflow (analysis only)
                function_calls, step_status = await agent.analyze_and_log_workflow(thread, run)
                
                # Step 4: Cleanup (cleanup only)
                await agent.cleanup()
                
                # Build metadata
                metadata = {
                    "has_structured_data": agent.has_structured_data,
                    "user_input": agent.user_input,
                    "request_body": agent.request_body,
                    "function_calls_count": len(function_calls),
                    "workflow_steps_completed": sum(step_status.values()),
                    "data_extraction_source": structured_results.get("data_source", "unknown"),
                    "data_extraction_successful": structured_results.get("extraction_successful", False)
                }
                
                return structured_results, run.status, metadata
    
    # =========================================================================
    # PUBLIC METHODS - Single Responsibility Per Method
    # =========================================================================
    
    async def run(self, message_content: str) -> Tuple[AgentThread, Any]:
        """
        Execute agent run on a message.
        
        Initializes agent if needed, creates thread, processes message,
        and returns execution artifacts.
        
        Args:
            message_content: The message/query to process
            
        Returns:
            tuple: (thread: AgentThread, run: ThreadRun)
            
        Raises:
            Exception: If agent run fails
        """
        try:
            # Initialize agent if not already done
            if self.agent is None:
                await self.initialize()
            
            # Create thread for communication
            thread = await self.agents_client.threads.create()
            self.logger.info(f"Created thread: {thread.id}")
            
            # Create message to thread
            await self.agents_client.messages.create(
                thread_id=thread.id,
                role=MessageRole.USER,
                content=message_content
            )
            self.logger.info(f"Added message to thread {thread.id}")
            
            # Create and process agent run in thread with auto function calling
            run = await self.agents_client.runs.create_and_process(
                thread_id=thread.id,
                agent_id=self.agent.id
            )
            
            # Track token usage if tracker is enabled (with detailed breakdown)
            if self.token_tracker:
                detailed_usage = await self.token_tracker.track_run_detailed(
                    run=run,
                    thread_id=thread.id,
                    agents_client=self.agents_client,
                    agent_name="InvoiceAgent"
                )
                if detailed_usage:
                    self.logger.info(
                        f"Detailed token tracking: {len(detailed_usage.get('steps', []))} steps, "
                        f"{len(detailed_usage.get('functions', {}))} unique functions"
                    )
            
            self.logger.info(f"Run completed with status: {run.status}")
            
            if run.status == "failed":
                self.logger.error(f"Run failed: {run.last_error}")
                raise Exception(f"Agent run failed: {run.last_error}")
            
            return thread, run
            
        except Exception as e:
            self.logger.error(f"Error during agent run: {e}")
            raise
    
    async def extract_response(self, thread: AgentThread) -> str:
        """
        Extract agent's text response from thread messages.
        
        Args:
            thread: The agent thread to extract response from
            
        Returns:
            str: The agent's text response
        """
        messages = self.agents_client.messages.list(
            thread_id=thread.id,
            order=ListSortOrder.DESCENDING
        )
        
        agent_response = ""
        async for msg in messages:
            if msg.text_messages:
                # Get the last text message (official SDK pattern)
                agent_response = msg.text_messages[-1].text.value
                break
        
        if not agent_response:
            self.logger.warning(f"No assistant response found in thread {thread.id}")
            agent_response = "No response received from invoice agent"
        else:
            self.logger.info(f"Retrieved AI response from thread {thread.id}")
        
        return agent_response
    
    async def extract_structured_results(self, thread: AgentThread, run: Any) -> Dict[str, Any]:
        """
        Extract structured results from step-level outputs (Steps 1-3).
        
        NEW: With step-level output support, we directly access function return values
        from tool_call.function.output instead of parsing arguments.
        
        This method extracts:
        - Step 1 output: category string (format: "CATEGORY: XXX\\nREASONING: ...\\nSTATUS: SUCCESS")
        - Step 2 output: extraction_results dict (JSON string)
        - Step 3 output: validation_results dict (JSON string)
        
        Args:
            thread: The agent thread
            run: The run object from agent execution
            
        Returns:
            dict: Structured results containing:
                - category: Invoice category from step 1
                - extraction_results: Complete extraction dict from step 2
                - validation_results: Complete validation dict from step 3
                - data_source: "step_outputs"
                - extraction_successful: Boolean indicating success
        """
        import json
        
        # Collect function calls with outputs
        function_calls = await self._collect_function_calls(thread, run.id)
        
        category = None
        extraction_results = None
        validation_results = None
        
        # Extract outputs from each step (outputs are already normalized)
        for call in function_calls:
            func_name = call["function_name"]
            output = call.get("output")
            
            if output is None:
                self.logger.debug(f"Skipping {func_name} - no output available")
                continue
            
            try:
                if func_name == "identify_invoice_category":
                    # Step 1: Parse string format
                    if isinstance(output, str):
                        category = self._parse_category_from_output(output)
                        if category:
                            self.logger.info(f"Step 1 output: category = {category}")
                    else:
                        self.logger.warning(f"Step 1 output is not string: {type(output)}")
                
                elif func_name == "extract_invoice_fields" and not extraction_results:
                    # Step 2: Handle dict or JSON/Python string representation
                    extraction_results = self._safe_parse_dict_output(output, func_name)
                    if extraction_results:
                        self.logger.info(f"Step 2 output: extraction_results ({len(extraction_results)} sections)")
                
                elif func_name == "compare_invoice_fields" and not validation_results:
                    # Step 3: Handle dict or JSON/Python string representation
                    validation_results = self._safe_parse_dict_output(output, func_name)
                    if validation_results:
                        self.logger.info(f"Step 3 output: validation_results ({len(validation_results)} sections)")
            
            except Exception as e:
                self.logger.error(f"Error processing {func_name} output: {e}")
                self.logger.error(f"Output type: {type(output)}")
        
        # Validate we got all required outputs
        missing = []
        if not category: missing.append("category (Step 1)")
        if not extraction_results: missing.append("extraction_results (Step 2)")
        if not validation_results: missing.append("validation_results (Step 3)")
        
        if missing:
            self.logger.warning(f"Missing outputs: {', '.join(missing)}")
            
            return {
                "category": category or "",
                "extraction_results": extraction_results or {},
                "validation_results": validation_results or {},
                "data_source": "step_outputs_incomplete",
                "extraction_successful": False,
                "error": f"Missing step outputs: {', '.join(missing)}"
            }
        
        self.logger.info("Successfully extracted all outputs from step-level data")
        
        return {
            "category": category,
            "extraction_results": extraction_results,
            "validation_results": validation_results,
            "data_source": "step_outputs",
            "extraction_successful": True
        }
    
    def _safe_parse_dict_output(self, output: Any, func_name: str) -> Optional[dict]:
        """
        Safely parse dict output from various formats.
        
        Handles:
        - Already a dict -> return as-is
        - Valid JSON string -> json.loads()
        - Python dict representation string (single quotes) -> ast.literal_eval()
        - Invalid format -> None with error log
        
        Args:
            output: Output from function (dict, JSON string, or Python repr string)
            func_name: Function name for logging
            
        Returns:
            Parsed dict or None if parsing fails
        """
        import ast
        import json
        
        # Case 1: Already a dict
        if isinstance(output, dict):
            return output
        
        # Case 2: String representation
        if isinstance(output, str):           
            # Try ast.literal_eval for Python dict representation (single quotes)
            try:
                parsed = ast.literal_eval(output)
                if isinstance(parsed, dict):
                    self.logger.info(f"{func_name}: Parsed Python dict representation (single quotes)")
                    return parsed
                else:
                    self.logger.error(f"{func_name}: literal_eval returned {type(parsed)}, not dict")
                    return None
            except (ValueError, SyntaxError) as e:
                self.logger.error(f"{func_name}: Failed to parse string as dict: {e}")
                OUTPUT_PREVIEW_LENGTH = 300
                self.logger.error(f"Output preview (first {OUTPUT_PREVIEW_LENGTH} chars): {output[:OUTPUT_PREVIEW_LENGTH]}")
                return None
        
        # Case 3: Unexpected type
        self.logger.error(f"{func_name}: Unexpected output type: {type(output)}")
        return None
    
    def _parse_category_from_output(self, output: str) -> str:
        """
        Parse category from Step 1 output string format.
        
        Expected format: "CATEGORY: Capex-Material\\nREASONING: ...\\nSTATUS: SUCCESS"
        
        Args:
            output: The string output from identify_invoice_category
            
        Returns:
            Extracted category string or empty string if parsing fails
        """
        try:
            for line in output.split('\n'):
                if line.startswith('CATEGORY:'):
                    category = line.replace('CATEGORY:', '').strip()
                    return category
            
            OUTPUT_PREVIEW_LENGTH = 100
            self.logger.warning(f"No 'CATEGORY:' line found in output: {output[:OUTPUT_PREVIEW_LENGTH]}")
            return ""
        
        except Exception as e:
            self.logger.error(f"Error parsing category from output: {e}")
            return ""
    
    async def analyze_and_log_workflow(self, thread: AgentThread, run: Any) -> Tuple[list[dict], dict]:
        """
        Analyze 3-step workflow progress and log visual status.
        
        Args:
            thread: The agent thread
            run: The run object from agent execution
            
        Returns:
            tuple: (function_calls: list[dict], step_status: dict)
        """
        # Collect function calls from run steps
        function_calls = await self._collect_function_calls(thread, run.id)
        
        # Analyze workflow progress
        step_status = self._analyze_workflow_progress(function_calls)
        
        # Log visual workflow status
        self._log_workflow_status(step_status, function_calls)
        
        return function_calls, step_status
    
    async def cleanup(self):
        """
        Clean up agent resources by deleting agent and resetting state.
        """
        try:
            if self.agent and self.agents_client:
                await self.agents_client.delete_agent(self.agent.id)
                self.logger.info(f"Deleted agent: {self.agent.id}")
                self.agent = None  # Reset for potential reuse
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
            # Don't raise - cleanup errors shouldn't break the flow
    
    # =========================================================================
    # INITIALIZATION METHOD
    # =========================================================================
    
    async def initialize(self):
        """
        Initialize agent with auto function calling (official pattern).
        
        Creates the agent with AsyncFunctionTool and enables auto function calling.
        This is called internally by run() method.
        
        Following official pattern Option 3: AsyncFunctionTool + AsyncToolSet
        """
        # Register invoice functions as tools (async versions)
        functions = AsyncFunctionTool(invoice_functions_set)
        
        # Create toolset and add functions (official pattern option 3)
        toolset = AsyncToolSet()
        toolset.add(functions)
        
        # Enable auto function calling with toolset (official pattern)
        self.agents_client.enable_auto_function_calls(toolset)
        
        # Create agent with tools.definitions (official pattern from SDK)
        self.agent = await self.agents_client.create_agent(
            model=self.config.model_name,
            name="invoice-processing-agent",
            instructions=self.instructions,
            tools=functions.definitions
        )
        
        self.logger.info(f"Created invoice agent: {self.agent.id}")
    
    # =========================================================================
    # PRIVATE HELPER METHODS - Internal Workflow Analysis
    # =========================================================================
    
    def _extract_raw_output(self, tool_call: RunStepFunctionToolCall) -> Optional[Any]:
        """
        Extract raw output from function tool call using multiple strategies.
        
        NOTE: Accessing function outputs via private _data attribute is not officially 
        documented in Azure AI SDK. This is a workaround that may break with SDK updates.
        
        Args:
            tool_call: RunStepFunctionToolCall object
            
        Returns:
            Raw output or None if extraction failed
        """
        func_name = tool_call.function.name
        
        # Strategy 1: Private _data attribute (undocumented)
        try:
            data = getattr(tool_call.function, "_data", None)
            if data is not None:
                if isinstance(data, dict):
                    return data.get('output')
                else:
                    try:
                        return data.__getitem__('output')
                    except (KeyError, TypeError, AttributeError):
                        pass
        except Exception as e:
            self.logger.debug(f"Could not access _data.output for {func_name}: {e}")
        
        # Strategy 2: Direct output attribute (some SDK versions)
        try:
            return getattr(tool_call.function, 'output', None)
        except AttributeError:
            pass
        
        # Strategy 3: as_dict() method
        try:
            if hasattr(tool_call.function, 'as_dict'):
                func_dict = tool_call.function.as_dict()
                return func_dict.get('output')
        except Exception as e:
            self.logger.debug(f"Could not get output via as_dict() for {func_name}: {e}")
        
        self.logger.warning(
            f"Could not extract output for {func_name} - "
            f"output field may not be available in this SDK version"
        )
        return None
        
    def _normalize_output(self, output: Any, func_name: str) -> Any:
        """
        Normalize extracted output to standard Python types.
        
        Args:
            output: Raw output from function
            func_name: Function name for logging
            
        Returns:
            Normalized output (dict, list, str, etc.)
        """
        # Already standard Python type - return as-is
        if isinstance(output, (dict, list, str, int, float, bool, type(None))):
            return output
        
        # Try as_dict() for SDK objects
        if hasattr(output, 'as_dict') and callable(output.as_dict):
            try:
                normalized = output.as_dict()
                self.logger.debug(f"Normalized {func_name} output via as_dict()")
                return normalized
            except Exception as e:
                self.logger.debug(f"as_dict() failed for {func_name}: {e}")
        
        # Try dict() for dict-like objects with items()
        if hasattr(output, 'items') and callable(output.items):
            try:
                normalized = dict(output.items())
                self.logger.debug(f"Normalized {func_name} output via items()")
                return normalized
            except Exception as e:
                self.logger.debug(f"items() conversion failed for {func_name}: {e}")
        
        # Try list() for iterables (but not strings)
        if hasattr(output, '__iter__') and not isinstance(output, (str, bytes)):
            try:
                normalized = list(output)
                self.logger.debug(f"Normalized {func_name} output via list()")
                return normalized
            except Exception as e:
                self.logger.debug(f"list() conversion failed for {func_name}: {e}")
        
        # Cannot normalize - return as-is with warning
        self.logger.warning(f"Could not normalize {func_name} output type: {type(output).__name__}")
        return output
        
    def _extract_and_normalize_output(self, tool_call: RunStepFunctionToolCall) -> Optional[Any]:
        """
        Extract and normalize function output by combining extraction and normalization.
        
        Args:
            tool_call: RunStepFunctionToolCall object
            
        Returns:
            Normalized output or None if extraction failed
        """
        func_name = tool_call.function.name
        
        # Step 1: Extract raw output
        raw_output = self._extract_raw_output(tool_call)
        if raw_output is None:
            return None
            
        # Step 2: Normalize output
        return self._normalize_output(raw_output, func_name)
    
    async def _collect_function_calls(self, thread: AgentThread, run_id: str) -> list[dict]:
        """
        Collect all function calls with outputs from run steps.
        
        Args:
            thread: The agent thread
            run_id: The run ID to analyze
            
        Returns:
            List of dictionaries containing function call details with normalized outputs
        """
        function_calls = []
        run_steps = self.agents_client.run_steps.list(thread_id=thread.id, run_id=run_id)
        
        async for step in run_steps:
            if isinstance(step.step_details, RunStepToolCallDetails):
                for tool_call in step.step_details.tool_calls:
                    if isinstance(tool_call, RunStepFunctionToolCall):
                        # Extract and normalize output
                        output = self._extract_and_normalize_output(tool_call)
                        
                        function_calls.append({
                            "function_name": tool_call.function.name,
                            "arguments": tool_call.function.arguments,
                            "output": output,  # Normalized output or None
                            "timestamp": getattr(step, 'created_at', None)
                        })
        
        return function_calls
    
    def _analyze_workflow_progress(self, function_calls: list[dict]) -> dict:
        """
        Analyze the 3-step invoice workflow progress from function calls.
        
        Expected workflow:
        1. identify_invoice_category - Determine invoice type
        2. extract_invoice_fields - Extract data from invoice
        3. compare_invoice_fields - Compare extracted vs provided data
        
        Args:
            function_calls: List of function call dictionaries
            
        Returns:
            Dictionary with step completion status
        """
        step_status = {
            "step1_category": False,
            "step2_extraction": False, 
            "step3_comparison": False
        }
        
        for call in function_calls:
            func_name = call.get("function_name", "")
            if func_name == "identify_invoice_category":
                step_status["step1_category"] = True
            elif func_name == "extract_invoice_fields":
                step_status["step2_extraction"] = True
            elif func_name == "compare_invoice_fields":
                step_status["step3_comparison"] = True
        
        return step_status
    
    def _log_workflow_status(self, step_status: dict, function_calls: list[dict]):
        """
        Enhanced logging for workflow progress with visual indicators.
        
        Args:
            step_status: Dictionary with step completion flags
            function_calls: List of all function calls made
        """
        self.logger.info("=" * 60)
        self.logger.info(" AGENTIC WORKFLOW ANALYSIS")
        self.logger.info("=" * 60)
        self.logger.info(f"  Step 1 (Category ID):  {'[YES]' if step_status['step1_category'] else '[NO]'}")
        self.logger.info(f"  Step 2 (Extraction):   {'[YES]' if step_status['step2_extraction'] else '[NO]'}")
        self.logger.info(f"  Step 3 (Comparison):   {'[YES]' if step_status['step3_comparison'] else '[NO]'}")
        
        completed = sum(step_status.values())
        self.logger.info("-" * 60)
        self.logger.info(f"  Progress: {completed}/3 steps completed")
        self.logger.info(f"  Total function calls: {len(function_calls)}")
        
        # Show function call sequence
        if function_calls:
            self.logger.info("-" * 60)
            self.logger.info("  Function Call Sequence:")
            for i, call in enumerate(function_calls, 1):
                self.logger.info(f"    {i}. {call['function_name']}")
        
        self.logger.info("=" * 60)
    
    # =========================================================================
    # UTILITY METHODS
    # =========================================================================
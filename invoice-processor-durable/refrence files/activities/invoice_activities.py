"""
Invoice Activities - Handle all invoice-related processing activities
"""
import json
import os
from datetime import datetime
from utilities.logger import get_context_logger
from pathlib import Path
from typing import Dict, Any, List
from urllib.parse import urlparse
 
from agents.invoice import InvoiceAgent
from config.constants import WorkflowType
from config import AppConfig
from utilities.error_handling import handle_activity_error
from utilities.token_tracking import TokenTracker
 
# Configuration constants
OUTPUT_PREVIEW_LENGTH = 300
 
 
# ============================================================================
# Main Invoice Activity
# ============================================================================
 
@handle_activity_error
async def process_invoice_activity(workflow_data: Dict) -> Dict:
    """
    Process invoice requests using unified Invoice Agent with 3-function workflow.
   
    Activity responsibility:
    - Extract user_input and request_body from workflow_data
    - Pass only necessary data to agent (not orchestration_result)
    - Call InvoiceAgent to process the invoice
    - Receive structured results from step-level outputs (category, extraction, validation)
    - Combine agent results with orchestration metadata
    - Return structured response with complete data
   
    Args:
        workflow_data: Contains user_input, request_body, and orchestration_result
       
    Returns:
        Dict: Structured response with complete processing results including:
              - category: Invoice category
              - extraction_results: Complete extraction dict from Step 2
              - validation_results: Complete validation dict from Step 3
              - orchestration metadata
    """
    # Extract data components
    user_input = workflow_data.get("user_input", "")
    request_body = workflow_data.get("request_body", {})
    orchestration_result = workflow_data.get("orchestration_result", {})
    has_structured_data = bool(request_body)
   
    # Initialize context logger
    instance_id = workflow_data.get("instance_id", "unknown")
    logger = get_context_logger(__name__, instance_id=instance_id, workflow_type="invoice")
   
    # Early validation: Check new attachments format and ensure Invoice document exists
    if has_structured_data:
        attachments = request_body.get("Attachments", [])
       
        # Use reusable validation utility
        from utilities.file_utils import validate_invoice_attachment
        is_valid, invoice_attachment, error_message = validate_invoice_attachment(attachments)
       
        if not is_valid:
            return {
                "workflow_type": WorkflowType.INVOICE,
                "status": "error",
                "error_message": error_message,
                "orchestration": orchestration_result
            }
       
        logger.info(f"Invoice document confirmed: {invoice_attachment.get('FileName', 'Unknown')}")
   
    # Log processing start
    logger.info(f"Processing invoice {'with structured data' if has_structured_data else 'as text query'}")
   
    # Create token tracker (enabled flag controls behavior - no-op when disabled)
    config = AppConfig.get_instance()
    token_tracker = TokenTracker(True)
   
    # Prepare agent input (only user_input and request_body - no orchestration_result)
    agent_input = {
        "user_input": user_input,
        "request_body": request_body
    }
   
    # Process with agent (retry logic handled at agent level)
    structured_results, run_status, metadata = await InvoiceAgent.create_and_process(
        agent_input,
        token_tracker=token_tracker
    )
   
    # Extract results for downstream processing with safe None handling
    extraction_results = structured_results.get("extraction_results") or {}
    validation_results = structured_results.get("validation_results") or {}
    is_extraction_successful = structured_results.get("extraction_successful", False)
    
    # Check for errors in results with explicit None checks
    extraction_error = None
    if isinstance(extraction_results, dict):
        extraction_error = extraction_results.get("error")
    
    validation_error = None
    if isinstance(validation_results, dict):
        validation_error = validation_results.get("error")
    
    # Use run_status and extraction_successful as source of truth (handles retry scenarios)
    is_agent_successful = (
        run_status != "failed" and 
        is_extraction_successful and
        not structured_results.get("error")  # Check top-level error from agent
    )
    
    # Log final processing status
    if not is_agent_successful:
        logger.error(f"Agent processing failed with errors: extraction={extraction_error}, validation={validation_error}")
    else:
        logger.info("Agent processing succeeded")
   
    # Log extraction status
    if not is_extraction_successful:
        logger.warning(f"Structured data extraction incomplete: {structured_results.get('error', structured_results.get('warning', 'Unknown issue'))}")
   
    # === FILE SAVES: Using simplified structure (YYYYMMDD/instance_id/) ===
   
    # Step 1: Save request data
    if workflow_data and (config.enable_local_file_save or config.enable_blob_file_save):
        try:
            from utilities.file_utils import save_file_simple
           
            request_data = {
                "timestamp": datetime.now().isoformat(),
                "instance_id": instance_id,
                "request_body": workflow_data.get("request_body", {}),
                "orchestration_result": workflow_data.get("orchestration_result", {})
            }
           
            request_result = save_file_simple(
                instance_id=instance_id,
                filename="request.json",
                content=request_data,
                content_type="json"
            )
           
            if request_result["success"]:
                logger.info(f"Request saved: {request_result.get('blob_url') or request_result.get('local_path')}")
            else:
                logger.warning(f"Request save failed: {request_result.get('errors')}")
               
        except Exception as e:
            logger.error(f"Error saving request: {str(e)}")
 
    # Step 2 & 3: Save attachment file and results (only after successful processing)
    file_save_result = None
    results_save_result = None
   
    attachments = request_body.get("Attachments", [])
   
    # Step 2: Save attachment file with original filename
    if attachments:
        try:
            from utilities.file_utils import validate_invoice_attachment, sanitize_filename, save_file_simple
            is_valid, invoice_attachment, _ = validate_invoice_attachment(attachments)
           
            if is_valid and invoice_attachment:
                file_url = invoice_attachment.get("FileUrl", "")
                original_filename = invoice_attachment.get("FileName", "invoice_document.pdf")
               
                if file_url:
                    # Convert FileUrl to bytes
                    from sap.file_to_base64_converter import convert_fileurl_to_base64
                    import base64
                   
                    base64_content, _ = convert_fileurl_to_base64(file_url, original_filename)
                    file_bytes = base64.b64decode(base64_content)
                   
                    # Use sanitized original filename
                    safe_filename = sanitize_filename(original_filename)
                   
                    file_save_result = save_file_simple(
                        instance_id=instance_id,
                        filename=safe_filename,
                        content=file_bytes,
                        content_type="bytes"
                    )
                   
                    if file_save_result["success"]:
                        logger.info(f"Attachment saved: {safe_filename} ({len(file_bytes)/1024/1024:.2f} MB)")
                    else:
                        logger.warning(f"Attachment save failed: {file_save_result.get('errors')}")
                else:
                    logger.debug("FileUrl empty - skipping attachment save")
            else:
                logger.warning("No Invoice document found - skipping attachment save")
               
        except Exception as e:
            logger.error(f"Error saving attachment: {str(e)}")
            logger.warning("Continuing with results save despite attachment save failure")
    else:
        logger.warning("No Attachments found - skipping attachment save")
   
    # Step 3: Save extraction results with complete audit trail
    try:
        from utilities.file_utils import save_file_simple
        
        # Get token usage
        token_usage_info = {}
        if token_tracker.enabled:
            detailed_summary = token_tracker.get_detailed_summary(agent_name="InvoiceAgent")
            if detailed_summary:
                token_usage_info = detailed_summary
        
        # Always save actual results for complete audit trail (never replace with error strings)
        results_data = {
            "timestamp": datetime.now().isoformat(),
            "instance_id": instance_id,
            "extraction_results": extraction_results,  # Always save actual structured results
            "validation_results": validation_results,  # Always save actual structured results
            "processing_status": {
                "is_agent_successful": is_agent_successful,
                "run_status": run_status,
                "extraction_successful": is_extraction_successful,
                "extraction_error": str(extraction_error) if extraction_error else None,
                "validation_error": str(validation_error) if validation_error else None
            },
            "token_usage": token_usage_info,
            "attachment_saved": bool(file_save_result and file_save_result.get("success")),
            "retry_info": {
                "function_calls_count": metadata.get("function_calls_count", 0),
                "workflow_steps_completed": metadata.get("workflow_steps_completed", 0)
            }
        }
        
        results_save_result = save_file_simple(
            instance_id=instance_id,
            filename="results.json",
            content=results_data,
            content_type="json"
        )
       
        if results_save_result["success"]:
            logger.info(f"Results saved: {results_save_result.get('blob_url') or results_save_result.get('local_path')}")
        else:
            logger.warning(f"Results save failed: {results_save_result.get('errors')}")
           
    except Exception as e:
        logger.error(f"Error saving results: {str(e)}")
        logger.warning("Continuing with SAP posting despite results save failure")
 
    # Post validation results to SAP BTP (non-blocking)
    sap_posting_result = None
    try:
        from sap import SAPClient
        
        # Get instance_id from workflow_data
        instance_id = workflow_data.get("instance_id", "unknown")
        
        logger.info(f"Initiating SAP BTP posting for instance: {instance_id}")
        
        # Create SAP client and post validation results
        sap_client = SAPClient()
 
        # If agent failed, send only error data to SAP
        if not is_agent_successful:
            validation_results_for_sap = {
                "status": "error",
                "processing_errors": {
                    "extraction_error": str(extraction_error) if extraction_error else None,
                    "validation_error": str(validation_error) if validation_error else None,
                    "agent_run_status": run_status,
                    "extraction_successful": is_extraction_successful
                },
                "timestamp": datetime.now().isoformat(),
                "instance_id": instance_id
            }
            logger.warning(f"SAP posting error data only for failed instance: {instance_id}")
        else:
            # Agent succeeded - send actual validation results
            validation_results_for_sap = validation_results.copy() if isinstance(validation_results, dict) else {}
            validation_results_for_sap["status"] = "success"
            logger.info(f"SAP posting validation results for successful instance: {instance_id}")
        
        sap_posting_result = await sap_client.post_validation_results(validation_results_for_sap, instance_id)
        
        if sap_posting_result.get("success"):
            logger.info(f"SAP BTP posting completed successfully for instance: {instance_id}")
        else:
            error_msg = sap_posting_result.get("error", "Unknown error")
            logger.error(f"SAP BTP posting failed for instance: {instance_id} - {error_msg}")
    except Exception as e:
        logger.error(f"SAP BTP posting exception for instance {workflow_data.get('instance_id', 'unknown')}: {str(e)}")
        sap_posting_result = {
            "success": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }
 
    # Build response with structured data from agent
    response = {
        "workflow_type": WorkflowType.INVOICE,
        "status": "completed" if (run_status != "failed" and is_agent_successful) else "error",
       
        # === INVOICE PROCESSING RESULTS ===
        "invoice_processing": {
            "category": structured_results.get("category", ""),
            "extraction_results": extraction_results if is_agent_successful else extraction_error,
            "validation_results": validation_results if is_agent_successful else validation_error,
            "extraction_successful": is_extraction_successful,
        },
       
        # === SAP POSTING RESULTS ===
        "sap_posting": sap_posting_result if sap_posting_result else {
            "success": False,
            "error": "SAP posting not attempted (no validation results or agent failed)",
            "timestamp": datetime.now().isoformat()
        },
       
        # === ATTACHMENT FILE SAVE RESULTS (Audit Trail) ===
        "file_save": {
            "attachment": file_save_result if file_save_result else {"success": False, "error": "Not saved"},
            "results": results_save_result if results_save_result else {"success": False, "error": "Not saved"}
        },    
       
        # === METADATA ===
        "agent_success": is_agent_successful,
        "workflow_steps_completed": metadata.get("workflow_steps_completed", 3),
        "function_calls_count": metadata.get("function_calls_count", 0),
        "has_structured_data": metadata.get("has_structured_data", has_structured_data),
        "run_status": run_status,
       
        # === ORCHESTRATION DATA ===
        "orchestration": orchestration_result,
        "category_identified": orchestration_result.get("category", ""),
        "confidence": orchestration_result.get("confidence", 0.0),
        "reasoning": orchestration_result.get("reasoning", "Unified invoice agent processing with 3-function workflow"),
       
        "extraction_successful": is_extraction_successful,
        "user_input": user_input,
        "request_body": request_body,
        "specialized_agent": "unified_invoice_agent",
        "activity_name": "process_invoice_activity",
        "flow_type": WorkflowType.INVOICE
    }
   
    # Add warning/error messages if present
    if "warning" in structured_results:
        response["data_extraction_warning"] = structured_results["warning"]
    if "error" in structured_results:
        response["data_extraction_error"] = structured_results["error"]
   
    # Add specific extraction/validation errors if present
    extraction_error = extraction_results.get("error") if isinstance(extraction_results, dict) else None
    validation_error = validation_results.get("error") if isinstance(validation_results, dict) else None
   
    if extraction_error:
        response["extraction_error"] = extraction_error
    if validation_error:
        response["validation_error"] = validation_error  
   
    logger.info(f"Unified invoice agent processing completed - Status: {'SUCCESS' if is_agent_successful else 'FAILED'}")
       
    return response
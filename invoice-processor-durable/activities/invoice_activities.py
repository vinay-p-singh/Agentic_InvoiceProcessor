import azure.functions as func
import azure.durable_functions as df
import logging
import os
import json
from datetime import datetime
from agents.invoice_agent import InvoiceAgent

bp = func.Blueprint()

@bp.activity_trigger(input_name="args")
async def process_invoice_activity(args: dict):
    """
    Activity that uses the InvoiceAgent to extract and validate invoice data.
    """
    result = await InvoiceAgent.create_and_process(args)
    
    # Save response to processed_requests folder
    try:
        output_dir = "processed_requests"
        os.makedirs(output_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"invoice_response_{timestamp}.json"
        file_path = os.path.join(output_dir, filename)
        
        with open(file_path, "w") as f:
            json.dump(result, f, indent=2)
            
        logging.info(f"Saved processing result to {file_path}")
    except Exception as e:
        logging.error(f"Failed to save processing result: {e}")
        
    return result

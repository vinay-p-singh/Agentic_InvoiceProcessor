import azure.functions as func
import azure.durable_functions as df
import logging
from activities.invoice_activities import bp as invoice_bp

app = df.DFApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# Register Blueprints
app.register_functions(invoice_bp)

# -------------------------------------------------------------------
# Orchestrator
# -------------------------------------------------------------------
@app.orchestration_trigger(context_name="context")
def invoice_processing_orchestrator(context: df.DurableOrchestrationContext):
    input_data = context.get_input()
    
    # Support legacy/direct input
    pdf_path = input_data.get('pdf_path')
    expected_fields = input_data.get('expected_fields', {})

    # Support new complex input structure
    if not pdf_path and "Attachments" in input_data:
        attachments = input_data.get("Attachments")
        if attachments and len(attachments) > 0:
            # Use FileUrl as the local path (assuming file is present locally)
            pdf_path = attachments[0].get("FileUrl") or attachments[0].get("FileName")
            
    if not expected_fields and "Invoice" in input_data:
        expected_fields = input_data.get("Invoice")
    
    # Call the unified agent activity
    result = yield context.call_activity("process_invoice_activity", {
        "pdf_path": pdf_path, 
        "expected_fields": expected_fields
    })

    return result



# -------------------------------------------------------------------
# HTTP Starter
# -------------------------------------------------------------------
@app.route(route="orchestrators/process_invoice", auth_level=func.AuthLevel.ANONYMOUS)
@app.durable_client_input(client_name="client")
async def http_start(req: func.HttpRequest, client: df.DurableOrchestrationClient):
    try:
        req_body = req.get_json()
    except ValueError:
        return func.HttpResponse("Invalid JSON body", status_code=400)

    instance_id = await client.start_new("invoice_processing_orchestrator", client_input=req_body)
    logging.info(f"Started orchestration with ID = '{instance_id}'.")
    return client.create_check_status_response(req, instance_id)

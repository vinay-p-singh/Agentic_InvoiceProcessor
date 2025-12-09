import os

class AppConfig:
    _instance = None

    def __init__(self):
        self.project_endpoint = os.environ.get("PROJECT_CONNECTION_STRING") # Or whatever the env var is
        self.user_assigned_managed_identity = os.environ.get("AZURE_CLIENT_ID")
        self.azure_openai_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
        self.azure_openai_api_key = os.environ.get("AZURE_OPENAI_API_KEY")
        self.azure_openai_api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-05-01-preview")
        self.azure_openai_deployment_name = os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME")

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

class WorkflowType:
    INVOICE = "invoice"

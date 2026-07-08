import os
from dotenv import load_dotenv
from masfactory import OpenAIModel

load_dotenv()

model = OpenAIModel(
    api_key=os.getenv("OPENAI_API_KEY", ""),
    base_url=os.getenv("OPENAI_BASE_URL") or None,
    model_name=os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini"),
)
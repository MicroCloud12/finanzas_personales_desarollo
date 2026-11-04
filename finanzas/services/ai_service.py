# finanzas/services/ai_service.py
import os
import json
import time
import logging
import base64
from functools import lru_cache
import google.generativeai as genai
from mistralai import Mistral
from django.conf import settings
from .prompts import PROMPTS

logger = logging.getLogger(__name__)

class GeminiService:
    """
    Service for interacting with Google Gemini API.
    Optimized for JSON output and minimal token usage.
    """
    def __init__(self):
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self.model = genai.GenerativeModel(
            "gemini-3.1-flash-lite",
            system_instruction="Extract financial data. Output JSON strictly. No extra text.",
            generation_config=genai.types.GenerationConfig(
                temperature=0.0,
                response_mime_type="application/json", # CRITICAL: Native JSON output
            )
        )
        self.safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        ]

    # Errores de la API que vale la pena reintentar (lentitud o saturación, no un fallo del contenido)
    ERRORES_TRANSITORIOS = ('504', '503', '429', 'Deadline', 'Unavailable', 'ResourceExhausted', 'timed out', 'timeout')

    @classmethod
    def es_transitorio(cls, error) -> bool:
        return any(t.lower() in str(error).lower() for t in cls.ERRORES_TRANSITORIOS)

    def _generate_and_parse(self, prompt: str, content) -> dict:
        inputs = [prompt, content] if content else prompt
        ultimo_error = None
        for intento in range(3):
            try:
                # Las imágenes tardan: 120 s de tope por llamada, y dos reintentos si la API está lenta.
                response = self.model.generate_content(
                    inputs, safety_settings=self.safety_settings,
                    request_options={"timeout": 120}
                )
                # Since response_mime_type="application/json", response.text is guaranteed valid JSON
                return json.loads(response.text)
            except Exception as e:
                ultimo_error = e
                if not self.es_transitorio(e) or intento == 2:
                    break
                espera = 10 * (intento + 1)
                logger.warning(f"Gemini lento o saturado ({e}); reintento {intento + 1}/2 en {espera}s")
                time.sleep(espera)
        logger.error(f"Gemini API Error: {ultimo_error}")
        return {"error": str(ultimo_error), "transitorio": self.es_transitorio(ultimo_error)}

    def extract_data(self, prompt_name: str, file_data, mime_type: str, context: str = "") -> dict:
        if prompt_name not in PROMPTS:
            raise ValueError(f"Prompt '{prompt_name}' not found.")
            
        raw_prompt = PROMPTS[prompt_name]
        prompt = raw_prompt.format(context_str=context) if "{context_str}" in raw_prompt else raw_prompt
        return self._generate_and_parse(prompt, {"mime_type": mime_type, "data": file_data})

    def extract_from_text(self, prompt_name: str, text: str, context: str = "") -> dict:
        if prompt_name not in PROMPTS:
            raise ValueError(f"Prompt '{prompt_name}' not found.")
            
        raw_prompt = PROMPTS[prompt_name]
        
        # Build prompt
        prompt = raw_prompt
        if "{context_str}" in prompt:
            prompt = prompt.replace("{context_str}", context)
        if "{text_content}" in prompt:
            prompt = prompt.replace("{text_content}", text)
        else:
            prompt += f"\n\nOCR:\n{text}"

        return self._generate_and_parse(prompt, None)

@lru_cache(maxsize=1)
def get_gemini_service() -> GeminiService:
    return GeminiService()

class MistralOCRService:
    """Service for Mistral OCR processing."""
    def __init__(self):
        self.api_key = os.getenv("MISTRAL_API_KEY") 
        self.client = Mistral(api_key=self.api_key) if self.api_key else None

    def get_text_from_image(self, file_content_bytes, mime_type="image/jpeg"):
        if not self.client:
            return {"error": "Mistral API Key missing"}

        # ponytail: la foto va tal cual; Mistral OCR ya endereza y limpia. Si algún ticket sale mal, preprocesar con PIL.
        b64 = base64.b64encode(file_content_bytes).decode('utf-8')
        if 'pdf' in mime_type:
            document = {"type": "document_url", "document_url": f"data:application/pdf;base64,{b64}"}
        else:
            document = {"type": "image_url", "image_url": f"data:{mime_type};base64,{b64}"}

        try:
            ocr_response = self.client.ocr.process(
                model="mistral-ocr-latest",
                document=document,
                include_image_base64=False
            )
            json_data = json.loads(ocr_response.model_dump_json())
            
            full_markdown = "".join([page.get("markdown", "") + "\n" for page in json_data.get("pages", [])])
            return {"text_content": full_markdown, "raw_json": json_data}
        except Exception as e:
            logger.error(f"Mistral API Error: {e}")
            return {"error": str(e)}

# finanzas/services/ai_service.py
import os
import json
import logging
import base64
import numpy as np
import cv2
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
            "gemini-2.5-flash-lite",
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

    def _prepare_content(self, file_data, mime_type: str):
        return {"mime_type": mime_type, "data": file_data}

    def _generate_and_parse(self, prompt: str, content) -> dict:
        inputs = [prompt, content] if content else prompt
        try:
            response = self.model.generate_content(inputs, safety_settings=self.safety_settings)
            # Since response_mime_type="application/json", response.text is guaranteed valid JSON
            return json.loads(response.text)
        except Exception as e:
            logger.error(f"Gemini API Error: {e}")
            return {"error": "Failed to parse AI response or API error"}

    def extract_data(self, prompt_name: str, file_data, mime_type: str, context: str = "") -> dict:
        if prompt_name not in PROMPTS:
            raise ValueError(f"Prompt '{prompt_name}' not found.")
            
        raw_prompt = PROMPTS[prompt_name]
        prompt = raw_prompt.format(context_str=context) if "{context_str}" in raw_prompt else raw_prompt
        prepared_content = self._prepare_content(file_data, mime_type)
        return self._generate_and_parse(prompt, prepared_content)

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

_gemini_singleton = None
def get_gemini_service() -> GeminiService:
    global _gemini_singleton
    if _gemini_singleton is None:
        _gemini_singleton = GeminiService()
    return _gemini_singleton

class MistralOCRService:
    """Service for Mistral OCR processing."""
    def __init__(self):
        self.api_key = os.getenv("MISTRAL_API_KEY") 
        self.client = Mistral(api_key=self.api_key) if self.api_key else None

    def _order_points(self, pts):
        rect = np.zeros((4, 2), dtype="float32")
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]
        rect[2] = pts[np.argmax(s)]
        diff = np.diff(pts, axis=1)
        rect[1] = pts[np.argmin(diff)]
        rect[3] = pts[np.argmax(diff)]
        return rect

    def _four_point_transform(self, image, pts):
        rect = self._order_points(pts)
        (tl, tr, br, bl) = rect
        widthA = np.sqrt(((br[0] - bl[0]) ** 2) + ((br[1] - bl[1]) ** 2))
        widthB = np.sqrt(((tr[0] - tl[0]) ** 2) + ((tr[1] - tl[1]) ** 2))
        maxWidth = max(int(widthA), int(widthB))
        heightA = np.sqrt(((tr[0] - br[0]) ** 2) + ((tr[1] - br[1]) ** 2))
        heightB = np.sqrt(((tl[0] - bl[0]) ** 2) + ((tl[1] - bl[1]) ** 2))
        maxHeight = max(int(heightA), int(heightB))
        dst = np.array([[0, 0], [maxWidth - 1, 0], [maxWidth - 1, maxHeight - 1], [0, maxHeight - 1]], dtype="float32")
        M = cv2.getPerspectiveTransform(rect, dst)
        return cv2.warpPerspective(image, M, (maxWidth, maxHeight))

    def _preprocess_image_advanced(self, file_bytes):
        try:
            nparr = np.frombuffer(file_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is None: return None

            detect_h = 800.0
            h, w = img.shape[:2]
            ratio = h / detect_h
            orig = img.copy()
            image_resized = cv2.resize(img, (int(w / ratio), int(detect_h))) if h > detect_h else img.copy()

            gray = cv2.cvtColor(image_resized, cv2.COLOR_BGR2GRAY)
            blur = cv2.GaussianBlur(gray, (5, 5), 0)
            _, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
            thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=2)
            thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=2)

            cnts, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cnts = sorted(cnts, key=cv2.contourArea, reverse=True)[:5]
            
            pts_for_transform = None
            if len(cnts) > 0:
                c = cnts[0]
                peri = cv2.arcLength(c, True)
                approx = cv2.approxPolyDP(c, 0.04 * peri, True)
                if len(approx) == 4:
                    pts_for_transform = approx.reshape(4, 2) * ratio
                else:
                    rect = cv2.minAreaRect(c)
                    box = np.int32(cv2.boxPoints(rect))
                    pts_for_transform = box.astype("float32") * ratio

            warped = self._four_point_transform(orig, pts_for_transform) if pts_for_transform is not None else orig
            warped_gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY) if len(warped.shape) == 3 else warped
            denoised = cv2.fastNlMeansDenoising(warped_gray, None, 10, 7, 21)
            processed_img = cv2.adaptiveThreshold(denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 21, 10)

            fill_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
            processed_img = cv2.morphologyEx(processed_img, cv2.MORPH_CLOSE, fill_kernel, iterations=2)
            processed_img = cv2.dilate(processed_img, fill_kernel, iterations=1)
            
            _, buffer = cv2.imencode('.jpg', processed_img)
            return base64.b64encode(buffer).decode('utf-8')
        except Exception as e:
            logger.error(f"Image preprocessing error: {e}")
            return None

    def get_text_from_image(self, file_content_bytes, mime_type="image/jpeg"):
        if not self.client:
            return {"error": "Mistral API Key missing"}

        base64_image = base64.b64encode(file_content_bytes).decode('utf-8') if 'pdf' in mime_type else self._preprocess_image_advanced(file_content_bytes)
        if not base64_image:
            base64_image = base64.b64encode(file_content_bytes).decode('utf-8')

        try:
            ocr_response = self.client.ocr.process(
                model="mistral-ocr-latest",
                document={"type": "image_url", "image_url": f"data:image/jpeg;base64,{base64_image}"},
                include_image_base64=False
            )
            json_data = json.loads(ocr_response.model_dump_json())
            
            full_markdown = "".join([page.get("markdown", "") + "\n" for page in json_data.get("pages", [])])
            return {"text_content": full_markdown, "raw_json": json_data}
        except Exception as e:
            logger.error(f"Mistral API Error: {e}")
            return {"error": str(e)}

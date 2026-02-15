"""HuggingFace model inference adapter.

This module provides the HuggingFaceAdapter class for calling HuggingFace
models through the Inference API, supporting various task types including
NLP, computer vision, and audio processing.
"""

import base64
import io
import os
import uuid
import requests
from io import BytesIO
from typing import Dict, Optional
from PIL import Image
from pydub import AudioSegment
from diffusers.utils import load_image
from huggingface_hub import InferenceClient


class HuggingFaceAdapter:
    """HuggingFace model inference adapter.
    
    This adapter handles inference calls to HuggingFace models through
    the Inference API, supporting multiple task types and data formats.
    """
    
    def __init__(self, token: Optional[str] = None, proxy: Optional[str] = None):
        """Initialize HuggingFace adapter.
        
        Args:
            token: HuggingFace access token.
            proxy: Proxy server address (optional).
        """
        self.token = token or os.getenv("HUGGINGFACE_ACCESS_TOKEN")
        if not self.token:
            raise ValueError("HuggingFace token is required. Set HUGGINGFACE_ACCESS_TOKEN environment variable.")
        
        self.proxies = {"https": proxy} if proxy else None
        self.headers = {
            "Authorization": f"Bearer {self.token}"
        }
    
    def inference(
        self,
        model_id: str,
        data: dict[str, object],
        task: str
    ) -> dict[str, object]:
        """
        Call HuggingFace model for inference.
        
        Args:
            model_id: Model ID.
            data: Input data.
            task: Task type.
        
        Returns:
            Inference result dictionary.
        """
        # Use new InferenceClient (supports router.huggingface.co)
        task_url = f"https://router.huggingface.co/models/{model_id}"
        client = InferenceClient(model=model_id, token=self.token)
        
        try:
            # NLP tasks
            if task == "question-answering":
                inputs = {
                    "question": data["text"],
                    "context": data.get("context", "")
                }
                result = client.post(json={"inputs": inputs})
            elif task == "sentence-similarity":
                inputs = {
                    "source_sentence": data["text1"],
                    "target_sentence": data["text2"]
                }
                result = client.post(json={"inputs": inputs})
            elif task in [
                "text-classification", "token-classification", "text2text-generation",
                "summarization", "translation", "conversational", "text-generation"
            ]:
                inputs = data["text"]
                result = client.post(json={"inputs": inputs})
            
            # Computer vision tasks
            elif task in ["visual-question-answering", "document-question-answering"]:
                img_url = data["image"]
                text = data["text"]
                img_data = self._image_to_bytes(img_url)
                img_base64 = base64.b64encode(img_data).decode("utf-8")
                json_data = {
                    "inputs": {
                        "question": text,
                        "image": img_base64
                    }
                }
                result = requests.post(task_url, headers=self.headers, json=json_data, proxies=self.proxies).json()
            
            elif task == "image-to-image":
                img_url = data["image"]
                img_data = self._image_to_bytes(img_url)
                self.headers["Content-Length"] = str(len(img_data))
                r = requests.post(task_url, headers=self.headers, data=img_data, proxies=self.proxies)
                result = r.json()
                if "path" in result:
                    result["generated image"] = result.pop("path")
            
            elif task == "text-to-image":
                inputs = data["text"]
                # Directly use requests to call router API
                # Note: router API endpoint format may differ, need to try different formats
                try:
                    # Try using router API standard endpoint
                    api_url = f"https://router.huggingface.co/models/{model_id}"
                    response = requests.post(
                        api_url,
                        headers=self.headers,
                        json={"inputs": inputs},
                        proxies=self.proxies,
                        timeout=60  # Image generation may take longer
                    )
                    
                    if response.status_code == 200:
                        # Save image
                        name = str(uuid.uuid4())[:4]
                        os.makedirs("outputs/images", exist_ok=True)
                        img_path = f"outputs/images/{name}.png"
                        with open(img_path, 'wb') as f:
                            f.write(response.content)
                        result = {"generated image": img_path}
                    elif response.status_code == 404:
                        # 404 may indicate incorrect endpoint format, try using InferenceClient
                        try:
                            # Try using InferenceClient
                            img = client.post(json={"inputs": inputs})
                            if hasattr(img, 'save'):
                                name = str(uuid.uuid4())[:4]
                                os.makedirs("outputs/images", exist_ok=True)
                                img.save(f"outputs/images/{name}.png")
                                result = {"generated image": f"outputs/images/{name}.png"}
                            else:
                                result = {"error": {"message": f"Image generation model {model_id} unavailable (404 Not Found). Model ID may be incorrect, model may not support inference API, or different calling method needed."}}
                        except Exception as e3:
                            result = {"error": {"message": f"Image generation model {model_id} unavailable (404 Not Found). Error details: {str(e3)}"}}
                    elif response.status_code == 410:
                        # 410 indicates resource deleted
                        result = {"error": {"message": f"Image generation service temporarily unavailable (model endpoint deleted). Please retry later or use other image generation service."}}
                    else:
                        error_text = response.text[:200] if hasattr(response, 'text') else str(response.status_code)
                        result = {"error": {"message": f"API returned status {response.status_code}: {error_text}"}}
                except Exception as e:
                    result = {"error": {"message": f"Image generation failed: {str(e)}"}}
            
            elif task == "image-segmentation":
                img_url = data["image"]
                img_data = self._image_to_bytes(img_url)
                image = Image.open(BytesIO(img_data))
                # Use requests to directly call API for raw response
                api_url = f"https://router.huggingface.co/models/{model_id}"
                response = requests.post(
                    api_url,
                    headers=self.headers,
                    data=img_data,
                    proxies=self.proxies,
                    timeout=30
                )
                if response.status_code == 200:
                    predicted = response.json()
                else:
                    predicted = []
                
                # Ensure predicted is in list format
                if not isinstance(predicted, list):
                    predicted = [predicted] if predicted else []
                
                # Process segmentation results (simplified version, actual processing may be more complex)
                import random
                colors = []
                for i in range(len(predicted)):
                    colors.append((random.randint(100, 255), random.randint(100, 255), random.randint(100, 255), 155))
                for i, pred in enumerate(predicted):
                    if isinstance(pred, dict) and "mask" in pred:
                        mask_data = pred.get("mask")
                        if isinstance(mask_data, str):
                            mask = mask_data.encode("utf-8")
                            mask = base64.b64decode(mask)
                            mask = Image.open(BytesIO(mask), mode='r')
                            mask = mask.convert('L')
                            layer = Image.new('RGBA', mask.size, colors[i])
                            image.paste(layer, (0, 0), mask)
                name = str(uuid.uuid4())[:4]
                os.makedirs("outputs/images", exist_ok=True)
                image.save(f"outputs/images/{name}.jpg")
                result = {
                    "generated image": f"outputs/images/{name}.jpg",
                    "predicted": predicted
                }
            
            elif task == "object-detection":
                img_url = data["image"]
                img_data = self._image_to_bytes(img_url)
                # Use requests to directly call API for raw response
                api_url = f"https://router.huggingface.co/models/{model_id}"
                response = requests.post(
                    api_url,
                    headers=self.headers,
                    data=img_data,
                    proxies=self.proxies,
                    timeout=30
                )
                # Manually parse JSON response
                if response.status_code == 200:
                    predicted = response.json()
                else:
                    predicted = []
                
                # Process detection results (simplified version)
                image = Image.open(BytesIO(img_data))
                from PIL import ImageDraw
                import random
                draw = ImageDraw.Draw(image)
                
                # Ensure predicted is in list format
                if not isinstance(predicted, list):
                    predicted = [predicted] if predicted else []
                
                labels = [item.get('label', '') for item in predicted if isinstance(item, dict)]
                color_map = {}
                for label in labels:
                    if label and label not in color_map:
                        color_map[label] = (random.randint(0, 255), random.randint(0, 100), random.randint(0, 255))
                
                for item in predicted:
                    if isinstance(item, dict) and "box" in item:
                        box = item["box"]
                        label = item.get("label", "unknown")
                        color = color_map.get(label, (255, 0, 0))
                        draw.rectangle(
                            ((box["xmin"], box["ymin"]), (box["xmax"], box["ymax"])),
                            outline=color, width=2
                        )
                        draw.text((box["xmin"]+5, box["ymin"]-15), label, fill=color)
                
                name = str(uuid.uuid4())[:4]
                os.makedirs("outputs/images", exist_ok=True)
                image.save(f"outputs/images/{name}.jpg")
                result = {
                    "generated image": f"outputs/images/{name}.jpg",
                    "predicted": predicted
                }
            
            elif task == "image-classification":
                img_url = data["image"]
                img_data = self._image_to_bytes(img_url)
                # Use InferenceClient's post method
                try:
                    result = client.post(data=img_data)
                except Exception as e:
                    # If fails, use requests to directly call API
                    try:
                        api_url = f"https://router.huggingface.co/models/{model_id}"
                        response = requests.post(
                            api_url,
                            headers=self.headers,
                            data=img_data,
                            proxies=self.proxies,
                            timeout=30
                        )
                        if response.status_code == 200:
                            result = response.json()
                        else:
                            result = {"error": {"message": f"API returned status {response.status_code}"}}
                    except Exception as e2:
                        result = {"error": {"message": f"Image classification failed: {str(e2)}"}}
            
            elif task == "image-to-text":
                img_url = data["image"]
                img_data = self._image_to_bytes(img_url)
                self.headers["Content-Length"] = str(len(img_data))
                r = requests.post(task_url, headers=self.headers, data=img_data, proxies=self.proxies)
                result = {}
                if r.status_code == 200:
                    response_json = r.json()
                    if isinstance(response_json, list) and len(response_json) > 0:
                        if "generated_text" in response_json[0]:
                            result["generated text"] = response_json[0].pop("generated_text")
            
            # Audio tasks
            elif task == "text-to-speech":
                inputs = data["text"]
                # Use requests to directly call API for raw response (audio file)
                api_url = f"https://router.huggingface.co/models/{model_id}"
                response = requests.post(
                    api_url,
                    headers=self.headers,
                    json={"inputs": inputs},
                    proxies=self.proxies,
                    timeout=30
                )
                name = str(uuid.uuid4())[:4]
                os.makedirs("outputs/audios", exist_ok=True)
                with open(f"outputs/audios/{name}.flac", "wb") as f:
                    f.write(response.content)
                result = {"generated audio": f"outputs/audios/{name}.flac"}
            
            elif task in ["automatic-speech-recognition", "audio-to-audio", "audio-classification"]:
                audio_url = data["audio"]
                audio_data = requests.get(audio_url, timeout=10, proxies=self.proxies).content
                # Use requests to directly call API for raw response
                api_url = f"https://router.huggingface.co/models/{model_id}"
                response = requests.post(
                    api_url,
                    headers=self.headers,
                    data=audio_data,
                    proxies=self.proxies,
                    timeout=30
                )
                result = response.json()
                if task == "audio-to-audio":
                    content = None
                    audio_type = None
                    if isinstance(result, list) and len(result) > 0:
                        for k, v in result[0].items():
                            if k == "blob":
                                content = base64.b64decode(v.encode("utf-8"))
                            if k == "content-type":
                                audio_type = "audio/flac".split("/")[-1]
                    if content and audio_type:
                        audio = AudioSegment.from_file(BytesIO(content))
                        name = str(uuid.uuid4())[:4]
                        os.makedirs("outputs/audios", exist_ok=True)
                        audio.export(f"outputs/audios/{name}.{audio_type}", format=audio_type)
                        result = {"generated audio": f"outputs/audios/{name}.{audio_type}"}
            
            else:
                result = {"error": {"message": f"Unsupported task type: {task}"}}
            
            return result
        
        except (requests.RequestException, ValueError, KeyError, OSError) as e:
            return {"error": {"message": str(e)}}
    
    def _image_to_bytes(self, img_url: str) -> bytes:
        """
        Converts an image URL to byte data.
        
        Args:
            img_url: Image URL or path.
        
        Returns:
            Image byte data.
        """
        if img_url.startswith("http"):
            response = requests.get(img_url, timeout=10, proxies=self.proxies)
            return response.content
        else:
            # Local file path
            from pathlib import Path
            img_path = Path(img_url)
            
            # If path doesn't exist, try looking in outputs directory
            if not img_path.exists():
                # Try outputs directory
                outputs_path = Path("outputs") / img_path.name
                if outputs_path.exists():
                    img_path = outputs_path
                else:
                    # Try current directory
                    if Path(img_path.name).exists():
                        img_path = Path(img_path.name)
                    else:
                        raise FileNotFoundError(f"Image file not found: {img_url}")
            
            # Read image file
            with open(img_path, 'rb') as f:
                return f.read()


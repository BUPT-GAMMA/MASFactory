"""Local model inference adapter.

This module provides the LocalAdapter class for calling locally deployed
models through a local inference server.
"""

import requests
from typing import Dict, Optional
from PIL import Image, ImageDraw
from diffusers.utils import load_image


class LocalAdapter:
    """Local model server inference adapter.
    
    This adapter handles inference calls to locally deployed models
    through a local inference server endpoint.
    """
    
    def __init__(self, host: str = "localhost", port: int = 8005):
        """Initialize local adapter.
        
        Args:
            host: Local model server host.
            port: Local model server port.
        """
        self.base_url = f"http://{host}:{port}"
    
    def inference(
        self,
        model_id: str,
        data: dict[str, object],
        task: str
    ) -> dict[str, object]:
        """Call local model for inference.
        
        Args:
            model_id: Model ID.
            data: Input data.
            task: Task type.
        
        Returns:
            Inference result.
        """
        task_url = f"{self.base_url}/models/{model_id}"
        
        try:
            # ControlNet-related tasks
            if model_id.startswith("lllyasviel/sd-controlnet-"):
                img_url = data["image"]
                text = data.get("text", "")
                response = requests.post(task_url, json={"img_url": img_url, "text": text})
                results = response.json()
                if "path" in results:
                    results["generated image"] = results.pop("path")
                return results
            
            if model_id.endswith("-control"):
                img_url = data["image"]
                response = requests.post(task_url, json={"img_url": img_url})
                results = response.json()
                if "path" in results:
                    results["generated image"] = results.pop("path")
                return results
            
            # Video generation
            if task == "text-to-video":
                response = requests.post(task_url, json=data)
                results = response.json()
                if "path" in results:
                    results["generated video"] = results.pop("path")
                return results
            
            # NLP tasks
            if task in ["question-answering", "sentence-similarity"]:
                response = requests.post(task_url, json=data)
                return response.json()
            
            if task in [
                "text-classification", "token-classification", "text2text-generation",
                "summarization", "translation", "conversational", "text-generation"
            ]:
                response = requests.post(task_url, json=data)
                return response.json()
            
            # Computer vision tasks
            if task == "depth-estimation":
                img_url = data["image"]
                response = requests.post(task_url, json={"img_url": img_url})
                results = response.json()
                if "path" in results:
                    results["generated image"] = results.pop("path")
                return results
            
            if task == "image-segmentation":
                img_url = data["image"]
                response = requests.post(task_url, json={"img_url": img_url})
                results = response.json()
                if "path" in results:
                    results["generated image"] = results.pop("path")
                return results
            
            if task == "image-to-image":
                img_url = data["image"]
                response = requests.post(task_url, json={"img_url": img_url})
                results = response.json()
                if "path" in results:
                    results["generated image"] = results.pop("path")
                return results
            
            if task == "text-to-image":
                response = requests.post(task_url, json=data)
                results = response.json()
                if "path" in results:
                    results["generated image"] = results.pop("path")
                return results
            
            if task == "object-detection":
                img_url = data["image"]
                response = requests.post(task_url, json={"img_url": img_url})
                predicted = response.json()
                if "error" in predicted:
                    return predicted
                # Draw detection boxes
                image = load_image(img_url)
                draw = ImageDraw.Draw(image)
                labels = [item['label'] for item in predicted]
                import random
                color_map = {}
                for label in labels:
                    if label not in color_map:
                        color_map[label] = (random.randint(0, 255), random.randint(0, 100), random.randint(0, 255))
                for label in predicted:
                    if "box" in label:
                        box = label["box"]
                        draw.rectangle(
                            ((box["xmin"], box["ymin"]), (box["xmax"], box["ymax"])),
                            outline=color_map[label["label"]], width=2
                        )
                        draw.text((box["xmin"]+5, box["ymin"]-15), label["label"], fill=color_map[label["label"]])
                import uuid
                name = str(uuid.uuid4())[:4]
                import os
                os.makedirs("outputs/images", exist_ok=True)
                image.save(f"outputs/images/{name}.jpg")
                results = {
                    "generated image": f"outputs/images/{name}.jpg",
                    "predicted": predicted
                }
                return results
            
            if task in [
                "image-classification", "image-to-text",
                "document-question-answering", "visual-question-answering"
            ]:
                img_url = data["image"]
                text = data.get("text")
                response = requests.post(task_url, json={"img_url": img_url, "text": text})
                results = response.json()
                return results
            
            # Audio tasks
            if task == "text-to-speech":
                response = requests.post(task_url, json=data)
                results = response.json()
                if "path" in results:
                    results["generated audio"] = results.pop("path")
                return results
            
            if task in ["automatic-speech-recognition", "audio-to-audio", "audio-classification"]:
                audio_url = data["audio"]
                response = requests.post(task_url, json={"audio_url": audio_url})
                return response.json()
            
            return {"error": {"message": f"Unsupported task type: {task}"}}
        
        except (requests.RequestException, ValueError, KeyError, OSError) as e:
            return {"error": {"message": str(e)}}


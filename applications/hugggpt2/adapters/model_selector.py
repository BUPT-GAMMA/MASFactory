"""Model selector: checks model availability and selects best models.

This module provides the ModelSelector class, which checks the availability
of models on both HuggingFace and local servers, and selects the best
candidates for each task.
"""

import requests
import threading
from queue import Queue, Empty
from typing import List, Dict, Optional


class ModelSelector:
    """Model selector: checks model availability.
    
    This class manages checking model availability across different
    inference endpoints (HuggingFace, local servers) and provides
    lists of available models for selection.
    """
    
    def __init__(
        self,
        huggingface_token: Optional[str] = None,
        local_server: Optional[str] = None,
        proxy: Optional[str] = None
    ):
        """Initialize model selector.
        
        Args:
            huggingface_token: HuggingFace access token.
            local_server: Local model server address (format: http://host:port).
            proxy: Proxy server address (optional).
        """
        self.huggingface_token = huggingface_token
        self.local_server = local_server
        self.proxies = {"https": proxy} if proxy else None
        self.hf_headers = {}
        if huggingface_token:
            self.hf_headers = {"Authorization": f"Bearer {huggingface_token}"}
    
    def get_available_models(
        self,
        candidates: List[dict[str, object]],
        topk: int = 5,
        inference_mode: str = "hybrid"
    ) -> Dict[str, List[str]]:
        """
        Gets a list of available models from candidates.
        
        Args:
            candidates: List of candidate models.
            topk: Maximum number of models to return.
            inference_mode: Inference mode ("local", "huggingface", "hybrid").
        
        Returns:
            Dictionary with "local" and "huggingface" lists of available model IDs.
        """
        all_available_models = {"local": [], "huggingface": []}
        threads = []
        result_queue = Queue()
        
        for candidate in candidates:
            model_id = candidate["id"]
            
            # Check HuggingFace models
            # Note: New router API may not support /status endpoint
            # For HuggingFace models, we assume they are all available, let InferenceClient handle errors during actual calls
            if inference_mode != "local":
                # New router API may not support status checks, directly assume models are available
                # InferenceClient will handle unavailable models during actual calls
                all_available_models["huggingface"].append(model_id)
                # If enough models found, can exit early
                if len(all_available_models["local"] + all_available_models["huggingface"]) >= topk:
                    break
            
            # Check local models
            if inference_mode != "huggingface" and self.local_server:
                local_status_url = f"{self.local_server}/status/{model_id}"
                thread = threading.Thread(
                    target=self._get_model_status,
                    args=(model_id, local_status_url, {}, result_queue, "local")
                )
                threads.append(thread)
                thread.start()
        
        # Process local model status checks (if enabled)
        result_count = len(threads)
        processed_models = set()
        
        while result_count > 0:
            try:
                model_id, status, endpoint_type = result_queue.get(timeout=2)
                if status and model_id not in processed_models:
                    all_available_models[endpoint_type].append(model_id)
                    processed_models.add(model_id)
                result_count -= 1
                
                # If enough models found, exit early
                if len(all_available_models["local"] + all_available_models["huggingface"]) >= topk:
                    break
            except Empty:
                # Queue is empty, thread may not have completed or timed out, continue waiting
                # Don't decrease result_count, give threads more time
                continue
            except (ValueError, KeyError):
                result_count -= 1
                continue
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join(timeout=1)
        
        # Remove duplicates from HuggingFace model list
        all_available_models["huggingface"] = list(set(all_available_models["huggingface"]))
        all_available_models["local"] = list(set(all_available_models["local"]))
        
        return all_available_models
    
    def _get_model_status(
        self,
        model_id: str,
        url: str,
        headers: Dict[str, str],
        queue: Queue,
        endpoint_type: str
    ) -> None:
        """
        Checks model status.
        
        Args:
            model_id: Model ID.
            url: Status check URL.
            headers: HTTP request headers.
            queue: Result queue.
            endpoint_type: Endpoint type ("local" or "huggingface").
        """
        try:
            if "huggingface" in url:
                r = requests.get(url, headers=headers, proxies=self.proxies, timeout=10)
            else:
                r = requests.get(url, timeout=10)
            
            if r.status_code == 200:
                data = r.json()
                # HuggingFace API may return different formats
                # Check multiple possible fields
                is_loaded = False
                if isinstance(data, dict):
                    # Check loaded field
                    if "loaded" in data:
                        is_loaded = data["loaded"]
                    # Or check state field
                    elif "state" in data:
                        is_loaded = data["state"] == "loaded" or data["state"] == "ready"
                    # Or check gpu field (indicates model is loaded)
                    elif "gpu" in data:
                        is_loaded = True
                    # Or check compute_type field (some API versions)
                    elif "compute_type" in data:
                        is_loaded = True
                
                if is_loaded:
                    queue.put((model_id, True, endpoint_type))
                    return
                # else:
                # Status code 200 but model not loaded
                pass
            
            # Status check failed
            queue.put((model_id, False, None))
        except requests.Timeout:
            # Timeout is not a complete failure, may just be slow network
            queue.put((model_id, False, None))
        except requests.RequestException as e:
            # Network error, log but don't raise exception
            queue.put((model_id, False, None))
        except (ValueError, KeyError) as e:
            # JSON parsing error or other error
            queue.put((model_id, False, None))
        except Exception as e:
            # Catch all other exceptions, ensure thread doesn't fail silently
            queue.put((model_id, False, None))


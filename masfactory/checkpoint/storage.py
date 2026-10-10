from pathlib import Path
import json
from datetime import datetime

class FileCheckpointStorage:
    def __init__(self,checkpoint_dir:str):
        self.checkpoint_dir=Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True,exist_ok=True)

    def save(self,checkpoint_state:dict)->str:
        timestamp=datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path=self.checkpoint_dir/f"checkpoint{timestamp}.json"
        with path.open('w',encoding="utf-8") as f:
            json.dump(checkpoint_state,f,ensure_ascii=False,indent=2)
        return str(path)

    def load(self,checkpoint_path:str)->dict:
        path=Path(checkpoint_path)
        with path.open('r',encoding="utf-8") as f:
            return json.load(f)
        
    def get_last_path(self):
        paths = list(self.checkpoint_dir.glob("checkpoint*.json"))
        if not paths:
            return None
        latest_path = max(paths, key=lambda path: path.stat().st_mtime)
        return str(latest_path)

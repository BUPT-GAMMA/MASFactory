from abc import ABC,abstractmethod

class Checkpointable(ABC):
    @abstractmethod
    def get_checkpoint_state(self) -> dict:
        """Export this object's runtime checkpoint state."""
        raise NotImplementedError
    
    @abstractmethod
    def load_checkpoint_state(self,state:dict) -> None:
        """Restore this object's runtime checkpoint state."""
        raise NotImplementedError
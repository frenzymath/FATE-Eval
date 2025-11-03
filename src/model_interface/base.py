"""
Defines the base interface for model access
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List


class ModelInterface(ABC):
    """
    Base class for all model interfaces
    """
    
    def __init__(self, model_config: Dict[str, Any]):
        """
        Initialize the model interface
        
        Args:
            model_config: Model configuration information
        """
        self.model_config = model_config
        self.model_name = model_config.get('name', 'unknown')
    
    @abstractmethod
    async def generate(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """
        Generate model response
        
        Args:
            prompt: Input prompt
            **kwargs: Additional parameters
        
        Returns:
            Dictionary containing the model response
        """
        pass
    
    @abstractmethod
    def generate_sync(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """
        Generate model response synchronously
        
        Args:
            prompt: Input prompt
            **kwargs: Additional parameters
        
        Returns:
            Dictionary containing the model response
        """
        pass 
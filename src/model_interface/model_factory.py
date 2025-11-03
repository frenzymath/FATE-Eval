"""
Model Factory: Creates model interface instances based on configuration
"""
import os
import yaml
from typing import Dict, Any, Optional

from .base import ModelInterface
from .commercial_api import CommercialAPIInterface


class ModelFactory:
    """
    Model Factory class: Creates model interface instances based on configuration
    """
    
    @staticmethod
    def load_config(config_path: str) -> Dict[str, Any]:
        """
        Load model configuration
        
        Args:
            config_path: Configuration file path
            
        Returns:
            Configuration dictionary
        """
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        return config
    
    @staticmethod
    def create_model(model_name: str, config_path: str = "config/models.yaml", api_key: Optional[str] = None) -> ModelInterface:
        """
        Create model interface based on model name
        
        Args:
            model_name: Model name
            config_path: Configuration file path
            api_key: API key (optional)
            
        Returns:
            Model interface instance
        """
        # Load configuration
        config = ModelFactory.load_config(config_path)
        
        # Look in commercial API models
        if 'commercial_apis' in config:
            for api_id, api_config in config['commercial_apis'].items():
                if api_id == model_name or api_config.get('name') == model_name:
                    return CommercialAPIInterface(api_config, api_key)
        
        raise ValueError(f"Model not found: {model_name}, please check configuration file or model name") 
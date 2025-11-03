"""
Budget calculator module - estimate and track API call costs.
"""
import logging
import os
import json
from datetime import datetime
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

class BudgetCalculator:
    """Budget calculation and cost tracking utility."""
    
    def __init__(self, model_configs: Dict[str, Dict[str, Any]]):
        """Initialize budget calculator.

        Args:
            model_configs: Model configuration mapping
        """
        self.model_configs = model_configs
        self.total_cost = 0.0
        self.model_costs = {}
        self.cost_log = []

    def record_api_call(self, model_name: str, input_tokens: int, output_tokens: int, problem_id: Optional[str] = None) -> float:
        """Record the cost of an API call.

        Args:
            model_name: Model name or ID
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            problem_id: Optional problem identifier

        Returns:
            The cost of this call
        """
        # Locate model config by key, model_id, or name
        model_config = None
        
        # Direct key match
        if model_name in self.model_configs:
            model_config = self.model_configs[model_name]
        else:
            # Try matching by model_id or name
            for config_name, config in self.model_configs.items():
                if config.get("model_id") == model_name or config.get("name") == model_name:
                    model_config = config
                    # Use canonical config name for logging/aggregation
                    model_name = config_name
                    break
        
        if not model_config:
            logger.warning(f"Model config not found: {model_name}")
            return 0.0
            
        if "input_price_per_1k" not in model_config or "output_price_per_1k" not in model_config:
            logger.warning(f"Model {model_name} missing price info; cannot compute cost")
            return 0.0
            
        input_price = model_config["input_price_per_1k"]
        output_price = model_config["output_price_per_1k"]
        
        # Compute costs
        input_cost = (input_tokens / 1000) * input_price
        output_cost = (output_tokens / 1000) * output_price
        call_cost = input_cost + output_cost
        
        # Update totals
        self.total_cost += call_cost
        
        # Update per-model breakdown
        if model_name not in self.model_costs:
            self.model_costs[model_name] = {
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "input_cost": 0.0,
                "output_cost": 0.0,
                "total_cost": 0.0
            }
        
        self.model_costs[model_name]["calls"] += 1
        self.model_costs[model_name]["input_tokens"] += input_tokens
        self.model_costs[model_name]["output_tokens"] += output_tokens
        self.model_costs[model_name]["input_cost"] += input_cost
        self.model_costs[model_name]["output_cost"] += output_cost
        self.model_costs[model_name]["total_cost"] += call_cost
        
        # Append call record
        self.cost_log.append({
            "timestamp": datetime.now().isoformat(),
            "model": model_name,
            "problem_id": problem_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "input_cost": round(input_cost, 6),
            "output_cost": round(output_cost, 6),
            "total_cost": round(call_cost, 6)
        })
        
        return call_cost
    
    def get_cost_summary(self) -> Dict[str, Any]:
        """Get cost summary report."""
        model_breakdown = {}
        for model_name, data in self.model_costs.items():
            model_breakdown[model_name] = {
                "calls": data["calls"],
                "input_tokens": data["input_tokens"],
                "output_tokens": data["output_tokens"],
                "total_tokens": data["input_tokens"] + data["output_tokens"],
                "input_cost": round(data["input_cost"], 2),
                "output_cost": round(data["output_cost"], 2),
                "total_cost": round(data["total_cost"], 2)
            }
            
        return {
            "total_cost": round(self.total_cost, 2),
            "currency": "USD",
            "model_breakdown": model_breakdown,
            "detailed_log": self.cost_log
        }
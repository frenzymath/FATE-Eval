import os
import sys
import json
import yaml
import argparse
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.model_interface.model_factory import ModelFactory
from src.model_interface.budget_calculator import BudgetCalculator

class TqdmLoggingHandler(logging.StreamHandler):
    def __init__(self, level=logging.NOTSET):
        super().__init__()

    def emit(self, record):
        try:
            msg = self.format(record)
            tqdm.write(msg)
            self.flush()
        except Exception:
            self.handleError(record)

# Configure logging
os.makedirs('logs', exist_ok=True)

# Remove existing StreamHandlers to avoid duplicate logs
for handler in logging.root.handlers[:]:
    if isinstance(handler, logging.StreamHandler):
        logging.root.removeHandler(handler)

# Use tqdm-friendly output only in interactive terminals
if sys.stdout.isatty():
    # Use tqdm.write in terminal
    stream_handler = TqdmLoggingHandler()
else:
    # Use standard stdout otherwise
    stream_handler = logging.StreamHandler(sys.stdout)

stream_handler.setLevel(logging.INFO)
stream_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logging.root.addHandler(stream_handler)

# 文件日志仍然用 FileHandler
file_handler = logging.FileHandler(os.path.join('logs', 'generate_solution.log'), encoding='utf-8', mode='a')
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logging.root.addHandler(file_handler)

logging.root.setLevel(logging.INFO)
logger = logging.getLogger(__name__)

def load_json_dataset(dataset_path: str, n: int = -1) -> List[Dict[str, Any]]:
    """
    Load dataset from a .json file.

    Args:
        dataset_path: Path to .json dataset
        n: Number of items to process (-1 for all)

    Returns:
        List of dataset items
    """
    try:
        if dataset_path.endswith('.json'):
            # Read JSON file
            with open(dataset_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
        # Ensure list shape
        if not isinstance(data, list):
            data = [data]
        
        logger.info(f"Loaded {len(data)} data items")
        
        # Use first n items if specified
        if n > 0:
            data = data[:n]
            logger.info(f"Will process first {len(data)} items")
        
        return data
    
    except Exception as e:
        logger.error(f"Failed to load dataset: {e}")
        return [] 

def load_model_configs() -> Dict[str, Dict[str, Any]]:
    """
    Load model configurations from config/models.yaml.

    Returns:
        Dict[str, Dict[str, Any]]: The merged model configuration map.
    """
    try:
        config_path = os.path.join("config", "models.yaml")
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = yaml.safe_load(f)
        
        # Merge different sections
        model_configs = {}
        for section in ["commercial_apis", "local_models"]:
            if section in config_data:
                model_configs.update(config_data[section])
        
        logger.info(f"Loaded {len(model_configs)} model configs")
        return model_configs
    except Exception as e:
        logger.error(f"Failed to load model configs: {e}")
        return {}

def generate_informal_prompt(informal_statement: str) -> str:
    if not informal_statement:
        raise ValueError("Informal statement cannot be empty")
    return f"""
        You are an expert mathematician in the field of abstract algebra and commutative algebra.
        Your task is to provide a complete and detailed proof for the following mathematical problem. 
        The solution will be meticulously assessed by a human expert for correctness, clarity, and logical rigor. 
        So while you can assume foundational knowledge, every step of your argument must be explicit, rigorous, and logically sound.
        Problem:
        {informal_statement}
    """
    
def generate_math_lean_prompt(formal_statement: str) -> str:
    if not formal_statement:
        raise ValueError("Formal statement cannot be empty")
    
    return f"""You are an expert in Lean 4 and Mathematics. Please finish the following proof in Lean4 code. 
        Do not change the original statement. Copy the final statement to prove exactly. 
        Please include the complete header (including imports and namespaces) so that your code can 
        pass the Lean4 compiler. Please solve the statement step by step and provide your complete 
        Lean4 code between ```lean4 and ``` after careful reasoning. Please also write down your complete
        natural language proof in detail before the Lean4 code.
    The statement for you to complete is: 

    ```lean4
        {formal_statement}
    ```"""

def generate_math_prompt(formal_statement: str) -> str:
    if not formal_statement:
        raise ValueError("Formal statement cannot be empty")
    
    return f"""You are an expert in Mathematics. Please complete the following proof. 
        The problem is stated in Lean4 code. You don’t need to write a formal proof—all reasoning and proofs should be explained in natural language.
        Solve the statement step by step and provide your final answer after ###Final Answer, after careful reasoning.
        The statement for you to complete is:

    ```lean4
        {formal_statement}
    ```"""
    
def generate_lean_prompt(formal_statement: str) -> str:
    if not formal_statement:
        raise ValueError("Formal statement cannot be empty")
    
    return f"""You are an expert in Lean 4 and Mathematics. Please finish the following proof in Lean4 code. 
        Do not change the original statement. Copy the final statement to prove exactly. 
        Please include the complete header (including imports and namespaces) so that your code can 
        pass the Lean4 compiler. Please solve the statement step by step and provide your complete 
        Lean4 code between ```lean4 and ``` after careful reasoning. 
    The statement for you to complete is: 

    ```lean4
        {formal_statement}
    ```"""

def generate_v2_cot_prompt(formal_statement: str) -> str:
    if not formal_statement:
        raise ValueError("Formal statement cannot be empty")
    
    return f"""Complete the following Lean 4 code:
    ```lean4
        {formal_statement}
    ```
    Before producing the Lean 4 code to formally prove the given theorem, provide a detailed proof plan outlining the main proof steps and strategies. The plan should highlight key ideas, intermediate lemmas, and proof structures that will guide the construction of the final formal proof.
    """
    
def generate_kimina_prompt(informal_statement: str, formal_statement: str) -> str:
    if not formal_statement:
        raise ValueError("Formal statement cannot be empty")
    
    return f"""Think about and solve the following problem step by step in Lean 4.
        # Problem:{informal_statement}
        # Formal statement:
        ```lean4
        {formal_statement}
        ```"""

def format_problem(data: List[Dict[str, Any]], prompt_mode: str) -> List[Dict[str, Any]]:
    """
    Format raw data items into prompt structures.

    Args:
        data: Raw data list

    Returns:
        List of formatted problems
    """
    
    # Format reference: testset/problem.json
    formatted_problems = []
    
    for item in data:
        if "formal_statement" not in item or not item["formal_statement"]:
            logger.warning(f"Skip item without formal_statement: {item.get('extra_info', {}).get('problem_id', 'unknown')}")
            continue
        
        if prompt_mode == "lean":
            prompt = generate_lean_prompt(item["formal_statement"])
        elif prompt_mode == "math_lean":
            prompt = generate_math_lean_prompt(item["formal_statement"])
        elif prompt_mode == "math":
            prompt = generate_math_prompt(item["formal_statement"])
        elif prompt_mode == "v2_cot":
            prompt = generate_v2_cot_prompt(item["formal_statement"])
        elif prompt_mode == "kimina":
            prompt = generate_kimina_prompt(item["informal_statement"], item["formal_statement"])
        elif prompt_mode == "informal":
            prompt = generate_informal_prompt(item["informal_statement"])
        else:
            logger.error(f"Unknown prompt mode: {prompt_mode}, choose from: lean, math_lean, math, v2_cot, kimina, informal")
            continue
        
        problem = {
            "prompt": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "extra_info": {
                "problem_id": item.get("id", "unknown"),
                "informal_statement": item.get("informal_statement", ""),
                "formal_statement": item.get("formal_statement", ""),
                "informal_proof": item.get("informal_proof", ""),
            }
        }
        
        formatted_problems.append(problem)
    
    logger.info(f"Formatted {len(formatted_problems)} problems")
    return formatted_problems

async def generate_single_solution(model, problem: Dict[str, Any], model_name, budget_calculator=None, semaphore=None, pbar=None) -> Dict[str, Any]:
    """
    Generate one solution attempt for a given problem.

    Args:
        model: Model interface
        problem: Problem data
        model_name: Model name (optional), for cost tracking
        budget_calculator: Budget calculator (optional)
        semaphore: Concurrency semaphore (optional)
        pbar: Global progress bar (optional)

    Returns:
        Dict with generation result
    """
    # Extract user prompt from problem
    prompts = problem.get("prompt", [])
    if not prompts:
        logger.error("No 'prompt' field in problem data")
        return {
            "problem_id": problem.get("extra_info", {}).get("problem_id", "unknown"),
            "prompt": "",
            "model_output": "",
            "error": "No prompt found in problem data"
        }
    
    # 获取用户提示内容
    user_prompt = next((p["content"] for p in prompts if p["role"] == "user"), None)
    if not user_prompt:
        logger.error("No user role content found in prompt list")
        return {
            "problem_id": problem.get("extra_info", {}).get("problem_id", "unknown"),
            "prompt": "",
            "model_output": "",
            "error": "No user prompt found"
        }
    
    problem_id = problem.get("extra_info", {}).get("problem_id", "unknown")
    
    try:
        # 调用模型生成
        if semaphore is not None:
            async with semaphore:
                start_time = datetime.now()
                result = await model.generate(user_prompt)
                generation_time = (datetime.now() - start_time).total_seconds()
        else:
            start_time = datetime.now()
            result = await model.generate(user_prompt)
            generation_time = (datetime.now() - start_time).total_seconds()
        
        # Record cost if enabled
        call_cost = 0.0
        if budget_calculator and "usage" in result:
            usage = result["usage"]
            # Prefer provided model_name over model.model_id
            budget_model_name = model_name or model.model_id
            call_cost = budget_calculator.record_api_call(
                budget_model_name,
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
                problem_id
            )

        return {
            "problem_id": problem_id,
            "prompt": user_prompt,
            "model_output": result.get("text", ""),
            "token_usage": result.get("usage", {}),
            "generation_time": generation_time,
            "cost": call_cost,
            "error": result.get("error", None),
            "reasoning_content": result.get("reasoning_content", None)
        }
    except Exception as e:
        logger.error(f"Failed to generate solution: {e}")
        return {
            "problem_id": problem_id,
            "prompt": user_prompt,
            "model_output": "",
            "error": str(e)
        }

async def evaluate_problem(
    model_name: str, 
    problem: Dict[str, Any], 
    attempts: int, 
    budget_calculator=None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate multiple attempts for a single problem to compute pass@k.

    Args:
        model_name: Model name
        problem: Problem data
        attempts: Number of attempts
        budget_calculator: Budget calculator (optional)
        api_key: API key (optional)

    Returns:
        Aggregated generation result
    """
    # 创建模型接口
    model = ModelFactory.create_model(model_name, api_key=api_key)
    
    results = []
    total_cost = 0.0
    
    # Extract problem id
    prompt = problem.get("prompt", [])
    extra_info = problem.get("extra_info", {})
    problem_id = extra_info.get("problem_id", "unknown")
    
    # Multiple attempts
    for i in range(attempts):
        logger.info(f"问题 {problem_id} - 尝试 {i+1}/{attempts}")
        
        # Generate one attempt
        solution = await generate_single_solution(
            model=model, 
            problem=problem, 
            model_name=model_name,
            budget_calculator=budget_calculator)
        
        # Accumulate cost
        if "cost" in solution:
            total_cost += solution["cost"]
            
        results.append(solution)
    
    return {
        "problem_id": problem_id,
        "prompt": prompt,
        "extra_info": extra_info,
        "attempts": attempts,
        "total_cost": total_cost,
        "results": results
    }

async def aysc_evaluate_problems(
    model_name: str, 
    problem: Dict[str, Any], 
    attempts: int, 
    budget_calculator=None,
    api_key: Optional[str] = None,
    semaphore: Optional[asyncio.Semaphore] = None,
    pbar=None,  # 新增
) -> Dict[str, Any]:
    """
    Generate attempts for a problem concurrently (for overall progress tracking).

    Args:
        model_name: Model name
        problem: Problem data
        attempts: Number of attempts
        budget_calculator: Budget calculator (optional)
        api_key: API key (optional)
        semaphore: Concurrency semaphore (optional)
        pbar: Global progress bar (optional)

    Returns:
        Aggregated generation result for the problem
    """
    # 创建模型接口
    model = ModelFactory.create_model(model_name, api_key=api_key)
    
    # 获取问题ID
    prompt = problem.get("prompt", [])
    extra_info = problem.get("extra_info", {})
    problem_id = extra_info.get("problem_id", "unknown")

    # Create async tasks for all attempts
    tasks = [
        generate_single_solution(
            model=model, 
            problem=problem, 
            model_name=model_name,
            budget_calculator=budget_calculator,
            semaphore=semaphore,
            pbar=pbar,  # 新增
        )
        for _ in range(attempts)
    ]

    # Update tqdm progress as tasks complete
    results = []
    for coro in asyncio.as_completed(tasks):
        result = await coro
        results.append(result)
        if pbar is not None:
            pbar.update(1)

    total_cost = sum(solution.get("cost", 0.0) for solution in results)
    return {
        "problem_id": problem_id,
        "prompt": prompt,
        "extra_info": extra_info,
        "attempts": attempts,
        "total_cost": total_cost,
        "results": results
    }
    
def save_generate_results(results: List[Dict[str, Any]], model_name: str, n: int, k: int, 
                cost_summary: Optional[Dict[str, Any]] = None) -> str:
    """
    Save evaluation results to a timestamped JSON file under model-specific directory.

    Args:
        results: List of evaluation results
        model_name: Model name
        n: Number of problems processed
        k: Attempts per problem
        cost_summary: Optional cost summary

    Returns:
        The saved file path
    """
    try:
        # Load generate_config
        with open("config/generate_config.yaml", 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # Persist under output_dir/<model_name>
        output_dir = os.path.join(config['io']['output_dir'], model_name)
        # Ensure directory exists
        os.makedirs(output_dir, exist_ok=True)
        
        output_file = config['io']['output_file']
        # Append timestamp before .json suffix
        output_file = output_file.split('.json')[0] + '_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.json'
        
        # Build output content
        output_data = {
            "model": model_name,
            "timestamp": datetime.now().isoformat(),
            "num_problems": n,
            "attempts_per_problem": k,
            "results": results
        }
        
        if cost_summary:
            output_data["cost_summary"] = cost_summary
        
        # Save results
        output_file = os.path.join(output_dir, output_file)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Results saved to: {output_file}")
        return output_file
    
    except Exception as e:
        logger.error(f"Failed to save results: {e}")
        # Fallback to default path
        default_output = os.path.join("outputs", f"results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        os.makedirs(os.path.dirname(default_output), exist_ok=True)

        with open(default_output, 'w', encoding='utf-8') as f:
            json.dump({
                "model": model_name,
                "timestamp": datetime.now().isoformat(),
                "num_problems": n,
                "attempts_per_problem": k,
                "results": results,
                "cost_summary": cost_summary if cost_summary else {}
            }, f, indent=2, ensure_ascii=False)
        
        logger.warning(f"Saved results to fallback path: {default_output}")
        return default_output

async def generate_to_file(
    model: str,
    dataset: str,
    n: int = 10,
    k: int = 1,
    api_key: Optional[str] = None,
    mode: str = "lean",
    concurrency: int = 150,
) -> str:
    """
    Public API: run generation stage and persist results to a file.

    Args:
        model: Model name (must exist in models.yaml)
        dataset: Input dataset path (JSON)
        n: Number of problems to process
        k: Attempts per problem
        api_key: API key
        mode: Prompt mode (lean, math_lean, math, v2_cot, kimina, informal)
        concurrency: Max concurrency

    Returns:
        Path to the generated results file
    """
    data = load_json_dataset(dataset, n)
    if not data:
        raise RuntimeError("No problem data found, abort")

    problems = format_problem(data, mode)

    model_configs = load_model_configs()
    if model not in model_configs:
        available_models = ", ".join(model_configs.keys())
        raise RuntimeError(f"Model '{model}' not found. Available: {available_models}")

    budget_calculator = BudgetCalculator(model_configs)
    semaphore = asyncio.Semaphore(concurrency)

    total_tasks = len(problems) * k
    with tqdm(total=total_tasks, desc="全部问题进度", disable=not sys.stdout.isatty()) as pbar:
        tasks = [
            aysc_evaluate_problems(
                model_name=model,
                problem=problem,
                attempts=k,
                budget_calculator=budget_calculator,
                api_key=api_key,
                semaphore=semaphore,
                pbar=pbar,
            )
            for problem in problems
        ]
        results = await asyncio.gather(*tasks)

    cost_summary = budget_calculator.get_cost_summary() if hasattr(budget_calculator, 'get_cost_summary') else None
    output_file = save_generate_results(results, model, len(problems), k, cost_summary)
    return output_file
    
async def main():
    parser = argparse.ArgumentParser(description="只做生成的脚本")
    parser.add_argument("--model", type=str, required=True, help="要测试的模型名称")
    parser.add_argument("--dataset", type=str, required=True, help="数据集文件路径")
    parser.add_argument("--n", type=int, default=10, help="要处理的问题数量")
    parser.add_argument("--k", type=int, default=1, help="每题尝试次数")
    parser.add_argument("--api_key", type=str, help="API密钥(如果未提供，将从环境变量读取)")
    parser.add_argument("--mode", type=str, default="lean", help="使用的prompt类型，默认为lean")
    parser.add_argument("--concurrency", type=int, default=150, help="最大并发数")

    args = parser.parse_args()

    output_file = await generate_to_file(
        model=args.model,
        dataset=args.dataset,
        n=args.n,
        k=args.k,
        api_key=args.api_key,
        mode=args.mode,
        concurrency=args.concurrency,
    )
    logger.info("Generation completed")
    logger.info(f"Results saved to: {output_file}")

if __name__ == "__main__":
    asyncio.run(main()) 
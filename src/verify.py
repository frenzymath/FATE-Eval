import os
import sys
import json
import yaml
import argparse
import logging
from tqdm import tqdm
from datetime import datetime
from typing import Dict, Any, List, Iterator, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lean_verifier import Verifier, CodeUtil
from lean_verifier.structs import VerifyResult
from calculation import calculate_pass_at_k as calc_pass_at_k

# Configure logging
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join('logs', 'verify_result.log'), encoding='utf-8', mode='a')
    ]
)
logger = logging.getLogger(__name__)


def load_verify_config() -> Dict[str, Dict[str, Any]]:
    """
    Load verification configuration for Lean.

    Returns:
        Dict[str, Dict[str, Any]]: Parsed verification configuration.
    """
    try:
        verify_path = os.path.join("config", "verify_config.yaml")
        with open(verify_path, 'r', encoding='utf-8') as f:
            config_data = yaml.safe_load(f)
        
        lake_path = config_data["verification"].get("lake_path", "")
        lean_workspace = config_data["verification"].get("lean_workspace", "")
        
        logger.info("Loaded Lean verification configuration")
        if lake_path:
            logger.info(f"lake_path = {lake_path}")
        if lean_workspace:
            logger.info(f"lean_workspace = {lean_workspace}")
        
        return config_data
    
    except Exception as e:
        logger.error(f"Failed to load Lean verification configuration: {e}")
        return {}

def load_generated_results(input_path: str) -> Dict[str, Any]:
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data
    
def extract_from_results(results_dict: Dict[str, Any]) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """
    Extract the last Lean code block from model outputs while keeping extra_info (including formal_statement).
    """
    codes = []
    extra_infos = []
    results = results_dict.get("results", [])
    for result in results:
        extra_info = result.get("extra_info", {})
        code_results = result.get("results", [])
        for code_result in code_results:
            model_output = code_result.get("model_output", "")
            if model_output:
                lean_block = CodeUtil.match_last_lean_code(model_output)
            else:
                lean_block = None
            codes.append(lean_block or "")
            extra_infos.append(extra_info)
    return zip(codes, extra_infos)


def verify_generated_results(verifier: Verifier, results: Dict[str, Any], timeout: int = 600, max_workers: int | None = None) -> List[Dict[str, Any]]:
    """
    Batch verification based on the old_verify idea:
    run static precheck first, collect valid samples for batch REPL verification,
    and reassemble results in the original order.

    Args:
        verifier: Verifier instance
        results: The dict of model generation outputs
        timeout: Timeout (seconds)

    Returns:
        List of verification results, each as a dict representation of VerifyResult
    """
    pairs = list(extract_from_results(results))

    # Pre-allocate result container to restore original ordering
    ordered_results: List[Dict[str, Any] | None] = [None] * len(pairs)

    # Collect samples that pass static precheck for batch verification
    batch_codes: List[str] = []
    batch_extra_infos: List[Dict[str, Any]] = []
    batch_indices: List[int] = []

    for idx, (code_text, extra_info) in enumerate(tqdm(pairs, desc="Static precheck")):
        formal_statement = extra_info.get("formal_statement", "")
        ok, reason, normalized = CodeUtil.static_precheck(code_text, formal_statement)
        if not ok:
            vr = VerifyResult.from_system_error(
                code_text or "", timeout, reason,
                lean_toolchain=str(verifier.lean_workspace)
            )
            vr.extra_info = extra_info
            ordered_results[idx] = vr.model_dump()
        else:
            batch_codes.append(normalized)
            batch_extra_infos.append(extra_info)
            batch_indices.append(idx)

    # Batch REPL verification for samples that passed static precheck
    if batch_codes:
        batch_verified = verifier.batch_verify(
            codes=batch_codes,
            timeout=timeout,
            extra_infos=batch_extra_infos,
            max_workers=max_workers,
        )
        for local_pos, vr in enumerate(batch_verified):
            global_idx = batch_indices[local_pos]
            ordered_results[global_idx] = vr.model_dump()

    # Cleanup and return
    verified: List[Dict[str, Any]] = [r for r in ordered_results if r is not None]
    return verified


def reformat_verified_results(verified_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Group results returned by lean_verifier by problem.
    """
    verified_result_dict = {}
    for result in verified_results:
        extra_info = result.get("extra_info", {})
        problem_id = extra_info.get("problem_id", "")
        if problem_id:
            if problem_id not in verified_result_dict:
                verified_result_dict[problem_id] = {
                    "extra_info": extra_info,
                    "results": []
                }
            verified_result_dict[problem_id]["results"].append(result)
    verified_result = []
    for key, value in verified_result_dict.items():
        extra_info = value.get("extra_info", {})
        verified_result.append(
            {
                "problem_id": key,
                "informal_statement": extra_info.get("informal_statement", ""),
                "formal_statement": extra_info.get("formal_statement", ""),
                "results": value.get("results", [])
            }
        )
    return (sorted(
        verified_result,
        key=lambda x: int(x["problem_id"])
    ))

def calculate_M_values_from_results(reformatted_verified_result: List[Dict[str, Any]]) -> List[int]:
    """
    Compute error counts M_j for each problem from reformatted results.
    A result is considered correct only if both pass_ and complete are True
    and system_errors is empty.

    Args:
        reformatted_verified_result: Reformatted verification result list

    Returns:
        List[int]: The list of error counts per problem (M_values).
    """
    M_values = []
    
    # Iterate over each problem
    for problem in reformatted_verified_result:
        results = problem.get("results", [])
        # Count errors: either pass_ and complete are not both True, or system_errors is non-empty
        Mj = 0
        for result in results:
            # If either pass_ and complete are not both True or system_errors is non-empty, count as error
            system_errors = result.get("system_errors")
            is_error = (not (result.get("pass_", False) and result.get("complete", False))) or (system_errors is not None and system_errors != "")
            if is_error:
                Mj += 1
        
        M_values.append(Mj)
    
    return M_values

def generate_k_values(N: int) -> List[int]:
    """
    Generate a list of k values based on total number of attempts N.
    Include all powers of two (1, 2, 4, 8, ...) less than or equal to N,
    and also include N itself if it is not already included.

    Args:
        N: Total number of attempts

    Returns:
        List[int]: List of k values
    """
    # Powers of two less than or equal to N
    k_values = [2**i for i in range(20) if 2**i <= N]  # 使用 20 作为上限，覆盖到 2^20 = 1048576
    # Include N itself if not already present
    if N > 0 and N not in k_values:
        k_values.append(N)
    # Ensure k_values is not empty; include 1 if N >= 1
    if not k_values:
        k_values = [1] if N >= 1 else []
    return sorted(k_values)

def main():
    parser = argparse.ArgumentParser(description="Lean verification CLI")
    parser.add_argument("--input", type=str, required=True, help="Path to generated results file")
    args = parser.parse_args()

    # Reuse public interface to avoid duplicating verify_file logic
    output_path = verify_file(args.input)
    logger.info(f"Verification results saved to {output_path}")

if __name__ == "__main__":
    main()

def verify_file(input_path: str, timeout: int | None = None, max_workers: int | None = None) -> str:
    """
    Public interface: verify a given generation results file and return
    the path of the verification results file.

    Args:
        input_path: Path to generation output JSON file
        timeout: Override timeout in seconds; None means use config value
        max_workers: Override maximum concurrency; None means use config value

    Returns:
        The output path of the verification results file
    """
    verify_config = load_verify_config()
    # Read lake/lean workspace settings from config
    lake_path = verify_config.get("verification", {}).get("lake_path", "")
    lean_workspace = verify_config.get("verification", {}).get("lean_workspace", "")

    # Resolve timeout and concurrency: prefer function args over config
    cfg_timeout = verify_config.get("verification", {}).get("timeout", 300)
    cfg_timeout = verify_config.get("verification", {}).get("verify_params", {}).get("timeout", cfg_timeout)
    use_timeout = timeout if timeout is not None else cfg_timeout

    cfg_max_workers = verify_config.get("verification", {}).get("max_workers")
    cfg_max_workers = verify_config.get("verification", {}).get("verify_params", {}).get("max_workers", cfg_max_workers)
    use_max_workers = max_workers if max_workers is not None else cfg_max_workers

    # Load generated results
    generated_result = load_generated_results(input_path)

    # Initialize verifier and execute verification
    verifier = Verifier(lean_workspace, lake_path)
    verified_result = verify_generated_results(
        verifier, generated_result, timeout=use_timeout, max_workers=use_max_workers
    )

    # Reformat results and compute pass@k (consistent with CLI)
    reformatted_verified_result = reformat_verified_results(verified_result)
    reformatted_results = {
        "generated_result_path": input_path,
        "model": generated_result.get("model", "unknown"),
        "timestamp": generated_result.get("timestamp", ""),
        "num_problems": generated_result.get("num_problems", ""),
        "attempts_per_problem": generated_result.get("attempts_per_problem", -1),
        "verified_result": reformatted_verified_result,
    }

    try:
        M_values = calculate_M_values_from_results(reformatted_verified_result)
        num_questions = len(M_values)
        if num_questions > 0:
            N = reformatted_results.get("attempts_per_problem", -1)
            if N <= 0:
                if reformatted_verified_result:
                    N = len(reformatted_verified_result[0].get("results", []))
                    logger.info(f"Inferred total attempts N = {N} from actual results")
                if N > 0:
                    reformatted_results["attempts_per_problem"] = N
            else:
                logger.info(f"Using configured total attempts N = {N}")

            if N > 0:
                k_values = generate_k_values(N)
                logger.info(f"Computing pass@k for k values: {k_values}")
                for k in k_values:
                    pass_at_k_count = calc_pass_at_k(N, k, M_values)
                    if pass_at_k_count is not None:
                        pass_at_k_rate = pass_at_k_count / num_questions
                        reformatted_results[f"pass@{k}"] = pass_at_k_rate
                        logger.info(f"pass@{k} result: {pass_at_k_rate:.6f} ({pass_at_k_count:.2f}/{num_questions})")
                    else:
                        logger.warning(f"pass@{k}: cannot compute (likely k > N or other error)")
        else:
            logger.warning("No verification results, skip pass@k computation")
    except Exception as e:
        logger.error(f"Exception when computing pass@k: {e}", exc_info=True)

    output_path = input_path.replace("generate", "verify")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(reformatted_results, f, indent=2, ensure_ascii=False)
    logger.info(f"Verification results saved to {output_path}")
    return output_path
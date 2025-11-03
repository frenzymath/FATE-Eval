import math
import random
from typing import List
import json

def calculate_M_values(input_file: str) -> List[int]:
    """
    Read per-problem error counts M_j from a verification result JSON file.
    A result is considered correct only if both pass_ and complete are True.

    Args:
        input_file (str): Path to the JSON file.

    Returns:
        List[int]: List of error counts per problem (M_values).
    """

    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    M_values = []
    
    # Iterate over each problem in verified_result
    for problem in data["verified_result"]:
        results = problem["results"]
        # Count errors: either pass_ and complete are not both True, or system_errors is non-empty
        Mj = 0
        for result in results:
            # If either pass_ and complete not both True, or system_errors non-empty, count as error
            system_errors = result.get("system_errors")
            is_error = (not (result.get("pass_", False) and result.get("complete", False))) or (system_errors is not None and system_errors != "")
            if is_error:
                Mj += 1
        
        M_values.append(Mj)
    
    return M_values

def calculate_pass_at_k(N, k, M_values):
    """
    Compute the expected pass@k according to the standard formula.

    Args:
        N (int): Total number of attempts.
        k (int): Number of samples to draw.
        M_values (list[int]): For each problem j, M_j is the number of incorrect attempts among N.

    Returns:
        float: Expected number of correctly solved problems (pass@k).
               Returns None if k > N.
    """
    num_questions = len(M_values)

    # Total combinations C(N, k). Guard against k > N to avoid division by zero.
    if k > N:
        print("Error: k cannot be greater than N.")
        return None
        
    total_combinations_N_k = math.comb(N, k)

    if total_combinations_N_k == 0:
        # Unable to sample; typically occurs only when k > N.
        print("Warning: C(N, k) is 0; cannot compute pass@k.")
        return None

    # Sum of C(M_j, k) for all j (all-sampled attempts incorrect)
    sum_of_error_combinations = 0
    for Mj in M_values:
        # For problem j, sample k from Mj incorrect attempts; math.comb handles k > Mj → 0.
        sum_of_error_combinations += math.comb(Mj, k)

    # Expected incorrect count = sum C(Mj, k) / C(N, k)
    expected_incorrect_count = sum_of_error_combinations / total_combinations_N_k

    # Expected correct count = total problems - expected incorrect
    expected_correct_count = num_questions - expected_incorrect_count
    
    return expected_correct_count
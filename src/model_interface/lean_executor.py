#!/usr/bin/env python
import os
import time
import logging
from typing import Dict, Any, Optional

from lean_verify.ray_verifier import verify_lean4_file_with_repl, verify_lean4_file_with_lean
from lean_verify.utils import CodeUtil

logger = logging.getLogger(__name__)

class LeanExecutor:
    """Lean verification executor wrapper."""
    
    def __init__(self, 
                 lake_path: Optional[str] = None, 
                 lean_workspace: Optional[str] = None):
        """Initialize Lean executor.

        Args:
            lake_path: Path to lake binary (fallback to env/default when None)
            lean_workspace: Path to Lean workspace (fallback to env/default when None)
        """
        self.lake_path = lake_path or os.getenv('LAKE_PATH', os.path.expanduser('~/.elan/bin/lake'))
        self.lean_workspace = lean_workspace or os.getenv('LEAN_WORKSPACE', 'lean_test_v4160')
        
        logger.info(f"Initialized LeanExecutor: lake_path={self.lake_path}, lean_workspace={self.lean_workspace}")
    
    def verify(self, 
              solution: str, 
              timeout: int = 60, 
              max_retries: int = 3,
              method: str = 'lean',
              verify_method: str = None,
              formal_statement: Optional[str] = None) -> Dict[str, Any]:
        """Verify a Lean solution.

        Args:
            solution: Lean code solution
            timeout: Verification timeout (seconds)
            max_retries: Maximum retry attempts
            method: Verification method, 'lean' or 'repl'
            verify_method: 'strict' or 'relaxed' mode
            formal_statement: Formal statement for strict/relaxed modes

        Returns:
            Dict with verification result
        """
        # Determine validation mode
        validation_method = verify_method
        
        # Prepare code by different modes
        if validation_method == 'relaxed':
            # Extract code block
            code = CodeUtil.extract_solution(solution, 'relaxed')
            
            # If provided, validate code contains the formal statement
            if formal_statement and code:
                # Extract the last statement from the formal_statement
                trunc_statement = CodeUtil.extract_last_statement_from_code(formal_statement)
                
                # Check whether code matches the statement
                if not CodeUtil.verify_code_statement(code, trunc_statement):
                    code = None
            
        elif validation_method == 'strict':
            # Extract proof code part
            proof_code = CodeUtil.extract_solution(solution, 'strict')
            
            # Combine formal_statement and proof_code
            if proof_code and formal_statement:
                code = formal_statement.strip() + proof_code
            else:
                code = proof_code
        else:
            # Fallback: extract code block directly
            code = CodeUtil.match_lean_code(solution)
            if not code:
                # If no markdown block, use raw solution
                code = solution
        
        # Empty code guard
        if not code or code.strip() == "":
            return {
                "success": False,
                "message": "Invalid or empty code",
                "errors": ["Invalid or empty code"],
                "warnings": []
            }
        
        # Retry loop
        retries = 0
        while retries < max_retries:
            try:
                # Choose verification method
                if method == 'repl':
                    result = verify_lean4_file_with_repl(
                        code, 
                        lake_path=self.lake_path, 
                        lean_workspace=self.lean_workspace,
                        timeout=timeout
                    )
                else:
                    result = verify_lean4_file_with_lean(
                        code, 
                        lake_path=self.lake_path, 
                        lean_workspace=self.lean_workspace,
                        timeout=timeout
                    )
                
                # Transform fields
                success = result.get("pass", False) and not result.get("timeout", False)
                
                return {
                    "success": success,
                    "complete": result.get("complete", False),
                    "message": "Verification succeeded" if success else "Verification failed",
                    "errors": result.get("errors", []),
                    "warnings": result.get("warnings", []),
                    "sorries": result.get("sorries", []),
                    "timeout": result.get("timeout", False),
                    "verify_time": result.get("verify_time", 0)
                }
            except Exception as e:
                retries += 1
                logger.warning(f"Verification failed (retry {retries}/{max_retries}): {str(e)}")
                time.sleep(1)
        
        # All retries exhausted
        return {
            "success": False,
            "message": f"Verification failed after max retries ({max_retries})",
            "errors": [f"Verification failed after max retries ({max_retries})"],
            "warnings": []
        } 
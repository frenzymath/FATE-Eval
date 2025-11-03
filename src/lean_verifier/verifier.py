import os
import time
import socket
import tempfile
import traceback
import datetime
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed

from tqdm import tqdm

from .utils import ProcessUtil
from .structs import Message, SortedMessages, VerifyResult

def get_workspace_toolchain(lean_workspace: str) -> str:
    with open(os.path.join(lean_workspace, 'lean-toolchain'), 'r', encoding='utf-8') as f:
        toolchain = f.read().strip()
    if not toolchain:
        raise ValueError("No toolchain specified in the lean workspace.")
    return toolchain.splitlines()[0]  # Return the first line as the toolchain

class Verifier:
    """ A class to verify Lean code using the Lean compiler. """
    def __init__(self, lean_workspace: str, lake_path: str = 'lake'):
        self.lake_path = lake_path
        self.lean_workspace = lean_workspace
    
    def _run_lean_verify(self, code, timeout: int) -> list[Message]:
        """ Run the Lean compiler to verify the provided code. """
        if code == "":
            raise ValueError("Code to verify cannot be empty.")
        
        pid = os.getpid()
        hostname = socket.gethostname()
        with tempfile.NamedTemporaryFile(mode='w+', encoding='utf-8', prefix=hostname + f"-{pid}-") as temp_file:
            temp_file.write(code + "\r\n\r\n")
            temp_file.seek(0)
            outputs = subprocess.run(
                    [self.lake_path, "env", 'lean', '--json', temp_file.name],
                    capture_output=True,
                    text=True,
                    cwd=self.lean_workspace,
                    timeout=timeout)

        if outputs.stderr:
            raise RuntimeError(f"Lean verification failed with error: {outputs.stderr.strip()}")
        
        result = []
        for line in outputs.stdout.splitlines():
            try:
                result.append(Message.model_validate_json(line))
            except Exception as e:
                raise ValueError(f"Failed to validate JSON line: {line}") from e
        return result

    @staticmethod
    def _sort_messages(messages: list[Message]) -> SortedMessages:
        """ Format messages into categorized lists. """
        sorries = [m for m in messages if m.severity == 'sorry']
        errors = [m for m in messages if m.severity == 'error']
        warnings = [m for m in messages if m.severity == 'warning']
        informations = [m for m in messages if m.severity == 'information']
        return SortedMessages(
            sorries=sorries,
            errors=errors,
            warnings=warnings,
            informations=informations
        )

    @staticmethod
    def _justify_pass(messages: SortedMessages) -> bool:
        """ Justify if the verification passed the compiler. sorry is accepted. """
        return not messages.errors

    @staticmethod
    def _justify_complete(messages: SortedMessages) -> bool:
        """ Justify if the verification is complete. 
            Core verification logic.
            Complete means no errors, no sorries, and no failed declarations.
        """
        return (Verifier._justify_pass(messages) and 
                not messages.sorries and 
                not any("declaration uses 'sorry'" in warning.data or
                        'failed' in warning.data 
                        for warning in messages.warnings))

    def verify(self, 
               code: str, 
               timeout: int, 
               extra_info: dict) -> VerifyResult:
        is_timeout = False
        system_errors = None
        messages = []
        sorted_messages = SortedMessages()
        pass_ = False
        complete = False
        start_time = time.time()
        lean_toolchain = self.lean_workspace
        try:
            messages = self._run_lean_verify(code, timeout)
        except subprocess.TimeoutExpired: # Handle timeout
            is_timeout = True
            system_errors = f"Verification timed out, traceback:\n{traceback.format_exc()}"
        except Exception:
            system_errors = traceback.format_exc()
        else:
            sorted_messages = self._sort_messages(messages)
            pass_ = self._justify_pass(sorted_messages)
            complete = self._justify_complete(sorted_messages)
        verify_time = time.time() - start_time
        complete_timestamp = datetime.datetime.now().isoformat(' ')
        return VerifyResult(
            sorted_messages=sorted_messages,
            system_errors=system_errors,
            verified_code=code,
            verified_timeout=timeout,
            pass_=pass_,
            complete=complete,
            is_timeout=is_timeout,
            verify_time=verify_time,
            complete_timestamp=complete_timestamp,
            extra_info=extra_info,
            lean_toolchain=lean_toolchain
        )
    
    def batch_verify(self, codes: list[str], timeout: int = 300,
                     max_workers: int | None = None,
                     extra_infos: list[dict] | None = None) -> list[VerifyResult]:
        if max_workers is None:
            max_workers = min(32, os.cpu_count() or 1)
        if extra_infos is None:
            extra_infos = [{}] * len(codes)
        if len(codes) != len(extra_infos):
            raise ValueError("Length of codes and extra_infos must match.")
        ordered_results: list[VerifyResult | None] = [None] * len(codes)

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self.verify, code, timeout, extra_info): idx
                for idx, (code, extra_info) in enumerate(zip(codes, extra_infos))
            }

            for future in tqdm(as_completed(futures),
                               total=len(codes),
                               desc="Verifying Lean codes"):
                idx = futures[future]                      # where this result belongs
                ordered_results[idx] = future.result() 
        if None in ordered_results:
            raise RuntimeError("Some futures did not complete successfully. "
                               "This may indicate an error in the verification process.")
        ProcessUtil.kill_lean()
        return ordered_results # type: ignore[return-value] 

    def verify_file(self, file_path: str, timeout: int = 300, extra_info: dict = {}) -> VerifyResult:
        with open(file_path, 'r', encoding='utf-8') as f:
            code = f.read()
        return self.verify(code, timeout, extra_info)
    
    def verify_dir(self, dir_path: str, timeout: int = 300, num_files: int | None = None) -> list[VerifyResult]:
        """ Verify all Lean files in a directory. """
        codes = []
        for root, _, files in os.walk(dir_path):
            if num_files is not None and len(files) > num_files:
                files = files[:num_files]
            for file in files:
                if file.endswith('.lean'):
                    file_path = os.path.join(root, file)
                    with open(file_path, 'r', encoding='utf-8') as f:
                        codes.append(f.read())
        return self.batch_verify(codes=codes, timeout=timeout)
    
    def verify_jsonl(self, file_path: str, column_name: str | None = None, timeout: int = 300, extra_infos: list[dict] | None = None) -> list[VerifyResult]:
        """ Verify jsonl file """
        import json
        with open(file_path) as f:
            data = [json.loads(line) for line in f]
        
        codes = []
        for d in data:
            if column_name is None:
                codes.append(d['formal_proof'])
            else:
                codes.append(d[column_name])
        return self.batch_verify(codes, timeout, extra_infos=extra_infos)

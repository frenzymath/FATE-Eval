import re
from typing import Optional, Any, List, Dict, Tuple
import traceback
import subprocess

class CodeUtil:
    @staticmethod
    def canonicalize_block(text: str) -> str:
        """
        Canonicalize a code/text block:
        - Normalize newlines (\r\n/\r → \n)
        - Strip trailing whitespace per line
        - Normalize spaces around ':=' to ' :='
        - Collapse consecutive spaces (keep newlines)
        - Collapse multiple blank lines into a single blank line
        - Strip leading/trailing whitespace
        """
        if text is None:
            return ''
        # normalize newlines
        s = text.replace('\r\n', '\n').replace('\r', '\n')
        # strip trailing spaces per line
        s = '\n'.join([line.rstrip() for line in s.split('\n')])
        # normalize spaces around ':='
        s = re.sub(r"\s*:=\s*", " := ", s)
        # collapse multiple spaces (but keep newlines)
        s = re.sub(r"[ \t]{2,}", " ", s)
        # compress multiple blank lines
        lines = []
        blank = 0
        for line in s.split('\n'):
            if line.strip() == '':
                blank += 1
            else:
                blank = 0
            if blank <= 1:
                lines.append(line)
        s = '\n'.join(lines)
        return s.strip()
    @staticmethod
    def match_lean_code(solution_str: str) -> Optional[str]:
        match1 = re.search(r"```lean4\s*([\s\S]*?)```", solution_str)
        if match1:
            return match1.group(1).strip('\n').strip()
        match2 = re.search(r"```lean\s*([\s\S]*?)```", solution_str)
        if match2:
            return match2.group(1).strip('\n').strip()

    @staticmethod
    def match_last_lean_code(solution_str: str) -> Optional[str]:
        # Find all lean/lean4 code blocks
        lean4_blocks = re.findall(r"```lean4?\s*([\s\S]*?)```", solution_str)
        if lean4_blocks:
            # Return the last lean4 block
            return lean4_blocks[-1].strip('\n').strip()
        return None

    @staticmethod
    def remove_proof(code: str) -> str:
        """
        Remove the proof part from Lean code and keep only declarations.
        Assumes the proof part starts with ':=' up to the next definition or EOF.
        """
        if code is None:
            return ''
        
        # Use regex to remove proof part
        pattern = r"(.*?)(?::=\s*by[\s\S]*?)(?=^noncomputable\b|^def\b|^lemma\b|^theorem\b|^instance\b|^example\b|^class\b|^structure\b|\Z)"
        
        def replacer(match):
            return match.group(1).strip()
        
        cleaned_code = re.sub(pattern, replacer, code, flags=re.MULTILINE)
        return cleaned_code.strip()
    
    @staticmethod
    def remove_comment(code: str) -> str:
        multiline_pattern = r'/-((!)?.*?)-/'
        code = re.sub(multiline_pattern, '', code, flags=re.DOTALL)
        singleline_pattern = r'--.*?$'
        # Using re.MULTILINE to make $ match the end of each line
        code = re.sub(singleline_pattern, '', code, flags=re.MULTILINE)
        return code

    @staticmethod
    def sanitize_lean_code(code: str) -> str:
        """
        Remove comments and excess whitespace, normalize newlines for regex-friendly processing.
        """
        if code is None:
            return ''
        code = CodeUtil.remove_comment(code)
        # Normalize newlines
        code = code.replace('\r\n', '\n').replace('\r', '\n')
        # Strip trailing whitespace
        code = '\n'.join([line.rstrip() for line in code.split('\n')])
        # Collapse multiple blank lines to at most one
        lines = []
        blank_streak = 0
        for line in code.split('\n'):
            if line.strip() == '':
                blank_streak += 1
            else:
                blank_streak = 0
            if blank_streak <= 1:
                lines.append(line)
        return '\n'.join(lines).strip()
    
    @staticmethod
    def normalize_headers(code: str) -> Optional[str]:
        """
        Remove all import lines; if any line imports Aesop, prepend 'import Mathlib' and 'import Aesop'.
        Otherwise, prepend only 'import Mathlib'.
        """
        if code is None:
            return None

        lines = code.split('\n')
        import_lines = [line for line in lines if 'import' in line]
        has_aesop = any('import Aesop' in line for line in import_lines)
        rest = [line for line in lines if not line.strip().startswith('import')]
        if has_aesop:
            header = 'import Mathlib\nimport Aesop'
        else:
            header = 'import Mathlib'
        code_body = '\n'.join(rest).lstrip('\n')  # Remove leading blank lines
        return f"{header}\n\n{code_body}"

    @staticmethod
    def _iter_blocks(code: str, kind: str) -> List[str]:
        """
        Extract multi-line blocks by kind (e.g., 'def').
        Each block starts at the matched item and ends at the next block start or EOF.
        """
        if not code.strip():
            return []
        
        # Possible block starters
        block_begin = r"(noncomputable\s+def|def|lemma|theorem|noncomputable\s+instance|instance|example|class|structure)"
        # End markers
        block_end = r"(?:^noncomputable\b|^def\b|^lemma\b|^theorem\b|^instance\b|^example\b|^variable\b|^open\b|^namespace\b|^section\b|^end\b|^class\b|^structure\b)"
        
        # Ensure trailing newline
        code_with_newline = code if code.endswith('\n') else code + '\n'
        
        # Build regex: from current kind to the next block_end, multi-line safe
        results = []
        pattern = rf"^{block_begin}.*?(?=\n{block_end}|\Z)"
        
        # DOTALL: make '.' match newlines
        matches = re.finditer(pattern, code_with_newline, re.MULTILINE | re.DOTALL)
        
        for match in matches:
            block_text = match.group(0)
            # Check if this block starts with the target kind
            first_line = block_text.lstrip().split('\n')[0]
            if kind == 'def':
                # Match either 'noncomputable def' or 'def'
                if first_line.startswith('noncomputable def ') or first_line.startswith('def '):
                    results.append(block_text.strip())
            elif kind == 'instance':
                # Match either 'noncomputable instance' or 'instance'
                if first_line.startswith('noncomputable instance ') or first_line.startswith('instance '):
                    results.append(block_text.strip())
            else:
                # Other kinds: direct prefix match
                if first_line.startswith(kind + ' '):
                    results.append(block_text.strip())
        
        return results

    @staticmethod
    def extract_components(code: str) -> Dict[str, Any]:
        """
        Split Lean code into components: headers and blocks by kind.
        Returns a dict with: defs, lemmas, instances, theorems, classes, structures, last_theorem.
        """
        sanitized = CodeUtil.sanitize_lean_code(code)
        
        # Extract components
        defs = CodeUtil._iter_blocks(sanitized, 'def')
        lemmas = CodeUtil._iter_blocks(sanitized, 'lemma')
        instances = CodeUtil._iter_blocks(sanitized, 'instance')
        theorems = CodeUtil._iter_blocks(sanitized, 'theorem')
        classes = CodeUtil._iter_blocks(sanitized, 'class')
        structures = CodeUtil._iter_blocks(sanitized, 'structure')
        
        # Extract the name of the last theorem (from text)
        last_theorem = None
        if theorems:
            last_block = theorems[-1]
            # Parse theorem name from the first line of the block
            first_line = last_block.strip().split('\n')[0]
            name_match = re.match(r'^theorem\s+([A-Za-z_][\w\']*)', first_line)
            if name_match:
                last_theorem = name_match.group(1)
        
        return {
            'defs': defs,
            'lemmas': lemmas,
            'instances': instances,
            'theorems': theorems,
            'classes': classes,
            'structures': structures,
            'last_theorem': last_theorem,
        }

    @staticmethod
    def check_forbidden(code: str) -> bool:
        """Return True if any forbidden keywords exist (indicating failure)."""
        text = CodeUtil.sanitize_lean_code(code)
        return re.search(r"\b(axiom|opaque|unsafe|unsound)\b", text) is not None

    @staticmethod
    def check_presence(codes: List[str], target_text: str) -> Tuple[bool, str]:
        """
        Check exact substring inclusion after canonicalization.
        - Canonicalize target_text and each code block, then test if block is a substring of target.
        - If any block is missing, return (False, first-line snippet of that block); otherwise (True, '').
        """
        if not codes:
            return True, ''
        if target_text is None:
            return False, codes[0] if codes else ''
        canon_target = CodeUtil.canonicalize_block(target_text)
        for item in codes:
            if item is None:
                continue
            s = str(item)
            if not s.strip():
                continue
            canon_item = CodeUtil.canonicalize_block(s)
            if canon_item not in canon_target:
                first_line = canon_item.split('\n', 1)[0]
                return False, first_line[:120]
        return True, ''

    @staticmethod
    def static_precheck(code: str, formal: str) -> Tuple[bool, str, str]:
        """
        To be add
        """
        if not code or not formal:
            return False, 'empty code or formal', ''

        # Normalize code
        normalized_code = CodeUtil.normalize_headers(CodeUtil.sanitize_lean_code(code))
        if normalized_code is None:
            return False, 'code normalization failed', ''
        normalized_formal = CodeUtil.normalize_headers(CodeUtil.sanitize_lean_code(formal))
        if normalized_formal is None:
            return False, 'formal normalization failed', ''
        
        # Forbidden keywords check
        if CodeUtil.check_forbidden(normalized_code):
            return False, 'forbidden keywords found', normalized_code
        
        formal_comps = CodeUtil.extract_components(normalized_formal)

        formal_defs: List[str] = formal_comps.get('defs', [])
        formal_lemmas: List[str] = formal_comps.get('lemmas', [])
        formal_instances: List[str] = formal_comps.get('instances', [])
        formal_structures: List[str] = formal_comps.get('structures', [])
        formal_classes: List[str] = formal_comps.get('classes', [])
        formal_last_theorem: Optional[str] = formal_comps.get('last_theorem')

        # Remove proof parts for comparison
        formal_lemmas = [CodeUtil.remove_proof(l) for l in formal_lemmas if l is not None]
        if formal_last_theorem is not None:
            formal_last_theorem = CodeUtil.remove_proof(formal_last_theorem)

        # Check presence of all formal_* in normalized_code
        checks = [
            ('def', formal_defs),
            ('lemma', formal_lemmas),
            ('instance', formal_instances),
            ('structure', formal_structures),
            ('class', formal_classes),
        ]

        # 在进行包含性检查前，对代码与各 formal item 进行统一规范化
        canon_code = CodeUtil.canonicalize_block(normalized_code)
        for kind, items in checks:
            if items:
                ok, missing = CodeUtil.check_presence(items, canon_code)
                if not ok:
                    return False, f"missing {kind}: {missing}", normalized_code

        if formal_last_theorem:
            ok, missing = CodeUtil.check_presence([formal_last_theorem], canon_code)
            if not ok:
                return False, f"missing last_theorem: {missing}", normalized_code

        return True, 'static checks passed', normalized_code
    
    @staticmethod
    def get_headers(code: str) -> List[str]:
        code = CodeUtil.remove_comment(code)
        headers = []
        for line in code.splitlines():
            if not line.strip().startswith("import"):
                break
            headers.append(line.strip())
        return headers
            
    
    @staticmethod
    def add_header(code: str, new_header: str) -> str:
        if new_header in CodeUtil.get_headers(code):
            return code
        return new_header + '\n' + code
    
    @staticmethod
    def find_lean_theorem_end_pos(lean_code: str) -> int:
        """
        找到 Lean4 字符串中最后一个 theorem/lemma/instance/example 后紧跟的 `:= by` 或 `:=by` 的结束位置。
        
        参数:
            lean_code: 包含 Lean4 定理和证明的字符串
            
        返回:
            最后一个匹配的 `:= by` 或 `:=by` 的结束位置（字符索引，从 0 开始），
            如果没有找到则返回 -1。
        """
        # 匹配 theorem/lemma/instance/example 后跟着 := by 或 :=by
        pattern = r'(?:theorem|lemma|instance|example).*?:=\s*by'
        
        # 查找所有匹配项
        matches = list(re.finditer(pattern, lean_code, re.DOTALL))
        
        if not matches:
            return -1  # 没有找到匹配
        
        # 取最后一个匹配
        last_match = matches[-1]
        
        # 返回匹配的结束位置（即 := by 后的第一个字符的位置）
        return last_match.end()
    
    @staticmethod
    def split_lean_proof_code(code: str) -> Optional[str]:
        end_pos = CodeUtil.find_lean_theorem_end_pos(code)
        if end_pos == -1:
            return None
        else:
            return code[end_pos:] 
    
    @staticmethod
    def extract_last_statement_from_code(code: str, keywords: List[str] = ['lemma', 'theorem', 'example']) -> str:
        pattern = rf'({"|".join(keywords)})'
        matches = list(re.finditer(pattern, code, re.IGNORECASE))
    
        if not matches:
            return code
    
        # Get the last match
        last_match = matches[-1]
        start_pos = last_match.start()
    
        # Return from the last keyword to the end of string
        return code[start_pos:]

class ProcessUtil:
    @staticmethod
    def kill_repl() -> None:
        cmd = ['pkill', '-9', 'repl']
        try:
            subprocess.run(cmd, check=True, stderr=subprocess.PIPE, text=True)
            print('Killed all repl process')
        except subprocess.CalledProcessError as e:
            if e.returncode == 1:
                print('No running repl process to kill')
            else:
                print(traceback.format_exc())
    
    @staticmethod
    def kill_lean() -> None:
        cmd = ['pkill', '-9', 'lean']
        try:
            subprocess.run(cmd, check=True, stderr=subprocess.PIPE, text=True)
            print('Killed all lean process')
        except subprocess.CalledProcessError as e:
            if e.returncode == 1:
                print('No running lean process to kill')
            else:
                print(traceback.format_exc())
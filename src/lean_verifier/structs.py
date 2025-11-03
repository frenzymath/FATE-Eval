from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from .pretty import pretty_print_message, no_pos_pretty_print_message

class Pos(BaseModel):
    line: int
    column: int

Severity = Literal['error', 'warning', 'information', 'sorry']

class Message(BaseModel):
    severity: Severity
    pos: Pos | None
    end_pos: Pos | None
    # kind: str
    keep_full_range: bool
    data: str
    caption: str

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    def pretty(self, code: str) -> str:
        if self.pos is None or self.end_pos is None:
            return no_pos_pretty_print_message(self.severity, self.caption, self.data)
        return pretty_print_message(
            self.pos.line, self.pos.column, self.end_pos.line, self.end_pos.column,
            self.severity, self.caption, self.data, code
        )
        

class SortedMessages(BaseModel):
    sorries: list[Message] = []
    errors: list[Message] = []
    warnings: list[Message] = []
    informations: list[Message] = []

    def pretty(self, code: str) -> str:
        """ Pretty print all messages with context from the code. """
        all_messages = self.sorries + self.errors + self.warnings + self.informations
        if not all_messages:
            return "No messages."
        
        pretty_messages = [msg.pretty(code) for msg in all_messages]
        return "\n\n".join(pretty_messages)

class VerifyResult(BaseModel):
    sorted_messages: SortedMessages
    system_errors: str | None
    verified_code: str
    verified_timeout: int
    pass_: bool # Indicates if the verification passed the compiler
    complete: bool # Indicates if the verification contains no sorries or failed declarations
    is_timeout: bool
    verify_time: float
    complete_timestamp: str
    extra_info: dict
    lean_toolchain: str | None = None

    @staticmethod
    def from_system_error(code: str, timeout: int, system_errors: str, lean_toolchain: str='remote') -> 'VerifyResult':
        return VerifyResult(
            sorted_messages=SortedMessages(),
            system_errors=system_errors,
            verified_code=code,
            verified_timeout=timeout,
            pass_=False,
            complete=False,
            is_timeout=False,
            verify_time=0.0,
            complete_timestamp=datetime.now().isoformat(),
            extra_info={},
            lean_toolchain=lean_toolchain
        )

    @staticmethod
    def from_timeout(code: str, timeout: int, lean_toolchain: str='remote') -> 'VerifyResult':
        return VerifyResult(
            sorted_messages=SortedMessages(),
            system_errors=None,
            verified_code=code,
            verified_timeout=timeout,
            pass_=False,
            complete=False,
            is_timeout=True,
            verify_time=0.0,
            complete_timestamp=datetime.now().isoformat(),
            extra_info={},
            lean_toolchain=lean_toolchain
        )
    def pretty(self) -> str:
        """ Pretty print the verification result. """
        result = []
        if self.system_errors:
            result.append(f"System Errors: {self.system_errors}")
        result.append(f"Pass: {self.pass_}, Complete: {self.complete}, Timeout: {self.is_timeout}")
        result.append(f"Messages:\n{self.sorted_messages.pretty(self.verified_code)}")
        return "\n".join(result)


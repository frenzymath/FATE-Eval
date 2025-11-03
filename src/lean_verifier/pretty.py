def no_pos_pretty_print_message(
    severity: str,
    caption: str,
    data: str
) -> str:
    return f"{severity.upper()}: {caption} - {data}"

def pretty_print_message(
    start_line: int, 
    start_column: int, 
    end_line: int, 
    end_column: int, 
    severity: str,
    caption: str,
    data: str,
    code: str, ctx: int=2
) -> str:
    """ Pretty print the message with context from the code, 
    so that users can understand the message better.
    """
    
    lines = code.splitlines()
    sl, sc = start_line, start_column
    el, ec = end_line, end_column

    out: list[str] = []
    ln_width = len(str(el + ctx))  # width for number column

    # Helper that prints a normal line with its number
    def add_line(n: int, text: str):
        out.append(f"{str(n).rjust(ln_width)}│ {text}")

    # Context *before* the span
    for i in range(max(1, sl - ctx), sl):
        add_line(i, lines[i - 1])

    # Handle single- vs multi-line span
    if sl == el:
        line = lines[sl - 1]
        add_line(sl, line)
        caret_len = max(1, ec - sc)
        out.append(
            f'{" " * ln_width}│ ' + " " * (sc) + "^" * caret_len
        )
    else:
        # first line
        first = lines[sl - 1]
        add_line(sl, first)
        out.append(
            f'{" " * ln_width}│ ' + " " * (sc) + "^" * (len(first) - sc + 1)
        )
        # middle lines
        for n in range(sl + 1, el):
            add_line(n, lines[n - 1])
            out.append(f'{" " * ln_width}│ ' + "^" * len(lines[n - 1]))
        # last line
        last = lines[el - 1]
        add_line(el, last)
        out.append(
            f'{" " * ln_width}│ ' + "^" * ec
        )

    # Context *after* the span
    for i in range(el + 1, min(len(lines) + 1, el + ctx + 1)):
        add_line(i, lines[i - 1])

    snippet = "\n".join(out)

    return f"{severity.upper()}: {caption} - {data}\nContext:\n{snippet}"
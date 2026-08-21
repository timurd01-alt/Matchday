"""Find the top-level declarations in a classic (non-module) browser script.

Matchday's front end is nine plain <script> files that share one global lexical
scope -- there is no bundler, no module system, and no build step. That makes a
name collision between any two of them a hard SyntaxError, and a SyntaxError in
a classic script blanks the whole app rather than degrading one panel. Nothing
was watching for it; this is what ui_audit uses so something is.

A regex cannot answer the question. These files carry 7,000-character lines and
build their markup in template literals, so the text `const x = 1` appears
inside strings, and `function` appears inside HTML attribute values. The scanner
below therefore tracks lexical state properly -- line and block comments, the
three string flavours, `${}` interpolation nesting inside template literals, and
regex literals -- and reports a declaration only at brace depth zero, outside
all of it.

Regex-vs-division is the one genuinely ambiguous case in JavaScript without a
full parser. The standard heuristic is used: a `/` begins a regex literal unless
the previous significant token could end an expression (an identifier, number,
`)`, `]`, or `}`). The keywords that can precede a regex despite being
identifier-shaped (`return`, `typeof`, `case`, ...) are listed explicitly.
"""

from __future__ import annotations

from typing import Iterator, NamedTuple

DECLARATION_KEYWORDS = ("const", "let", "var", "function", "class")

# Identifier-shaped tokens after which a `/` still starts a regex, not division.
_REGEX_PRECEDING_KEYWORDS = frozenset({
    "return", "typeof", "instanceof", "in", "of", "new", "delete", "void",
    "throw", "case", "do", "else", "yield", "await",
})

_ID_START = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_$")
_ID_CHARS = _ID_START | set("0123456789")


class Declaration(NamedTuple):
    name: str
    kind: str
    line: int


def _is_identifier_char(ch: str) -> bool:
    return ch in _ID_CHARS


def top_level_declarations(source: str) -> list[Declaration]:
    """Every name declared at brace depth zero, in source order."""
    return list(_scan(source))


def _scan(source: str) -> Iterator[Declaration]:
    i = 0
    n = len(source)
    line = 1
    depth = 0                 # {} nesting
    paren = 0                 # () nesting -- a declaration inside for(...) is not top level
    bracket = 0
    template_stack: list[int] = []   # depth of `${` interpolation per open template
    prev_token = ""           # last significant token, for the regex heuristic

    while i < n:
        ch = source[i]

        if ch == "\n":
            line += 1
            i += 1
            continue

        # ---- comments -------------------------------------------------
        if ch == "/" and i + 1 < n:
            nxt = source[i + 1]
            if nxt == "/":
                j = source.find("\n", i)
                i = n if j == -1 else j
                continue
            if nxt == "*":
                j = source.find("*/", i + 2)
                j = n if j == -1 else j + 2
                line += source.count("\n", i, j)
                i = j
                continue
            # ---- regex literal vs division ----------------------------
            if _starts_regex(prev_token):
                i, line = _skip_regex(source, i, line)
                prev_token = "/regex/"
                continue
            prev_token = "/"
            i += 1
            continue

        # ---- strings --------------------------------------------------
        if ch in "'\"":
            i, line = _skip_quoted(source, i, line, ch)
            prev_token = "'str'"
            continue

        if ch == "`":
            template_stack.append(depth)
            i, line, closed = _skip_template(source, i, line)
            if closed:
                template_stack.pop()
                prev_token = "`str`"
            else:
                # stopped at a `${` -- resume normal scanning inside it
                prev_token = "${"
            continue

        # A `}` that closes a `${` interpolation resumes the template.
        if ch == "}" and template_stack and depth == template_stack[-1]:
            i, line, closed = _skip_template(source, i, line, resuming=True)
            if closed:
                template_stack.pop()
                prev_token = "`str`"
            else:
                prev_token = "${"
            continue

        # ---- structure ------------------------------------------------
        if ch == "{":
            depth += 1
            prev_token = "{"
            i += 1
            continue
        if ch == "}":
            depth -= 1
            prev_token = "}"
            i += 1
            continue
        if ch == "(":
            paren += 1
            prev_token = "("
            i += 1
            continue
        if ch == ")":
            paren -= 1
            prev_token = ")"
            i += 1
            continue
        if ch == "[":
            bracket += 1
            prev_token = "["
            i += 1
            continue
        if ch == "]":
            bracket -= 1
            prev_token = "]"
            i += 1
            continue

        # ---- identifiers / keywords -----------------------------------
        if ch in _ID_START:
            j = i + 1
            while j < n and _is_identifier_char(source[j]):
                j += 1
            word = source[i:j]
            if (word in DECLARATION_KEYWORDS
                    and depth == 0 and paren == 0 and bracket == 0
                    and not template_stack
                    and prev_token not in {".", "?."}):
                name = _declared_name(source, j)
                if name:
                    yield Declaration(name, word, line)
            prev_token = word
            i = j
            continue

        if not ch.isspace():
            prev_token = ch
        i += 1


def _declared_name(source: str, index: int) -> str | None:
    """The identifier following a declaration keyword, if there is a plain one.

    Destructuring (`const {a, b} = x`) and `function*` are deliberately not
    reported: the collision rule this feeds only needs plain named bindings,
    and guessing at destructured names would produce false collisions.
    """
    i = index
    n = len(source)
    while i < n and source[i] in " \t\r\n*":
        i += 1
    if i >= n or source[i] not in _ID_START:
        return None
    j = i + 1
    while j < n and _is_identifier_char(source[j]):
        j += 1
    return source[i:j]


def _starts_regex(prev_token: str) -> bool:
    if not prev_token:
        return True
    if prev_token in _REGEX_PRECEDING_KEYWORDS:
        return True
    last = prev_token[-1]
    if last in ")]}":
        return False
    if prev_token in {"'str'", "`str`", "/regex/"}:
        return False
    if _is_identifier_char(last):
        return False
    return True


def _skip_quoted(source: str, i: int, line: int, quote: str) -> tuple[int, int]:
    n = len(source)
    i += 1
    while i < n:
        ch = source[i]
        if ch == "\\":
            if source[i + 1:i + 2] == "\n":
                line += 1
            i += 2
            continue
        if ch == "\n":
            line += 1
        elif ch == quote:
            return i + 1, line
        i += 1
    return n, line


def _skip_regex(source: str, i: int, line: int) -> tuple[int, int]:
    n = len(source)
    i += 1
    in_class = False
    while i < n:
        ch = source[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "\n":          # unterminated; bail rather than run away
            return i, line
        if ch == "[":
            in_class = True
        elif ch == "]":
            in_class = False
        elif ch == "/" and not in_class:
            i += 1
            while i < n and source[i].isalpha():   # flags
                i += 1
            return i, line
        i += 1
    return n, line


def _skip_template(source: str, i: int, line: int,
                   resuming: bool = False) -> tuple[int, int, bool]:
    """Advance through a template literal to its close or its next `${`.

    Returns (index, line, closed) -- closed is False when it stopped at a `${`,
    meaning the caller should resume ordinary scanning of the interpolation.
    """
    n = len(source)
    i += 1                      # step over the opening ` or the closing } of ${}
    while i < n:
        ch = source[i]
        if ch == "\\":
            if source[i + 1:i + 2] == "\n":
                line += 1
            i += 2
            continue
        if ch == "\n":
            line += 1
        elif ch == "`":
            return i + 1, line, True
        elif ch == "$" and source[i + 1:i + 2] == "{":
            return i + 2, line, False
        i += 1
    return n, line, True

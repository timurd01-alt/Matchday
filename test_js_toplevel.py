"""The top-level declaration scanner, and the cases a regex gets wrong.

This exists because ui_audit's js-global-collision rule is only as trustworthy
as its parsing. Matchday's front-end scripts build their markup in template
literals on 7,000-character lines, so the literal text `const x=1` and the word
`function` both appear inside strings that are not code. A scanner that reports
those produces phantom collisions, and a rule that cries wolf gets deleted.

The scanner was validated against a real JavaScript engine before these tests
were written: run over the nine scripts index.html loads, it reported 393
function declarations, every one of which was a live function on `window` in the
browser -- zero false positives -- and missed only `researchSignalsPanel`, which
is a `window.x = function` assignment rather than a declaration and so is
correctly out of scope. These tests pin the lexical corners that validation
exercised only incidentally.
"""

import unittest
from pathlib import Path

from js_toplevel import top_level_declarations


def names(source):
    return [d.name for d in top_level_declarations(source)]


class BasicDeclarationTests(unittest.TestCase):
    def test_each_declaration_keyword_is_recognised(self):
        source = "const a=1;\nlet b=2;\nvar c=3;\nfunction d(){}\nclass e{}\n"
        self.assertEqual(names(source), ["a", "b", "c", "d", "e"])

    def test_the_kind_and_line_are_reported(self):
        decls = top_level_declarations("const a=1;\n\nfunction b(){}\n")
        self.assertEqual([(d.name, d.kind, d.line) for d in decls],
                         [("a", "const", 1), ("b", "function", 3)])

    def test_nested_declarations_are_not_top_level(self):
        source = "function outer(){ const inner=1; function deeper(){} }\n"
        self.assertEqual(names(source), ["outer"])

    def test_a_declaration_inside_a_block_is_not_top_level(self):
        self.assertEqual(names("{ const scoped=1; }\nconst real=2;\n"), ["real"])

    def test_a_for_loop_binding_is_not_top_level(self):
        self.assertEqual(names("for(let i=0;i<3;i++){}\nconst after=1;\n"), ["after"])

    def test_an_async_function_is_recognised(self):
        self.assertEqual(names("async function go(){}\n"), ["go"])

    def test_a_generator_star_does_not_swallow_the_name(self):
        self.assertEqual(names("function* gen(){}\n"), ["gen"])


class StringAndCommentTests(unittest.TestCase):
    """The cases that make a regex-based scanner unusable on this codebase."""

    def test_a_declaration_inside_a_single_quoted_string_is_ignored(self):
        self.assertEqual(names("const real='const fake=1';\n"), ["real"])

    def test_a_declaration_inside_a_double_quoted_string_is_ignored(self):
        self.assertEqual(names('const real="function fake(){}";\n'), ["real"])

    def test_a_declaration_inside_a_template_literal_is_ignored(self):
        self.assertEqual(names("const real=`\nconst fake=1;\nfunction alsoFake(){}\n`;\n"),
                         ["real"])

    def test_markup_in_a_template_literal_is_ignored(self):
        # The actual shape of app-3-panels.js: HTML with class attributes,
        # newlines, and quotes, all inside a template literal.
        source = ('function renderThing(){\n'
                  '  return `<div class="statuscard info">\n'
                  '<span class="slbl">let x</span>\n'
                  '<button onclick="var y=1">go</button>\n'
                  '</div>`;\n'
                  '}\n'
                  'const after=1;\n')
        self.assertEqual(names(source), ["renderThing", "after"])

    def test_code_inside_template_interpolation_is_still_scanned_but_not_top_level(self):
        source = "const a=`x${(() => { const inner=1; return inner; })()}y`;\nconst b=2;\n"
        self.assertEqual(names(source), ["a", "b"])

    def test_a_nested_template_inside_interpolation_is_handled(self):
        source = "const a=`outer ${cond ? `inner const fake=1` : ''} end`;\nconst b=2;\n"
        self.assertEqual(names(source), ["a", "b"])

    def test_an_escaped_quote_does_not_end_the_string(self):
        self.assertEqual(names("const a='it\\'s const fake=1';\nconst b=2;\n"), ["a", "b"])

    def test_an_escaped_backtick_does_not_end_a_template(self):
        self.assertEqual(names("const a=`tick \\` const fake=1`;\nconst b=2;\n"), ["a", "b"])

    def test_a_line_comment_is_ignored(self):
        self.assertEqual(names("// const fake=1;\nconst real=2;\n"), ["real"])

    def test_a_block_comment_is_ignored(self):
        self.assertEqual(names("/* const fake=1;\n function alsoFake(){} */\nconst real=2;\n"),
                         ["real"])

    def test_lines_are_still_counted_through_a_block_comment(self):
        decls = top_level_declarations("/*\n\n\n*/\nconst a=1;\n")
        self.assertEqual(decls[0].line, 5)


class RegexLiteralTests(unittest.TestCase):
    """Regex-vs-division is the one real ambiguity without a full parser."""

    def test_a_brace_inside_a_regex_does_not_open_a_block(self):
        source = "const re=/[{]/;\nconst after=1;\n"
        self.assertEqual(names(source), ["re", "after"])

    def test_a_quote_inside_a_regex_does_not_open_a_string(self):
        source = "const re=/['\"]/;\nconst after=1;\n"
        self.assertEqual(names(source), ["re", "after"])

    def test_a_slash_inside_a_character_class_does_not_end_the_regex(self):
        source = "const re=/[/]{/;\nconst after=1;\n"
        self.assertEqual(names(source), ["re", "after"])

    def test_division_is_not_mistaken_for_a_regex(self):
        source = "const a=(1)/2;\nconst b=x/y;\nconst c=3;\n"
        self.assertEqual(names(source), ["a", "b", "c"])

    def test_a_regex_after_return_is_recognised(self):
        source = "function f(){ return /}{/.test(s); }\nconst after=1;\n"
        self.assertEqual(names(source), ["f", "after"])

    def test_a_regex_with_flags_is_consumed(self):
        self.assertEqual(names("const re=/ab{/gi;\nconst after=1;\n"), ["re", "after"])


class ShippedBundleTests(unittest.TestCase):
    """Sanity checks against the real files, not synthetic snippets."""

    BUNDLE = ("translations.js", "updates.js", "app-1-core.js",
              "official-selections.js", "app-2-views.js",
              "app-3-panels.js", "app-4-features.js", "research-signals.js")

    def declarations(self):
        out = {}
        for name in self.BUNDLE:
            path = Path(name)
            if not path.is_file():
                continue
            for decl in top_level_declarations(
                    path.read_text(encoding="utf-8", errors="replace")):
                out.setdefault(decl.name, []).append((name, decl.line))
        return out

    def test_the_shipped_bundle_parses_without_a_runaway(self):
        # A scanner that loses its place in a template literal reports almost
        # nothing; one that loses its place in a string reports nonsense. The
        # real bundle sits in the hundreds.
        decls = self.declarations()
        self.assertGreater(len(decls), 300)

    def test_known_helpers_are_found(self):
        decls = self.declarations()
        for name in ("esc", "load", "setView", "renderScore", "openMatchModal"):
            with self.subTest(helper=name):
                self.assertIn(name, decls)

    def test_words_that_only_appear_inside_markup_are_not_reported(self):
        # These read like declarations to a line-based regex because they occur
        # at the start of a wrapped line inside a template literal. They are
        # not declarations, and reporting them would invent collisions.
        decls = self.declarations()
        for name in ("statuscard", "slbl", "div", "span"):
            with self.subTest(word=name):
                self.assertNotIn(name, decls)


if __name__ == "__main__":
    unittest.main()

"""build_css.minify_css keeps the meaning of every selector (PASS-59-167)."""
from build_css import minify_css


def test_space_before_pseudo_class_is_kept():
    # `html :is(.a)` matches a descendant; `html:is(.a)` only the root itself.
    assert minify_css("html :is(.a, .b) { color: red; }") == "html :is(.a,.b){color:red}"


def test_declaration_colons_still_tight():
    assert minify_css(".a:hover { color: red; }") == ".a:hover{color:red}"

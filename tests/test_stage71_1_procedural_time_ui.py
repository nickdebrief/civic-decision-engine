from __future__ import annotations

from html.parser import HTMLParser

from api import record_governed_procedural_time as rg71


class _StructureParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.unbalanced: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"form", "section", "table", "div", "label"}:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs) -> None:
        return

    def handle_endtag(self, tag: str) -> None:
        if tag not in {"form", "section", "table", "div", "label"}:
            return
        if not self.stack or self.stack[-1] != tag:
            self.unbalanced.append(f"unexpected </{tag}>")
            return
        self.stack.pop()


def _page() -> str:
    from api.routes import admin_session

    return admin_session._stage71_html(
        admin_session={"username": "admin"},
        diagnostic={"records": []},
        sources=[],
        objects=[],
    )


def test_stage71_forms_and_sections_are_balanced_and_separate() -> None:
    html = _page()
    parser = _StructureParser()
    parser.feed(html)

    assert parser.unbalanced == []
    assert parser.stack == []
    assert html.count('<section class="stage71-panel"') == 2
    assert html.count('<form ') == html.count('</form>')
    assert html.count('action="/api/admin/session/governed-procedural-time/notices"') == 1
    assert html.count('action="/api/admin/session/governed-procedural-time/deadlines"') == 1
    assert html.index('action="/api/admin/session/governed-procedural-time/notices"') < html.index('action="/api/admin/session/governed-procedural-time/deadlines"')
    assert html.index('</form></section><section class="stage71-panel"') < html.index('Record deadline')
    assert 'id="stage71-notice-heading"' in html
    assert 'id="stage71-deadline-heading"' in html


def test_stage71_controls_are_bounded_and_table_is_responsive() -> None:
    html = _page()

    assert ".stage71-panel" in html
    assert ".stage71-panel input,.stage71-panel select,.stage71-panel textarea" in html
    assert "box-sizing:border-box" in html
    assert "max-width:100%" in html
    assert "width:100vw" not in html
    assert "min-width:100vw" not in html
    assert 'class="stage71-table-wrap"' in html
    assert "overflow-x:auto" in html
    assert "No procedural notices or deadlines recorded." in html


def test_stage71_declaration_is_neutral_by_default_and_category_specific() -> None:
    html = _page()
    declaration = rg71.DECLARATIONS["notice_received_as_evidenced"]

    assert 'id="stage71-notice-declaration" class="stage71-declaration" hidden' in html
    assert 'id="stage71-notice-declaration-checkbox" type="checkbox" name="declaration_acknowledged" value="1" disabled' in html
    assert 'for="stage71-notice-declaration-checkbox"' in html
    assert 'Select a category to display any category-specific declaration required.' not in html
    assert declaration in html
    assert 'category.value==="notice_received_as_evidenced"' in html
    assert 'No additional category-specific declaration applies.' in html
    assert 'box.checked=false' in html
    assert rg71.NOTICE_CATEGORIES


def test_stage71_language_and_navigation_boundaries_remain_present() -> None:
    html = _page()

    assert "NOTICE ISSUED IS NOT NOTICE RECEIVED." in html
    assert "TIME CALCULATED IS NOT LATENESS DETERMINED." in html
    assert "does not establish service, lateness, default, admissibility, waiver, abandonment, jurisdiction or legal effect" in html
    assert "/admin/governed-procedural-time" in html
    assert 'href="/admin/governed-procedural-time"' in html
    assert 'href="/governed-procedural-time"' not in html

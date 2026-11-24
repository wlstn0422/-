"""reports/ 아래 마크다운을 docs/ 아래 HTML로 바꾼다(GitHub Pages용)."""

from __future__ import annotations

import posixpath
import re
from pathlib import Path

import markdown
from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

from .settings import Settings

TEMPLATE_DIR = Path(__file__).parent / "templates"
_MD_LINK = re.compile(r"\]\((?!https?://|mailto:|#)([^)\s]+?)\.md(#[^)]*)?\)")
_TABLE = re.compile(r"(<table>.*?</table>)", re.S)
_REL_LINK = re.compile(r"\]\((?!https?://|mailto:|#|/)([^)\s]+)\)")


def rebase_md_links(text: str, from_dir: str) -> str:
    """from_dir 폴더 기준 상대 링크를 사이트 맨 위 기준으로 바꾼다('../../theories.md#x' → 'theories.md#x')."""
    def fix(m: re.Match) -> str:
        path, sep, frag = m.group(1).partition("#")
        new = posixpath.normpath(posixpath.join(from_dir, path)) if path else ""
        return f"]({new}{sep}{frag})"
    return _REL_LINK.sub(fix, text)


def md_to_html(text: str) -> str:
    text = _MD_LINK.sub(lambda m: f"]({m.group(1)}.html{m.group(2) or ''})", text)
    html = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "sane_lists", "md_in_html", "attr_list"],
        output_format="html5",
    )
    return _TABLE.sub(r'<div class="table-wrap">\1</div>', html)


def build_site(settings: Settings) -> list[Path]:
    src = settings.reports_dir
    dst = settings.docs_dir
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=False)
    page = env.get_template("page.html.j2")
    site_title = settings.report_cfg.get("title", "매일 기업 케이스 노트")
    has_scale = (src / "scale.md").exists()
    written = []
    for md_path in sorted(src.rglob("*.md")):
        rel = md_path.relative_to(src)
        out_rel = Path("index.html") if rel.as_posix() == "README.md" else rel.with_suffix(".html")
        out = dst / out_rel
        depth = len(out_rel.parts) - 1
        root = "../" * depth
        text = md_path.read_text(encoding="utf-8")
        m = re.search(r"^#\s+(.+)$", text, re.M)
        title = m.group(1).strip() if m else site_title
        html = page.render(title=title, body=Markup(md_to_html(text)), root=root, site_title=site_title, has_scale=has_scale)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
        written.append(out)
    # 오늘의 노트(today.html): 가장 최근 일일 노트를 고정 주소로. 앱의 '오늘의 노트' 탭이 연다.
    dailies = sorted(src.glob("daily/*/*.md"))
    if dailies:
        latest = dailies[-1]
        text = rebase_md_links(latest.read_text(encoding="utf-8"), latest.parent.relative_to(src).as_posix())
        m = re.search(r"^#\s+(.+)$", text, re.M)
        title = m.group(1).strip() if m else site_title
        out = dst / "today.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(page.render(title=title, body=Markup(md_to_html(text)), root="", site_title=site_title,
                                   has_scale=has_scale), encoding="utf-8")
        written.append(out)
    (dst / ".nojekyll").parent.mkdir(parents=True, exist_ok=True)
    (dst / ".nojekyll").write_text("", encoding="utf-8")
    return written

import re
import unittest
from pathlib import Path
from urllib.parse import unquote


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


class DocumentationLinksTests(unittest.TestCase):
    def test_local_markdown_links_resolve(self):
        failures: list[str] = []
        markdown_files = sorted(REPOSITORY_ROOT.glob("*.md"))
        markdown_files.extend(
            sorted((REPOSITORY_ROOT / ".agents").rglob("*.md"))
        )
        markdown_files.extend(
            sorted((REPOSITORY_ROOT / ".github").rglob("*.md"))
        )
        markdown_files.extend(
            sorted((REPOSITORY_ROOT / "docs").rglob("*.md"))
        )

        for document in markdown_files:
            inside_fenced_code = False
            for line_number, line in enumerate(
                document.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if line.lstrip().startswith(("```", "~~~")):
                    inside_fenced_code = not inside_fenced_code
                    continue
                if inside_fenced_code:
                    continue

                for raw_target in MARKDOWN_LINK.findall(line):
                    target = raw_target.strip()
                    if target.startswith(("#", "http://", "https://", "mailto:")):
                        continue

                    # Markdown titles are not used by the project. If one is added,
                    # keep the path before the title for a useful failure message.
                    target = target.split(maxsplit=1)[0].strip("<>")
                    path_part = unquote(target.split("#", maxsplit=1)[0])
                    if not path_part:
                        continue

                    resolved = (document.parent / path_part).resolve()
                    try:
                        resolved.relative_to(REPOSITORY_ROOT)
                    except ValueError:
                        failures.append(
                            f"{document.relative_to(REPOSITORY_ROOT)}:{line_number}: "
                            f"link escapes repository: {raw_target}"
                        )
                        continue

                    if not resolved.exists():
                        failures.append(
                            f"{document.relative_to(REPOSITORY_ROOT)}:{line_number}: "
                            f"missing link target: {raw_target}"
                        )

        self.assertEqual([], failures, "\n" + "\n".join(failures))


if __name__ == "__main__":
    unittest.main()

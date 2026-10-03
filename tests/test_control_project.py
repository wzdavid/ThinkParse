import json
import unittest
from pathlib import Path

from control.project import ProjectionError, project_mineru

FIXTURE = Path(__file__).parent / "fixtures" / "legacy_projection" / "middle.json"
REAL_MIDDLE = Path(__file__).parent / "fixtures" / "legacy_projection" / "mineru_flash_p1-3.json"
BASIC_MIDDLE = Path(__file__).parent / "fixtures" / "legacy_projection" / "mineru_basic_p10_15_27.json"


class ProjectionTests(unittest.TestCase):
    def test_middle_projects_to_legacy_fields(self) -> None:
        middle = json.loads(FIXTURE.read_text(encoding="utf-8"))
        markdown = "# A Paper\n\n![](images/fig1.jpg)\n"
        view = project_mineru(markdown=markdown, middle=middle)

        self.assertNotIn("schema", view.middle_pdf_info)
        self.assertNotIn("docvortex", json.dumps(view.middle_pdf_info))
        self.assertNotIn("data:image", view.markdown)
        self.assertEqual(["fig1.jpg"], view.image_names)
        with self.assertRaises(ProjectionError):
            project_mineru(markdown="![](data:image/png;base64,AAAA)", middle=middle)

        kinds = [item["type"] for item in view.content_list]
        self.assertEqual(kinds, ["discarded", "text", "text", "equation", "image", "table", "discarded"])
        title = view.content_list[1]
        self.assertEqual(title["text"], "A Paper")
        self.assertEqual(title["text_level"], 1)
        self.assertEqual(title["page_idx"], 0)
        self.assertIn("bbox", title)
        equation = view.content_list[3]
        self.assertEqual(equation["text"], "E=mc^2")
        self.assertEqual(view.content_list[5]["table_body"], "<table><tr><td>a</td></tr></table>")

        discarded = view.middle_pdf_info["pdf_info"][0]["discarded_blocks"]
        self.assertEqual([block["type"] for block in discarded], ["header", "discarded"])
        self.assertEqual(_discarded_text(view.middle_pdf_info), "doi:10.1000/example\nwatermark")
        self.assertEqual(view.middle_pdf_info["pdf_info"][0]["page_size"], [612, 792])
        self.assertEqual(view.native_middle["schema"], "docvortex.middle")

    def test_v1_content_list_is_kept(self) -> None:
        content_list = [
            {"type": "text", "text": "kept", "page_idx": 0, "bbox": [0, 0, 1, 1]},
            {"type": "discarded", "text": "header", "page_idx": 0},
        ]
        view = project_mineru(
            markdown="kept",
            middle={"schema": "docvortex.middle", "pages": []},
            content_list=content_list,
        )
        self.assertEqual(view.content_list[0]["text"], "kept")
        self.assertNotIn("schema", view.middle_pdf_info)
        self.assertEqual(
            view.middle_pdf_info["pdf_info"][0]["discarded_blocks"][0]["lines"][0]["spans"][0]["content"],
            "header",
        )

    def test_docvortex_spans_project_for_thinkextract(self) -> None:
        middle = {
            "schema": "docvortex.middle",
            "schema_version": "2.0",
            "pages": [
                {
                    "page_idx": 0,
                    "page_size": [612, 792],
                    "blocks": [
                        {
                            "type": "page_header",
                            "bbox": [10, 1, 200, 20],
                            "content": [{"type": "text", "content": "doi:10.1000/example"}],
                        },
                        {
                            "type": "paragraph_title",
                            "level": 1,
                            "bbox": [10, 40, 400, 70],
                            "content": [{"type": "text", "content": "A Paper"}],
                        },
                        {
                            "type": "table",
                            "bbox": [10, 80, 400, 200],
                            "content": [
                                {
                                    "type": "table_body",
                                    "content": "<table><tr><td>a</td></tr></table>",
                                    "image_path": "images/table.png",
                                }
                            ],
                        },
                    ],
                }
            ],
        }
        view = project_mineru(markdown="# A Paper", middle=middle)
        self.assertEqual(_discarded_text(view.middle_pdf_info), "doi:10.1000/example")
        self.assertEqual(view.content_list[1]["text"], "A Paper")
        self.assertEqual(view.content_list[1]["text_level"], 1)
        self.assertEqual(view.content_list[2]["table_body"], "<table><tr><td>a</td></tr></table>")

    def test_real_mineru_flash_pages_project_for_thinkextract(self) -> None:
        middle = json.loads(REAL_MIDDLE.read_text(encoding="utf-8"))
        view = project_mineru(markdown="# MinerU2.5-Pro", middle=middle)
        self.assertEqual(middle["schema"], "docvortex.middle")
        self.assertNotIn("schema", view.middle_pdf_info)
        self.assertEqual(len(view.middle_pdf_info["pdf_info"]), 3)
        self.assertIn("arXiv:2604.04771v2", _discarded_text(view.middle_pdf_info))
        headers = [
            span["content"]
            for page in view.middle_pdf_info["pdf_info"]
            for block in page["discarded_blocks"]
            if block["type"] == "header"
            for line in block["lines"]
            for span in line["spans"]
        ]
        self.assertIn("MinerU2.5-Pro: Pushing the Limits of Data-Centric Document Parsing at Scale", headers)
        body = " ".join(item.get("text", "") for item in view.content_list if item.get("type") == "text")
        self.assertIn("heconghui@pjlab.org.cn", body)
        self.assertNotIn("{'type'", body)
        self.assertTrue(any(item["type"] == "equation" for item in view.content_list))

    def test_real_mineru_basic_pages_keep_formula_and_table(self) -> None:
        middle = json.loads(BASIC_MIDDLE.read_text(encoding="utf-8"))
        self.assertEqual(middle["extensions"]["mineru"]["tier"], "basic")
        view = project_mineru(markdown="Table 1", middle=middle)
        self.assertEqual(view.middle_pdf_info["pdf_info"][0]["page_size"], [612.0, 792.0])
        equations = [item["text"] for item in view.content_list if item["type"] == "equation" and item.get("text")]
        self.assertGreaterEqual(len(equations), 1)
        self.assertIn(r"\frac", equations[0])
        tables = [item for item in view.content_list if item["type"] == "table"]
        self.assertGreaterEqual(len(tables), 1)
        self.assertTrue(tables[0]["table_body"].startswith("<table>"))
        self.assertIn("Stage 1", tables[0]["table_body"])
        self.assertTrue(any("Table 1:" in caption for item in tables for caption in item.get("table_caption", [])))
        headers = [
            span["content"]
            for page in view.middle_pdf_info["pdf_info"]
            for block in page["discarded_blocks"]
            if block["type"] == "header"
            for line in block["lines"]
            for span in line["spans"]
        ]
        self.assertIn("MinerU2.5-Pro: Pushing the Limits of Data-Centric Document Parsing at Scale", headers)

    def test_unreadable_output_fails(self) -> None:
        with self.assertRaises(ProjectionError):
            project_mineru(markdown="", middle={"schema": "docvortex.middle"}, content_list=[{"type": "unknown_block"}])


def _discarded_text(middle_json: dict) -> str:
    """Same walk as ThinkExtract PaperIngestionService middle_json DOI/header reader."""
    texts: list[str] = []
    for page in middle_json["pdf_info"]:
        for block in page.get("discarded_blocks") or []:
            if block.get("type") not in {"header", "footer", "page_number", "discarded"}:
                continue
            for line in block.get("lines") or []:
                parts = [
                    span["content"].strip()
                    for span in line.get("spans") or []
                    if isinstance(span.get("content"), str) and span["content"].strip()
                ]
                if parts:
                    texts.append(" ".join(parts))
        if texts:
            break
    return "\n".join(texts)


if __name__ == "__main__":
    unittest.main()

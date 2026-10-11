import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "rcc_capture_workflow.py"
SAMPLE_PAGE_1 = """ID
项目名称

3151027
金陵石化供热中心项目 (中国石油化工股份有限公司金陵分公司) v.1
江苏省 / 南京市
设计
1500.00
2100.97
2026-08-24 09:00

3140792
高精度推拉反馈钢索制造技术提升项目(山东泰龙航空动力科技有限公司) v.1
山东省 / 泰安市
封顶后分包...
30.00
2026-08-24 08:59
"""
SAMPLE_PAGE_2 = """3150097
宁夏吴忠市红寺堡区供电用地项目(某能源有限公司)
宁夏回族自治区 / 吴忠市
未确定
20.00
50.00
2026-08-24 08:58
"""


class WorkflowTest(unittest.TestCase):
    def run_cli(self, workspace: Path, *arguments: str, input_text: str | None = None) -> dict:
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--workspace-root", str(workspace), *arguments],
            input=input_text, capture_output=True, text=True, encoding="utf-8", check=True,
            env=environment,
        )
        return json.loads(result.stdout)

    def test_state_machine_and_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            created = self.run_cli(workspace, "new", "--start-page", "3", "--end-page", "4", "--label", "test")
            self.assertEqual(created["status"], "AWAITING_SETTINGS")
            self.run_cli(workspace, "confirm", "--current-page", "3", "--page-size", "100")
            self.run_cli(workspace, "start")
            saved = self.run_cli(workspace, "save-page", "--page", "3", input_text=SAMPLE_PAGE_1)
            self.assertEqual(saved["next_expected_page"], 4)
            status = self.run_cli(workspace, "status")
            self.assertEqual(status["captured_pages"], [3])
            self.assertEqual(status["missing_pages"], [4])
            completed = self.run_cli(workspace, "save-page", "--page", "4", input_text=SAMPLE_PAGE_2)
            self.assertEqual(completed["status"], "CAPTURED")

    def test_parser_fields(self):
        sys.path.insert(0, str(ROOT / "work"))
        from parse_rcc_full_fields import parse_text

        rows = parse_text(SAMPLE_PAGE_1, 1)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["省份"], "江苏省")
        self.assertEqual(rows[0]["城市"], "南京市")
        self.assertEqual(rows[0]["造价"], "1500.00")
        self.assertEqual(rows[1]["总投资额"], "")


if __name__ == "__main__":
    unittest.main()

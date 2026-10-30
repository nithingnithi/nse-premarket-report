import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


class WorkflowIsolationTests(unittest.TestCase):
    def test_staging_workflow_uses_branch_and_cannot_write_main(self):
        text=(ROOT/'.github/workflows/report-v2-live-dry-run.yml').read_text()
        self.assertIn("github.ref == 'refs/heads/improve/report-v2-deploy'",text)
        self.assertIn('ref: ${{ github.ref }}',text)
        self.assertIn('contents: read',text)
        self.assertIn("DRY_RUN: 'true'",text)
        self.assertNotIn('contents: write',text)
        self.assertNotIn('git push',text)
        self.assertNotIn('integrated.deliver',text)

    def test_production_collection_is_main_only(self):
        text=(ROOT/'.github/workflows/integrated-collect.yml').read_text()
        self.assertIn("github.ref == 'refs/heads/main'",text)
        self.assertIn('ref: main',text)


if __name__=='__main__':unittest.main()

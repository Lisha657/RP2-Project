
import tempfile
import unittest
from pathlib import Path

from src.powerbi.dax_validation import collect_tmdl_measures


class TestPowerBIAgent(unittest.TestCase): 
 
    
    def test_detects_duplicate_measure_names(self):
        from src.powerbi.dax_validation import validate_duplicate_measure_names
        import src.powerbi.dax_validation as app

        findings = []

        measures = [
            {
                "name": "Total Sales",
                "table": "Sales",
                "file": "Sales.tmdl",
            },
            {
                "name": "total sales",
                "table": "Orders",
                "file": "Orders.tmdl",
            },
        ]

        original_collector = app.collect_tmdl_measures

        try:
            app.collect_tmdl_measures = lambda root: measures

            validate_duplicate_measure_names(".", findings)

            assert any(
                finding.get("Category") == "Duplicate Measure Names"
                and finding.get("Status") == "WARNING"
                for finding in findings
            )
        finally:
            app.collect_tmdl_measures = original_collector
    
    def test_duplicate_measure_validator_with_tmdl_files(self):
        import tempfile
        from pathlib import Path
        from src.powerbi.dax_validation import validate_duplicate_measure_names

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            (root / "Sales.tmdl").write_text(
                "table Sales\n"
                "    measure 'Total Sales' = SUM(Sales[Amount])\n",
                encoding="utf-8"
            )

            (root / "Orders.tmdl").write_text(
                "table Orders\n"
                "    measure 'total sales' = SUM(Orders[Amount])\n",
                encoding="utf-8"
            )

            findings = []
            validate_duplicate_measure_names(root, findings)

            self.assertTrue(
                any(
                    item.get("Category") == "Duplicate Measure Names"
                    and item.get("Status") == "WARNING"
                    for item in findings
                ),
                msg=f"Duplicate measure warning not found: {findings}"
            )
    
    def test_detects_duplicate_relationships(self):
        import tempfile
        from pathlib import Path
        import src.powerbi.model_validation as app

        findings = []

        original_validator = app.validate_model_relationships

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)

                # Two relationships with identical endpoints.
                (root / "Model.tmdl").write_text(
                    "relationship rel1\n"
                    "    fromColumn: Sales.DateKey\n"
                    "    toColumn: Calendar.DateKey\n"
                    "\n"
                    "relationship rel2\n"
                    "    fromColumn: Sales.DateKey\n"
                    "    toColumn: Calendar.DateKey\n",
                    encoding="utf-8"
                )

                app.validate_duplicate_relationships(root, findings)

            self.assertTrue(
                any(
                    item.get("Category") == "Duplicate Relationships"
                    and item.get("Status") == "WARNING"
                    for item in findings
                ),
                msg=f"Duplicate relationship warning not found: {findings}"
            )
        finally:
            app.validate_model_relationships = original_validator
    
    def test_no_duplicate_measure_names_returns_pass(self):
        import tempfile
        from pathlib import Path
        import src.powerbi.dax_validation as app

        findings = []

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            (root / "Sales.tmdl").write_text(
                "table Sales\n"
                "    measure 'Total Sales' = SUM(Sales[Amount])\n",
                encoding="utf-8"
            )

            (root / "Orders.tmdl").write_text(
                "table Orders\n"
                "    measure 'Order Count' = COUNTROWS(Orders)\n",
                encoding="utf-8"
            )

            app.validate_duplicate_measure_names(root, findings)

        self.assertTrue(
            any(
                item.get("Category") == "Duplicate Measure Names"
                and item.get("Status") == "PASS"
                for item in findings
            ),
            msg=f"Expected PASS finding, got: {findings}"
        )
    
    def test_empty_measure_validator_reports_result(self):
        import tempfile
        from pathlib import Path
        import src.powerbi.dax_validation as app

        findings = []

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            (root / "Sales.tmdl").write_text(
                "table Sales\n"
                "    measure 'Total Sales' = SUM(Sales[Amount])\n",
                encoding="utf-8"
            )

            app.validate_empty_measure_expressions(root, findings)

        self.assertTrue(
            any(
                item.get("Category") == "Empty Measure Expressions"
                and item.get("Status") == "PASS"
                for item in findings
            ),
            msg=f"Expected PASS finding, got: {findings}"
        )
    
    def test_duplicate_measure_names_case_insensitive(self):
        import tempfile
        from pathlib import Path
        import src.powerbi.dax_validation as app

        findings = []

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            (root / "Sales.tmdl").write_text(
                "table Sales\n"
                "    measure 'Total Sales' = SUM(Sales[Amount])\n",
                encoding="utf-8"
            )

            (root / "Orders.tmdl").write_text(
                "table Orders\n"
                "    measure 'total sales' = SUM(Orders[Amount])\n",
                encoding="utf-8"
            )

            app.validate_duplicate_measure_names(root, findings)

        self.assertTrue(
            any(
                item.get("Category") == "Duplicate Measure Names"
                and item.get("Status") == "WARNING"
                for item in findings
            ),
            msg=f"Expected duplicate warning, got: {findings}"
        )

    def test_validate_pbir_visual_details_detects_slicers_and_inventory(self):
        import json
        import tempfile
        from pathlib import Path
        import src.powerbi.project_validation as app

        findings = []

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_dir = root / "Sales.Report" / "definition" / "pages" / "p1"
            (report_dir / "visuals" / "v1").mkdir(parents=True, exist_ok=True)
            (report_dir / "visuals" / "v2").mkdir(parents=True, exist_ok=True)

            (report_dir / "page.json").write_text(
                json.dumps({"name": "p1", "displayName": "Executive Summary"}),
                encoding="utf-8"
            )

            (report_dir / "visuals" / "v1" / "visual.json").write_text(
                json.dumps({
                    "visual": {
                        "visualType": "slicer",
                        "visualContainerObjects": {
                            "title": [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}}, "text": {"expr": {"Literal": {"Value": "'Date Slicer'"}}}}}]
                        }
                    },
                    "position": {"x": 10, "y": 10, "width": 200, "height": 100}
                }),
                encoding="utf-8"
            )

            (report_dir / "visuals" / "v2" / "visual.json").write_text(
                json.dumps({
                    "visual": {
                        "visualType": "barChart",
                        "visualContainerObjects": {
                            "title": [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}}, "text": {"expr": {"Literal": {"Value": "'Revenue by Region'"}}}}}]
                        }
                    },
                    "position": {"x": 220, "y": 10, "width": 500, "height": 300}
                }),
                encoding="utf-8"
            )

            app.validate_pbir_visual_details(root, findings)

        self.assertTrue(
            any(
                item.get("Category") == "Visual Static Inspection"
                and item.get("Status") == "PASS"
                for item in findings
            ),
            msg=f"Expected Visual Static Inspection PASS, got: {findings}"
        )

        self.assertTrue(
            any(
                item.get("Category") == "Interactive Controls"
                and item.get("Status") == "PASS"
                and "1 interactive slicer" in item.get("Issue", "")
                for item in findings
            ),
            msg=f"Expected Interactive Controls PASS, got: {findings}"
        )

    def test_validate_pbir_visual_details_flags_missing_title_and_zero_dimension(self):
        import json
        import tempfile
        from pathlib import Path
        import src.powerbi.project_validation as app

        findings = []

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_dir = root / "Sales.Report" / "definition" / "pages" / "p1"
            (report_dir / "visuals" / "v1").mkdir(parents=True, exist_ok=True)

            (report_dir / "visuals" / "v1" / "visual.json").write_text(
                json.dumps({
                    "visual": {"visualType": "columnChart"},
                    "position": {"x": 0, "y": 0, "width": 0, "height": 100}
                }),
                encoding="utf-8"
            )

            app.validate_pbir_visual_details(root, findings)

        self.assertTrue(
            any(
                item.get("Category") == "Visual Layout & Coordinates"
                and item.get("Status") == "WARNING"
                for item in findings
            ),
            msg=f"Expected zero-dimension warning, got: {findings}"
        )

        self.assertTrue(
            any(
                item.get("Category") == "Visual Title & Accessibility"
                and item.get("Status") == "WARNING"
                for item in findings
            ),
            msg=f"Expected missing title warning, got: {findings}"
        )

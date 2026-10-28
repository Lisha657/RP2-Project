
import json
from pathlib import Path

report_path = Path("reports/pbip_check_results.json")

with report_path.open("r", encoding="utf-8") as file:
    report = json.load(file)

print("\nREMAINING WARNINGS AND UNTESTED CHECKS\n")
print("-" * 80)

count = 0

for item in report.get("findings", []):
    status = str(item.get("status", "")).upper()

    if status in ("WARNING", "NOT_TESTED", "FAIL"):
        count += 1
        print(f"Status:  {status}")
        print(f"Source:  {item.get('source', '')}")
        print(f"Check:   {item.get('check', '')}")
        print(f"File:    {item.get('file', item.get('dataset', ''))}")
        print(f"Message: {item.get('message', '')}")
        print("-" * 80)

print(f"\nTotal findings displayed: {count}")

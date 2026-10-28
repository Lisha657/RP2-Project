
from src.powerbi_testing.dashboard_visual_checker import check_dashboard_visuals

project_path = (
    r"C:\Users\HP\Downloads\superstore-powerbi-pbip-dashboard-main"
    r"\superstore-powerbi-pbip-dashboard-main"
)

result = check_dashboard_visuals(project_path)

print("Status:", result["status"])
print("Warnings:", result["warnings"])

for finding in result["findings"]:
    if finding["severity"] == "WARNING":
        print("\nPage:", finding.get("page"))
        print("Visual A:", finding.get("visual_a"))
        print("Visual B:", finding.get("visual_b"))
        print("Overlap ratio:", finding.get("overlap_ratio"))
        print("Message:", finding.get("message"))

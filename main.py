from data_quality import check_data_quality

results = check_data_quality("test_data/sales.csv")

print("\nDATA QUALITY TEST REPORT")
print("=" * 30)

for key, value in results.items():
    print(f"{key}: {value}")
import os
import json
import csv
from pathlib import Path
from config import LOGS_DIR_PATH, OUTPUT_CSV_PATH


def generate_summary_csv():
    LOGS_DIR = Path(LOGS_DIR_PATH)
    OUTPUT_PATH = Path(OUTPUT_CSV_PATH)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    rows = []

    for file in LOGS_DIR.glob("*.json"):
        try:
            with open(file, "r", encoding="utf-8") as f:
                data = json.load(f)

            domain = data.get("domain", "")
            emails = data.get("email_extraction", {}).get("emails_found", [])
            email_str = ", ".join(emails)

            form_info = data.get("form_submission", {})
            form_url = form_info.get("url") if form_info.get(
                "submit_clicked") else ""

            rows.append({
                "Domain": domain,
                "Email(s)": email_str,
                "Form": form_url
            })

        except Exception as e:
            print(f"[ERROR] Failed to parse {file.name}: {e}")

    with open(OUTPUT_PATH, "w", newline='', encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=[
                                "Domain", "Email(s)", "Form"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n✅ Final CSV summary written to: {OUTPUT_PATH}")

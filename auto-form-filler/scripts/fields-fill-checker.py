import os
import json
from pathlib import Path
from bs4 import BeautifulSoup
from collections import defaultdict
from difflib import SequenceMatcher

# === CONFIG ===
BASE_LOG_DIR = Path(r"C:\Users\hp\Desktop\leadsup\v0\form-checking\logs")
HTML_DIR = Path(r"C:\Users\hp\Desktop\leadsup\v0\form-checking\html-codes")
FILLED_DIR = BASE_LOG_DIR / "fillable-forms"
UNFILLED_DIR = BASE_LOG_DIR / "unfilled-forms"
FILLED_DIR.mkdir(parents=True, exist_ok=True)
UNFILLED_DIR.mkdir(parents=True, exist_ok=True)

# === PREDEFINED FIELD GROUPS ===
PREDEFINED_FIELDS = {
    "email": "someone@example.com",
    "first_name": "John",
    "last_name": "Doe",
    "phone": "1234567890",
    "message": "I'm interested in advertising opportunities.",
    "subject": "Advertising Inquiry",
    "address": "123 Main St, City, Country",
    "website": "https://example.com",
    "company_name": "Acme Inc.",
    "postal_code": "12345"
}

GROUP_KEYWORDS = {
    "Email": ["email", "e-mail"],
    "First Name": ["first_name", "firstname", "name_first", "given_name", "author", "name"],
    "Last Name": ["last_name", "lastname", "name_last", "surname", "family_name"],
    "Phone": ["phone", "mobile", "tel"],
    "Message": ["message", "comments", "inquiry", "enquiry", "text", "questions"],
    "Subject": ["subject", "reason"],
    "Address": ["address", "addr", "location", "street"],
    "Website": ["website", "site", "url"],
    "Company Name": ["company", "company_name", "organization", "employer"],
    "Postal Code": ["postal", "zip", "zipcode"]
}


def normalize(text):
    return text.strip().lower().replace(" ", "_")


def smart_match(label, input_type):
    if input_type:
        input_type = input_type.lower()
        if input_type == "email":
            return "Email"
        elif input_type in ["tel", "phone"]:
            return "Phone"
        elif input_type == "url":
            return "Website"
        elif input_type == "text":
            norm = normalize(label)
            for key, keywords in GROUP_KEYWORDS.items():
                if any(kw in norm for kw in keywords):
                    return key
                for kw in keywords:
                    if SequenceMatcher(None, norm, kw).ratio() > 0.8:
                        return key
    elif label:
        norm = normalize(label)
        for key, keywords in GROUP_KEYWORDS.items():
            if any(kw in norm for kw in keywords):
                return key
            for kw in keywords:
                if SequenceMatcher(None, norm, kw).ratio() > 0.8:
                    return key
    return None


form_filled_count = 0
total_forms = 0
captcha_ignored_forms = 0
checkbox_ignored_forms = 0
unfilled_due_to_unrequired_only = 0
unfilled_due_to_required = 0

# === MAIN LOOP ===
for file in HTML_DIR.glob("*.html"):
    try:
        with open(file, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f.read(), "html.parser")

        fields = soup.find_all(["input", "textarea", "select"])
        all_fields = []
        ignored_captcha = False
        ignored_checkbox = False

        for field in fields:
            input_type = field.get("type")
            if input_type == "hidden" or input_type == "submit" or input_type == "checkbox":
                if input_type == "checkbox":
                    ignored_checkbox = True
                continue

            if "display:none" in field.get("style", "").replace(" ", "").lower():
                continue

            parent = field.parent
            skip_due_to_hidden_parent = False
            while parent:
                if "display:none" in parent.get("style", "").replace(" ", "").lower():
                    skip_due_to_hidden_parent = True
                    break
                parent = parent.parent
            if skip_due_to_hidden_parent:
                continue

            label = None
            if field.get("aria-label"):
                label = field["aria-label"]
            elif field.get("placeholder"):
                label = field["placeholder"]
            elif field.get("name"):
                label = field["name"]
            elif field.get("id"):
                label_tag = soup.find("label", attrs={"for": field["id"]})
                if label_tag:
                    label = label_tag.get_text(strip=True)

            if not label:
                continue

            norm_label = normalize(label)
            if any(key in norm_label for key in ["captcha", "quiz", "g-recaptcha"]):
                ignored_captcha = True
                continue

            matched_group = smart_match(label, input_type)
            field_info = {
                "label": label,
                "type": input_type,
                "matched_group": matched_group,
                "required": field.has_attr("required")
            }
            all_fields.append(field_info)

        total_forms += 1
        all_matched = all(f["matched_group"] for f in all_fields)

        form_log_data = {
            "form_file": file.name,
            "form_path": str(file.resolve()),
            "fields": all_fields,
            "ignored_captcha": ignored_captcha,
            "ignored_checkbox": ignored_checkbox
        }

        if ignored_captcha:
            captcha_ignored_forms += 1
        if ignored_checkbox:
            checkbox_ignored_forms += 1

        if all_matched:
            form_filled_count += 1
            with open(FILLED_DIR / f"{file.stem}.json", "w", encoding="utf-8") as f:
                json.dump(form_log_data, f, indent=2)
        else:
            non_filled_fields = [
                f for f in all_fields if not f["matched_group"]]
            form_log_data["non_filled_fields"] = non_filled_fields
            with open(UNFILLED_DIR / f"{file.stem}.json", "w", encoding="utf-8") as f:
                json.dump(form_log_data, f, indent=2)

            # Check reason for unfilled
            if all(not f["required"] for f in non_filled_fields):
                unfilled_due_to_unrequired_only += 1
            if any(f["required"] for f in non_filled_fields):
                unfilled_due_to_required += 1

    except Exception as e:
        print(f"[ERROR] Failed parsing {file.name}: {e}")

# === SUMMARY ===
filled_percentage = (form_filled_count / total_forms) * \
    100 if total_forms else 0

print(f"\nTotal Forms Processed: {total_forms}")
print(f"Forms Fully Fillable:  {form_filled_count} ({filled_percentage:.2f}%)")
print(f"Incomplete Forms Logged: {total_forms - form_filled_count}")
print(f"Forms Ignoring Captcha Fields: {captcha_ignored_forms}")
print(f"Forms Ignoring Checkbox Fields: {checkbox_ignored_forms}")
print(
    f"Unfilled Forms Due to Only Unrequired Fields: {unfilled_due_to_unrequired_only}")
print(f"Unfilled Forms Due to Required Fields: {unfilled_due_to_required}")

import os
from pathlib import Path
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
import time

# === CONFIG ===
HTML_DIR = Path(r"C:\Users\hp\Desktop\leadsup\v0\form-checking\html-codes")
CHROMEDRIVER_PATH = r"C:\Users\hp\Desktop\leadsup\v0\chromedriver-win64\chromedriver.exe"
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
    "Message": ["message", "comments", "inquiry", "enquiry", "text", "questions", "comment"],
    "Subject": ["subject", "reason"],
    "Address": ["address", "addr", "location", "street"],
    "Website": ["website", "site", "url"],
    "Company Name": ["company", "company_name", "organization", "employer"],
    "Postal Code": ["postal", "zip", "zipcode"]
}


def normalize(text):
    return text.strip().lower().replace(" ", "_")


def contains_keywords(attributes, keywords):
    for attr in attributes:
        if attr:
            norm_attr = normalize(attr)
            for kw in keywords:
                if kw in norm_attr:
                    return True
    return False


def smart_match(label, input_type):
    from difflib import SequenceMatcher
    norm = normalize(label)
    for key, keywords in GROUP_KEYWORDS.items():
        if any(kw in norm for kw in keywords):
            return key
        for kw in keywords:
            if SequenceMatcher(None, norm, kw).ratio() > 0.8:
                return key
    return None


# === SELENIUM SETUP ===
options = Options()
options.add_argument("--disable-gpu")
options.add_argument("--log-level=3")
options.add_experimental_option("excludeSwitches", ["enable-logging"])

service = Service(CHROMEDRIVER_PATH)
driver = webdriver.Chrome(service=service, options=options)


def attempt_submit():
    try:
        submit_buttons = driver.find_elements(
            By.XPATH, "//button[@type='submit'] | //input[@type='submit']")
        if submit_buttons:
            # submit_buttons[0].click()
            print("[INFO] Submit button found (not clicked). Ready for activation.")
        else:
            print("[INFO] No submit button found.")
    except Exception as e:
        print(f"[ERROR] Submit attempt failed: {e}")


for file in HTML_DIR.glob("*.html"):
    try:
        driver.get(f"file:///{file.resolve()}")
        time.sleep(1)

        fields = driver.find_elements(
            By.XPATH, "//input | //textarea | //select")
        filled_count = 0
        issues = []
        field_info_list = []
        matched_groups = set()

        for field in fields:
            try:
                tag_name = field.tag_name
                input_type = field.get_attribute("type") or tag_name
                name = field.get_attribute("name")
                field_id = field.get_attribute("id")
                placeholder = field.get_attribute("placeholder")
                aria_label = field.get_attribute("aria-label")
                title = field.get_attribute("title")
                required = field.get_attribute("required") is not None
                style = field.get_attribute("style")

                if input_type in ["hidden", "submit", "checkbox"]:
                    continue
                if style and "display:none" in style.replace(" ", "").lower():
                    continue

                parent = field
                hidden = False
                while parent:
                    try:
                        parent = parent.find_element(By.XPATH, "..")
                        parent_style = parent.get_attribute("style")
                        if parent_style and "display:none" in parent_style.replace(" ", "").lower():
                            hidden = True
                            break
                    except:
                        break
                if hidden:
                    continue

                raw_info = {
                    "tag": tag_name,
                    "type": input_type,
                    "name": name,
                    "id": field_id,
                    "placeholder": placeholder,
                    "aria_label": aria_label,
                    "title": title,
                    "required": required,
                    "style": style
                }
                field_info_list.append(raw_info)

                label = aria_label or placeholder or name or ""
                matched_group = smart_match(label, input_type)

                if not matched_group:
                    attributes = [name, field_id,
                                  placeholder, aria_label, title]
                    unmatched_keys = [k for k in PREDEFINED_FIELDS if normalize(
                        k) not in matched_groups]
                    matched = False
                    for key in unmatched_keys:
                        if contains_keywords(attributes, GROUP_KEYWORDS.get(key.title().replace("_", " "), [])):
                            matched_group = key.title().replace("_", " ")
                            matched = True
                            break
                    if not matched:
                        for key in matched_groups:
                            if contains_keywords(attributes, GROUP_KEYWORDS.get(key.title().replace("_", " "), [])):
                                matched_group = key.title().replace("_", " ")
                                break

                if not matched_group:
                    issues.append(f"No match for field with label: '{label}'")
                    continue

                predefined_key = normalize(matched_group)
                value = PREDEFINED_FIELDS.get(predefined_key)
                if value:
                    field.clear()
                    field.send_keys(value)
                    filled_count += 1
                    matched_groups.add(predefined_key)
                else:
                    issues.append(
                        f"No predefined value for matched group: '{matched_group}'")

            except Exception as inner_e:
                issues.append(f"Field error: {inner_e}")

        print(
            f"\n[RESULT] {file.name} - Fields Filled: {filled_count}, Issues: {len(issues)}")
        for issue in issues:
            print(f"  - {issue}")

        print("\n[DEBUG] Raw field info collected:")
        for field_data in field_info_list:
            print(field_data)

        attempt_submit()
        time.sleep(1)

    except Exception as e:
        print(f"[ERROR] Failed to process {file.name}: {e}")

# === CLEANUP ===
driver.quit()

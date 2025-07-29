import os
import time
import json
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from dotenv import load_dotenv
from anticaptchaofficial.recaptchav2proxyless import recaptchaV2Proxyless

# === ENV + CONFIG ===
load_dotenv()
ANTI_CAPTCHA_KEY = os.getenv("ANTI_CAPTCHA_KEY")

URL_LIST_PATH = Path(
    r"C:\Users\hp\Desktop\leadsup\v0\form-checking\detected_form_urls.txt")
CHROMEDRIVER_PATH = r"C:\Users\hp\Desktop\leadsup\v0\chromedriver-win64\chromedriver.exe"
CAPTCHA_LOG_PATH = Path(__file__).parent / "captcha_log.txt"
FORM_LOG_DIR = Path(r"C:\Users\hp\Desktop\leadsup\v0\form-checking\form-logs")
FORM_LOG_DIR.mkdir(parents=True, exist_ok=True)

PREDEFINED_FIELDS = {
    "email": "ibrahim.m7004@gmail.com",
    "first_name": "Ivan",
    "last_name": "Ivan",
    "phone": "+1-769-456588",
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


def attempt_submit():
    try:
        submit_buttons = driver.find_elements(
            By.XPATH, "//button[@type='submit'] | //input[@type='submit']"
        )
        for btn in submit_buttons:
            try:
                driver.execute_script(
                    "arguments[0].scrollIntoView(true);", btn)
                time.sleep(0.3)
                btn.click()
                print("[INFO] Submit button clicked.")
                return True
            except Exception as inner_e:
                print(f"[WARN] Failed to click submit: {inner_e}")
                continue
        print("[INFO] No submit button could be clicked.")
        return False
    except Exception as e:
        print(f"[ERROR] Submit attempt failed: {e}")
        return False


def solve_recaptcha(driver, url, timeout_seconds=90):
    captcha_present = False
    captcha_solved = False
    fallback_used = False
    error_message = ""
    try:
        recaptcha_element = driver.find_element(By.CLASS_NAME, "g-recaptcha")
        sitekey = recaptcha_element.get_attribute("data-sitekey")
        if not sitekey:
            raise Exception("Missing sitekey")

        print("\U0001f9d1‍\U0001f916 Solving reCAPTCHA via Anti-Captcha...")
        captcha_present = True

        solver = recaptchaV2Proxyless()
        solver.set_verbose(1)
        solver.set_key(ANTI_CAPTCHA_KEY)
        solver.set_website_url(url)
        solver.set_website_key(sitekey)

        try:
            start_time = time.time()
            task_id = solver.create_task()
            if task_id == 0:
                raise Exception(
                    f"❌ Failed to create task: {solver.error_code}")
            print(f"🔁 Task created: {task_id}. Waiting for solution...")
            while True:
                time.sleep(5)
                g_response = solver.get_task_result()
                if g_response != 0:
                    break
                if time.time() - start_time > timeout_seconds:
                    raise Exception("❌ CAPTCHA solving timed out")
        except TypeError as e:
            print("[WARN] create_task failed. Using fallback method.")
            fallback_used = True
            g_response = solver.solve_and_return_solution()
            if g_response == 0:
                raise Exception(
                    f"❌ CAPTCHA solving failed: {solver.error_code}")

        driver.execute_script("""
            document.getElementById("g-recaptcha-response").style.display = "block";
            document.getElementById("g-recaptcha-response").value = arguments[0];
        """, g_response)

        with open(CAPTCHA_LOG_PATH, "a") as f:
            f.write("recaptcha_v2\n")

        captcha_solved = True
        print("✅ CAPTCHA Solved and injected.")
    except Exception as e:
        error_message = str(e)
        print(f"[INFO] CAPTCHA solve failed or not found: {e}")
    return captcha_present, captcha_solved, fallback_used, error_message


# === SELENIUM SETUP ===
options = Options()
options.add_argument("--disable-gpu")
options.add_argument("--log-level=3")
options.add_experimental_option("excludeSwitches", ["enable-logging"])

service = Service(CHROMEDRIVER_PATH)
driver = webdriver.Chrome(service=service, options=options)

with open(URL_LIST_PATH, "r", encoding="utf-8") as url_file:
    urls = [line.strip() for line in url_file if line.strip()]

for url in urls:
    log_data = {
        "url": url,
        "filled_fields": [],
        "captcha_present": False,
        "captcha_solved": False,
        "captcha_fallback_used": False,
        "captcha_error": "",
        "submit_clicked": False,
        "errors": []
    }
    try:
        print(f"\n--- Visiting: {url} ---")
        driver.get(url)
        time.sleep(2)

        fields = driver.find_elements(
            By.XPATH, "//input | //textarea | //select")
        filled_count = 0
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
                    log_data["errors"].append(
                        f"No match for field with label: '{label}'")
                    continue

                predefined_key = normalize(matched_group)
                value = PREDEFINED_FIELDS.get(predefined_key)
                if value:
                    field.clear()
                    field.send_keys(value)
                    filled_count += 1
                    matched_groups.add(predefined_key)
                    log_data["filled_fields"].append({predefined_key: value})
                else:
                    log_data["errors"].append(
                        f"No predefined value for matched group: '{matched_group}'")

            except Exception as inner_e:
                log_data["errors"].append(f"Field error: {inner_e}")

        captcha_present, captcha_solved, fallback_used, captcha_error = solve_recaptcha(
            driver, url)
        log_data["captcha_present"] = captcha_present
        log_data["captcha_solved"] = captcha_solved
        log_data["captcha_fallback_used"] = fallback_used
        log_data["captcha_error"] = captcha_error

        log_data["submit_clicked"] = attempt_submit()
        time.sleep(2)

    except Exception as e:
        log_data["errors"].append(f"[ERROR] Failed to process {url}: {e}")

    try:
        log_filename = FORM_LOG_DIR / \
            f"{normalize(url.replace('https://', '').replace('http://', '').replace('/', '_'))}.json"
        with open(log_filename, "w", encoding="utf-8") as log_file:
            json.dump(log_data, log_file, indent=2)
    except Exception as log_err:
        print(f"[ERROR] Failed to write log file: {log_err}")

# === CLEANUP ===
driver.quit()

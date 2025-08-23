import time
from selenium.webdriver.common.by import By
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

from config import CHROMEDRIVER_PATH, PREDEFINED_FIELDS
from form_submit.utils import smart_match, contains_keywords, normalize, GROUP_KEYWORDS, solve_recaptcha


def fill_and_submit_form(form_url, log):
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--log-level=3")
    options.add_experimental_option("excludeSwitches", ["enable-logging"])

    service = Service(CHROMEDRIVER_PATH)
    driver = webdriver.Chrome(service=service, options=options)

    log_data = {
        "url": form_url,
        "filled_fields": [],
        "submit_clicked": False,
        "errors": [],
        "captcha_present": False,
        "captcha_solved": False,
        "captcha_fallback_used": False,
        "captcha_error": ""
    }

    try:
        driver.get(form_url)
        time.sleep(2)

        # Detect and solve CAPTCHA (via Anti-Captcha)
        captcha_present, captcha_solved, fallback_used, captcha_error = solve_recaptcha(
            driver, form_url)
        log_data["captcha_present"] = captcha_present
        log_data["captcha_solved"] = captcha_solved
        log_data["captcha_fallback_used"] = fallback_used
        log_data["captcha_error"] = captcha_error

        fields = driver.find_elements(
            By.XPATH, "//input | //textarea | //select")
        matched_groups = set()

        # === Step 1: Pre-check for required fields
        unmatched_required_fields = []
        for field in fields:
            try:
                input_type = field.get_attribute("type") or field.tag_name
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

                label = aria_label or placeholder or name or field_id or title or ""
                matched_group = smart_match(label, input_type)

                if required and (not matched_group or normalize(matched_group) not in PREDEFINED_FIELDS):
                    unmatched_required_fields.append(label)
            except:
                continue

        if unmatched_required_fields:
            print(
                f"[SKIPPED] Cannot fill form. Required fields not matched: {unmatched_required_fields}")
            log_data["errors"].append(
                f"Skipped form: unmatched required fields: {unmatched_required_fields}")
            return

        # === Step 2: Proceed with filling
        for field in fields:
            try:
                tag_name = field.tag_name
                input_type = field.get_attribute("type") or tag_name
                name = field.get_attribute("name")
                field_id = field.get_attribute("id")
                placeholder = field.get_attribute("placeholder")
                aria_label = field.get_attribute("aria-label")
                title = field.get_attribute("title")
                style = field.get_attribute("style")

                if input_type in ["hidden", "submit", "checkbox"]:
                    continue
                if style and "display:none" in style.replace(" ", "").lower():
                    continue

                label = aria_label or placeholder or name or field_id or title or ""
                matched_group = smart_match(label, input_type)

                if not matched_group:
                    attributes = [name, field_id,
                                  placeholder, aria_label, title]
                    unmatched_keys = [k for k in PREDEFINED_FIELDS if normalize(
                        k) not in matched_groups]
                    for key in unmatched_keys:
                        if contains_keywords(attributes, GROUP_KEYWORDS.get(key.title().replace("_", " "), [])):
                            matched_group = key.title().replace("_", " ")
                            break

                if matched_group:
                    predefined_key = normalize(matched_group)
                    value = PREDEFINED_FIELDS.get(predefined_key)
                    if value:
                        field.clear()
                        field.send_keys(value)
                        matched_groups.add(predefined_key)
                        log_data["filled_fields"].append(
                            {predefined_key: value})
            except Exception as fe:
                log_data["errors"].append(str(fe))

        log_data["submit_clicked"] = attempt_submit(driver)
        time.sleep(2)

    except Exception as e:
        log_data["errors"].append(str(e))
    finally:
        driver.quit()
        log['form_submission'] = log_data


def attempt_submit(driver):
    try:
        submit_buttons = driver.find_elements(
            By.XPATH, "//button[@type='submit'] | //input[@type='submit']")
        for btn in submit_buttons:
            try:
                driver.execute_script(
                    "arguments[0].scrollIntoView(true);", btn)
                time.sleep(0.3)
                btn.click()
                print("[INFO] Submit button clicked.")
                return True
            except:
                continue
        return False
    except:
        return False

from difflib import SequenceMatcher
from config import PREDEFINED_FIELDS

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
    norm = normalize(label)
    for key, keywords in GROUP_KEYWORDS.items():
        if any(kw in norm for kw in keywords):
            return key
        for kw in keywords:
            if SequenceMatcher(None, norm, kw).ratio() > 0.8:
                return key
    return None


def form_is_fillable(fields):
    unmatched_required_fields = []

    for field in fields:
        input_type = field.get("type") or field.get("tag", "")
        style = field.get("style") or ""

        if input_type in ["hidden", "submit", "checkbox"]:
            continue
        if "display:none" in style.replace(" ", "").lower():
            continue

        required = field.get("required", False)
        label = field.get("aria_label") or field.get("placeholder") or field.get(
            "name") or field.get("id") or field.get("title") or ""
        matched_group = smart_match(label, input_type)

        if required and (not matched_group or normalize(matched_group) not in PREDEFINED_FIELDS):
            unmatched_required_fields.append(label)

    return len(unmatched_required_fields) == 0


def solve_recaptcha(driver, url, timeout_seconds=90):
    from anticaptchaofficial.recaptchav2proxyless import recaptchaV2Proxyless
    from config import ANTI_CAPTCHA_KEY
    from selenium.webdriver.common.by import By
    import time

    captcha_present = False
    captcha_solved = False
    fallback_used = False
    error_message = ""

    try:
        recaptcha_element = driver.find_element(By.CLASS_NAME, "g-recaptcha")
        sitekey = recaptcha_element.get_attribute("data-sitekey")
        if not sitekey:
            raise Exception("Missing sitekey")

        print("🤖 Solving reCAPTCHA via Anti-Captcha...")
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
        except TypeError:
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

        captcha_solved = True
        print("✅ CAPTCHA Solved and injected.")
    except Exception as e:
        error_message = str(e)
        print(f"[INFO] CAPTCHA solve failed or not found: {e}")

    return captcha_present, captcha_solved, fallback_used, error_message

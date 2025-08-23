import os
import json
import re
import time
import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI
from pathlib import Path
import concurrent.futures

# Load environment variables
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# === CONFIG ===
CSV_PATH = r"C:\Users\hp\Desktop\leadsup\v0\gpt-web-search-approach-2\gpt-4o\lb_findings_domains_emails_forms.csv"
LOGS_DIR = Path(
    r"C:\Users\hp\Desktop\leadsup\v0\gpt-web-search-approach-2\gpt-4o\v2\logs")
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# === PRICING CONFIG (fallback if usage not available) ===
PRICE_PER_1K_TOKENS = 0.005  # Estimate for GPT-4.1 web search per 1k tokens

# === Load CSV ===
df = pd.read_csv(CSV_PATH)

# Ensure required columns exist
df = df.rename(columns=lambda x: x.strip().lower())
assert 'domain' in df.columns and 'email/form' in df.columns


def extract_form_fields_from_url(form_url):
    print(
        f"[INFO] Starting secondary GPT call to extract form fields from: {form_url}")

    prompt = f"""
    Visit the following URL: {form_url}

    Wait for the page to load completely, including any JavaScript-rendered content.

    Once loaded, inspect the page's HTML and identify the **form fields** present.

    For each field, return a dictionary containing:
    - id (if present)
    - name (if present)
    - label (either direct label tag or inferred from nearby/parent text)
    - placeholder (if present)
    - required (true/false)
    - input type (text, email, checkbox, etc)
    - tag (input, select, textarea, etc)
    - any descriptive text nearby

    Return only the final result in JSON format:
    {{
      "form_url": "{form_url}",
      "fields": [{{...}}]
    }}
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-search-preview",
            web_search_options={},
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        output = response.choices[0].message.content.strip()
        print(f"[DEBUG] GPT form field response:\n{output}\n")

        try:
            parsed = json.loads(output)
            return parsed
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', output, re.DOTALL)
            if match:
                return json.loads(match.group(0))

    except Exception as e:
        print(f"[ERROR] Failed to extract form fields: {e}")
        return {"error": str(e)}


def process_domain(domain, expected_email, expected_form):
    print(f"\n==============================")
    print(f"[INFO] Processing domain: {domain}")

    input_prompt = f"""
    You are a web research agent.

    Search online and visit the official website of "{domain}".

    Your task is to find **all relevant contact methods** that can be used to inquire about advertising, media buying, sponsored content, or marketing collaborations.

    1. Look through the entire site and its subpages, especially any titled or related to:
       - Advertise
       - Sponsorship
       - Media Kit
       - Contact
       - Partnerships

    2. If you find multiple emails, return the one most relevant to advertising/marketing.
       - Prefer emails like advertising@, media@, marketing@, ads@, partnerships@, etc.

    3. If there's a contact form clearly related to advertising/sponsorship, return that form's direct URL.

    Only return ONE result — the **best possible** advertising contact method from the options available.

    Format strictly as:
    {{"type": "email", "value": "..."}} or {{"type": "form", "value": "..."}}

    If no such contact is found, return:
    {{"type": "none", "value": "No advertising contact found."}}
    """

    log_data = {
        "domain": domain,
        "emails": [],
        "form": [],
        "form_fields": {},
        "token_usage": {
            "tokens_used": None,
            "summarize_calls": 1,
            "estimated_cost_usd": None
        },
        "matches_expected": {
            "email": False,
            "form": False
        },
        "timed_out": False
    }

    try:
        print("[DEBUG] Sending GPT request to analyze site...")
        response = client.chat.completions.create(
            model="gpt-4o-search-preview",
            web_search_options={},
            messages=[
                {"role": "user", "content": input_prompt}
            ]
        )

        output_text = response.choices[0].message.content.strip()
        print(f"[DEBUG] GPT initial response:\n{output_text}\n")

        tokens_used = response.usage.total_tokens if hasattr(
            response, 'usage') else 700
        estimated_cost = (tokens_used / 1000) * PRICE_PER_1K_TOKENS

        log_data["token_usage"] = {
            "tokens_used": tokens_used,
            "summarize_calls": 1,
            "estimated_cost_usd": round(estimated_cost, 5)
        }

        try:
            result = json.loads(output_text)
        except json.JSONDecodeError:
            match = re.search(
                r'{"type":\s*"(email|form|none)",\s*"value":\s*"([^"]+)"}', output_text)
            if match:
                result = {"type": match.group(1), "value": match.group(2)}
            else:
                raise ValueError("Could not parse GPT response.")

        print(f"[INFO] Contact method detected: {result}")

        if result["type"] == "email":
            log_data["emails"].append(result["value"])
            if expected_email and expected_email in result["value"].lower():
                log_data["matches_expected"]["email"] = True

        elif result["type"] == "form":
            log_data["form"].append(result["value"])
            if expected_form and "form" in expected_form.lower():
                log_data["matches_expected"]["form"] = True

            print("[INFO] Form detected. Starting field extraction...")
            form_fields_data = extract_form_fields_from_url(result["value"])
            log_data["form_fields"] = form_fields_data

    except Exception as e:
        print(f"[ERROR] Exception occurred during processing: {e}")
        log_data["timed_out"] = True
        log_data["error"] = str(e)

    return log_data


# === Main loop with timeout ===
for _, row in df.iterrows():
    domain = row['domain'].strip()
    expected_email = str(row['email/form']).strip().lower()
    expected_form = str(row.get('form', '')).strip().lower()

    log_path = LOGS_DIR / f"{domain.replace('.', '_')}.json"

    print(f"\n[START] Processing: {domain}")

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                process_domain, domain, expected_email, expected_form)
            log_data = future.result(timeout=120)  # 2 minutes timeout

    except concurrent.futures.TimeoutError:
        print(f"[TIMEOUT] Domain took too long: {domain}")
        log_data = {
            "domain": domain,
            "emails": [],
            "form": [],
            "form_fields": {},
            "token_usage": {
                "tokens_used": None,
                "summarize_calls": 1,
                "estimated_cost_usd": None
            },
            "matches_expected": {
                "email": False,
                "form": False
            },
            "timed_out": True
        }

    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log_data, f, indent=2)

    print(f"✅ Logged: {domain}")
    time.sleep(1.5)

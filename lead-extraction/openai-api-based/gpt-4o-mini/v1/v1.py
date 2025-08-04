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
CSV_PATH = r"C:\Users\hp\Desktop\leadsup\v0\gpt-web-search-approach-2\gpt-4o-mini\lb_findings_domains_emails_forms.csv"
LOGS_DIR = Path(
    r"C:\Users\hp\Desktop\leadsup\v0\gpt-web-search-approach-2\gpt-4o-mini\v1\logs")
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# === PRICING CONFIG FOR GPT-4o-MINI SEARCH ===
# Pricing per https://openai.com/pricing (as of 2025)
# gpt-4o-mini: $0.0005 per 1K input tokens, $0.0015 per 1K output tokens (web search context excluded)
# Assume roughly 700 tokens for now until OpenAI exposes usage data
PRICE_PER_1K_TOKENS_INPUT = 0.0005
PRICE_PER_1K_TOKENS_OUTPUT = 0.0015
ESTIMATED_INPUT_TOKENS = 350
ESTIMATED_OUTPUT_TOKENS = 350

# === Load CSV ===
df = pd.read_csv(CSV_PATH)

# Ensure required columns exist
df = df.rename(columns=lambda x: x.strip().lower())
assert 'domain' in df.columns and 'email/form' in df.columns


def process_domain(domain, expected_email, expected_form):
    input_prompt = f"""
    You are a web research agent.

    Search online and visit the official website of \"{domain}\".

    Your task is to find **all relevant contact methods** that can be used to inquire about advertising, media buying, sponsored content, or marketing collaborations.

    1. Look through the entire site and its subpages, especially any titled or related to:
       - Advertise
       - Sponsorship
       - Media Kit
       - Contact
       - Partnerships

    2. If you find multiple emails, return the one most relevant to advertising/marketing. 

    3. If there's a contact form clearly related to advertising/sponsorship, return that form's direct URL.

    Important Note:
    Be smart about this and understand that the best email/form might not be present on the 
    domain home page- you will need to delve into the linked pages and subpages leading 
    from the main domain page. Ensure you have actually found the best possible ways 
    for advertising contact.

    Only return ONE email and ONE form — the **best possible** advertising contact methods from the options available.
    If either is unavailable, you should return that value as empty.

    Format strictly as:
    {{"best_email": "email_address", "best_form": "form_url"}}
    """

    log_data = {
        "domain": domain,
        "emails": [],
        "form": [],
        "token_usage": {
            "tokens_used": ESTIMATED_INPUT_TOKENS + ESTIMATED_OUTPUT_TOKENS,
            "summarize_calls": 1,
            "estimated_cost_usd": round((ESTIMATED_INPUT_TOKENS * PRICE_PER_1K_TOKENS_INPUT + ESTIMATED_OUTPUT_TOKENS * PRICE_PER_1K_TOKENS_OUTPUT) / 1000, 5)
        },
        "matches_expected": {
            "email": False,
            "form": False
        },
        "timed_out": False
    }

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini-search-preview",
            web_search_options={},
            messages=[
                {
                    "role": "user",
                    "content": input_prompt,
                }
            ]
        )

        output_text = response.choices[0].message.content.strip()

        try:
            result = json.loads(output_text)
        except json.JSONDecodeError:
            match = re.search(
                r'{"type":\s*"(email|form|none)",\s*"value":\s*"([^"]+)"}', output_text)
            if match:
                result = {"type": match.group(1), "value": match.group(2)}
            else:
                raise ValueError("Could not parse GPT response.")

        best_email = result.get("best_email", "").strip()
        best_form = result.get("best_form", "").strip()

        if best_email:
            log_data["emails"].append(best_email)
            if expected_email and expected_email in best_email.lower():
                log_data["matches_expected"]["email"] = True

        if best_form:
            log_data["form"].append(best_form)
            if expected_form and "form" in expected_form.lower():
                log_data["matches_expected"]["form"] = True

    except Exception as e:
        log_data["timed_out"] = True
        log_data["error"] = str(e)

    return log_data


# === Main loop with timeout ===
for _, row in df.iterrows():
    domain = row['domain'].strip()
    expected_email = str(row['email/form']).strip().lower()
    expected_form = str(row.get('form', '')).strip().lower()

    log_path = LOGS_DIR / f"{domain.replace('.', '_')}.json"

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                process_domain, domain, expected_email, expected_form)
            log_data = future.result(timeout=240)  # 4 min timeout

    except concurrent.futures.TimeoutError:
        log_data = {
            "domain": domain,
            "emails": [],
            "form": [],
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

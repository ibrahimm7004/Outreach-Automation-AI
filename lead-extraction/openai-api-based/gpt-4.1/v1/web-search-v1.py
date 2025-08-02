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
CSV_PATH = r"C:\Users\hp\Desktop\leadsup\v0\lb_findings_domains_emails_forms.csv"
LOGS_DIR = Path(r"C:/Users/hp/Desktop/leadsup/v0/logs")
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# === PRICING CONFIG (fallback if usage not available) ===
PRICE_PER_1K_TOKENS = 0.005  # Estimate for GPT-4.1 web search per 1k tokens

# === Load CSV ===
df = pd.read_csv(CSV_PATH)

# Ensure required columns exist
df = df.rename(columns=lambda x: x.strip().lower())
assert 'domain' in df.columns and 'email/form' in df.columns


def process_domain(domain, expected_email, expected_form):
    input_prompt = f"""
    You are a web research agent.

    Search online and visit the official website of "{domain}".
    Your task is to find the best possible **advertising or marketing-related contact method** that I
    can use to contact {domain} for running ads on their website, or for other marketing possibilities.

    Return ONLY one of the following:
    1. A direct email address for advertising/marketing (e.g., advertising@{domain})
    2. A specific contact form URL meant for advertising or partnerships

    If none is found, return:
    {{"type": "none", "value": "No advertising contact found."}}

    Your response must be ONLY the JSON result.
    """

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
        "timed_out": False
    }

    try:
        response = client.responses.create(
            model="gpt-4.1",
            input=input_prompt,
            tools=[{"type": "web_search_preview"}],
            tool_choice={"type": "web_search_preview"}
        )

        output_text = response.output_text.strip()

        if hasattr(response, 'usage') and response.usage:
            tokens_used = response.usage.total_tokens
        else:
            tokens_used = 700  # Estimate

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

        if result["type"] == "email":
            log_data["emails"].append(result["value"])
            if expected_email and expected_email in result["value"].lower():
                log_data["matches_expected"]["email"] = True

        elif result["type"] == "form":
            log_data["form"].append(result["value"])
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
            log_data = future.result(timeout=120)  # 2 minutes timeout

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
    time.sleep(1.5)  # Be polite to the API and avoid rate limits

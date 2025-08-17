import re
import os
from openai import OpenAI
from gpt.summarizers import summarize_page_text
from config import AVAILABLE_TEXT_TOKENS, GPT_COST_PER_TOKEN

key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=key)


def extract_emails_using_gpt_combined(pages_dict, log):
    print("\nCombining texts from multiple pages for GPT email extraction")
    combined_parts = []
    total_chars = sum(len(v) for v in pages_dict.values())

    if total_chars < AVAILABLE_TEXT_TOKENS:
        for name, text in pages_dict.items():
            combined_parts.append(f"### Page: {name}\n{text}")
    else:
        avg_limit = AVAILABLE_TEXT_TOKENS // len(pages_dict)
        for name, text in pages_dict.items():
            if len(text) > avg_limit:
                log['token_usage']['summarize_calls'] += 1
                text = summarize_page_text(text, log)
            combined_parts.append(f"### Page: {name}\n{text}")

    combined_text = "\n\n".join(combined_parts)
    prompt = (
        "You are helping a marketing agency find the most appropriate email addresses for advertising, marketing partnerships, or press inquiries.\n"
        "Below are page contents from a website. Return the best 1–3 emails based on relevance. If you find no clear match, return the most relevant one you can find.\n"
        "Do NOT return anything outside of a plain comma-separated list of email addresses.\n"
        "Return an empty string ONLY if absolutely no email addresses are found.\n\n"
        f"{combined_text[:AVAILABLE_TEXT_TOKENS]}"
    )

    try:
        token_est = len(prompt.split())
        log['token_usage']['tokens_used'] += token_est
        log['token_usage']['estimated_cost_usd'] += token_est * GPT_COST_PER_TOKEN

        response = client.responses.create(
            model="gpt-4o-mini",
            input=[{"role": "user", "content": prompt}]
        )
        print("\nGPT email extraction response:\n" +
              response.output_text.strip())
        return [
            e.strip() for e in response.output_text.split(",")
            if e.strip() and re.match(r"[^@\s]+@[^@\s]+\.[^@\s]+", e.strip())
        ]
    except Exception as e:
        print(f"[API ERROR] Failed to extract emails: {e}")
        return []

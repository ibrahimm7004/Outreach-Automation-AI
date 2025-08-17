import os
from openai import OpenAI
from config import AVAILABLE_TEXT_TOKENS, GPT_COST_PER_TOKEN

key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=key)


def summarize_page_text(text, log):
    prompt = (
        "Summarize the following webpage content and extract only the email addresses and their contexts relevant to marketing, advertising or press.\n\n"
        f"{text[:3000]}"
    )
    try:
        token_est = len(prompt.split())
        log['token_usage']['summarize_calls'] += 1
        log['token_usage']['tokens_used'] += token_est
        log['token_usage']['estimated_cost_usd'] += token_est * GPT_COST_PER_TOKEN

        response = client.responses.create(
            model="gpt-4o-mini",
            input=[{"role": "user", "content": prompt}]
        )
        return response.output_text.strip()
    except Exception as e:
        print(f"[API ERROR] Failed to summarize page: {e}")
        return ""


def summarize_form_text_for_selection(content, log):
    prompt = (
        "Summarize the purpose of the following webpage HTML form and page content in one sentence. "
        "Indicate what the form is about and what kind of contact it's intended for:\n"
        f"{content}"
    )
    try:
        token_est = len(prompt.split())
        log['token_usage']['tokens_used'] += token_est
        log['token_usage']['estimated_cost_usd'] += token_est * GPT_COST_PER_TOKEN

        response = client.responses.create(
            model="gpt-4o-mini",
            input=[{"role": "user", "content": prompt}]
        )
        return response.output_text.strip()
    except Exception as e:
        print(f"[API ERROR] Failed to summarize form content: {e}")
        return ""

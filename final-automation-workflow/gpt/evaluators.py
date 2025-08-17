import os
from openai import OpenAI
from gpt.summarizers import summarize_page_text
from config import AVAILABLE_TEXT_TOKENS, GPT_COST_PER_TOKEN

key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=key)


def evaluate_form_relevance_with_gpt(form_html, page_text, log):
    try:
        if 'token_usage' not in log:
            log['token_usage'] = {
                'tokens_used': 0,
                'summarize_calls': 0,
                'estimated_cost_usd': 0.0
            }

        if len(form_html) + len(page_text) > AVAILABLE_TEXT_TOKENS:
            log['token_usage']['summarize_calls'] += 1
            page_text = summarize_page_text(page_text, log)

        prompt = f"""You are evaluating whether an HTML form is explicitly meant for advertising, sponsorship, or marketing inquiries — not general contact.

Form HTML:
{form_html}

Page Text:
{page_text}

Instructions:
- Only respond with "True" if the form is clearly intended for advertising, marketing, sponsorship, or media-related business.
- Ignore generic contact forms, support requests, customer service, sales inquiries, or job applications.
- Look for strong cues like: "advertise with us", "sponsorship opportunities", "marketing inquiry", "media kit", "promote your product", etc.
- If uncertain or unclear, respond with "False".

Respond ONLY with: True or False (exactly one of these)."""

        token_est = len(prompt.split())
        log['token_usage']['tokens_used'] += token_est
        log['token_usage']['estimated_cost_usd'] += token_est * GPT_COST_PER_TOKEN

        response = client.responses.create(
            model="gpt-4o-mini",
            input=[{"role": "user", "content": prompt}]
        )
        reply = response.output_text.strip().lower()
        return reply == "true"
    except Exception as e:
        print(f"[API ERROR] Failed to evaluate form relevance: {e}")
        return False


def choose_best_form_using_gpt(summary_dict, log):
    print("\nChoosing best form from multiple ones...")
    prompt = (
        "Given the following numbered summaries of different contact forms found across a website, "
        "choose the ONE most relevant for advertising, marketing, or press inquiries. "
        "Only return the number of the most appropriate summary.\n\n"
    )
    for key, summary in summary_dict.items():
        prompt += f"{key}: {summary}\n"
    prompt += "\nReturn only the number (e.g., 2)."

    try:
        token_est = len(prompt.split())
        log['token_usage']['tokens_used'] += token_est
        log['token_usage']['estimated_cost_usd'] += token_est * GPT_COST_PER_TOKEN

        response = client.responses.create(
            model="gpt-4o-mini",
            input=[{"role": "user", "content": prompt}]
        )
        result = response.output_text.strip()
        return int(result) if result.isdigit() else None
    except Exception as e:
        print(f"[API ERROR] Failed to select best form: {e}")
        return None

import json
import os
from openai import OpenAI

from gpt.evaluators import choose_best_form_using_gpt
from gpt.summarizers import summarize_form_text_for_selection
from extraction.form_extraction import parse_form_fields, extract_submit_button
from form_submit.fill_form import fill_and_submit_form
from config import GPT_COST_PER_TOKEN

key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=key)


def gpt_choose_message_field(textarea_dict, log):
    prompt = f"""
You are given a dictionary of form fields that are all unrequired <textarea> elements from a website's contact form.

Each key is an index, and the value is a dictionary with field metadata.

Your task is to determine which index most likely corresponds to the message box.

ONLY RETURN THE INTEGER INDEX (e.g., 0, 1, etc.).

Here is the dictionary:\n{json.dumps(textarea_dict, indent=2)}
"""
    try:
        token_est = len(prompt.split())
        log['token_usage']['tokens_used'] += token_est
        log['token_usage']['estimated_cost_usd'] += token_est * GPT_COST_PER_TOKEN

        response = client.responses.create(
            model="gpt-4o-mini",
            input=[{"role": "user", "content": prompt}]
        )

        output = response.output_text.strip()
        return int(output) if output.isdigit() else next(iter(textarea_dict))
    except Exception as e:
        print(f"[API ERROR] GPT failed during message field selection: {e}")
        return next(iter(textarea_dict))


def process_detected_forms(log, detected_forms_dict):
    if len(detected_forms_dict) == 0:
        print("\n0 forms detected in process_detected_forms")
        return None

    if len(detected_forms_dict) == 1:
        key, value = list(detected_forms_dict.items())[0]
        html, text, url = value

        fill_and_submit_form(url, log)

        return {
            'page_url': url,
            'summary': '',
        }

    summarized_dict = {}
    new_dict = {}

    for i, (idx, value) in enumerate(detected_forms_dict.items(), start=1):
        html, text, url = value
        log['token_usage']['summarize_calls'] += 1
        summarized = summarize_form_text_for_selection(f"{html}\n{text}", log)
        summarized_dict[i] = summarized
        new_dict[i] = [html, text, url, summarized]

    detected_forms_dict.clear()
    detected_forms_dict.update(new_dict)

    chosen_key = choose_best_form_using_gpt(summarized_dict, log)

    if isinstance(chosen_key, int) and chosen_key in detected_forms_dict:
        html, text, url, summary = detected_forms_dict[chosen_key]

        fill_and_submit_form(url, log)

        return {
            'page_url': url,
            'summary': summary,
        }

    print(f"[WARNING] No valid form selected by GPT. Got: {chosen_key}")
    return None


def process_detected_forms(log, detected_forms_dict):
    if len(detected_forms_dict) == 0:
        print("\n0 forms detected in process_detected_forms")
        return None

    if len(detected_forms_dict) == 1:
        key, value = list(detected_forms_dict.items())[0]
        html, text, url = value

        fill_and_submit_form(url, log)

        return {
            'page_url': url,
            'summary': '',
        }

    summarized_dict = {}
    new_dict = {}

    for i, (idx, value) in enumerate(detected_forms_dict.items(), start=1):
        html, text, url = value
        summarized = summarize_form_text_for_selection(f"{html}\n{text}", log)
        summarized_dict[i] = summarized
        new_dict[i] = [html, text, url, summarized]

    detected_forms_dict.clear()
    detected_forms_dict.update(new_dict)

    chosen_key = choose_best_form_using_gpt(summarized_dict, log)

    if isinstance(chosen_key, int) and chosen_key in detected_forms_dict:
        html, text, url, summary = detected_forms_dict[chosen_key]

        fill_and_submit_form(url, log)

        return {
            'page_url': url,
            'summary': summary,
        }

    print(f"[WARNING] No valid form selected by GPT. Got: {chosen_key}")
    return None

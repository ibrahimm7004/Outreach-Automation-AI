from collections import Counter
from bs4 import BeautifulSoup
import time
import re
import unicodedata
import spacy
import json
import os
import pandas as pd
import psutil
import warnings
import contextlib
from concurrent.futures import ThreadPoolExecutor, TimeoutError as ThreadTimeoutError
from urllib.parse import urljoin
from bs4 import BeautifulSoup, Tag
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from openai import OpenAI
from dotenv import load_dotenv

warnings.filterwarnings("ignore")

load_dotenv()
nlp = spacy.load("en_core_web_sm")

CHROMEDRIVER_PATH = r"C:\\Users\\hp\\Desktop\\leadsup\\v0\\chromedriver-win64\\chromedriver.exe"
CSV_FILE_PATH = r"C:\Users\hp\Desktop\leadsup\v0\lb_findings_domains_emails_forms.csv"
LOGS_DIR_PATH = r"C:\\Users\\hp\\Desktop\\leadsup\\v0\\logs"

INTENT_KEYWORDS = ["contact", "advertise", "ad",
                   "marketing", "sales", "press", "collaborate"]
EXCLUSION_PHRASES = ["terms of sale", "terms", "policy",
                     "markets", "media & entertainment", "media-entertainment"]

detected_forms_dict = {}

GPT_MAX_TOKENS = 16000
SAFETY_BUFFER_TOKENS = 1000
AVAILABLE_TEXT_TOKENS = GPT_MAX_TOKENS - SAFETY_BUFFER_TOKENS
GPT_COST_PER_1K_TOKENS = 0.005

key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=key)


def monitor_and_kill_outlook():
    for proc in psutil.process_iter(['name']):
        if proc.info['name'] and 'outlook' in proc.info['name'].lower():
            print("[WARNING] Outlook detected — killing process.")
            proc.kill()


def print_debug(message):
    print(f"\n{'='*30}\n[DEBUG] {message}\n")


def normalize_text(text):
    text = unicodedata.normalize("NFKD", text)
    text = re.sub(r"[^\w\s@\[\]\(\)\.-]+", "", text)
    return text.strip().lower()


def is_relevant_link(text):
    text_clean = normalize_text(text)
    if any(ex in text_clean for ex in EXCLUSION_PHRASES):
        return False
    doc = nlp(text_clean)
    lemmas = {token.lemma_ for token in doc}
    relevant_links = any(k in lemmas for k in INTENT_KEYWORDS)
    return relevant_links


def extract_links(driver, restrict_to_header_footer=True, all_links=False):
    print("Extracting links from page...")
    links = []
    sections = []
    if restrict_to_header_footer:
        for tag in ["header", "footer"]:
            try:
                sections.append(driver.find_element(By.TAG_NAME, tag))
            except:
                continue
    else:
        sections = [driver.find_element(By.TAG_NAME, "body")]

    for section in sections:
        try:
            soup = BeautifulSoup(section.get_attribute(
                "innerHTML"), "html.parser")
            for a in soup.find_all("a", href=True):
                text = a.get_text(strip=True)
                href = a['href']
                if not href or not text:
                    continue
                if not all_links:
                    if 'about' in text.lower() and not text.lower().strip().startswith('about'):
                        continue
                    links.append((text, href))
                else:
                    links.append((text, href))
        except:
            continue

    print(f"Total links found: {len(links)}")

    return links


def extract_text_from_page(driver, page_num, page_url, log):
    try:
        body = driver.find_element(By.TAG_NAME, "body")
        html = body.get_attribute("innerHTML")
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator="\n")
        form_dict = extract_form_details_from_driver(
            driver, page_num, page_url, log)
        return text, form_dict
    except:
        return "", {}


def scroll_to_bottom(driver, timeout=60):
    start_time = time.time()
    last_height = driver.execute_script("return document.body.scrollHeight")
    while True:
        driver.execute_script(
            "window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height
        if time.time() - start_time > timeout:
            print("[WARN] Scrolling timeout exceeded. Proceeding with partial content.")
            break


def extract_emails_from_text(text):
    print("\nExtracting emails from text...")
    text = normalize_text(text)
    obfuscated = re.findall(
        r"[\w\.-]+\s?\[?at\]?\s?[\w\.-]+\s?(dot|\.)\s?[a-z]{2,}", text)
    deobfuscated = [re.sub(
        r"\s?\[?at\]?\s?", "@", re.sub(r"\s?(dot|\.)\s?", ".", m)) for m in obfuscated]
    standard = re.findall(r"[\w\.-]+@[\w\.-]+\.[a-zA-Z]{2,}", text)
    all_emails = list(set(standard + deobfuscated))
    final_emails = [email for email in all_emails if email != "."]
    print(f"Emails found: {final_emails}")
    return final_emails


def summarize_page_text(text, log):
    prompt = (
        "Summarize the following webpage content and extract only the email addresses and their contexts relevant to marketing, advertising or press.\n\n"
        f"{text[:3000]}"
    )
    try:
        token_est = len(prompt.split())
        log['token_usage']['summarize_calls'] += 1
        log['token_usage']['tokens_used'] += token_est
        response = client.responses.create(
            model="gpt-4o-mini", input=[{"role": "user", "content": prompt}])
        print("\nGPT summarization response:\n" +
              response.output_text.strip())
        return client.responses.create(model="gpt-4o-mini", input=[{"role": "user", "content": prompt}]).output_text.strip()
    except Exception as e:
        print(f"[API ERROR] Failed to summarize page: {e}")
        return ""


def parse_form_fields(form_html):
    soup = BeautifulSoup(form_html, 'html.parser')
    parsed_fields = []

    # Collect all label elements mapped by 'for' attribute
    labels = {
        label.get('for'): label.get_text(strip=True)
        for label in soup.find_all('label')
        if label.get('for')
    }

    # Locate form input elements
    input_tags = soup.find_all(['input', 'textarea', 'select'])

    for tag in input_tags:
        if not isinstance(tag, Tag):
            continue

        field_info = {}
        tag_name = tag.name

        field_info['tag'] = tag_name
        field_info['type'] = tag.get('type', 'text').lower(
        ) if tag_name == 'input' else tag_name
        field_info['name'] = tag.get('name') or tag.get('id') or ''
        field_info['id'] = tag.get('id', '')
        field_info['required'] = bool(tag.has_attr(
            'required') or tag.get('aria-required') == 'true')
        field_info['placeholder'] = tag.get('placeholder') or ''
        field_info['autocomplete'] = tag.get('autocomplete') or ''
        field_info['maxlength'] = tag.get('maxlength') or ''
        field_info['pattern'] = tag.get('pattern') or ''
        field_info['class'] = tag.get('class', [])
        # ✅ New: Store the style attribute
        field_info['style'] = tag.get('style', '')

        # ===== Enhanced Label Resolution =====
        label_text = ''

        # 1. Match <label for="id">
        if field_info['id'] and field_info['id'] in labels:
            label_text = labels[field_info['id']]

        # 2. Look for parent <label>
        if not label_text:
            parent_label = tag.find_parent('label')
            if parent_label:
                label_text = parent_label.get_text(strip=True)

        # 3. Fallback to placeholder or aria-label
        if not label_text:
            label_text = field_info['placeholder'] or tag.get(
                'aria-label') or ''

        # 4. Check nearby visual cues
        if not label_text:
            # Try preceding text from nearby elements like <div>/<span>
            prev_label_tag = tag.find_previous(['label', 'div', 'span'])
            if prev_label_tag and prev_label_tag.get_text(strip=True):
                nearby = prev_label_tag.get_text(strip=True)
                if 0 < len(nearby) < 120:
                    label_text = nearby

        # 5. Check previous text node as last resort
        if not label_text:
            prev = tag.find_previous(string=True)
            if prev:
                cleaned = prev.strip()
                if 0 < len(cleaned) < 120:
                    label_text = cleaned

        # 6. Infer required flag from '*'
        if '*' in label_text and not field_info['required']:
            field_info['required'] = True

        field_info['label'] = label_text.strip()

        # Only include fields that look meaningful
        if field_info['name'] or field_info['label']:
            parsed_fields.append(field_info)

    return parsed_fields


def extract_submit_button(form_html):
    soup = BeautifulSoup(form_html, 'html.parser')

    # 1. Look for <button type="submit">
    buttons = soup.find_all('button')
    for button in buttons:
        if button.get('type', 'submit').lower() == 'submit' and not _is_hidden(button):
            return str(button)

    # 2. Look for <input type="submit">
    inputs = soup.find_all('input')
    for inp in inputs:
        if inp.get('type', '').lower() == 'submit' and not _is_hidden(inp):
            return str(inp)

    # 3. Look for <input type="image">
    for inp in inputs:
        if inp.get('type', '').lower() == 'image' and not _is_hidden(inp):
            return str(inp)

    # 4. Last resort: <div> or <span> with role="button" (if no true submit found)
    for tag in soup.find_all(['div', 'span']):
        if tag.get('role') == 'button' and not _is_hidden(tag):
            return str(tag)

    return None


def _is_hidden(tag):
    # Check if element is hidden using inline style or type
    style = tag.get('style', '').lower()
    hidden_type = tag.get('type', '').lower() == 'hidden'
    display_none = 'display:none' in style.replace(" ", "")
    return hidden_type or display_none


def gpt_choose_message_field(textarea_dict, log):
    prompt = f"""
      You are given a dictionary of form fields that are all unrequired <textarea> elements from a website's contact form.

      Each key is an index, and the value is a dictionary with field metadata, including things like tag, type, name, placeholder, label, etc.

      Your task is to determine which index most likely corresponds to the message box — where a user would type a message or inquiry.

      ONLY RETURN THE INTEGER INDEX (e.g., 0, 1, etc.). DO NOT explain or return any other text.

      Here is the dictionary:\n{json.dumps(textarea_dict, indent=2)}
      """

    try:
        token_est = len(prompt.split())
        log['token_usage']['tokens_used'] += token_est

        response = client.responses.create(
            model="gpt-4o-mini",
            input=[{"role": "user", "content": prompt}]
        )

        output = response.output_text.strip()
        if output.isdigit():
            return int(output)
        else:
            print(f"[GPT WARNING] Unexpected GPT output: {output}")
            return next(iter(textarea_dict))  # fallback to first
    except Exception as e:
        print(f"[API ERROR] GPT failed during message field selection: {e}")
        return next(iter(textarea_dict))  # fallback to first


def clean_form_fields(fields, log=None):
    """
    Cleans a list of parsed form fields.

    Args:
        fields (list): List of parsed field dicts.
        gpt_choose_message_field (func): Optional GPT function to choose best unrequired textarea.
        track_added (bool): If True, returns a dict of added unrequired textareas.

    Returns:
        cleaned_fields (list): Final cleaned list of fields.
        added_unrequired_textareas (dict): Only returned if `track_added` is True.
    """
    required_counter = Counter()
    unrequired_counter = Counter()
    cleaned_fields = []

    temp_fields = []
    removed_debug = []

    # === STAGE 1: REMOVE hidden, style=display:none, or "invisible" class ===
    for field in fields:
        reason = None
        if field.get('type') == 'hidden':
            reason = "Removed: type='hidden'"
        elif "display:none" in field.get("style", "").replace(" ", "").lower():
            reason = "Removed: style contains 'display:none'"
        elif "invisible" in field.get("class", []):
            reason = "Removed: class contains 'invisible'"

        if reason:
            print(
                f"[REMOVED] {reason} → Field: {json.dumps(field, indent=2)}\n")
            removed_debug.append((reason, field))
            continue

        temp_fields.append(field)

    # === STAGE 2: Handle unrequired fields & preserve unrequired textarea ===
    required_fields = [f for f in temp_fields if f.get('required')]
    removed_fields = [f for f in temp_fields if not f.get('required')]

    has_required_textarea = any(
        f['tag'] == 'textarea' for f in required_fields)
    added_unrequired_textareas = {}
    added_textarea_id = 1

    if has_required_textarea:
        final_fields = required_fields
    else:
        def is_not_captcha(field):
            for value in field.values():
                if isinstance(value, str) and 'captcha' in value.lower():
                    return False
                if isinstance(value, list) and any('captcha' in str(item).lower() for item in value):
                    return False
            return True

        unrequired_textareas = {
            idx: f for idx, f in enumerate(removed_fields)
            if f['tag'] == 'textarea' and is_not_captcha(f)
        }

        if len(unrequired_textareas) > 1:
            chosen_idx = gpt_choose_message_field(unrequired_textareas, log)
            chosen_textarea = unrequired_textareas[chosen_idx]
            final_fields = required_fields + [chosen_textarea]
            print(
                f"[ADDED UNREQUIRED TEXTAREA] GPT chose index {chosen_idx}:\n{json.dumps(chosen_textarea, indent=2)}")
            added_unrequired_textareas[added_textarea_id] = chosen_textarea
        elif len(unrequired_textareas) == 1:
            only_idx = next(iter(unrequired_textareas))
            chosen_textarea = unrequired_textareas[only_idx]
            final_fields = required_fields + [chosen_textarea]
            print(
                f"[ADDED UNREQUIRED TEXTAREA] Only one available:\n{json.dumps(chosen_textarea, indent=2)}")
            added_unrequired_textareas[added_textarea_id] = chosen_textarea
        else:
            final_fields = required_fields

    # === Optional: store added textareas in log (if log dict provided)
    if log is not None:
        log["added_unrequired_textareas"] = list(
            added_unrequired_textareas.values())

    return final_fields


def summarize_form_text_for_selection(content, log):
    prompt = f"""Summarize the purpose of the following webpage HTML form and page content in one sentence, ensuring you capture the main objective of the form. Indicate what the form is about and what kind of contact it's intended for: \
\n{content}"""
    try:
        token_est = len(prompt.split())
        log['token_usage']['tokens_used'] += token_est
        response = client.responses.create(
            model="gpt-4o-mini",
            input=[{"role": "user", "content": prompt}]
        )
        return response.output_text.strip()
    except Exception as e:
        print(f"[API ERROR] Failed to summarize form content: {e}")
        return ""


def choose_best_form_using_gpt(summary_dict, log):
    print("\nChoosing best form from mutliple ones...")
    prompt = """Given the following numbered summaries of different contact forms found across a website, choose the ONE most relevant for advertising, marketing, or press inquiries. Only return the number of the most appropriate summary. 
If multiple seem equally relevant, choose the one with the clearest purpose.

"""
    for key, summary in summary_dict.items():
        prompt += f"{key}: {summary}\n"
    prompt += "\nReturn only the number (e.g., 2)."

    try:
        token_est = len(prompt.split())
        log['token_usage']['tokens_used'] += token_est
        response = client.responses.create(
            model="gpt-4o-mini",
            input=[{"role": "user", "content": prompt}]
        )
        result = response.output_text.strip()
        return int(result) if result.isdigit() else None
    except Exception as e:
        print(f"[API ERROR] Failed to select best form: {e}")
        return None


def process_detected_forms(log):
    global detected_forms_dict
    if len(detected_forms_dict) == 0:
        print("\n0 forms detected in process_detected_forms")
        return None

    elif len(detected_forms_dict) == 1:
        print("\n1 form detected in process_detected_forms")
        key, value = list(detected_forms_dict.items())[0]
        html, text, url = value

        parsed_fields = parse_form_fields(html)
        cleaned_fields = clean_form_fields(parsed_fields, log)
        submit_button = extract_submit_button(html)

        save_dir = r"C:\Users\hp\Desktop\leadsup\v0\html-codes"
        os.makedirs(save_dir, exist_ok=True)

        domain = url.split("//")[-1].split("/")[0].replace('.', '_')
        filename = f"{domain}_final_chosen_form.html"
        filepath = os.path.join(save_dir, filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html)

        print(f"[✓] Saved single detected form to disk: {filepath}")

        return {
            'page_url': url,
            'summary': '',
            'fields': cleaned_fields,
            'submit_button': submit_button
        }

    else:
        print("\n[INFO] Multiple forms detected. Building summaries...")
        summarized_dict = {}
        new_dict = {}

        for i, (idx, value) in enumerate(detected_forms_dict.items(), start=1):
            html, text, url = value
            content = f"{html}\n{text}"
            summarized = summarize_form_text_for_selection(content, log)
            summarized_dict[i] = summarized
            new_dict[i] = [html, text, url, summarized]

        detected_forms_dict.clear()
        detected_forms_dict.update(new_dict)

        print("\n[DEBUG] Form Summaries:", summarized_dict)
        print("\n[DEBUG] Full Form Content:", detected_forms_dict)

        chosen_key = choose_best_form_using_gpt(summarized_dict, log)

        print(f"[DEBUG] Chosen Key from GPT: {chosen_key}")
        print(
            f"[DEBUG] Keys in detected_forms_dict: {list(detected_forms_dict.keys())}")

        if isinstance(chosen_key, int) and chosen_key in detected_forms_dict:
            chosen_form = detected_forms_dict[chosen_key]
            html, text, url, summary = chosen_form

            parsed_fields = parse_form_fields(html)
            cleaned_fields = clean_form_fields(parsed_fields, log)
            submit_button = extract_submit_button(html)

            save_dir = r"C:\Users\hp\Desktop\leadsup\v0\html-codes"
            os.makedirs(save_dir, exist_ok=True)

            domain = url.split("//")[-1].split("/")[0].replace('.', '_')
            filename = f"{domain}_final_chosen_form.html"
            filepath = os.path.join(save_dir, filename)

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(html)

            print(f"[✓] Saved chosen form to disk: {filepath}")

            return {
                'page_url': url,
                'summary': summary,
                'fields': cleaned_fields,
                'submit_button': submit_button
            }
        else:
            print(
                f"[WARNING] No valid form selected by GPT. Got: {chosen_key}")
            return None


def evaluate_form_relevance_with_gpt(form_html, page_text, log):
    try:
        total_chars = len(form_html) + len(page_text)
        if total_chars > AVAILABLE_TEXT_TOKENS:
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

        response = client.responses.create(
            model="gpt-4o-mini",
            input=[{"role": "user", "content": prompt}]
        )
        reply = response.output_text.strip().lower()

        if reply == "true":
            return True
        elif reply == "false":
            return False
        else:
            print(f"[WARNING] Unexpected GPT output: {reply!r}")
            return False  # default to False on any deviation

    except Exception as e:
        print(f"[API ERROR] Failed to evaluate form relevance: {e}")
        return False


def extract_form_details_from_driver(driver, page_num, page_url, log):
    result = {}
    try:
        page_source = driver.page_source
        soup = BeautifulSoup(page_source, 'html.parser')
        forms = soup.find_all('form')

        if not forms:
            print("[NOT FOUND] No form found on page")
            return result

        for idx, form in enumerate(forms):
            # === Pre-filter 1: Skip search forms with a single input ===
            input_tags = form.find_all(['input', 'textarea', 'select'])

            if len(input_tags) == 1:
                input_tag = input_tags[0]
                input_type = input_tag.get('type', 'text').lower()
                input_name = input_tag.get('name', '').lower()

                if input_type == 'search' or input_name == 's':
                    print(
                        f"[SKIPPED] Search form filtered out. URL: {page_url}")
                    continue

            # === Pre-filter 2: Require message field and at least 1 other field ===
            has_textarea = any(tag.name == 'textarea' for tag in input_tags)
            has_other_field = any(tag.name != 'textarea' for tag in input_tags)

            if not (has_textarea and has_other_field):
                print(
                    f"[SKIPPED] Form lacks message box + 1 other input. URL: {page_url}")
                continue

            # ==== Form passed pre-filters ====
            form_html = str(form)
            important_text = []

            # Collect page title
            title_tag = soup.find('title')
            if title_tag and title_tag.text.strip():
                important_text.append(f"Page Title: {title_tag.text.strip()}")

            # Get nearby context (up to 3 parents)
            parent = form.parent
            for _ in range(3):
                if parent is None:
                    break
                nearby_text = parent.get_text(separator=" ", strip=True)
                if nearby_text:
                    important_text.append(nearby_text)
                parent = parent.parent

            # Get form's own visible text
            form_text = form.get_text(separator=" ", strip=True)
            if form_text:
                important_text.append(f"Form Content: {form_text}")

            final_text = "\n".join(important_text)

            # Run GPT relevance check
            is_relevant = evaluate_form_relevance_with_gpt(
                form_html, final_text, log)

            if is_relevant:
                result[page_num + idx] = [form_html, final_text, page_url]
                print(f"[RELEVANT FORM] Saved form {idx+1} from {page_url}")
            else:
                print(f"[SKIPPED] Form {idx+1} not relevant. URL: {page_url}")

    except Exception as e:
        print(f"[ERROR] Form detection failed: {e}")
    return result


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
        response = client.responses.create(
            model="gpt-4o-mini", input=[{"role": "user", "content": prompt}])
        print("\nGPT email extraction response:\n" +
              response.output_text.strip())
        return [e.strip() for e in response.output_text.split(",") if e.strip() and re.match(r"[^@\s]+@[^@\s]+\.[^@\s]+", e.strip())]
    except Exception as e:
        print(f"[API ERROR] Failed to extract emails: {e}")
        return []


def nested_subpage_recovery(driver, domain_url, log):
    print("\nPerforming nested subpage recovery")
    log['used_recovery'] = True
    all_links = extract_links(
        driver, restrict_to_header_footer=False, all_links=True)
    seen_urls = set()
    final_emails = {}
    form_dict = {}  # form dictionary for recovery pages
    page_urls = [urljoin(domain_url, href) for _, href in all_links if href]

    for i, page_url in enumerate(page_urls):
        if page_url in seen_urls:
            continue
        seen_urls.add(page_url)
        try:
            driver.get(page_url)
            scroll_to_bottom(driver)
            text, extracted_forms = extract_text_from_page(
                driver, i + 1, page_url, log)
            if not text.strip():
                continue
            emails = extract_emails_from_text(text)
            if emails:
                final_emails[page_url] = emails
            form_dict.update(extracted_forms)
        except Exception as e:
            print(f"[ERROR] during recovery at {page_url}: {e}")
            continue

    print("\n[RECOVERY FORM DICT RESULT]:")
    for idx, (html, context_text, url) in form_dict.items():
        print(
            f"\n[FORM {idx}] URL: {url}\nHTML (truncated): {html[:300]}...\nText: {context_text[:300]}...\n")

    print(f"\nSubpage emails found: {final_emails}")
    return final_emails


@contextlib.contextmanager
def suppress_output():
    with open(os.devnull, "w") as fnull:
        with contextlib.redirect_stdout(fnull), contextlib.redirect_stderr(fnull):
            yield


def process_domain(domain_url, expected_email):
    log = {
        'domain': domain_url,
        'manual_emails': [],
        'gpt_emails': [],
        'token_usage': {'tokens_used': 0, 'summarize_calls': 0},
        'matches_expected': {'manual': False, 'gpt': False},
        'used_recovery': False,
        'timed_out': False,
        'form_detected': False,
        'form_page_urls': [],
        'chosen_form': {}
    }

    global detected_forms_dict
    detected_forms_dict = {}

    start_time = time.time()
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--log-level=3")
    options.add_experimental_option("excludeSwitches", ["enable-logging"])

    with suppress_output():
        driver = webdriver.Chrome(service=Service(
            CHROMEDRIVER_PATH), options=options)

    driver.get(domain_url)
    time.sleep(3)

    raw_links = extract_links(driver, restrict_to_header_footer=True)
    found_links = {}
    seen_urls = set()
    relevant_link_texts = []

    for text, href in raw_links:
        abs_url = urljoin(domain_url, href)
        if abs_url in seen_urls:
            continue
        if is_relevant_link(text):
            relevant_link_texts.append(text)
            found_links[text] = abs_url
            seen_urls.add(abs_url)

    print(f"\nTotal relevant links found: {len(relevant_link_texts)}")
    print(f"Relevance result: {relevant_link_texts}")

    if not found_links:
        fallback_links = extract_links(driver, restrict_to_header_footer=False)
        for text, href in fallback_links:
            abs_url = urljoin(domain_url, href)
            if abs_url in seen_urls:
                continue
            if is_relevant_link(text):
                found_links[text] = abs_url
                seen_urls.add(abs_url)

    page_texts = {}
    form_dict = {}

    for i, (page_name, page_url) in enumerate(found_links.items()):
        if time.time() - start_time > 240:
            log['timed_out'] = True
            print(f"[TIME LIMIT] Partial scrape used for {domain_url}.")
            break
        try:
            driver.get(page_url)
            scroll_to_bottom(driver)
            text, extracted_forms = extract_text_from_page(
                driver, i + 1, page_url, log)
            if text.strip():
                page_texts[page_name] = text
            form_index = len(detected_forms_dict) + 1
            for form in extracted_forms.values():
                detected_forms_dict[form_index] = form
                form_index += 1
                print(
                    f"[DEBUG] Total forms collected so far: {len(detected_forms_dict)}")

        except:
            continue

    print("\n[FORM DICT RESULT]:")
    for idx, (html, context_text, url) in form_dict.items():
        print(
            f"\n[FORM {idx}] URL: {url}\nHTML (truncated): {html[:300]}...\nText: {context_text[:300]}...\n")

    log['form_detected'] = len(detected_forms_dict) > 0
    log['form_page_urls'] = [url for _,
                             (_, _, url) in detected_forms_dict.items()]
    log['matches_expected']['form'] = 'form' in expected_email.lower()

    if not page_texts:
        page_texts = nested_subpage_recovery(driver, domain_url, log)

    driver.quit()

    if page_texts:
        combined_text = "\n\n".join(page_texts.values())
        log['manual_emails'] = extract_emails_from_text(combined_text)
        log['gpt_emails'] = extract_emails_using_gpt_combined(page_texts, log)
        log['matches_expected']['manual'] = expected_email.lower() in [e.lower()
                                                                       for e in log['manual_emails']]
        log['matches_expected']['gpt'] = expected_email.lower() in [e.lower()
                                                                    for e in log['gpt_emails']]
    else:
        log['timed_out'] = True

    log['token_usage']['estimated_cost_usd'] = round(
        (log['token_usage']['tokens_used'] / 1000) * GPT_COST_PER_1K_TOKENS, 5
    )

    chosen_form = process_detected_forms(log)
    if chosen_form:
        log['chosen_form'] = chosen_form

    return log


def main():
    print_debug("Starting scraping process")

    df = pd.read_csv(CSV_FILE_PATH)
    df = df.dropna(subset=['domain'])

    for _, row in df.iterrows():
        domain = row['domain'].strip()
        expected_email = str(
            row['email/form']).strip() if pd.notna(row['email/form']) else ""
        expected_form = 'form' in expected_email.lower()

        print_debug(f"Processing domain: {domain}")

        monitor_and_kill_outlook()

        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    process_domain, "https://" + domain, expected_email)
                log = future.result(timeout=300)
        except ThreadTimeoutError:
            log = {
                'domain': domain,
                'manual_emails': [],
                'gpt_emails': [],
                'token_usage': {'tokens_used': 0, 'summarize_calls': 0, 'estimated_cost_usd': 0},
                'matches_expected': {'manual': False, 'gpt': False, 'form': False},
                'used_recovery': False,
                'timed_out': True,
                'form_detected': False,
                'form_page_urls': [],
                'chosen_form': {}
            }
            print_debug(f"[TIMEOUT] Skipped {domain} after full limit.")
        except Exception as e:
            print_debug(f"[ERROR] Failed to process {domain}: {e}")
            continue

        log_path = os.path.join(
            LOGS_DIR_PATH, f"{domain.replace('.', '_')}.json")
        with open(log_path, 'w', encoding='utf-8') as f:
            json.dump(log, f, indent=2)
            print_debug(f"{domain} completed and log saved.")

    print_debug("Scraping completed for all domains")


if __name__ == "__main__":
    main()

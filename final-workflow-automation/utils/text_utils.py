import re
import unicodedata


def print_debug(message):
    print(f"\n{'='*30}\n[DEBUG] {message}\n")


def normalize_text(text):
    text = unicodedata.normalize("NFKD", text)
    text = re.sub(r"[^\w\s@\[\]\(\)\.-]+", "", text)
    return text.strip().lower()


def extract_emails_from_text(text):
    print("\nExtracting emails from text...")
    text = normalize_text(text)

    obfuscated = re.findall(
        r"[\w\.-]+\s?\[?at\]?\s?[\w\.-]+\s?(dot|\.)\s?[a-z]{2,}", text
    )
    deobfuscated = [
        re.sub(r"\s?\[?at\]?\s?", "@", re.sub(r"\s?(dot|\.)\s?", ".", m))
        for m in obfuscated
    ]
    standard = re.findall(r"[\w\.-]+@[\w\.-]+\.[a-zA-Z]{2,}", text)
    all_emails = list(set(standard + deobfuscated))
    final_emails = [email for email in all_emails if email != "."]

    print(f"Emails found: {final_emails}")
    return final_emails

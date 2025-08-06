from datetime import datetime
import os
import warnings
import spacy
from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path

PREDEFINED_FIELDS = {
    "email": "abc123@gmail.com",
    "first_name": "John",
    "last_name": "Doe",
    "phone": "+1-333-123456",
    "message": "I'm interested in advertising opportunities.",
    "subject": "Advertising Inquiry",
    "address": "123 Main St, City, Country",
    "website": "https://example.com",
    "company_name": "Acme Inc.",
    "postal_code": "12345"
}

ANTI_CAPTCHA_KEY = os.getenv("ANTI_CAPTCHA_KEY")

# === Suppress warnings globally ===
warnings.filterwarnings("ignore")

# === Load .env variables ===
load_dotenv()

# === Load spaCy model ===
nlp = spacy.load("en_core_web_sm")

# === Base Paths ===
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
BIN_DIR = BASE_DIR / "bin"

OUTPUT_CSV_PATH = DATA_DIR / "output" / "final_summary.csv"

# === File paths ===
CHROMEDRIVER_PATH = BIN_DIR / "chromedriver-win64" / "chromedriver.exe"
DOMAINS_TXT_PATH = DATA_DIR / "input" / "domains.txt"

# Logs creation
LOGS_PARENT_DIR = DATA_DIR / "logs"
timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
LOGS_DIR_PATH = LOGS_PARENT_DIR / f"run_{timestamp}"
os.makedirs(LOGS_DIR_PATH, exist_ok=True)

# === Keyword logic ===
INTENT_KEYWORDS = ["contact", "advertise", "ad",
                   "marketing", "sales", "press", "collaborate"]
EXCLUSION_PHRASES = ["terms of sale", "terms", "policy",
                     "markets", "media & entertainment", "media-entertainment"]

# === GPT Token config ===
GPT_MAX_TOKENS = 16000
SAFETY_BUFFER_TOKENS = 1000
AVAILABLE_TEXT_TOKENS = GPT_MAX_TOKENS - SAFETY_BUFFER_TOKENS
GPT_COST_PER_1K_TOKENS = 0.005
GPT_COST_PER_TOKEN = GPT_COST_PER_1K_TOKENS / 1000  # $0.000005 per token

# === OpenAI setup ===
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

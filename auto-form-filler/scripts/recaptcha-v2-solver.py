import os
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from dotenv import load_dotenv
from anticaptchaofficial.recaptchav2proxyless import recaptchaV2Proxyless

# === ENV + CONFIG ===
load_dotenv()
ANTI_CAPTCHA_KEY = os.getenv("ANTI_CAPTCHA_KEY")

TARGET_URL = "https://bloggingthebracket.com/contact?community_id=247"
CHROMEDRIVER_PATH = r"C:\Users\hp\Desktop\leadsup\v0\chromedriver-win64\chromedriver.exe"

if not ANTI_CAPTCHA_KEY:
    raise ValueError("ANTI_CAPTCHA_KEY not found in .env file")

# === Setup Selenium ===
options = Options()
options.add_argument("--disable-gpu")
options.add_argument("--log-level=3")
options.add_experimental_option("excludeSwitches", ["enable-logging"])

service = Service(CHROMEDRIVER_PATH)
driver = webdriver.Chrome(service=service, options=options)

# === Step 1: Open Page and Wait for Manual Field Entry ===
driver.get(TARGET_URL)
print("\n🔓 Page loaded. Fill in the form fields manually in the browser.")
input("📥 Press ENTER in terminal once you are ready to solve CAPTCHA...")

# === Step 2: Extract sitekey and solve CAPTCHA ===
try:
    recaptcha_element = driver.find_element(By.CLASS_NAME, "g-recaptcha")
    sitekey = recaptcha_element.get_attribute("data-sitekey")
    print(f"🔑 Extracted sitekey: {sitekey}")
except:
    driver.quit()
    raise Exception("❌ Failed to find reCAPTCHA element or sitekey.")

print("🧠 Solving CAPTCHA via Anti-Captcha...")

solver = recaptchaV2Proxyless()
solver.set_verbose(1)
solver.set_key(ANTI_CAPTCHA_KEY)
solver.set_website_url(TARGET_URL)
solver.set_website_key(sitekey)
solver.set_soft_id(0)

g_response = solver.solve_and_return_solution()
if g_response == 0:
    driver.quit()
    raise Exception("❌ CAPTCHA solving failed: " + solver.error_code)

print("✅ CAPTCHA Solved! Injecting token into page...")

# === Step 3: Inject CAPTCHA token ===
driver.execute_script("""
    document.getElementById("g-recaptcha-response").style.display = "block";
    document.getElementById("g-recaptcha-response").value = arguments[0];
""", g_response)

print("📨 CAPTCHA response injected.")
print("📌 Now manually submit the form in the browser.")

# === Step 4: Wait for final ENTER press ===
input("✅ Press ENTER in terminal once you've submitted the form...")

# === Clean Exit ===
print("👋 Exiting.")
driver.quit()

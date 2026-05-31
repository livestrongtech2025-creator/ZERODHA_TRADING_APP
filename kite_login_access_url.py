import webbrowser
import os
import re
from kiteconnect import KiteConnect
from config import ZERODHA_API_KEY, ZERODHA_API_SECRET

# --- CONFIGURATION ---
API_KEY = ZERODHA_API_KEY
API_SECRET = ZERODHA_API_SECRET
ENV_FILE = ".env"
ENV_VAR_NAME = "ZERODHA_ACCESS_TOKEN"

# 1. Initialize KiteConnect
kite = KiteConnect(api_key=API_KEY)

def get_token_from_env():
    """Read ZERODHA_ACCESS_TOKEN value from .env file."""
    if not os.path.exists(ENV_FILE):
        return None
    with open(ENV_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith(f"{ENV_VAR_NAME}="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                return value if value else None
    return None

def update_token_in_env(new_token):
    """Update or insert ZERODHA_ACCESS_TOKEN in the .env file."""
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r") as f:
            content = f.read()

        # If the variable exists, replace its value
        pattern = rf"^{ENV_VAR_NAME}=.*$"
        replacement = f"{ENV_VAR_NAME}={new_token}"
        new_content, count = re.subn(pattern, replacement, content, flags=re.MULTILINE)

        if count == 0:
            # Variable not found, append it
            new_content = content.rstrip("\n") + f"\n{ENV_VAR_NAME}={new_token}\n"
    else:
        # .env file doesn't exist, create it
        new_content = f"{ENV_VAR_NAME}={new_token}\n"

    with open(ENV_FILE, "w") as f:
        f.write(new_content)

def login():
    # If a token already exists in .env, try using it first
    token = get_token_from_env()
    if token:
        kite.set_access_token(token)
        try:
            # Test if token is still valid by fetching profile
            kite.profile()
            print("Welcome back! Using existing session.")
            return
        except Exception:
            print("Existing session expired. Logging in again...")

    # 2. Open the login URL automatically
    login_url = kite.login_url()
    print(f"Opening browser for login: {login_url}")
    webbrowser.open(login_url)

    # 3. Get the request_token from you
    request_token = input("\nPaste the 'request_token' from the browser URL: ").strip()

    try:
        # 4. Generate the session (Library handles checksum internally)
        data = kite.generate_session(request_token, api_secret=API_SECRET)
        access_token = data["access_token"]

        # 5. Save the token directly into .env
        update_token_in_env(access_token)
        
        kite.set_access_token(access_token)
        print(f"Login successful! Token updated in {ENV_FILE} under {ENV_VAR_NAME}.")

    except Exception as e:
        print(f"Error during login: {e}")

# Run the login
login()

# --- YOUR TRADING CODE STARTS HERE ---
# Example: print(kite.margins())
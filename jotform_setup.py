import keyring
import getpass

print("=== JotForm Secure Setup ===")
print("Your credentials will be stored in macOS Keychain.\n")

api_key = getpass.getpass("Paste your JotForm API key (hidden): ").strip()
team_id = getpass.getpass("Paste your JotForm Team ID (hidden, press Enter to skip): ").strip()

keyring.set_password("jotform", "api_key", api_key)
keyring.set_password("jotform", "team_id", team_id)

print("\nCredentials saved securely to macOS Keychain.")
print("You can now run jotform_sync.py anytime without entering your keys.")

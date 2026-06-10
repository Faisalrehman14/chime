"""One-time Gmail OAuth setup for CHIMME (CLI fallback)."""

from src.gmail_oauth import redirect_uri, start_web_oauth


def main() -> None:
    print("Browser mein Gmail connect khulega...")
    print(f"Redirect URI (Google Cloud mein add karo): {redirect_uri()}")
    url = start_web_oauth()
    print(f"Open this URL:\n{url}")
    print("\nWebsite use kar rahe ho to Settings se 'Connect Gmail' dabao.")


if __name__ == "__main__":
    main()

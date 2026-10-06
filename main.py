"""
main.py — Entry point for Social Cleaner.
Run: python main.py
"""
import sys

# Ensure UTF-8 console output on Windows to prevent UnicodeEncodeError
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def main():
    try:
        from app import main as run_app
        run_app()
    except ImportError as e:
        print(f"[ERROR] Missing dependency: {e}")
        print("\nPlease install requirements:")
        print("  pip install -r requirements.txt")
        print("  playwright install chromium")
        sys.exit(1)
    except Exception as e:
        print(f"[FATAL] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

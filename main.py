"""
main.py — Entry point for Social Cleaner.
Run: python main.py
"""
import sys

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

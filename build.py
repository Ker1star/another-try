from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parent
SOURCE_STATIC = ROOT / "app" / "static"
TARGET_STATIC = ROOT / "public" / "static"


def main():
    if not SOURCE_STATIC.exists():
        raise SystemExit(f"Static source folder is missing: {SOURCE_STATIC}")

    if TARGET_STATIC.exists():
        shutil.rmtree(TARGET_STATIC)

    TARGET_STATIC.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SOURCE_STATIC, TARGET_STATIC)
    print(f"Copied static assets to {TARGET_STATIC}")


if __name__ == "__main__":
    main()

"""Start the standalone local workbench: python -m autokaggle.run."""
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Run the AutoKaggle local prototype")
    parser.add_argument("--port", type=int, default=8877)
    parser.add_argument("--env-file", type=Path, action="append", help="Private environment file; repeat for separate model and email settings")
    args = parser.parse_args()
    if args.env_file:
        from dotenv import load_dotenv
        for path in args.env_file:
            load_dotenv(path, override=False)
    import uvicorn
    from .app import create_app
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()

"""Start the Streamlit UI on this machine only: `quacky-ui`.

Streamlit's defaults listen on every network interface, send usage statistics
and show a "Deploy" button, so this launcher sets localhost, turns statistics
off and hides the button.
"""

import sys
from pathlib import Path


def main() -> int:
    try:
        from streamlit.web import cli as streamlit_cli
    except ImportError:
        print('The UI needs Streamlit. Install it with: pip install -e ".[ui]"', file=sys.stderr)
        return 1

    sys.argv = [
        "streamlit", "run", str(Path(__file__).with_name("app.py")),
        "--server.address", "localhost",
        "--browser.gatherUsageStats", "false",
        "--client.toolbarMode", "minimal",  # no "Deploy" button: Quacky is local-only
        *sys.argv[1:],  # e.g. --server.port 8502
    ]
    return streamlit_cli.main()


if __name__ == "__main__":
    sys.exit(main())

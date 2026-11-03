"""Start the Streamlit UI on this machine only: `quacky-ui`.

Streamlit's defaults listen on every network interface, send usage statistics
and show a "Deploy" button, so this launcher sets localhost, turns statistics
off and hides the button. It also applies Quacky's theme ("the pond at night").
"""

import sys
from pathlib import Path

# Deep pond-water ground, moonlit cream text, duck-yellow for actions.
THEME = {
    "base": "dark",
    "primaryColor": "#FFD84D",
    "backgroundColor": "#0E1A1D",
    "secondaryBackgroundColor": "#15262A",
    "textColor": "#EDE5D0",
    "borderColor": "#24393F",
    "linkColor": "#FFD84D",
    "codeBackgroundColor": "#0A1416",
    "codeTextColor": "#F3D98A",
    "greenColor": "#8CC084",
    "orangeColor": "#F2A541",
    "redColor": "#E8776B",
    "blueColor": "#7FB7C9",
    "dataframeHeaderBackgroundColor": "#15262A",
    "font": "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    "headingFont": "'Bricolage Grotesque', -apple-system, sans-serif",
    "codeFont": "ui-monospace, 'SF Mono', Menlo, monospace",
    "baseRadius": "0.65rem",
}


def main() -> int:
    try:
        from streamlit.web import cli as streamlit_cli
    except ImportError:
        print('The UI needs Streamlit. Install it with: pip install -e ".[ui]"', file=sys.stderr)
        return 1

    theme_flags = [arg for key, value in THEME.items() for arg in (f"--theme.{key}", value)]
    sys.argv = [
        "streamlit", "run", str(Path(__file__).with_name("app.py")),
        "--server.address", "localhost",
        "--server.enableStaticServing", "true",  # serves the bundled font in quacky/static
        "--browser.gatherUsageStats", "false",
        "--client.toolbarMode", "minimal",  # no "Deploy" button: Quacky is local-only
        *theme_flags,
        *sys.argv[1:],  # e.g. --server.port 8502
    ]
    return streamlit_cli.main()


if __name__ == "__main__":
    sys.exit(main())

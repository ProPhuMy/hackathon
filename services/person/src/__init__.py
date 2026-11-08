def main() -> None:
    from .main import main as cli_main

    raise SystemExit(cli_main())

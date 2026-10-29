"""Render the portable demo-function SQL for a caller-supplied UC name."""

import argparse
from pathlib import Path


def quote_function_name(function_name: str) -> str:
    """Validate and quote a catalog.schema.function name."""
    parts = function_name.split(".")
    if len(parts) != 3 or not all(parts):
        raise ValueError(
            "Function name must have three non-empty parts: "
            "catalog.schema.function"
        )
    return ".".join(f"`{part.replace('`', '``')}`" for part in parts)


def render_sql(function_name: str) -> str:
    template = Path(__file__).with_name("create_demo_function.sql").read_text(
        encoding="utf-8"
    )
    return template.replace("{{FUNCTION_NAME}}", quote_function_name(function_name))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render SQL for the sample Unity Catalog function."
    )
    parser.add_argument(
        "--function-name",
        required=True,
        help="Three-part Unity Catalog name: catalog.schema.function",
    )
    args = parser.parse_args()
    print(render_sql(args.function_name), end="")


if __name__ == "__main__":
    main()

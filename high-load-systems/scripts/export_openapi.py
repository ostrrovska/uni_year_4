"""Write the OpenAPI document to docs/openapi.json.

The spec is committed so it can be reviewed in a diff and consumed without running
the stack; `/docs` remains the live version.
"""

import json
from pathlib import Path

from app.main import create_app

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "docs" / "openapi.json"


def main() -> None:
    schema = create_app().openapi()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    paths = len(schema.get("paths", {}))
    print(f"Wrote {OUTPUT_PATH} ({paths} paths).")


if __name__ == "__main__":
    main()

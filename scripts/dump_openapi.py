"""Write the OpenAPI schema the TypeScript client is generated from.

CLAUDE.md: API client types are generated, never hand-written. This is the seam.
"""

import json
import sys
from pathlib import Path

# Run from anywhere, including from web/ via npm run gen:api.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.main import app  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "openapi.json"


def main() -> None:
    OUT.write_text(json.dumps(app.openapi(), indent=2))
    print(f"wrote {OUT.name}")


if __name__ == "__main__":
    main()

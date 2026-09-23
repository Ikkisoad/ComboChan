from .cli import main
import sys

try:
    main()
except (ValueError, RuntimeError, OSError) as exc:
    print(f"ComboChan: {exc}", file=sys.stderr)
    raise SystemExit(1)

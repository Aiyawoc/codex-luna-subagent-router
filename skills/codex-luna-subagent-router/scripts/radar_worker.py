"""Private HTTP subprocess entry; output is bounded public JSON, never secrets."""
import sys
import radar_snapshot


def main():
    try:
        timeout = int(sys.argv[1])
        if not 250 <= timeout <= 10000:
            return 2
        raw = radar_snapshot.fetch(timeout)
        sys.stdout.buffer.write(raw)
        return 0
    except Exception:
        # Parent records a fixed failure code, not untrusted server error text.
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

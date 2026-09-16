#!/usr/bin/env python3
"""Maintainer-only upstream metadata lookup. Never used by installed hooks."""
import argparse
import json
import urllib.request


def get_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "codex-luna-subagent-router-runtime-build"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default="3.13.15")
    parser.add_argument("--pbs-tag", default="20260901")
    args = parser.parse_args()
    win = get_json(f"https://www.python.org/ftp/python/{args.python}/windows-{args.python}.json")
    release = get_json(f"https://api.github.com/repos/astral-sh/python-build-standalone/releases/tags/{args.pbs_tag}")
    selected = {"windows": [v for v in win["versions"] if v["id"] in ("pythonembed-3.13-64", "pythonembed-3.13-arm64")],
                "macos_candidates": [{k: a.get(k) for k in ("name", "size", "digest", "browser_download_url")}
                    for a in release["assets"] if "cpython-3.13." in a["name"] and "apple-darwin-install_only_stripped" in a["name"]],
                "pbs_release": release["html_url"], "pbs_commit": release["target_commitish"]}
    print(json.dumps(selected, indent=2))


if __name__ == "__main__":
    main()

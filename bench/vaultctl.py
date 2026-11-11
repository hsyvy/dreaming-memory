#!/usr/bin/env python3
"""A deliberately awkward CLI for the learning-loop benchmark.

Fetching a record takes four things the tool only reveals one error at a time, and one of
them (which realm a record lives in) is never stated: it has to be worked out by trying.
A session that remembers the procedure needs one call; one that does not needs six or more.
"""

import hashlib
import sys

REALMS = ("north", "south", "archive")
WORDS = ("amber", "basalt", "cobalt", "dune", "ember", "fjord", "garnet", "heron", "indigo", "juniper")


def realm_of(record: str) -> str:
    last = int(record[-1])
    return "north" if last <= 3 else "south" if last <= 6 else "archive"


def value_of(record: str) -> str:
    digest = hashlib.sha256(f"vault:{record}".encode()).hexdigest()
    return f"{WORDS[int(digest[0], 16) % len(WORDS)]}-{int(digest[1:6], 16) % 9000 + 1000}"


def fail(code: str, message: str) -> None:
    print(f"{code}: {message}", file=sys.stderr)
    sys.exit(2)


def main(argv: list[str]) -> None:
    if not argv or argv[0] in ("help", "-h", "--help"):
        print("usage: vaultctl.py get <record-id> [options] | vaultctl.py realms")
        return
    if argv[0] == "realms":
        print("realms: " + ", ".join(REALMS) + "\nRecords are sharded across realms.")
        return
    if argv[0] != "get" or len(argv) < 2 or not argv[1].isdigit():
        fail("E00", "usage: vaultctl.py get <record-id> [options]")
    record, rest = argv[1], argv[2:]
    opts = {rest[i]: rest[i + 1] for i in range(0, len(rest) - 1, 2)}
    if "--realm" not in opts:
        fail("E01", "--realm is required. Run `vaultctl.py realms` to list realms.")
    if opts["--realm"] not in REALMS:
        fail("E01", f"unknown realm {opts['--realm']!r}. Run `vaultctl.py realms`.")
    if "--stamp" not in opts:
        fail("E03", "--stamp is required: the record id with its digits reversed.")
    if opts["--stamp"] != record[::-1]:
        fail("E03", "bad stamp: it must be the record id with its digits reversed.")
    if opts.get("--format") != "v2":
        fail("E04", "legacy output format is disabled; pass --format v2.")
    if opts["--realm"] != realm_of(record):
        fail("E02", f"record {record} is not in realm {opts['--realm']!r}.")
    print(f"value: {value_of(record)}")


if __name__ == "__main__":
    main(sys.argv[1:])

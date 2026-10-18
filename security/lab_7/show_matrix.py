"""Print the current access matrix without starting the server.

Reads the same acl.json the server uses, so it shows the state the last protocol
run left behind - handy during a demonstration.
"""

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [_HERE, os.path.dirname(_HERE)]  # run directly: find `common` and siblings

from acl import AccessMatrix

sys.stdout.reconfigure(encoding='utf-8')  # Cyrillic output survives a pipe


def main():
    ap = argparse.ArgumentParser(description="Show the access matrix")
    ap.add_argument("--acl", default=os.path.join(_HERE, "acl.json"))
    ap.add_argument("--storage", default=os.path.join(_HERE, "storage"))
    args = ap.parse_args()

    matrix = AccessMatrix(args.acl, args.storage)
    if not matrix.objects:
        print("Матриця порожня: спершу запустіть демонстрацію лабораторної 7.")
        return

    subjects = sorted({matrix.owner_of(o) for o in matrix.objects} |
                      {s for o in matrix.objects for s in matrix.objects[o]["acl"]})
    print(f"Суб'єктів: {len(subjects)}    Об'єктів: {len(matrix.objects)}")
    print()
    print(matrix.render_matrix(subjects))
    print()
    print("Власники об'єктів:")
    for obj in sorted(matrix.objects):
        print(f"  {obj:<16} {matrix.owner_of(obj)}")


if __name__ == "__main__":
    main()

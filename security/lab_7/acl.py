"""Lab 7, variant 1 - discretionary access control.

The access matrix A(S, O) is stored as sparse access lists: for every protected
object we keep the identifiers of the subjects together with their rights, i.e.
one column of the matrix per object. The owner right gives a subject full control
over the column of its object, which is exactly what discretionary control means.
"""

import datetime
import json
import os
import re

READ, WRITE, DELETE, GRANT, OWN = "read", "write", "delete", "grant", "own"
ALL_RIGHTS = (READ, WRITE, DELETE, GRANT, OWN)
GRANTABLE = (READ, WRITE, DELETE, GRANT, OWN)
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,48}$")


class AccessError(Exception):
    pass


class AccessMatrix:
    def __init__(self, acl_path, storage_dir):
        self.acl_path = acl_path
        self.storage_dir = storage_dir
        os.makedirs(storage_dir, exist_ok=True)
        self.objects = {}
        self.load()

    # --- persistence ---

    def load(self):
        if os.path.isfile(self.acl_path):
            with open(self.acl_path, "r", encoding="utf-8") as fh:
                self.objects = json.load(fh).get("objects", {})
        else:
            self.objects = {}

    def save(self):
        with open(self.acl_path, "w", encoding="utf-8") as fh:
            json.dump({"objects": self.objects}, fh, ensure_ascii=False, indent=2,
                      sort_keys=True)

    # --- helpers ---

    @staticmethod
    def validate_name(obj):
        if not NAME_RE.match(obj or ""):
            raise AccessError(f"illegal object name '{obj}'")
        return obj

    def path_of(self, obj):
        return os.path.join(self.storage_dir, self.validate_name(obj) + ".txt")

    def exists(self, obj):
        return obj in self.objects

    def owner_of(self, obj):
        return self.objects[obj]["owner"]

    def rights_of(self, subject, obj):
        """Effective rights = explicit access list entry, plus everything for the owner."""
        if obj not in self.objects:
            return set()
        if self.objects[obj]["owner"] == subject:
            return set(ALL_RIGHTS)
        return set(self.objects[obj]["acl"].get(subject, []))

    def capability_list(self, subject):
        """Row of the access matrix: objects this subject may touch, with its rights."""
        return {obj: sorted(self.rights_of(subject, obj))
                for obj in sorted(self.objects)
                if self.rights_of(subject, obj)}

    def access_list(self, obj):
        """Column of the access matrix: subjects allowed on this object."""
        entry = self.objects[obj]
        column = {entry["owner"]: sorted(ALL_RIGHTS)}
        for subject, rights in entry["acl"].items():
            if subject != entry["owner"]:
                column[subject] = sorted(rights)
        return column

    def check(self, subject, obj, right):
        if obj not in self.objects:
            return False, f"object '{obj}' does not exist"
        if right in self.rights_of(subject, obj):
            owner = " (as owner)" if self.objects[obj]["owner"] == subject else ""
            return True, f"right '{right}' on '{obj}' is present{owner}"
        return False, f"subject '{subject}' has no right '{right}' on '{obj}'"

    # --- operations ---

    def create(self, subject, obj, content=""):
        self.validate_name(obj)
        if obj in self.objects:
            raise AccessError(f"object '{obj}' already exists")
        self.objects[obj] = {
            "owner": subject,
            "acl": {},
            "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        with open(self.path_of(obj), "w", encoding="utf-8") as fh:
            fh.write(content)
        self.save()

    def read(self, obj):
        with open(self.path_of(obj), "r", encoding="utf-8") as fh:
            return fh.read()

    def write(self, obj, text):
        with open(self.path_of(obj), "a", encoding="utf-8") as fh:
            fh.write(text.rstrip("\n") + "\n")

    def delete(self, obj):
        path = self.path_of(obj)
        if os.path.isfile(path):
            os.remove(path)
        self.objects.pop(obj, None)
        self.save()

    def set_right(self, obj, subject, right, enabled):
        if right not in GRANTABLE:
            raise AccessError(f"unknown right '{right}'")
        entry = self.objects[obj]
        if right == OWN and enabled:
            entry["owner"] = subject          # ownership transfer
            entry["acl"].pop(subject, None)
            self.save()
            return
        current = set(entry["acl"].get(subject, []))
        if enabled:
            current.add(right)
        else:
            current.discard(right)
        if current:
            entry["acl"][subject] = sorted(current)
        else:
            entry["acl"].pop(subject, None)
        self.save()

    def render_matrix(self, subjects):
        """Plain-text access matrix for the work protocol."""
        objects = sorted(self.objects)
        width = max([len(s) for s in subjects] + [8])
        head = " " * (width + 2) + " ".join(f"{o[:11]:>11}" for o in objects)
        lines = [head, "-" * len(head)]
        for s in subjects:
            cells = []
            for o in objects:
                rights = self.rights_of(s, o)
                mark = "".join(r[0].upper() if r in rights else "." for r in ALL_RIGHTS)
                cells.append(f"{mark:>11}")
            lines.append(f"{s:<{width}}  " + " ".join(cells))
        lines.append("")
        lines.append("columns = objects, rows = subjects, flags = " +
                     " ".join(f"{r[0].upper()}={r}" for r in ALL_RIGHTS))
        return "\n".join(lines)

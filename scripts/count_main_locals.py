#!/usr/bin/env python3
"""Identify heaviest main-body local-variable blocks in SMC++.pine."""

src = open("SMC++.pine").read()
lines = src.split("\n")

in_helper = False
blocks = []
bs = None
bc = 0
px = ("string ", "int ", "float ", "bool ", "color ", "var ", "OrderBlock ", "FVG ", "LongSetupState ")

for i, line in enumerate(lines):
    s = line.strip()
    if s.endswith("=>") and not s.startswith("//") and not s.startswith("if ") and not s.startswith("else"):
        if bc > 0 and bs is not None:
            blocks.append((bs + 1, i + 1, bc, lines[bs].strip()[:80]))
            bc = 0
            bs = None
        in_helper = True
        continue
    if in_helper and len(line) > 0 and not line[0].isspace() and not s.startswith("//"):
        in_helper = False
    if not in_helper:
        hit = any(s.startswith(p) for p in px)
        if hit:
            if bs is None:
                bs = i
            bc += 1
        elif bc > 0 and bs is not None and not s.startswith("//") and s != "":
            blocks.append((bs + 1, i + 1, bc, lines[bs].strip()[:80]))
            bc = 0
            bs = None

if bc > 0 and bs is not None:
    blocks.append((bs + 1, len(lines), bc, lines[bs].strip()[:80]))

blocks.sort(key=lambda x: -x[2])
total = sum(b[2] for b in blocks)
print(f"Total main-body locals: {total}")
print(f"\nTop 25 blocks:")
for st, en, c, f in blocks[:25]:
    print(f"  L{st}-L{en}: {c} locals  {f}")

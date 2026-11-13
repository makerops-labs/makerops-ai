"""Fail if any `<x>.launch(...)` call doesn't pass `share=False` literally.

smolagents' GradioUI.launch (like gradio's) can open a public *.gradio.live
tunnel; smolagents defaults share=True. Parses each tracked .py file's AST,
so comments, strings and formatting can't fool it.
"""

import ast
import subprocess
import sys

files = subprocess.run(["git", "ls-files", "*.py"], capture_output=True,
                       text=True, check=True).stdout.split()
bad = []
for path in files:
    try:
        tree = ast.parse(open(path, encoding="utf-8").read(), path)
    except SyntaxError as e:
        bad.append(f"{path}: unparseable ({e.msg})")
        continue
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "launch"):
            share = next((k.value for k in node.keywords if k.arg == "share"), None)
            if not (isinstance(share, ast.Constant) and share.value is False):
                bad.append(f"{path}:{node.lineno}: .launch() without share=False")
for line in bad:
    print(line)
sys.exit(1 if bad else 0)

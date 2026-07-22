"""Fix index.html to use actual unicode characters instead of literal escape sequences."""
import re

path = r"E:\Projects\RepoLens\static\index.html"

with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Replace literal \ud83d\udd0d with actual 🔍 (magnifying glass)
content = content.replace(r"\ud83d\udd0d", "\U0001f50d")
# Replace literal \u26a0\ufe0f with actual ⚠️ (warning sign)
content = content.replace(r"\u26a0\ufe0f", "\u26a0\ufe0f")
# Replace literal \u2014 with actual — (em dash)
content = content.replace(r"\u2014", "\u2014")

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("Fixed! Unicode characters replaced successfully.")

# Verify - count occurrences of literal escape sequences
lines = content.split("\n")
for i, line in enumerate(lines, 1):
    if r"\u" in line and "utf-8" not in line.lower() and "encoding" not in line.lower():
        print(f"  WARNING: Line {i} still has literal \\u: {line.strip()[:80]}")
print("Done.")

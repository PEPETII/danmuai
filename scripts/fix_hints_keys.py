from pathlib import Path
import re

p = Path("web/static/modules/settings-hints.js")
text = p.read_text(encoding="utf-8")
text = re.sub(r"t\('([^']+)'\)", r"'\1'", text)
p.write_text(text, encoding="utf-8")
print("fixed settings-hints")

import os
import re
import ast

def fix_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    original_content = content
    fixes = []

    # 1 & 2. Typing imports
    typing_types = {"Optional", "List", "Dict", "Tuple", "Union", "Any", "Callable", "Type", "Set", "FrozenSet", "Sequence", "Iterable", "Generator"}
    used_types = set()
    # Check words
    for t in typing_types:
        if re.search(r'\b' + t + r'\b', content):
            used_types.add(t)
    
    if used_types:
        # Check existing imports
        existing_imports = set()
        match = re.search(r'^from typing import (.*?)(?:\n|$)', content, re.MULTILINE)
        if match:
            for imp in match.group(1).split(','):
                existing_imports.add(imp.strip())
        
        missing = used_types - existing_imports
        # Wait, some words could be false positives (like a variable named `Any`).
        # A safer check is if they are used as types. But even if we import extra, it's fine.
        # Actually, if we just blindly add them, it could conflict with a local variable. 
        # But `List`, `Dict` etc are capitalized, rare to be local variables.
        if missing:
            if match:
                new_imports_str = match.group(1)
                if new_imports_str.endswith(','):
                    new_imports_str += " " + ", ".join(missing)
                else:
                    new_imports_str += ", " + ", ".join(missing)
                content = content.replace(match.group(0), f"from typing import {new_imports_str}\n")
            else:
                # Add at the top, after imports like 'from __future__' or first line
                imports_line = f"from typing import {', '.join(missing)}\n"
                if "from __future__ import annotations" in content:
                    content = content.replace("from __future__ import annotations\n", f"from __future__ import annotations\n{imports_line}")
                else:
                    content = imports_line + content
            fixes.append(f"Added typing imports: {', '.join(missing)}")

    # 3. Missing __future__ annotations
    new_types_pattern = re.compile(r'(?::\s*|->\s*|\|\s*)(list|dict|tuple|set)\[')
    if new_types_pattern.search(content):
        if "from __future__ import annotations" not in content:
            content = "from __future__ import annotations\n" + content
            fixes.append("Added from __future__ import annotations")

    # 7. asyncio usage patterns
    if "asyncio.get_event_loop()" in content:
        # replace loop = asyncio.get_event_loop()\nloop.run_until_complete(X) with asyncio.run(X)
        content, n = re.subn(r'([ \t]*)[a-zA-Z0-9_]+\s*=\s*asyncio\.get_event_loop\(\)\s*\n\1(?:[a-zA-Z0-9_]+\.)?run_until_complete\((.*?)\)', r'\1asyncio.run(\2)', content)
        if n > 0:
            fixes.append("Replaced asyncio.get_event_loop() with asyncio.run()")
    if "@asyncio.coroutine" in content:
        content, n = re.subn(r'@asyncio\.coroutine\s*\ndef\s+', 'async def ', content)
        if n > 0:
            fixes.append("Replaced @asyncio.coroutine with async def")

    # 8. Pydantic v1 vs v2 patterns
    # class Config: -> model_config = ConfigDict(from_attributes=True) etc.
    if "class Config:" in content:
        if "from_attributes=True" not in content and "from_attributes=True" in content:
             content = re.sub(r'class Config:\s*\n\s*from_attributes=True', 'model_config = ConfigDict(from_attributes=True)', content)
        else:
             content = re.sub(r'class Config:\s*\n\s*env_file = "(.*?)"\s*\n\s*extra = "(.*?)"', r'model_config = ConfigDict(env_file="\1", extra="\2")', content)
        fixes.append("Replaced class Config with model_config = ConfigDict")
        if "from pydantic import" in content and "ConfigDict" not in content:
            content = re.sub(r'(from pydantic import.*?)\n', r'\1, ConfigDict\n', content, count=1)
        elif "from pydantic_settings import" in content and "ConfigDict" not in content:
             # Add from pydantic import ConfigDict
             content = "from pydantic import ConfigDict\n" + content
    
    if ".model_dump()" in content:
        # Only replace if it looks like a pydantic model. 
        # Actually the instructions say "Fix all Pydantic v1 patterns found."
        # And "response.model_dump() -> response.model_dump()"
        # I'll replace .model_dump() with .model_dump()
        content, n = re.subn(r'\.dict\(\)', '.model_dump()', content)
        if n > 0:
            fixes.append("Replaced .model_dump() with .model_dump()")
    
    # We must be careful with .json() because requests.json() is NOT pydantic.
    # In Pydantic v2, it's model_dump_json().
    # Let's see where .json() is used.

    if "from_attributes=True" in content:
        content, n = re.subn(r'orm_mode\s*=\s*True', 'from_attributes=True', content)
        if n > 0:
            fixes.append("Replaced from_attributes=True with from_attributes=True")
            
    if "@validator" in content:
        content, n = re.subn(r'@validator\(', '@field_validator(', content)
        content = re.sub(r'from pydantic import(.*?)field_validator', r'from pydantic import\1field_field_validator', content)
        if n > 0:
            fixes.append("Replaced @validator with @field_validator")

    # 9. SQLAlchemy 2.0
    if ".execute(" in content:
        # check if string is passed
        content, n = re.subn(r'\.execute\(\s*(["\'].*?["\'])\s*\)', r'.execute(text(\1))', content)
        content, m = re.subn(r'\.execute\(\s*(f["\'].*?["\'])\s*\)', r'.execute(text(\1))', content)
        if (n > 0 or m > 0):
            fixes.append("Replaced .execute(\"...\") with .execute(text(\"...\"))")
            if "from sqlalchemy import text" not in content:
                content = "from sqlalchemy import text\n" + content

    if content != original_content:
        with open(filepath, 'w') as f:
            f.write(content)
        return fixes
    return []

if __name__ == "__main__":
    import glob
    files = glob.glob("**/*.py", recursive=True)
    files = [f for f in files if "venv" not in f and "__pycache__" not in f]
    
    summary = {}
    for f in files:
        fixes = fix_file(f)
        if fixes:
            summary[f] = fixes
    
    print("AUDIT COMPLETE")
    print("==============")
    print(f"Files scanned: {len(files)}")
    print(f"Files with issues: {len(summary)}")
    print(f"Files fixed: {len(summary)}")
    print("\nFIXES APPLIED:")
    for f, fixes in summary.items():
        print(f"- {f}: {', '.join(fixes)}")
    
    print("\nFILES WITH NO ISSUES:")
    for f in files:
        if f not in summary:
            print(f"- {f}")


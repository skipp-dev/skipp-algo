#!/usr/bin/env python3
"""Deep audit script — checks session_state, widget keys, API key exposure,
unsafe_allow_html, hardcoded tickers, unbounded caches, etc."""
import ast
import os
import re
import sys
from collections import Counter, defaultdict

EXCLUDE_DIRS = {'.venv', '__pycache__', '.git', 'node_modules', 'artifacts'}

def collect_py_files():
    files = []
    for root, dirs, fnames in os.walk('.'):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in fnames:
            if f.endswith('.py') and f != '_deep_audit.py':
                files.append(os.path.join(root, f))
    return sorted(files)

def audit_session_state(files):
    """Find direct session_state[key] reads without .get() or setdefault()."""
    issues = []
    # Pattern: st.session_state["key"] or st.session_state['key'] used for reading (not assignment)
    # We look for bare bracket access that is NOT on the left side of =
    pat_bracket = re.compile(r'st\.session_state\[(["\'][^"\']+["\'])\]')
    pat_set = re.compile(r'st\.session_state\[(["\'][^"\']+["\'])\]\s*=')
    pat_get = re.compile(r'st\.session_state\.get\(')
    pat_setdefault = re.compile(r'st\.session_state\.setdefault\(')
    
    for f in files:
        for i, line in enumerate(open(f), 1):
            stripped = line.strip()
            if stripped.startswith('#'):
                continue
            # Find bracket reads that aren't assignments
            bracket_matches = pat_bracket.findall(line)
            set_matches = pat_set.findall(line)
            for key in bracket_matches:
                if key not in set_matches:
                    # This is a read via bracket — check if there's a prior setdefault
                    # For now, flag it
                    if 'if ' in line and 'in st.session_state' in line:
                        continue  # guarded by "if key in st.session_state"
                    if '.pop(' in line:
                        continue
                    if 'del ' in line:
                        continue
                    issues.append(f"  SESSION_READ  {f}:{i} — bare st.session_state[{key}] (may crash if key missing)")
    return issues

def audit_widget_keys(files):
    """Find duplicate widget key= values and widgets in loops without unique keys."""
    issues = []
    key_locations = defaultdict(list)
    # Pattern for key="..." in widget calls
    pat_key = re.compile(r'key\s*=\s*["\']([^"\']+)["\']')
    pat_key_fstr = re.compile(r'key\s*=\s*f["\']([^"\']+)["\']')
    
    for f in files:
        in_loop = False
        loop_depth = 0
        for i, line in enumerate(open(f), 1):
            stripped = line.strip()
            indent = len(line) - len(line.lstrip())
            
            if stripped.startswith('for ') or stripped.startswith('while '):
                in_loop = True
                loop_depth = indent
            elif in_loop and indent <= loop_depth and stripped and not stripped.startswith('#'):
                in_loop = False
            
            # Check for static keys inside loops
            if in_loop:
                static_keys = pat_key.findall(line)
                fstr_keys = pat_key_fstr.findall(line)
                for k in static_keys:
                    if k not in [fk for fk in fstr_keys] and '{' not in k:
                        if any(w in line for w in ['st.button', 'st.toggle', 'st.selectbox', 'st.checkbox', 
                                                     'st.text_input', 'st.number_input', 'st.slider',
                                                     'st.radio', 'st.multiselect', 'st.text_area']):
                            issues.append(f"  WIDGET_LOOP  {f}:{i} — static key=\"{k}\" inside loop (will crash on 2nd iteration)")
            
            # Collect all keys for duplicate detection
            for k in pat_key.findall(line):
                if '{' not in k:  # skip f-string keys
                    key_locations[k].append(f"{f}:{i}")
    
    # Check for duplicates
    for k, locs in key_locations.items():
        if len(locs) > 1:
            # Filter: same file same key is likely intentional (different branches)
            unique_files = set(loc.rsplit(':', 1)[0] for loc in locs)
            if len(unique_files) == 1 and len(locs) <= 2:
                continue  # Likely if/else branches
            issues.append(f"  DUP_KEY  key=\"{k}\" appears {len(locs)} times: {', '.join(locs[:5])}")
    
    return issues

def audit_api_key_exposure(files):
    """Find API keys being logged, displayed, or exposed in error messages."""
    issues = []
    key_vars = ['api_key', 'fmp_api_key', 'benzinga_api_key', 'finnhub_key', 'openai_api_key',
                'OPENAI_API_KEY', 'FMP_API_KEY', 'BENZINGA_API_KEY', 'FINNHUB_KEY', 'newsapi_key']
    
    for f in files:
        for i, line in enumerate(open(f), 1):
            stripped = line.strip()
            if stripped.startswith('#'):
                continue
            for kv in key_vars:
                if kv in line:
                    # Check if it's being logged/displayed
                    if any(p in line for p in ['st.write(', 'st.text(', 'st.code(', 'st.markdown(',
                                                 'st.error(', 'st.warning(', 'st.info(',
                                                 'print(', 'logger.info(', 'logger.warning(',
                                                 'logger.error(', 'logger.debug(']):
                        # Check if the key variable itself is in the output (not just checking "if key")
                        if f'({kv})' in line or f', {kv})' in line or f'{{{kv}}}' in line:
                            issues.append(f"  API_EXPOSE  {f}:{i} — {kv} may be exposed in output: {stripped[:100]}")
    return issues

def audit_unsafe_html(files):
    """Find unsafe_allow_html=True usages."""
    issues = []
    for f in files:
        for i, line in enumerate(open(f), 1):
            if 'unsafe_allow_html' in line and 'True' in line:
                stripped = line.strip()
                issues.append(f"  UNSAFE_HTML  {f}:{i} — {stripped[:120]}")
    return issues

def audit_hardcoded_tickers(files):
    """Find hardcoded ticker symbols that might be stale."""
    issues = []
    # Known problematic tickers
    stale_tickers = {'TWTR', 'FB', 'XLNX', 'ATVI', 'SIVB', 'FRC', 'SBNY'}
    
    for f in files:
        for i, line in enumerate(open(f), 1):
            for ticker in stale_tickers:
                if re.search(r'\b' + ticker + r'\b', line) and not line.strip().startswith('#'):
                    issues.append(f"  STALE_TICKER  {f}:{i} — hardcoded '{ticker}' may be delisted")
    return issues

def audit_unbounded_growth(files):
    """Find append/extend on session_state lists or module-level lists without bounds."""
    issues = []
    for f in files:
        for i, line in enumerate(open(f), 1):
            stripped = line.strip()
            if stripped.startswith('#'):
                continue
            # session_state list append without trim
            if 'session_state' in line and '.append(' in line:
                issues.append(f"  UNBOUNDED  {f}:{i} — session_state list .append() — check if bounded: {stripped[:100]}")
            # Module-level list/dict that grows
            if '.extend(' in line and 'session_state' in line:
                issues.append(f"  UNBOUNDED  {f}:{i} — session_state .extend() — check if bounded: {stripped[:100]}")
    return issues

def audit_bare_index(files):
    """Find bare [0] or [key] access on API responses without length/existence checks."""
    issues = []
    # Look for patterns like: response[0], data["key"], result[0]
    pat = re.compile(r'(?:response|result|data|json|body|resp|res)\[(?:0|["\'])')
    
    for f in files:
        for i, line in enumerate(open(f), 1):
            stripped = line.strip()
            if stripped.startswith('#'):
                continue
            if pat.search(line):
                # Check if there's a prior length check or try/except context
                if 'if ' not in line and '.get(' not in line:
                    issues.append(f"  BARE_INDEX  {f}:{i} — potential unchecked index access: {stripped[:100]}")
    return issues

def audit_file_io_paths(files):
    """Find file I/O where paths might be influenced by user input."""
    issues = []
    for f in files:
        for i, line in enumerate(open(f), 1):
            stripped = line.strip()
            if stripped.startswith('#'):
                continue
            # open() with f-string or format
            if 'open(' in line and ('{' in line or '.format(' in line or '+' in line):
                if 'encoding' in line or 'mode' in line or 'open(' in line:
                    issues.append(f"  FILE_PATH  {f}:{i} — dynamic file path in open(): {stripped[:100]}")
    return issues

def audit_manual_session_state_widget(files):
    """Find widgets that manually assign to session_state instead of using key=."""
    issues = []
    widget_funcs = ['st.toggle', 'st.selectbox', 'st.checkbox', 'st.text_input', 
                    'st.number_input', 'st.slider', 'st.radio', 'st.multiselect']
    for f in files:
        lines = open(f).readlines()
        for i, line in enumerate(lines, 1):
            for w in widget_funcs:
                if w + '(' in line:
                    # Check if next 3 lines have session_state assignment
                    context = ''.join(lines[i:i+3]) if i < len(lines) else ''
                    if 'session_state[' in context and '=' in context:
                        issues.append(f"  MANUAL_STATE  {f}:{i} — {w} result manually assigned to session_state (use key= instead)")
    return issues

def audit_thread_safety(files):
    """Find shared mutable state accessed from background threads."""
    issues = []
    # Look for global/module-level mutable structures
    for f in files:
        lines = open(f).readlines()
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            # Module-level mutable assignments
            indent = len(line) - len(line.lstrip())
            if indent == 0 and not stripped.startswith('#') and not stripped.startswith('def ') and not stripped.startswith('class '):
                if re.match(r'^[A-Z_]+\s*[:=]\s*(dict|list|\{|\[)', stripped):
                    # Check if this module has threading
                    full_text = ''.join(lines)
                    if 'threading' in full_text or 'Thread(' in full_text or 'background' in full_text.lower():
                        issues.append(f"  THREAD  {f}:{i} — module-level mutable {stripped[:60]} in file with threading")
    return issues

def main():
    files = collect_py_files()
    print(f"Auditing {len(files)} Python files...\n")
    
    all_issues = []
    
    checks = [
        ("Session State Bare Reads", audit_session_state),
        ("Widget Key Issues", audit_widget_keys),
        ("API Key Exposure", audit_api_key_exposure),
        ("Unsafe HTML", audit_unsafe_html),
        ("Stale Tickers", audit_hardcoded_tickers),
        ("Unbounded Growth", audit_unbounded_growth),
        ("Bare Index Access", audit_bare_index),
        ("File Path Safety", audit_file_io_paths),
        ("Manual Session State Widgets", audit_manual_session_state_widget),
        ("Thread Safety", audit_thread_safety),
    ]
    
    for name, fn in checks:
        issues = fn(files)
        if issues:
            print(f"{'='*60}")
            print(f"  {name} — {len(issues)} finding(s)")
            print(f"{'='*60}")
            for issue in issues:
                print(issue)
            print()
        else:
            print(f"✓ {name} — clean")
        all_issues.extend(issues)
    
    print(f"\n{'='*60}")
    print(f"TOTAL: {len(all_issues)} finding(s) across {len(files)} files")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Structural gate for the Master Trove opt-in forms.

Every check here exists because the defect it catches actually shipped. The
expensive one was invisible for weeks: the confirmation block was nested inside
the step container that gets hidden on submit, so a lead submitted the form and
watched it vanish into an empty card. Generation worked the whole time, so
nothing downstream ever flagged it.

Run:  python3 scripts/audit_forms.py [file ...]     (defaults to all four forms)
Exit: 0 all clear, 1 at least one FAIL.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATES = ('processingState', 'errorState', 'successState')
TAG = re.compile(r'<div\b[^>]*>|</div>', re.I)

failures = 0
notes = 0


def fail(f, msg, detail=''):
    global failures
    failures += 1
    print(f"  [FAIL] {f:16} {msg}" + (f"  {detail}" if detail else ''))


def warn(f, msg, detail=''):
    global notes
    notes += 1
    print(f"  [warn] {f:16} {msg}" + (f"  {detail}" if detail else ''))


def ok(f, msg):
    print(f"  [ ok ] {f:16} {msg}")


def div_balance(src):
    """Return (unclosed, strays) as lists of (line, label) / line."""
    stack, strays = [], []
    for m in TAG.finditer(src):
        line = src[:m.start()].count('\n') + 1
        if m.group(0).startswith('</'):
            stack.pop() if stack else strays.append(line)
        else:
            i = re.search(r'id="([^"]+)"', m.group(0))
            c = re.search(r'class="([^"]+)"', m.group(0))
            stack.append((line, i.group(1) if i else (c.group(1) if c else 'div')))
    return stack, strays


def span(src, start):
    depth = 0
    for m in TAG.finditer(src, start):
        depth += -1 if m.group(0).startswith('</') else 1
        if depth == 0:
            return start, m.end()
    return start, len(src)


def check(path):
    name = path.parts[-3]
    src = path.read_text()

    # 1. Unbalanced tags make every other structural check unreliable, and they
    #    are what let the browser silently reparent the state blocks.
    unclosed, strays = div_balance(src)
    if unclosed or strays:
        fail(name, 'div tags unbalanced',
             f"unclosed={[f'{w}@{l}' for l, w in unclosed]} stray_close_at={strays}")
    else:
        ok(name, 'div tags balanced')

    # 2. THE one that shipped: a state block inside a step container can never
    #    paint, because submitting hides that container.
    bad = []
    for m in re.finditer(r'<div\b[^>]*class="[^"]*form-tab-content[^"]*"[^>]*>', src):
        s, e = span(src, m.start())
        sid = re.search(r'id="([^"]+)"', m.group(0))
        for st in STATES:
            hit = re.search(r'id="%s"' % st, src)
            if hit and s < hit.start() < e:
                bad.append(f"{st} inside #{sid.group(1) if sid else '?'}")
    if bad:
        fail(name, 'state block nested in a step container', '; '.join(bad))
    else:
        ok(name, 'state blocks are outside the step containers')

    # 3. Dead JS references - a form can look perfect and be inert.
    missing = [i for i in sorted(set(re.findall(r"getElementById\('([^']+)'\)", src)))
               if f'id="{i}"' not in src]
    if missing:
        warn(name, 'getElementById targets that do not exist', ' '.join(missing))
    else:
        ok(name, 'every getElementById target exists')

    # 4. The submit label lives in two places. Changing only the HTML makes an
    #    errored form silently revert to the old wording.
    html_label = re.search(r'<button[^>]*onclick="generateTrove\(\)"[^>]*>([^<]*)<', src)
    js_labels = [x for x in re.findall(r"submitButton\.textContent\s*=\s*'([^']*)'", src)
                 if 'Generating' not in x]
    if html_label and js_labels:
        h = html_label.group(1).strip()
        if any(j.strip() != h for j in js_labels):
            fail(name, 'button label differs between HTML and the JS restore',
                 f"html={h!r} js={js_labels!r}")
        else:
            ok(name, 'button label matches its JS restore string')

    # 5. required= is decorative here (submit is type=button with no
    #    checkValidity), so it must never be the only thing marking a field.
    if re.search(r'<input[^>]*id="phone"[^>]*required', src):
        fail(name, 'phone is marked required', 'it must stay optional')
    else:
        ok(name, 'phone is not required')

    # 6. Every state transition must reset scroll, or a long step collapsing to
    #    a short confirmation leaves the viewport on blank page.
    transitions = len(re.findall(r"getElementById\('(?:%s)'\)" % '|'.join(STATES), src))
    scrolls = len(re.findall(r'window\.scrollTo\(', src))
    if transitions and scrolls < 3:
        warn(name, 'fewer than 3 scrollTo calls', f'{scrolls} found')
    else:
        ok(name, 'state changes reset scroll')


def main():
    args = sys.argv[1:]
    files = [pathlib.Path(a).resolve() for a in args] if args else sorted(
        ROOT.glob('tools/*/master-trove/index.html'))
    files = [f for f in files if f.exists() and 'master-trove' in str(f)]
    if not files:
        print('no opt-in forms matched; nothing to check')
        return 0
    print(f'Auditing {len(files)} opt-in form(s)\n')
    for f in files:
        check(f)
        print()
    print(f'{failures} failures, {notes} warnings')
    if failures:
        print('Fix the FAILs before pushing - each one has shipped to a customer before.')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())

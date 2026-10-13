"""Check navigation, static assets and route ownership without importing the app."""
from __future__ import annotations

import ast
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def local_target(owner: Path, reference: str) -> Path | None:
    reference = reference.strip('<>')
    parsed = urlsplit(reference)
    if parsed.scheme or parsed.netloc or not parsed.path:
        return None
    return (owner.parent / unquote(parsed.path)).resolve()


def verify_navigation() -> int:
    documents = {ROOT / 'AGENTS.md'}
    for directory in ('core', 'routes', 'scripts', 'static'):
        documents.update((ROOT / directory).rglob('AGENTS.md'))
    documents.update(ROOT / 'docs' / name for name in (
        'README.md', 'SERVER_RULES_INDEX.md', 'PROJECT_FUNCTIONS_AND_LOGIC.md',
        'CODE_FLOW_MAP.md', 'LOGIC_DECISION_LEDGER.md', 'isolated-design-server.md',
    ))
    count = 0
    anchors = {}
    failures = []
    for document in sorted(documents):
        content = document.read_text(encoding='utf-8')
        for reference in re.findall(r'\[[^\]]+\]\((<?[^\s)]+>?)\)', content):
            target = local_target(document, reference)
            parsed = urlsplit(reference.strip('<>'))
            if target is None and parsed.fragment and not parsed.scheme and not parsed.netloc:
                target = document
            if target is None:
                continue
            assert target.is_relative_to(ROOT), f'Navigation escapes repository: {document.name}: {reference}'
            assert target.exists(), f'Broken navigation: {document.relative_to(ROOT)}: {reference}'
            if parsed.fragment and target.suffix == '.md':
                if target not in anchors:
                    text = target.read_text(encoding='utf-8')
                    present = set(re.findall(r'<a\s+[^>]*(?:id|name)=["\']([^"\']+)["\']', text))
                    seen = defaultdict(int)
                    for heading in re.findall(r'^#{1,6}\s+(.+?)\s*#*$', text, re.MULTILINE):
                        heading = re.sub(r'<[^>]+>', '', heading)
                        heading = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', heading)
                        slug = ''.join(char for char in heading.lower() if char.isalnum() or char in '-_' or char.isspace()).replace(' ', '-')
                        suffix = f'-{seen[slug]}' if seen[slug] else ''
                        present.add(slug + suffix)
                        seen[slug] += 1
                    anchors[target] = present
                if unquote(parsed.fragment) not in anchors[target]:
                    failures.append(f'{document.relative_to(ROOT)}: {reference}')
            count += 1
    assert not failures, 'Broken Markdown anchors:\n' + '\n'.join(failures)
    assert (ROOT / 'AGENTS.md').stat().st_size < 32 * 1024, 'AGENTS.md exceeds 32 KiB'
    return count


class AssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets: list[str] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        reference = attributes.get('src') if tag == 'script' else (
            attributes.get('href') if tag == 'link' and attributes.get('rel') == 'stylesheet' else None
        )
        if reference:
            self.assets.append(reference)


def verify_assets() -> int:
    count = 0
    static = ROOT / 'static'
    for shell in sorted(static.glob('*.html')):
        parser = AssetParser()
        parser.feed(shell.read_text(encoding='utf-8'))
        for reference in parser.assets:
            parsed = urlsplit(reference)
            if parsed.scheme or parsed.netloc:
                continue
            asset = (static / unquote(parsed.path).lstrip('/')) if parsed.path.startswith('/') else (shell.parent / unquote(parsed.path))
            asset = asset.resolve()
            assert asset.is_relative_to(static), f'Asset escapes static root: {shell.name}: {reference}'
            assert asset.is_file(), f'Missing asset: {shell.name}: {reference}'
            count += 1
    for module in sorted(static.rglob('*.js')):
        source = module.read_text(encoding='utf-8')
        references = re.findall(r'^import\s+[\s\S]*?\sfrom\s+["\']([^"\']+)["\'];', source, re.MULTILINE)
        references += re.findall(r'\bimport\(\s*["\']([^"\']+)["\']\s*\)', source)
        for reference in references:
            parsed = urlsplit(reference)
            if parsed.scheme or parsed.netloc:
                continue
            imported = (static / unquote(parsed.path).lstrip('/')) if parsed.path.startswith('/') else (module.parent / unquote(parsed.path))
            imported = imported.resolve()
            assert imported.is_relative_to(static), f'Import escapes static root: {module.relative_to(static)}: {reference}'
            assert imported.is_file(), f'Missing imported module: {module.relative_to(static)}: {reference}'
            count += 1
    return count


def verify_route_owners() -> int:
    app_tree = ast.parse((ROOT / 'app.py').read_text(encoding='utf-8'))
    registered = {node.args[0].id for node in ast.walk(app_tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                  and node.func.attr == 'register_blueprint' and node.args and isinstance(node.args[0], ast.Name)}
    owners = defaultdict(list)
    for source in sorted((ROOT / 'routes').glob('*.py')):
        tree = ast.parse(source.read_text(encoding='utf-8'))
        prefixes = {}
        for node in tree.body:
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                continue
            if not isinstance(node.value.func, ast.Name) or node.value.func.id != 'Blueprint':
                continue
            prefix = next((ast.literal_eval(item.value) for item in node.value.keywords if item.arg == 'url_prefix'), '')
            for target in node.targets:
                if isinstance(target, ast.Name):
                    prefixes[target.id] = prefix
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                    continue
                if not isinstance(decorator.func.value, ast.Name) or decorator.func.value.id not in registered:
                    continue
                method = decorator.func.attr
                if method not in {'route', 'get', 'post', 'patch', 'put', 'delete'} or not decorator.args:
                    continue
                if not isinstance(decorator.args[0], ast.Constant) or not isinstance(decorator.args[0].value, str):
                    continue
                methods = [method.upper()] if method != 'route' else next(
                    (ast.literal_eval(item.value) for item in decorator.keywords if item.arg == 'methods'), ['GET'])
                url = prefixes.get(decorator.func.value.id, '') + decorator.args[0].value
                for verb in methods:
                    owners[(verb.upper(), url)].append(source.name)
    duplicates = {key: value for key, value in owners.items() if len(value) != 1}
    assert not duplicates, f'Duplicate registered routes: {duplicates}'
    for method, url, source in (
        ('GET', '/api/students', 'api_students.py'), ('POST', '/api/update', 'api_students.py'),
        ('GET', '/api/student/bootstrap', 'api_student_bootstrap.py'),
        ('GET', '/api/updates', 'api_updates.py'), ('POST', '/api/updates/patch', 'api_updates.py'),
        ('GET', '/api/logs', 'api_logs.py'), ('POST', '/api/logs/patch', 'api_logs.py'),
        ('GET', '/api/materials', 'api_materials.py'), ('POST', '/api/mat-assign', 'api_materials.py'),
        ('GET', '/api/school-calendar', 'api_school_calendar.py'),
    ):
        assert owners[(method, url)] == [source], f'Owner drift: {method} {url}: {owners[(method, url)]}'
    for url in ['/api/students', '/api/materials', '/api/logs']:
        assert ('POST', url) not in owners, f'Retired collection write restored: {url}'
    assert not any(url == '/api/fs/page-folders' for _, url in owners), 'Retired page-folders route restored'
    return len(owners)


def verify():
    counts = (verify_navigation(), verify_assets(), verify_route_owners())
    print(f'Static repository contracts passed: {counts[0]} navigation links, {counts[1]} shell/module assets, {counts[2]} route/method owners; no app/runtime imports')


if __name__ == '__main__':
    verify()

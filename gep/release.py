"""Closed-file-list reference releases; raw licensed documents stay local."""
import hashlib
import json
import re
import shutil
from pathlib import Path

MANIFEST = 'manifest.json'
ALLOWED = {'.md', '.json', '.csv', '.sha256', '.txt'}
SECRET = re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|ms-[a-fA-F0-9]{8}-[a-fA-F0-9-]{27,})')


def _files(root):
    root = Path(root)
    result = {}
    for p in sorted(root.rglob('*')):
        if p.is_symlink():
            raise ValueError('symlinks cannot enter a release')
        if p.is_dir():
            continue
        relative = p.relative_to(root).as_posix()
        if any(part.startswith('.') for part in p.relative_to(root).parts) or p.suffix not in ALLOWED:
            raise ValueError(f'disallowed release file: {relative}')
        body = p.read_bytes()
        if SECRET.search(body):
            raise ValueError(f'credential pattern found in {relative}')
        if relative != MANIFEST:
            result[relative] = {'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body)}
    return result


def seal(root, release_id):
    root = Path(root)
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]*', release_id):
        raise ValueError('invalid release ID')
    files = _files(root)
    if not files:
        raise ValueError('empty release')
    manifest = {'schema_version': 1, 'release_id': release_id, 'scope': 'reference_only',
                'accounting_ready': False, 'files': files}
    with (root / MANIFEST).open('x', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write('\n')
    return manifest


def verify(root):
    try:
        root = Path(root)
        if (root / MANIFEST).is_symlink():
            raise ValueError('manifest cannot be a symlink')
        manifest = json.loads((root / MANIFEST).read_text())
        if (manifest.get('schema_version') != 1 or manifest.get('accounting_ready') is not False
                or manifest.get('scope') != 'reference_only'
                or not isinstance(manifest.get('release_id'), str)
                or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]*', manifest['release_id'])):
            raise ValueError('unsupported release schema/scope')
        files = _files(root)
        if files != manifest['files']:
            raise ValueError('file set, size or SHA-256 differs from sealed manifest')
        if not files:
            raise ValueError('empty release')
        return {'valid': True, 'release_id': manifest['release_id'], 'file_count': len(files),
                'manifest_sha256': hashlib.sha256((root / MANIFEST).read_bytes()).hexdigest()}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {'valid': False, 'errors': [str(exc)]}


def upload(root, repo_id, token):
    """Create a new path, never sync-delete; download every file to verify transfer."""
    import tempfile
    from modelscope_hub import HubApi
    root = Path(root)
    report = verify(root)
    if not report['valid']:
        raise ValueError('release validation failed')
    manifest = json.loads((root / MANIFEST).read_text())
    expected = {**manifest['files'], MANIFEST: {'sha256': report['manifest_sha256']}}
    prefix = 'releases/' + report['release_id']
    # Only the reviewed snapshot is passed to the SDK. Files subsequently added
    # to the user's working directory cannot enter this release.
    with tempfile.TemporaryDirectory(prefix='gep-publish-') as tmp:
        snapshot = Path(tmp) / 'snapshot'
        snapshot.mkdir()
        for name in expected:
            destination = snapshot / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / name, destination)
        if not verify(snapshot)['valid']:
            raise ValueError('release changed while snapshot was created')
        if hashlib.sha256((snapshot / MANIFEST).read_bytes()).hexdigest() != report['manifest_sha256']:
            raise ValueError('manifest changed while snapshot was created')
        api = HubApi(token=token)
        remote_files = api.list_repo_files(repo_id, 'dataset', recursive=True)
        if any(f.path == prefix or f.path.startswith(prefix + '/') for f in remote_files):
            raise ValueError('remote release path already exists; use a new release ID')
        result = api.upload_folder(repo_id, 'dataset', snapshot, path_in_repo=prefix,
                                   commit_message=f'Add reviewed reference release {report["release_id"]}',
                                   allow_patterns=list(expected), use_cache=False,
                                   sync_remote_repo=False, disable_tqdm=True)
        remote_paths = {f.path for f in api.list_repo_files(repo_id, 'dataset', recursive=True)
                        if f.path.startswith(prefix + '/') and f.type != 'tree'}
        if remote_paths != {prefix + '/' + name for name in expected}:
            raise ValueError('remote release file set differs from manifest')
        for name, meta in expected.items():
            local = api.download_file(repo_id, 'dataset', prefix + '/' + name,
                                      local_dir=Path(tmp) / 'roundtrip', force=True)
            if hashlib.sha256(Path(local).read_bytes()).hexdigest() != meta['sha256']:
                raise ValueError(f'remote roundtrip hash mismatch: {name}')
    commit_ids = []
    def collect_commits(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key.lower().replace('_', '') in {'commitid', 'oid', 'sha'} and isinstance(item, str):
                    commit_ids.append(item)
                elif isinstance(item, (dict, list)):
                    collect_commits(item)
        elif isinstance(value, list):
            for item in value:
                collect_commits(item)
    collect_commits(result)
    return {'repo_id': repo_id, 'path': prefix, 'verified_files': len(expected),
            'manifest_sha256': report['manifest_sha256'], 'roundtrip_verified': True,
            'commit_ids': list(dict.fromkeys(commit_ids))}

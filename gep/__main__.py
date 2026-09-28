import argparse
import json
import os
from pathlib import Path
from . import catalog, workflow, release, fetch
from .server import serve
from .worker import SupplementWorker
from .smart_data.assets import scan_known_assets
from .task_service import GepStore


def main():
    p = argparse.ArgumentParser(description='Haidian reference-data workbench; no complete GEP total yet')
    sub = p.add_subparsers(dest='command', required=True)
    for name in ('check', 'build'):
        s = sub.add_parser(name); s.add_argument('csv')
        if name == 'build': s.add_argument('--out', required=True)
    s = sub.add_parser('fetch'); s.add_argument('source', choices=fetch.SOURCES); s.add_argument('--root', required=True)
    s = sub.add_parser('example'); s.add_argument('--out', required=True)
    s = sub.add_parser('resolve'); s.add_argument('run'); s.add_argument('--input', required=True); s.add_argument('--out', required=True)
    s = sub.add_parser('approve'); s.add_argument('run'); s.add_argument('--reviewer', required=True); s.add_argument('--out', required=True)
    s = sub.add_parser('seal'); s.add_argument('folder'); s.add_argument('--id', required=True)
    s = sub.add_parser('verify-release'); s.add_argument('folder')
    s = sub.add_parser('upload'); s.add_argument('folder'); s.add_argument('--repo', default='WeijieWu/haidian_GEP')
    s = sub.add_parser('serve', help='run the local task API and Web canvas')
    s.add_argument('--database', required=True)
    s.add_argument('--host', default='127.0.0.1')
    s.add_argument('--port', type=int, default=8000)
    s = sub.add_parser('worker', help='process persisted supplement jobs without an HTTP server')
    s.add_argument('--database', required=True)
    s.add_argument('--once', action='store_true')
    s.add_argument('--poll-seconds', type=float, default=1.0)
    s = sub.add_parser('smart-data-scan', help='register known data assets in the task database')
    s.add_argument('--database', required=True)
    s.add_argument('--data-root', required=True)
    s.add_argument('--data-version', default='smart-data-2024-v1')
    s = sub.add_parser('smart-data-build', help='build large smart-data artifacts with optional spatial dependencies')
    s.add_argument('stage', choices=('aef',))
    s.add_argument('--data-root', required=True)
    s.add_argument('--boundary', required=True)
    s.add_argument('--year', type=int, default=2024)
    s.add_argument('--index')
    s.add_argument('--output-dir')
    args = p.parse_args()
    try:
        if args.command == 'serve':
            serve(args.host, args.port, args.database)
            return
        if args.command == 'worker':
            worker = SupplementWorker(args.database)
            if args.once:
                result = worker.run_once() or {'status': 'idle'}
            else:
                worker.run_forever(args.poll_seconds)
                return
        elif args.command == 'smart-data-scan':
            from .smart_data.observations import load_observation_manifest
            store = GepStore(args.database)
            try:
                assets = scan_known_assets(Path(args.data_root), args.data_version)
                registered = [store.smart_data.register_asset(asset) for asset in assets]
                manifest = Path(args.data_root) / 'catalog' / 'smart_data_observations_2024.json'
                observations = [store.smart_data.register_observation(item) for item in load_observation_manifest(manifest)] if manifest.is_file() else []
                result = {'registered_count': len(registered), 'asset_ids': [item['asset_id'] for item in registered],
                          'observation_count': len(observations)}
            finally:
                store.close()
        elif args.command == 'smart-data-build':
            from .smart_data.aef_pipeline import build_aef_subset, plan_aef_subset
            root = Path(args.data_root)
            boundary = json.loads(Path(args.boundary).read_text(encoding='utf-8'))
            indexes = [Path(args.index)] if args.index else sorted(root.glob('**/aef_index.parquet'))
            if len(indexes) != 1:
                raise ValueError('exactly one AEF index is required')
            output = Path(args.output_dir) if args.output_dir else root / '03_features' / 'alphaearth_2024'
            result = build_aef_subset(plan_aef_subset(indexes[0], boundary, args.year), output)
        elif args.command == 'check': result = catalog.check(args.csv)
        elif args.command == 'build':
            result = catalog.build(args.csv); workflow.save(result, args.out)
        elif args.command == 'fetch': result = fetch.download(args.source, args.root)
        elif args.command == 'example':
            result = workflow.new_example(); workflow.save(result, args.out)
        elif args.command in ('resolve', 'approve'):
            run = json.loads(Path(args.run).read_text())
            result = (workflow.resolve(run, 'fish', json.loads(Path(args.input).read_text()))
                      if args.command == 'resolve' else workflow.approve(run, 'fish', args.reviewer))
            workflow.save(result, args.out)
        elif args.command == 'seal': result = release.seal(args.folder, args.id)
        elif args.command == 'verify-release': result = release.verify(args.folder)
        else:
            token = os.environ.get('MODELSCOPE_TOKEN')
            if not token: raise ValueError('MODELSCOPE_TOKEN is required in the environment')
            result = release.upload(args.folder, args.repo, token)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        if result.get('valid') is False: raise SystemExit(1)
    except (ValueError, OSError, KeyError) as exc:
        p.exit(2, f'{type(exc).__name__}: {exc}\n')


if __name__ == '__main__':
    main()

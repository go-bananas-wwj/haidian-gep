import argparse
import json
import os
from pathlib import Path
from . import catalog, workflow, release, fetch


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
    args = p.parse_args()
    try:
        if args.command == 'check': result = catalog.check(args.csv)
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

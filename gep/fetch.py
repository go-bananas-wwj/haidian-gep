"""Public reference download with receipts; no credentials required."""
import hashlib
import json
import shutil
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SOURCES = {
    'yearbook': ('https://zyk.bjhd.gov.cn/jbdt/auto4514_51808/auto4514_54025/auto4514/auto4514_54045/auto4514_54047/202601/P020260106620799985028.zip', '01_raw/statistics/haidian_yearbook_2025.zip'),
    'aef-readme': ('https://data.source.coop/tge-labs/aef/README.md', '01_raw/methods/source_aef_README.md'),
    'aef-index': ('https://data.source.coop/tge-labs/aef/v1/annual/aef_index.parquet', '01_raw/remote_sensing/aef_index.parquet'),
}


def download(source, root):
    url, name = SOURCES[source]
    path = Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f'existing original: {path}')
    tmp = path.with_suffix(path.suffix + '.partial')
    with tmp.open('xb') as f:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'haidian-gep/0.1 (+https://github.com/go-bananas-wwj/haidian-gep)'}), timeout=90) as response:
            shutil.copyfileobj(response, f)
    digest = hashlib.sha256(tmp.read_bytes()).hexdigest()
    # Hard link refuses to overwrite an original created by another process.
    path.hardlink_to(tmp)
    tmp.unlink()
    receipt = {'source': source, 'url': url, 'path': name, 'bytes': path.stat().st_size,
               'sha256': digest, 'downloaded_utc': datetime.now(timezone.utc).isoformat(),
               'redistribution': 'review license before publication'}
    with path.with_suffix(path.suffix + '.receipt.json').open('x') as f:
        json.dump(receipt, f, ensure_ascii=False, indent=2)
    return receipt

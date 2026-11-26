"""Discover a local Folirina-style paired-image folder without copying its assets."""
from pathlib import Path
import csv

REQUIRED = {'pair_id', 'source_image', 'target_image', 'source_width', 'source_height',
            'target_width', 'target_height', 'matrix_3x3_json'}


def discover_bundle(path):
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError('请选择已解压的配准目录')
    # Accept the standard standalone folder and Folirina's images/ layout.
    matches = []
    for name in ('registration_pairs.csv', 'pairs.csv'):
        manifest = root / name
        if not manifest.is_file():
            continue
        for base in (root, root / 'images'):
            source, target = base / 'source', base / 'target'
            if source.is_dir() and target.is_dir():
                resolved = tuple(p.resolve() for p in (manifest, source, target))
                if not all(p.is_relative_to(root) for p in resolved):
                    raise ValueError('配准目录包含指向外部的路径')
                matches.append(resolved)
    if len(matches) != 1:
        raise ValueError('未找到唯一的配准清单与 source/target 目录；请选正确的解压目录，或手动浏览。')
    manifest, source, target = matches[0]
    with manifest.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        if not REQUIRED.issubset(reader.fieldnames or ()):
            raise ValueError('配准 CSV 缺少必要字段')
        ids = set()
        for row in reader:
            pid = (row.get('pair_id') or '').strip()
            if not pid or pid in ids:
                raise ValueError('配对编号为空或重复')
            ids.add(pid)
        if not ids:
            raise ValueError('配准清单没有图片配对')
    return manifest, source, target

"""Push the built dataset (dist/) to Hugging Face Datasets.

Run after `python -m src.build`. Needs a write token in the HF_TOKEN environment variable (or `huggingface-cli
login` done once); the token never touches this file or the repository.

    pip install huggingface_hub
    HF_TOKEN=hf_... python scripts/push_huggingface.py --repo realurls/verified-domains
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
FILES = ["README.md", "domains.txt", "domains.json", "entities.json", "registry.json", "manifest.json"]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo", required=True, help="dataset repo id, e.g. realurls/verified-domains")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    missing = [f for f in FILES if f != "README.md" and not (DIST / f).exists()]
    if missing:
        print(f"missing in dist/: {missing}; run `python -m src.build` first", file=sys.stderr)
        return 1
    version = json.loads((DIST / "manifest.json").read_text(encoding="utf-8"))["dataset_version"]
    # dist/ is generated and git-ignored; the dataset card lives next to this script and is copied in.
    (DIST / "README.md").write_text((ROOT / "scripts" / "huggingface_dataset_card.md").read_text(encoding="utf-8"), encoding="utf-8")
    if args.dry_run:
        print(f"would upload {FILES} to {args.repo} as dataset version {version}")
        return 0

    from huggingface_hub import HfApi
    api = HfApi()
    api.create_repo(args.repo, repo_type="dataset", exist_ok=True)
    api.upload_folder(
        repo_id=args.repo, repo_type="dataset", folder_path=str(DIST), allow_patterns=FILES,
        commit_message=f"dataset {version}",
    )
    print(f"uploaded dataset {version} to https://huggingface.co/datasets/{args.repo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

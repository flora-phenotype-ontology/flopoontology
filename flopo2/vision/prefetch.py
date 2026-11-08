"""Download pinned model artifacts before requesting a GPU allocation."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    from huggingface_hub import snapshot_download
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    specs = json.loads(args.models.read_text())
    manifest = {}
    for name, spec in specs.items():
        directory = args.out / name
        snapshot_download(spec["repository"], revision=spec["revision"], local_dir=directory,
            allow_patterns=["*.json", "*.txt", "*.model", "*.py", "*.safetensors", "README.md"], max_workers=4)
        hashes = {}
        for path in sorted(directory.iterdir()):
            if path.is_file():
                with path.open("rb") as handle:
                    hashes[path.name] = hashlib.file_digest(handle, "sha256").hexdigest()
        manifest[name] = {**spec, "files": hashes}
        print(f"Prepared {name}: {spec['revision']}", flush=True)
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()

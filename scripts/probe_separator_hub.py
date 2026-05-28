"""Probe HuggingFace Hub for live BS-Roformer / SCNet / MelBand checkpoints.

Prints (repo_id, downloads, license, files-with-.ckpt) so we can update
``fetch_sota_separator.py`` with real, working repos.
"""

from __future__ import annotations

from huggingface_hub import HfApi


QUERIES = [
    "BS-Roformer",
    "mel-band-roformer",
    "MelBandRoformer",
    "BSRoformer",
    "SCNet music separation",
    "audio-separator",
    "music source separation",
]


def main() -> None:
    api = HfApi()
    seen = set()
    for q in QUERIES:
        print(f"\n=== query: {q} ===")
        try:
            # huggingface-hub 1.x dropped the `direction` kwarg; the default
            # already sorts descending by downloads when sort="downloads".
            models = list(api.list_models(search=q, limit=12, sort="downloads"))
        except Exception as e:
            print(f"  ! query failed: {e}")
            continue
        for m in models:
            if m.id in seen:
                continue
            seen.add(m.id)
            try:
                info = api.model_info(m.id, files_metadata=False)
                ckpts = [s.rfilename for s in (info.siblings or [])
                         if s.rfilename.endswith((".ckpt", ".pth", ".pt"))]
                lic = getattr(info, "license", None) or getattr(m, "license", None)
                dl = m.downloads or 0
                print(f"  {m.id:55s} dl={dl:>8d}  lic={lic}")
                for c in ckpts[:6]:
                    print(f"      -> {c}")
            except Exception as e:
                print(f"  ! {m.id}: {e}")


if __name__ == "__main__":
    main()

"""AUX reference DB source fetchers.

Each module exposes ``fetch(out_dir: Path) -> list[ReferenceItem]`` that
downloads + renders the source into normalised wav clips with category
labels. ``build_aux_reference_db.py`` aggregates them all into a single
embedding bank.
"""

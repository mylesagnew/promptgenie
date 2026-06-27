"""artifact.py — build a prompt artifact (manifest + layers) from a spec/prompt.

An *artifact* is the content-addressable bundle the registry stores: every file
a prompt needs to run becomes a digest-named layer, described by a manifest with
a JSON config blob of prompt-level metadata.

``build_artifact`` enumerates layers from a PromptSpec's on-disk references
(spec file, template, policy, context files, output schema) or, for a Markdown
prompt, a single prompt layer. ``materialise`` reverses the process —
reconstructing the files under an output directory, guarded against path
traversal.

The layer set is intentionally limited to **concrete files**: glob / command /
URL context sources cannot be vendored as a single blob, so they are recorded in
the config metadata (``dynamic_context``) rather than materialised.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from promptgenie.core.errors import EXIT_USAGE, PromptGenieError
from promptgenie.core.registry_store import (
    CONFIG_MEDIA_TYPE,
    KIND_ANNOTATION,
    LAYER_MEDIA_TYPES,
    PATH_ANNOTATION,
    Descriptor,
    Manifest,
    RegistryError,
    compute_digest,
)

if TYPE_CHECKING:
    from promptgenie.core.registry_backend import RegistryStore

_SPEC_SUFFIXES = {".yaml", ".yml", ".json"}
_POLICY_NAMES = (".promptgenie.policy.yaml", "promptgenie.policy.yaml")


@dataclass
class Layer:
    kind: str
    rel_path: str
    data: bytes

    @property
    def descriptor(self) -> Descriptor:
        media = LAYER_MEDIA_TYPES.get(self.kind, "application/octet-stream")
        return Descriptor(
            media_type=media,
            digest=compute_digest(self.data),
            size=len(self.data),
            annotations={PATH_ANNOTATION: self.rel_path, KIND_ANNOTATION: self.kind},
        )


@dataclass
class ArtifactBundle:
    """An unpushed artifact: config + layers + manifest annotations."""

    config: dict
    layers: list[Layer]
    annotations: dict[str, str] = field(default_factory=dict)

    @property
    def config_bytes(self) -> bytes:
        return json.dumps(self.config, indent=2, sort_keys=True).encode("utf-8")

    def manifest(self) -> Manifest:
        data = self.config_bytes
        config_desc = Descriptor(CONFIG_MEDIA_TYPE, compute_digest(data), len(data))
        return Manifest(
            config=config_desc,
            layers=[layer.descriptor for layer in self.layers],
            annotations=dict(self.annotations),
        )


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def build_artifact(
    source: str | Path,
    *,
    name: str,
    tag: str | None = None,
    description: str = "",
    annotate: dict[str, str] | None = None,
) -> ArtifactBundle:
    """Build an :class:`ArtifactBundle` from *source* (a spec or a prompt file)."""
    path = Path(source)
    if not path.exists():
        raise PromptGenieError(f"Source not found: {path}", code=EXIT_USAGE)

    if path.suffix.lower() in _SPEC_SUFFIXES:
        layers, config = _build_spec_layers(path)
    else:
        layers, config = _build_prompt_layers(path)

    config["name"] = name
    if description:
        config["description"] = description
    config["created"] = datetime.now(timezone.utc).isoformat()

    annotations: dict[str, str] = {
        "org.promptgenie.name": name,
        "org.opencontainers.image.created": config["created"],
    }
    if tag:
        annotations["org.promptgenie.tag"] = tag
    if description:
        annotations["org.promptgenie.description"] = description
    # Surface a few config fields as annotations so `search` can match them.
    for key in ("provider", "model", "classification"):
        if config.get(key):
            annotations[f"org.promptgenie.{key}"] = str(config[key])
    annotations.update(annotate or {})

    return ArtifactBundle(config=config, layers=layers, annotations=annotations)


def _build_spec_layers(path: Path) -> tuple[list[Layer], dict]:
    # Validate it is a real spec (raises PromptGenieError with a clear message).
    from promptgenie.core.spec import load_spec

    load_spec(path)

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    spec_dir = path.parent
    layers: list[Layer] = [Layer("spec", path.name, path.read_bytes())]
    seen: set[str] = {str(path.resolve())}

    def add(kind: str, ref: str) -> None:
        target = (spec_dir / ref).resolve()
        if str(target) in seen or not target.is_file():
            return
        seen.add(str(target))
        layers.append(Layer(kind, _safe_rel(spec_dir, target), target.read_bytes()))

    if isinstance(raw.get("template"), str):
        add("template", raw["template"])

    policy = raw.get("policy")
    for pref in [policy] if isinstance(policy, str) else (policy or []):
        if isinstance(pref, str):
            add("policy", pref)
    # Auto-discovered policy alongside the spec.
    for pname in _POLICY_NAMES:
        if (spec_dir / pname).is_file():
            add("policy", pname)
            break

    for src in raw.get("context", []) or []:
        if isinstance(src, dict):
            ref = src.get("path") or src.get("file")
            if isinstance(ref, str):
                add("context", ref)

    oc = raw.get("output_contract")
    if isinstance(oc, dict) and isinstance(oc.get("schema"), str):
        add("schema", oc["schema"])
    if isinstance(raw.get("vars_file"), str):
        add("vars", raw["vars_file"])

    config: dict = {
        "kind": "spec",
        "source": path.name,
        "provider": raw.get("provider", ""),
        "model": raw.get("model", ""),
        "target": raw.get("target", ""),
        "classification": _classification(raw),
    }
    dynamic = _dynamic_context(raw)
    if dynamic:
        config["dynamic_context"] = dynamic
    return layers, config


def _build_prompt_layers(path: Path) -> tuple[list[Layer], dict]:
    layers = [Layer("prompt", path.name, path.read_bytes())]
    config = {"kind": "prompt", "source": path.name}
    return layers, config


def _classification(raw: dict) -> str:
    policy = raw.get("policy")
    if isinstance(policy, dict):
        return str(policy.get("classification", ""))
    return str(raw.get("classification", ""))


def _dynamic_context(raw: dict) -> list[str]:
    """Context sources that cannot be vendored (glob/cmd/url) — recorded only."""
    out: list[str] = []
    for src in raw.get("context", []) or []:
        if isinstance(src, dict):
            for key in ("pattern", "glob", "command", "cmd", "url"):
                if src.get(key):
                    out.append(f"{key}:{src[key]}")
    return out


def _safe_rel(base: Path, target: Path) -> str:
    """Relative path of *target* under *base*, else its bare filename.

    Keeps materialised files inside the output directory; a reference that
    resolves outside the spec tree is flattened to its basename.
    """
    try:
        rel = target.relative_to(base.resolve())
        return rel.as_posix()
    except ValueError:
        return target.name


# ---------------------------------------------------------------------------
# Push & materialise
# ---------------------------------------------------------------------------


def push_bundle(
    store: RegistryStore, bundle: ArtifactBundle, repository: str, tag: str
) -> str:
    """Write *bundle*'s blobs + manifest to *store* and point *repository:tag* at it.

    Returns the manifest digest.
    """
    store.put_blob(bundle.config_bytes, media_type=CONFIG_MEDIA_TYPE)
    for layer in bundle.layers:
        desc = layer.descriptor
        store.put_blob(layer.data, media_type=desc.media_type, annotations=desc.annotations)
    manifest = bundle.manifest()
    digest = store.put_manifest(manifest)
    store.set_tag(repository, tag, digest)
    return digest


def materialise(store: RegistryStore, manifest: Manifest, out_dir: str | Path) -> list[Path]:
    """Reconstruct *manifest*'s layers under *out_dir* (path-traversal-guarded)."""
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for layer in manifest.layers:
        rel = layer.annotations.get(PATH_ANNOTATION) or _digest_filename(layer.digest)
        dest = _safe_join(out, rel)
        data = store.get_blob(layer.digest)  # verifies digest (fail-closed)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        written.append(dest)
    return written


def _digest_filename(digest: str) -> str:
    return digest.replace(":", "_")


def _safe_join(base: Path, rel: str) -> Path:
    """Join *rel* under *base*, rejecting absolute paths and ``..`` escapes."""
    candidate = Path(rel)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise RegistryError(f"Unsafe layer path rejected: {rel!r}")
    dest = (base / candidate).resolve()
    if base != dest and base not in dest.parents:
        raise RegistryError(f"Layer path escapes output directory: {rel!r}")
    return dest

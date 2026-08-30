import ast
from pathlib import Path

import pytest

from morph_gen.generator_basis import synthesize_generator
from morph_gen.scrambled_latent import affine_scaling_machine, make_slo


def test_public_system_rejects_oracle_metadata_and_synthesis_ignores_values():
    instance = make_slo(
        affine_scaling_machine(2, 61), 8, encoding="affine", seed=62
    )
    instance.system.metadata["arbitrary_note"] = "claims feistel and parity"
    first = synthesize_generator(instance.system)
    instance.system.metadata["arbitrary_note"] = "claims triangular and counter"
    second = synthesize_generator(instance.system)
    assert first.basis.digest() == second.basis.digest()

    original = instance.system.metadata
    instance.system.metadata = {"family": "forbidden"}
    with pytest.raises(ValueError):
        instance.system.__post_init__()
    instance.system.metadata = original


def test_backend_selection_source_has_no_metadata_branch():
    source = (Path(__file__).parents[1] / "morph_gen" / "generator_basis.py").read_text()
    tree = ast.parse(source)
    selections = [
        ast.get_source_segment(source, node) or ""
        for node in ast.walk(tree)
        if isinstance(node, (ast.If, ast.Match))
    ]
    assert all("metadata" not in selection for selection in selections)

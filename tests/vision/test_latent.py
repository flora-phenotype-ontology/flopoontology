"""Checks of inference semantics and taxon-only learning, not plant accuracy."""
import pytest
import torch

pytest.importorskip("deeplog")
from flopo2.vision.latent import CompiledQueries, LatentTaxonWMC
from flopo2.vision.logic import combine, probability


def test_shared_proofs_values_and_gradients_match_exact_oracle():
    a, b = ("eq", "leaf", 0), ("eq", "petal", 1)
    queries = [a, ("or", a, a), ("or", a, ("and", a, b), b),
               ("and", a, ("eq", "leaf", 1)), True, False]
    compiled = CompiledQueries({"leaf": 3, "petal": 2}, queries).double()
    torch.manual_seed(17)
    logits = {v: torch.randn(4, n, dtype=torch.float64, requires_grad=True)
              for v, n in {"leaf": 3, "petal": 2}.items()}
    ps = {v: x.softmax(-1) for v, x in logits.items()}
    actual = compiled(ps)
    expected = torch.stack([torch.stack([
        torch.as_tensor(probability(q, {v: p[row] for v, p in ps.items()}), dtype=torch.float64)
        for q in queries]) for row in range(4)])
    torch.testing.assert_close(actual, expected)
    ga = torch.autograd.grad(actual.square().sum(), tuple(logits.values()), retain_graph=True)
    ge = torch.autograd.grad(expected.square().sum(), tuple(logits.values()))
    for x, y in zip(ga, ge):
        torch.testing.assert_close(x, y)


def test_no_visual_evidence_returns_taxon_prior_despite_profile_sparsity():
    ref = {"leaf": [.7, .3], "petal": [.4, .6]}
    profiles = {"sparse": True, "one": ("eq", "leaf", 0),
                "two": ("and", ("eq", "leaf", 0), ("eq", "petal", 1))}
    model = LatentTaxonWMC({"leaf": 2, "petal": 2}, profiles, ref, prior=[1, 2, 3])
    p = {v: torch.tensor([x], dtype=torch.float64) for v, x in ref.items()}
    torch.testing.assert_close(model(p).exp()[0], torch.tensor([1/6, 2/6, 3/6], dtype=torch.float64))


def test_taxon_labels_alone_train_compatible_latent_state():
    profiles = {"green_taxon": ("eq", "leaf", 0), "yellow_taxon": ("eq", "leaf", 1)}
    model = LatentTaxonWMC({"leaf": 2}, profiles, {"leaf": [.5, .5]})
    logits = torch.nn.Parameter(torch.zeros(2, 2, dtype=torch.float64))
    opt = torch.optim.Adam([logits], lr=.15)
    targets = torch.tensor([0, 1])
    initial = torch.nn.functional.nll_loss(model({"leaf": logits.softmax(-1)}), targets).item()
    for _ in range(30):
        opt.zero_grad()
        loss = torch.nn.functional.nll_loss(model({"leaf": logits.softmax(-1)}), targets)
        loss.backward()
        opt.step()
    assert loss.item() < initial / 3
    assert logits.softmax(-1).diag().min() > .95


def test_identical_profiles_cannot_teach_distinguishing_traits():
    f = ("eq", "leaf", 0)
    model = LatentTaxonWMC({"leaf": 2}, {"a": f, "b": f}, {"leaf": [.5, .5]})
    logits = torch.tensor([[.1, -.2]], dtype=torch.float64, requires_grad=True)
    model({"leaf": logits.softmax(-1)})[0, 0].backward()
    torch.testing.assert_close(logits.grad, torch.zeros_like(logits))


def test_unassessable_profiles_neutral_and_constants_differentiable():
    # Caller removed all unassessable groups, leaving two empty (True) profiles.
    model = LatentTaxonWMC({"leaf": 2}, {"a": True, "b": True}, {"leaf": [.5, .5]})
    logits = torch.tensor([[8., -8.]], dtype=torch.float64, requires_grad=True)
    output = model({"leaf": logits.softmax(-1)})
    torch.testing.assert_close(output.exp(), torch.full_like(output, .5))
    output.sum().backward()
    torch.testing.assert_close(logits.grad, torch.zeros_like(logits))


def test_constraint_uses_joint_reference_normalization():
    a, b = ("eq", "leaf", 0), ("eq", "petal", 0)
    model = LatentTaxonWMC({"leaf": 2, "petal": 2}, {"a": a, "b": b},
                          {"leaf": [.3, .7], "petal": [.4, .6]}, constraint=("or", a, b))
    p = {"leaf": torch.tensor([[.3, .7]], dtype=torch.float64),
         "petal": torch.tensor([[.4, .6]], dtype=torch.float64)}
    torch.testing.assert_close(model(p).exp(), torch.tensor([[.5, .5]], dtype=torch.float64))

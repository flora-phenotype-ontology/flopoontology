"""Experimental taxon-supervised latent traits using exact DeepLog WMC.

This is a finite categorical mechanism, not a trained plant recognizer. Profiles
contain eligible, visible-organ events grounded by logic.Scene. Unassessable
groups must be omitted BEFORE constructing a profile, never asserted false.
Install pydeeplog[mvsdd]==5.0.0 in Python >=3.12 for this optional backend.
"""
from __future__ import annotations

import torch
from torch import nn

from .logic import Formula, combine


class CompiledQueries(nn.Module):
    """Compile shared categorical proofs once; evaluate batches with autograd.

    Variable independence is an explicit model assumption. Correlated states
    require a joint categorical variable, as in the existing Scene evaluator.
    """

    def __init__(self, domains: dict[str, int], queries: list[Formula]):
        super().__init__()
        from deeplog import Compiler, SymTensor, reshape
        from deeplog.grounding.prolog import SimpleGrounder, str_to_rules
        from deeplog.systems.deepproblog import Solver, compile_to_module

        if not domains or not queries or any(n < 1 for n in domains.values()):
            raise ValueError("Nonempty categorical domains and queries required")
        self.domains = dict(domains)
        self.queries = list(queries)
        variables = {v: f"v{i}" for i, v in enumerate(domains)}
        rules = ["; ".join(f"weight({variables[v]},{i})::state({variables[v]},{i})"
                            for i in range(n)) + "." for v, n in domains.items()]
        predicates = {}

        def emit(f):
            if isinstance(f, bool):
                name = "certain" if f else "impossible"
                if f:
                    rules.append("certain.")
                else:
                    # A categorical choice cannot take two different states.
                    # For a singleton domain, use a separate contradictory pair.
                    rules.extend(["0.5::contradiction(a);0.5::contradiction(b).",
                                  "impossible :- contradiction(a),contradiction(b)."])
                return name
            if f in predicates:
                return predicates[f]
            if f[0] == "eq":
                _, v, state = f
                if v not in domains or not isinstance(state, int) or not 0 <= state < domains[v]:
                    raise ValueError(f"Invalid categorical state: {f}")
                return f"state({variables[v]},{state})"
            if f[0] not in ("and", "or") or len(f) < 2:
                raise ValueError(f"Invalid formula: {f}")
            name = f"proof{len(predicates)}"
            predicates[f] = name
            children = [emit(child) for child in f[1:]]
            if f[0] == "and":
                rules.append(f"{name} :- {','.join(children)}.")
            else:
                rules.extend(f"{name} :- {child}." for child in children)
            return name

        # Deduplicate roots too: the front end maps formula objects to names.
        self.roots = list(dict.fromkeys(q for q in queries if not isinstance(q, bool)))
        self.positions = {q: i for i, q in enumerate(self.roots)}
        self.circuit = None
        if self.roots:
            for i, query in enumerate(self.roots):
                rules.append(f"answer({i}) :- {emit(query)}.")
            rules.append("?- answer(Q).")
            self.program = "\n".join(rules)
            result = Solver(SimpleGrounder()).get_query_result(tuple(str_to_rules(self.program)))
            self.circuit = reshape(compile_to_module(result, Compiler()), input=tuple(
                SymTensor([f"weight({variables[v]},{i}) _ probability" for i in range(n)])
                for v, n in domains.items()), output=SymTensor([
                    f"answer({i}) _ probability" for i in range(len(self.roots))]))

    def forward(self, probabilities: dict[str, torch.Tensor]):
        first = probabilities[next(iter(self.domains))]
        for v, n in self.domains.items():
            if probabilities[v].shape != (*first.shape[:-1], n):
                raise ValueError(f"Wrong probability shape for {v}")
        values = self.circuit(*(probabilities[v] for v in self.domains)) if self.circuit else None
        # Multiplication by zero retains a valid zero gradient for constant roots.
        zero = first.sum(-1) * 0
        return torch.stack([zero + float(q) if isinstance(q, bool)
                            else values[..., self.positions[q]] for q in self.queries], dim=-1)


class LatentTaxonWMC(nn.Module):
    """Reference-normalized soft profile evidence followed by a taxon softmax.

    A whole-profile contamination model: phi_t = eps + (1-eps) I[profile_t].
    score_t = E_q[I[K] phi_t] / E_reference[I[K] phi_t].
    P(t|x) is proportional to prior_t * score_t. Missing profile = True.
    This prototype uses one noise allowance per profile, not per source record.
    """

    def __init__(self, domains, profiles, reference, *, epsilon=0.1,
                 constraint=True, prior=None):
        super().__init__()
        if not profiles:
            raise ValueError("At least one taxon profile required")
        if not 0 < epsilon <= 1:
            raise ValueError("epsilon must lie in (0, 1]")
        self.taxa = tuple(profiles)
        self.epsilon = epsilon
        self.wmc = CompiledQueries(domains, [constraint] + [
            combine("and", [constraint, f]) for f in profiles.values()])
        ref = {v: torch.as_tensor(reference[v], dtype=torch.float64).reshape(1, n)
               for v, n in domains.items()}
        if any(not torch.isfinite(p).all() or (p < 0).any() or
               not torch.allclose(p.sum(-1), torch.ones(1, dtype=p.dtype)) for p in ref.values()):
            raise ValueError("Invalid reference probabilities")
        with torch.no_grad():
            baseline = self._potential(self.wmc.double()(ref))[0]
        if not torch.isfinite(baseline).all() or (baseline <= 0).any():
            raise ValueError("Reference gives no mass to the constraint")
        self.register_buffer("baseline", baseline)
        prior = torch.ones(len(profiles), dtype=torch.float64) if prior is None else torch.as_tensor(prior, dtype=torch.float64)
        if prior.shape != (len(profiles),) or not torch.isfinite(prior).all() or (prior <= 0).any():
            raise ValueError("Positive taxon prior required")
        self.register_buffer("log_prior", (prior / prior.sum()).log())

    def _potential(self, values):
        return self.epsilon * values[..., :1] + (1 - self.epsilon) * values[..., 1:]

    def forward(self, probabilities):
        potential = self._potential(self.wmc(probabilities))
        # All-zero mass on K is an invalid visual distribution, not a prediction.
        if not torch.isfinite(potential).all() or (potential <= 0).any():
            raise ValueError("Visual distribution gives no mass to the constraint")
        scores = potential.log() - self.baseline.log() + self.log_prior
        return scores.log_softmax(-1)

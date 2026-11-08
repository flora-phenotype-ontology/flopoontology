"""Small localized concept model, marginal weak loss, and fixed profile scorer.

The first executable slice is organ × colour. It uses frozen crop features, with no
taxon identifier or whole-image feature input. The other phenotype groups remain
compiler audit entries until their visual primitives have been represented.
"""
import math
import torch
from torch import nn

from .logic import Expr, HAS_PART, HAS_QUALITY, OWL, Scene, probability


class PrimitiveHead(nn.Module):
    def __init__(self, feature_dim, organs, colours):
        super().__init__()
        self.organs, self.colours = organs, colours
        self.organ = nn.Linear(feature_dim, len(organs))
        self.colour_given_organ = nn.Linear(feature_dim, len(organs) * len(colours))

    def forward(self, features):
        organ = self.organ(features).softmax(-1)
        conditional = self.colour_given_organ(features).reshape(-1, len(self.organs), len(self.colours)).softmax(-1)
        return (organ.unsqueeze(-1) * conditional).flatten(1)


def localized_scene(vocabulary, region_ids, assessable, ancestors):
    """Typed projections share a joint organ/colour choice; fixed gates cannot collapse.

    assessable is a fixed visibility gate. It may come from review or a frozen model;
    callers using an uncalibrated heuristic must retain that provenance as weak evidence.
    A false gate means no observed support; it never creates a biological negative.
    """
    if len(region_ids) > 6 or len(set(region_ids)) != len(region_ids):
        raise ValueError('Use at most six distinct regions per image')
    organs, colours = vocabulary['organs'], vocabulary['colours']
    states = [(o['iri'], c['iri']) for o in organs for c in colours]
    nodes = {'plant': {'types': ['http://semanticscience.org/resource/SIO_010056']}}
    domains, edges = {}, []
    for region in region_ids:
        if type(assessable[region]) is not bool:
            raise ValueError('Eligibility must be fixed Boolean data')
        variable = f'{region}.joint'
        domains[variable] = tuple(tuple(t for t in state if t) for state in states)
        nodes[region] = {'choice': variable, 'state_types': [(o,) if o else () for o, c in states]}
        nodes[f'{region}.quality'] = {'choice': variable, 'state_types': [(c,) if c else () for o, c in states]}
        edges.extend([('plant', HAS_PART, region, True),
                      (region, HAS_QUALITY, f'{region}.quality', assessable[region])])
    return Scene(nodes, edges, domains, ancestors)


def weak_loss(formula, probabilities, *, eligible, epsilon, weight=1.0):
    """One audited source event. Deduplicate statements before calling this function."""
    if type(eligible) is not bool:
        raise ValueError('Eligibility must be fixed and detached')
    if not 0 < epsilon < 1 or not math.isfinite(weight) or weight < 0:
        raise ValueError('Invalid fixed contamination or source weight')
    reference = next(iter(probabilities.values()))
    if not eligible or weight == 0:
        return reference.sum() * 0
    p = torch.as_tensor(probability(formula, probabilities), device=reference.device, dtype=reference.dtype)
    return -weight * torch.log(epsilon + (1 - epsilon) * p)


def trait_query(organ, colours):
    allowed = tuple(Expr('atom', colour) for colour in colours)
    if not allowed:
        raise ValueError('An allowed event needs at least one state')
    quality = allowed[0] if len(allowed) == 1 else Expr('or', children=allowed)
    return Expr('some', HAS_PART, (Expr('and', children=(Expr('atom', organ),
        Expr('some', HAS_QUALITY, (quality,)))),))


def ungrounded_atoms(expr, vocabulary, ancestors):
    """Reject partially representable unions: 'cream OR yellow' cannot mean just yellow."""
    covered = {'http://semanticscience.org/resource/SIO_010056', OWL + 'Thing'}
    for item in vocabulary['organs'] + vocabulary['colours']:
        if item['iri']:
            covered.update(ancestors.get(item['iri'], [item['iri']]))
    def atoms(e):
        return {e.value} if e.op == 'atom' else set().union(*(atoms(c) for c in e.children))
    return atoms(expr) - covered


def rank_profiles(evidence, profiles, reference, min_coverage=1, min_margin=0.0):
    """Fixed evidence ranking; no learned species channel, hard exclusions or posterior.

    evidence[group] and reference[group] are distributions over mutually exclusive
    reviewed states. Profiles map group to {allowed: [...], reliability: [0,1]}.
    Missing groups contribute zero. Each group contributes once, including ancestors.
    """
    results = []
    for distributions in (reference, evidence):
        for group, distribution in distributions.items():
            if not distribution or any(not math.isfinite(p) or p < 0 for p in distribution.values()) or abs(sum(distribution.values()) - 1) > 1e-5:
                raise ValueError(f'Invalid distribution for {group}')
    for taxon, groups in profiles.items():
        score, contributions = 0.0, {}
        for group in sorted(evidence.keys() & groups.keys()):
            if group not in reference or set(evidence[group]) != set(reference[group]):
                raise ValueError(f'Missing or mismatched training reference for {group}')
            item = groups[group]; allowed = set(item['allowed'])
            if not allowed <= evidence[group].keys() or not 0 <= item['reliability'] <= 1:
                raise ValueError('Unaudited profile states or reliability')
            contribution = item['reliability'] * sum(evidence[group][state] - reference[group][state] for state in allowed)
            contributions[group] = contribution; score += contribution
        results.append({'taxon': taxon, 'score': score, 'coverage': len(contributions), 'contributions': contributions})
    results.sort(key=lambda row: (-row['score'], row['taxon']))
    margin = results[0]['score'] - results[1]['score'] if len(results) > 1 else 0.0
    tied = [r['taxon'] for r in results if results and abs(r['score'] - results[0]['score']) < 1e-9]
    abstain = not results or results[0]['coverage'] < min_coverage or margin <= min_margin
    return {'ranking': results, 'ties': tied, 'margin': margin, 'abstain': abstain,
            'interpretation': 'evidence score, not species posterior'}

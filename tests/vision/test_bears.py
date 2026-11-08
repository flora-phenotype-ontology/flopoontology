import itertools
import math

import torch

from flopo2.vision.bears import diversification, joint_log_probability, kl_integrand, uncertainty
from flopo2.vision.latent_train import observations, profile_formula
from flopo2.vision.logic import probability


def test_mixture_preserves_member_joint_worlds():
    worlds = {'a': torch.tensor([[0]]), 'b': torch.tensor([[1]])}
    first = {'a': torch.tensor([[.999, .001]]), 'b': torch.tensor([[.999, .001]])}
    second = {g: p.flip(-1) for g,p in first.items()}
    actual = torch.stack([joint_log_probability(p, worlds).exp() for p in [first,second]]).mean(0)
    marginals = {g: (first[g]+second[g])/2 for g in first}
    wrong = joint_log_probability(marginals,worlds).exp()
    assert float(actual) < .002
    torch.testing.assert_close(wrong, torch.tensor([[.25]]))


def test_sampled_joint_kl_gradient_matches_enumerated_gradient():
    torch.set_num_threads(1)
    torch.manual_seed(7)
    a = torch.tensor([[.3,-.2]], dtype=torch.float64, requires_grad=True)
    b = torch.tensor([[-.1,.4]], dtype=torch.float64, requires_grad=True)
    q = {'a': a.softmax(-1), 'b': b.softmax(-1)}
    previous = [{'a': torch.tensor([[.8,.2]],dtype=torch.float64),
                 'b': torch.tensor([[.1,.9]],dtype=torch.float64)}]
    worlds = dict(zip(q, [torch.tensor([[w[i]] for w in itertools.product(range(2),repeat=2)]) for i in range(2)]))
    integrand, logq = kl_integrand(q, previous, worlds)
    exact = (logq.exp()*integrand).sum(0)/math.log(2)
    expected = torch.autograd.grad(exact.sum(), (a,b), retain_graph=True)
    estimated, _ = diversification(q, previous, samples=100000)
    actual = torch.autograd.grad(estimated.sum(), (a,b))
    torch.testing.assert_close(estimated, exact, atol=.004, rtol=0)
    for x,y in zip(actual,expected):
        torch.testing.assert_close(x,y,atol=.004,rtol=0)


def test_identical_members_have_zero_epistemic_uncertainty():
    p = torch.tensor([[.3,.7]])
    _, ent, mi = uncertainty([p,p,p])
    assert ent.item() > 0
    assert mi.item() < 1e-7
    kl, _ = diversification({'x':p}, [{'x':p}], samples=32)
    torch.testing.assert_close(kl, torch.zeros_like(kl), atol=1e-7,rtol=0)


def test_profile_drops_unobserved_organs_without_negating_them():
    profile = {'leaf.colour': {'allowed':['0']}, 'petal.colour': {'allowed':['1']}}
    formula = profile_formula(profile, ('leaf.colour',))
    assert probability(formula, {'leaf.colour':[.8,.2]}) == .8
    assert profile_formula(profile, ()) is True


def test_focal_organ_selection_ignores_species_and_gates_small_hair_crops():
    rows = [dict(observation_id=1,taxon='a',genus='g',split='train')]
    samples = [dict(observation_id=1,organ='leaf',detector_score=.4,box=[0,0,120,120]),
               dict(observation_id=1,organ='leaf',detector_score=.8,box=[0,0,50,50])]
    specs = {'leaf.colour':dict(organ='leaf',attribute='colour'),
             'leaf.hairiness':dict(organ='leaf',attribute='hairiness')}
    first = observations(rows,samples,specs)
    rows[0]['taxon']='b'
    second = observations(rows,samples,specs)
    assert first[0]['regions'] == second[0]['regions'] == {'leaf.colour':1}

"""BEARS joint-concept diversification (Marconato et al., UAI 2024, Eq. 16).

The mixture contains complete member joint distributions, including the current
member. For large concept spaces, KL is estimated by sampling current-member
worlds, with a score-function correction for gradients through that sampling.
The categorical entropy is exact under the explicit factorization assumption.
"""
import math
import torch


def joint_log_probability(probabilities, worlds):
    return sum(p.clamp_min(1e-30).log().gather(1, worlds[g].T).T
               for g, p in probabilities.items())


def kl_integrand(current, previous, worlds):
    logp = joint_log_probability(current, worlds)
    logs = [joint_log_probability(old, worlds) for old in previous] + [logp]
    logmix = torch.logsumexp(torch.stack(logs), dim=0) - math.log(len(logs))
    return logp - logmix, logp


def diversification(current, previous, samples=64):
    """Return normalized joint-KL surrogate and exact normalized entropy per row.

    Previous-member predictions must be detached. The surrogate's value is the
    Monte Carlo KL estimate; its gradient also accounts for sampling from q_theta.
    A leave-one-out baseline reduces score-function variance without bias.
    """
    if samples < 2:
        raise ValueError("At least two joint-world samples required")
    entropy = sum(-(p * p.clamp_min(1e-30).log()).sum(-1) for p in current.values())
    entropy = entropy / sum(math.log(p.shape[-1]) for p in current.values())
    if not previous:
        return entropy * 0, entropy
    if any(p.requires_grad for old in previous for p in old.values()):
        raise ValueError("Previous ensemble members must be frozen")
    worlds = {g: torch.multinomial(p.detach(), samples, replacement=True).T
              for g, p in current.items()}
    contrast, logp = kl_integrand(current, previous, worlds)
    detached = contrast.detach()
    baseline = (detached.sum(0, keepdim=True) - detached) / (samples - 1)
    correction = (detached - baseline) * (logp - logp.detach())
    return (contrast + correction).mean(0) / math.log(len(previous) + 1), entropy


def uncertainty(members):
    """Marginal predictive entropy and epistemic MI; neither is a calibration claim."""
    stack = torch.stack(members)
    mean = stack.mean(0)
    total = -(mean * mean.clamp_min(1e-30).log()).sum(-1)
    within = -(stack * stack.clamp_min(1e-30).log()).sum(-1).mean(0)
    return mean, total, (total - within).clamp_min(0)

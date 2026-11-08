"""Controls for distinguishing image-dependent learning from trait offsets."""
import torch
from torch import nn


class AnchoredHead(nn.Module):
    def __init__(self, text, centers, kind):
        super().__init__()
        self.kind = kind
        self.register_buffer('reference', 10 * text.clone())
        self.register_buffer('centers', centers.clone())
        if kind == 'offset':
            self.offset = nn.Parameter(torch.zeros(text.shape[0], device=text.device))
        elif kind == 'centered':
            self.residual = nn.Parameter(torch.zeros_like(text))
        else:
            raise ValueError(kind)

    def forward(self, x):
        initial = x @ self.reference.T - 3.
        if self.kind == 'offset':
            return initial + self.offset
        # Each trait's residual averages to zero on its training organ features.
        return initial + x @ self.residual.T - (self.centers * self.residual).sum(-1)


def organ_centers(x, rows, traits):
    centers = torch.zeros(len(traits), x.shape[1], device=x.device, dtype=x.dtype)
    for t in traits:
        ids = [i for i, r in enumerate(rows) if r['split'] == 'train' and r['organ'] == t['organ']]
        if ids:
            centers[t['index']] = x[ids].mean(0)
    return centers


def make_head(text, kind='linear', centers=None):
    if kind == 'linear':
        head = nn.Linear(text.shape[1], text.shape[0]).to(text.device)
        with torch.no_grad():
            head.weight.copy_(10 * text); head.bias.fill_(-3.)
        return head
    if centers is None:
        centers = torch.zeros_like(text)
    return AnchoredHead(text, centers, kind)

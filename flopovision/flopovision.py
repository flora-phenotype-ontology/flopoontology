"""FLOPOVision: plant traits from a photograph.

    python flopovision.py photo.jpg [photo2.jpg ...] [--top 3] [--json] [--weights DIR] [--encoder DIR] [--device cuda]

Several photographs are treated as views of one plant: the probabilities are averaged. The image is embedded with the image
tower of BioCLIP 2 (downloaded from the Hugging Face hub on first use); FLOPOVision adds one small head per trait.

    from flopovision import FLOPOVision
    model = FLOPOVision()                      # or FLOPOVision(weights='path/to/folder')
    model.predict(['a.jpg', 'b.jpg'])          # {'leaf_hair': {'hairy': 0.91, 'glabrous': 0.09}, ...}
"""
import argparse, json
from pathlib import Path
import torch

REPO = 'bio-ontology-research-group/FLOPOVision'        # Hugging Face model repository of the heads
ENCODER = 'hf-hub:imageomics/bioclip-2'


class FLOPOVision:
    def __init__(self, weights=None, device=None, encoder=None):
        import open_clip
        from safetensors.torch import load_file
        self.device = device or ('cuda' if torch.cuda.is_available() else 'cpu')
        if weights is None:
            from huggingface_hub import snapshot_download
            weights = snapshot_download(REPO, allow_patterns=['flopovision-heads.safetensors', 'config.json'])
        weights = Path(weights)
        self.config = json.loads((weights / 'config.json').read_text())
        state = load_file(str(weights / 'flopovision-heads.safetensors'))
        self.heads = {}
        for trait, info in self.config['traits'].items():
            net = torch.nn.Sequential(torch.nn.Linear(self.config['embedding_dim'], self.config['hidden']), torch.nn.GELU(), torch.nn.Dropout(0.2),
                                      torch.nn.Linear(self.config['hidden'], len(info['classes'])))
            net.load_state_dict({k[len(trait) + 1:]: v for k, v in state.items() if k.startswith(trait + '.')})
            self.heads[trait] = net.to(self.device).eval()
        if encoder is None:
            self.encoder, _, self.transform = open_clip.create_model_and_transforms(ENCODER)
        else:       # a local copy of the BioCLIP 2 repository (open_clip_model.safetensors, open_clip_config.json), for offline use
            cfg = json.loads((Path(encoder) / 'open_clip_config.json').read_text())['preprocess_cfg']
            self.encoder, _, self.transform = open_clip.create_model_and_transforms(
                'ViT-L-14', pretrained=str(Path(encoder) / 'open_clip_model.safetensors'), image_mean=cfg['mean'], image_std=cfg['std'])
        self.encoder = self.encoder.to(self.device).eval()

    @torch.no_grad()
    def embed(self, paths):
        """L2-normalised BioCLIP 2 image embeddings, one row per photograph."""
        from PIL import Image
        x = torch.stack([self.transform(Image.open(p).convert('RGB')) for p in paths]).to(self.device)
        return torch.nn.functional.normalize(self.encoder.encode_image(x).float(), dim=-1)

    @torch.no_grad()
    def predict(self, paths, per_photo=False):
        """Probability of every value of every trait. One plant (mean over the photographs) or, with per_photo, a list."""
        z = self.embed([paths] if isinstance(paths, (str, Path)) else list(paths))
        out = [{} for _ in range(len(z))] if per_photo else {}
        for trait, net in self.heads.items():
            p = torch.softmax(net(z), -1).cpu()
            classes = self.config['traits'][trait]['classes']
            if per_photo:
                for k in range(len(z)):
                    out[k][trait] = dict(zip(classes, map(float, p[k])))
            else:
                out[trait] = dict(zip(classes, map(float, p.mean(0))))
        return out


def main():
    a = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    a.add_argument('photos', nargs='+'); a.add_argument('--top', type=int, default=3); a.add_argument('--json', action='store_true')
    a.add_argument('--weights'); a.add_argument('--device'); a.add_argument('--encoder', help='local folder with BioCLIP 2 (offline use)')
    a = a.parse_args()
    pred = FLOPOVision(a.weights, a.device, a.encoder).predict(a.photos)
    if a.json:
        print(json.dumps(pred, indent=1)); return
    for trait, p in pred.items():
        best = sorted(p.items(), key=lambda kv: -kv[1])[:a.top]
        print(f"{trait:18s} " + ', '.join(f'{c} {v:.2f}' for c, v in best))


if __name__ == '__main__':
    main()

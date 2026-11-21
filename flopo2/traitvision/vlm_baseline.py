"""Chat-model baseline: ask a vision-language model for the trait value of test observations.

    python -m flopo2.traitvision.vlm_baseline DIR     (DIR holds sample.json and images/; answers go to answers.jsonl)

One question per observation and trait, with up to two photos and the list of allowed values; the model
answers with one value, or "unclear".  Default: the Qwen server on unimatrix01 (12 parallel requests).
"""
import base64
import concurrent.futures
import io
import json
import os
import sys
import urllib.request
from pathlib import Path

from PIL import Image

URL = 'http://unimatrix01.kaust.edu.sa:8000/v1/chat/completions'
MODEL = 'qwen3.8-27b'
QUESTION = {
    'flower_colour': 'What is the main colour of the flowers (petals) of the plant shown?',
    'fruit_colour': 'What is the colour of the fruits of the plant shown?',
    'habit': 'What is the growth habit of the plant shown?',
    'leaf_arrangement': 'How are the leaves arranged on the stem of the plant shown?',
    'leaf_complexity': 'Are the leaves of the plant shown simple (one blade) or compound (divided into leaflets)?',
    'leaf_margin': 'What is the leaf margin of the plant shown: entire (smooth), toothed, or lobed?',
    'spines': 'Does the plant shown bear spines, thorns or prickles? Answer present or absent.',
    'inflorescence': 'What type of inflorescence does the plant shown have?',
}


def picture(path):
    im = Image.open(path).convert('RGB')
    im.thumbnail((768, 768))
    buf = io.BytesIO()
    im.save(buf, 'JPEG', quality=88)
    return 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()


def ask(row, classes, files, key):
    content = [{'type': 'image_url', 'image_url': {'url': picture(files[p])}} for p in row['photos'].split('|') if p in files]
    if not content:
        return None
    content.append({'type': 'text', 'text': f"{QUESTION[row['trait']]} Judge only from what is visible; do not rely on "
                    f"recognising the species. Answer with exactly one of: {', '.join(classes)}; or 'unclear' if it cannot be seen."})
    body = {'model': MODEL, 'max_tokens': 8, 'temperature': 0,
            'messages': [{'role': 'system', 'content': 'Reply with a single word and nothing else.'},
                         {'role': 'user', 'content': content}],
            'chat_template_kwargs': {'enable_thinking': False}}
    req = urllib.request.Request(URL, json.dumps(body).encode(), {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    for _ in range(3):
        try:
            return json.load(urllib.request.urlopen(req, timeout=300))['choices'][0]['message']['content'].strip().lower().strip('.\'" ')
        except Exception as e:
            err = str(e)
    return 'error: ' + err


def main(folder):
    folder = Path(folder)
    sample = json.loads((folder / 'sample.json').read_text())
    files = {f.stem: f for f in (folder / 'images').rglob('*') if f.is_file()}
    key = Path(os.path.expanduser('~/.config/borg-llm/api-key')).read_text().strip()
    out = folder / 'answers.jsonl'
    done = {(json.loads(l)['observation'], json.loads(l)['trait']) for l in open(out)} if out.exists() else set()
    todo = [r for r in sample['rows'] if (r['observation'], r['trait']) not in done]
    with concurrent.futures.ThreadPoolExecutor(12) as pool, open(out, 'a') as f:
        futures = {pool.submit(ask, r, sample['classes'][r['trait']], files, key): r for r in todo}
        for n, fut in enumerate(concurrent.futures.as_completed(futures)):
            ans = fut.result()
            if ans is not None and not ans.startswith('error'):
                f.write(json.dumps({**futures[fut], 'answer': ans}) + '\n')
                f.flush()
            if n % 100 == 0:
                print(n, len(todo), ans, flush=True)


if __name__ == '__main__':
    main(sys.argv[1])

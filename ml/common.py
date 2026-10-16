import csv, json
from pathlib import Path

def validate(csv_path,manifest_path):
    from PIL import Image
    manifest=json.loads(Path(manifest_path).read_text())
    if manifest['domain'] not in ('aerial','closeup'): raise ValueError('Domain must be aerial or closeup')
    rows=list(csv.DictReader(open(csv_path))); root=Path(csv_path).resolve().parent
    required={'path','label','group','crop','domain','split'}
    if not rows or not required.issubset(rows[0]): raise ValueError('Missing dataset columns or empty dataset')
    groups={}; seen=set(); pixels={}
    import hashlib
    for row in rows:
        path=(root/row['path']).resolve()
        if path in seen: raise ValueError(f'Duplicate path: {path}')
        seen.add(path)
        if row['label'] not in manifest['labels'] or row['crop'] not in manifest['crops'] or row['domain']!=manifest['domain']: raise ValueError(f'Unsupported dataset row: {row}')
        if row['split'] not in ('train','val','test'): raise ValueError('Use train, val, or test splits')
        if row['group'] in groups and groups[row['group']]!=row['split']: raise ValueError('Farm/session group leakage across splits')
        groups[row['group']]=row['split']
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if digest in pixels: raise ValueError(f'Duplicate image content: {path}')
        pixels[digest]=row['split']
        with Image.open(path) as im: im.verify()
        row['resolved_path']=str(path)
    if {r['split'] for r in rows}!={'train','val','test'}: raise ValueError('All three dataset splits are required')
    if {r['label'] for r in rows if r['split']=='train'}!=set(manifest['labels']): raise ValueError('Training split must contain every configured label')
    return rows,manifest

def dataset(rows,meta,split):
    from torch.utils.data import Dataset
    from torchvision.transforms import Compose,Resize,ToTensor,Normalize
    from PIL import Image
    class Crops(Dataset):
        def __init__(self):
            self.rows=[r for r in rows if r['split']==split]
            self.transform=Compose([Resize((224,224)),ToTensor(),Normalize([.485,.456,.406],[.229,.224,.225])])
        def __len__(self):return len(self.rows)
        def __getitem__(self,i):
            r=self.rows[i]
            with Image.open(r['resolved_path']) as im: x=self.transform(im.convert('RGB'))
            return x,meta['labels'].index(r['label'])
    return Crops()

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('csv');p.add_argument('manifest');a=p.parse_args()
    rows,meta=validate(a.csv,a.manifest)
    print(json.dumps({'samples':len(rows),'domain':meta['domain'],'groups':len({r['group'] for r in rows})}))

import csv, json, importlib.util
from pathlib import Path
from PIL import Image
import pytest
spec=importlib.util.spec_from_file_location('ml_common',Path(__file__).resolve().parents[2]/'ml/common.py')
common=importlib.util.module_from_spec(spec);spec.loader.exec_module(common)

def test_dataset_validator_and_leakage(tmp_path):
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps({'labels':['healthy'],'domain':'aerial','crops':['wheat']}))
    rows=[]
    for i,split in enumerate(['train','val','test']):
        file=tmp_path/f'{split}.jpg';Image.new('RGB',(20,20),(i*70,100,50)).save(file)
        rows.append({'path':file.name,'label':'healthy','group':f'farm-{i}','crop':'wheat','domain':'aerial','split':split})
    data=tmp_path/'dataset.csv'
    def save():
        with data.open('w') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    save();validated,meta=common.validate(data,manifest);assert len(validated)==3 and meta['domain']=='aerial'
    rows[1]['group']=rows[0]['group'];save()
    with pytest.raises(ValueError,match='leakage'):common.validate(data,manifest)
    rows[1]['group']='farm-other';rows[1]['domain']='closeup';save()
    with pytest.raises(ValueError,match='Unsupported'):common.validate(data,manifest)

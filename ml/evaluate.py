import argparse,json
from pathlib import Path
from common import validate,dataset

def main():
    p=argparse.ArgumentParser();p.add_argument('csv');p.add_argument('manifest');p.add_argument('model');p.add_argument('--output',default='evaluation.json');a=p.parse_args()
    rows,meta=validate(a.csv,a.manifest)
    import torch
    from torch.utils.data import DataLoader
    from sklearn.metrics import classification_report,confusion_matrix
    model=torch.jit.load(a.model,map_location='cpu').eval();truth=[];pred=[]
    with torch.no_grad():
        for x,y in DataLoader(dataset(rows,meta,'test'),batch_size=16):truth.extend(y.tolist());pred.extend(model(x).argmax(1).tolist())
    labels=list(range(len(meta['labels'])))
    metrics={'domain':meta['domain'],'crop_domain':meta['crops'],'model_version':meta['version'],'samples':len(truth),'split':'test','groups':sorted({r['group'] for r in rows if r['split']=='test'}),
             'report':classification_report(truth,pred,labels=labels,target_names=meta['labels'],output_dict=True,zero_division=0),'confusion_matrix':confusion_matrix(truth,pred,labels=labels).tolist(),
             'calibrated':False,'aerial_deployment_approved':False}
    Path(a.output).write_text(json.dumps(metrics,indent=2));print('Saved evaluation to',a.output)
if __name__=='__main__':main()

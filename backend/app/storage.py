from pathlib import Path
from .config import settings

def client():
    import boto3
    return boto3.client('s3',endpoint_url=settings.s3_endpoint)

def put(key,data):
    if settings.storage_backend=='s3': client().put_object(Bucket=settings.s3_bucket,Key=key,Body=data,ContentType='image/jpeg' if key.endswith('.jpg') else 'image/png')
    else:
        root=Path(settings.storage_dir); root.mkdir(parents=True,exist_ok=True)
        (root/key).write_bytes(data)

def get(key):
    if settings.storage_backend=='s3': return client().get_object(Bucket=settings.s3_bucket,Key=key)['Body'].read()
    return (Path(settings.storage_dir)/key).read_bytes()

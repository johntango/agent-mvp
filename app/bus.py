import faust
from app.config import load_config
cfg=load_config()
app=faust.App('agent',broker=f"kafka://{cfg['REDPANDA_BROKERS']}",value_serializer='json',key_serializer='raw')
task_topic=app.topic(cfg['TASK_TOPIC'])
report_topic=app.topic(cfg['REPORT_TOPIC'])

def make_report(tid,status,summary):
    return {'task_id':tid,'status':status,'summary':summary}

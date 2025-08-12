def step_request(task_id, step_id, name, inputs, attempt, lease_id, deadline=None):
    return {'task_id':task_id,'step_id':step_id,'name':name,'inputs':inputs,'attempt':attempt,'lease_id':lease_id,'deadline':deadline}

def step_result(task_id, step_id, status, artifacts, log, metrics=None):
    return {'task_id':task_id,'step_id':step_id,'status':status,'artifacts':artifacts,'log':log,'metrics':metrics or {}}

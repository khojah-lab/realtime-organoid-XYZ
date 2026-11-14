import secrets
from urllib.parse import urlsplit
from flask import Blueprint,jsonify,request,session
from services import drive_spool

drive_storage_bp=Blueprint('drive_storage',__name__)

@drive_storage_bp.get('/drive-storage/status')
def status():
    token=session.setdefault('drive_storage_csrf',secrets.token_urlsafe(32))
    result=drive_spool.status(); result['csrf']=token
    response=jsonify(result);response.headers['Cache-Control']='no-store'
    return response

@drive_storage_bp.post('/drive-storage/control')
def control():
    origin=request.headers.get('Origin')
    if origin and urlsplit(origin).netloc!=request.host: return jsonify(error='Cross-origin request rejected'),403
    token=session.get('drive_storage_csrf','')
    if not token or not secrets.compare_digest(token,request.headers.get('X-Drive-CSRF','')):
        return jsonify(error='Refresh the page before changing Drive settings'),403
    body=request.get_json(silent=True)
    if not isinstance(body,dict) or len(body)!=1: return jsonify(error='Send one control action'),400
    try:
        if 'enabled' in body: drive_spool.request_enabled(body['enabled'])
        elif 'paused' in body: drive_spool.request_paused(body['paused'])
        else: raise ValueError('Unknown action')
    except ValueError as exc: return jsonify(error=str(exc)),400
    return jsonify(ok=True)

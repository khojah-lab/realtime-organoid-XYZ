import secrets
from urllib.parse import urlsplit
from flask import Blueprint,jsonify,request,session
from services import drive_spool
from services import storage_manager

drive_storage_bp=Blueprint('drive_storage',__name__)

@drive_storage_bp.get('/drive-storage/status')
def status():
    token=session.setdefault('drive_storage_csrf',secrets.token_urlsafe(32))
    result=storage_manager.status(); result['csrf']=token
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
        if 'mode' in body: storage_manager.set_mode(body['mode'])
        elif 'pause' in body:
            value=body['pause']; storage_manager.pause(value['provider'],value['paused'])
            if value['provider']=='drive': drive_spool.request_paused(value['paused'])
        elif 'preview' in body: return jsonify(storage_manager.waive_preview(body['preview']))
        elif 'waive' in body:
            value=body['waive']; return jsonify(storage_manager.waive(value['provider'],value['token']))
        else: raise ValueError('Unknown action')
    except (ValueError,KeyError,TypeError) as exc: return jsonify(error=str(exc)),400
    except Exception as exc: return jsonify(error=str(exc)),503
    return jsonify(ok=True)

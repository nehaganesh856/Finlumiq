import json, os
from app import app
client = app.test_client()
resp = client.post('/api/ai/chat', json={'message':'Hi'})
print('status', resp.status_code)
print('data', resp.get_data(as_text=True))

"""
BHUMI-NITI: Automated Verification & Test Suite
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from main import app
from app.core.database import get_db_connection

def run_tests():
    client = TestClient(app)
    
    print("=== 1. Testing Auth & User Registration ===", flush=True)
    reg_resp = client.post('/api/v1/auth/register', json={
        'email': 'officer@bhuminiti.gov.in',
        'password': 'SecurePassword2026!',
        'full_name': 'Collector Officer',
        'requested_role': 'Government Official'
    })
    print('Register status:', reg_resp.status_code, reg_resp.json().get('status'), flush=True)

    login_resp = client.post('/api/v1/auth/login', json={
        'email': 'officer@bhuminiti.gov.in',
        'password': 'SecurePassword2026!'
    })
    print('Login status:', login_resp.status_code, login_resp.json().get('status'), flush=True)
    token = login_resp.json().get('access_token')

    me_resp = client.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {token}'})
    print('Me status:', me_resp.status_code, me_resp.json(), flush=True)

    print("\n=== 2. Testing National Location Resolution (36 States/UTs) ===", flush=True)
    locs = ['Bhopal', 'Bengaluru', 'Sanand', 'Noida', 'Pune']
    for loc in locs:
        res = client.get(f'/api/v1/resolve?query={loc}')
        if res.status_code == 200:
            d = res.json()
            state = d['hierarchy']['state']
            area = d['exact_area_sqkm']
            print(f'Resolved {loc}: state={state}, area={area} sqkm', flush=True)
        else:
            print(f'Failed {loc}:', res.status_code, res.text, flush=True)

    print("\n=== 3. Testing Policy Simulation & Hard Constraint Override ===", flush=True)
    sim_resp = client.post('/api/v1/simulate', json={
        'query': 'Sasan Gir',
        'proposed_use': 'Industrial Factory',
        'buffer_meters': 500
    }, headers={'Authorization': f'Bearer {token}'})
    print('Sim HTTP status:', sim_resp.status_code, sim_resp.text[:150], flush=True)

    print("\n=== 4. Testing Grounded RAG AI Query & Fallback ===", flush=True)
    ai_resp1 = client.post('/api/v1/ai/query', json={
        'query': 'What are the NA conversion rules and tenancy restrictions?',
        'location': 'Bengaluru'
    }, headers={'Authorization': f'Bearer {token}'})
    print('AI RAG HTTP status (Bengaluru):', ai_resp1.status_code, ai_resp1.text[:200], flush=True)

    ai_resp2 = client.post('/api/v1/ai/query', json={
        'query': 'What is the quantum mechanics formula for gravity?',
        'location': 'Gandhinagar'
    }, headers={'Authorization': f'Bearer {token}'})
    print('AI Fallback HTTP status:', ai_resp2.status_code, ai_resp2.text[:200], flush=True)

    print("\n=== 5. Checking Database Tables in bhumi_niti.db ===", flush=True)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [r['name'] for r in cursor.fetchall()]
    print('Database tables initialized:', tables, flush=True)
    conn.close()

if __name__ == "__main__":
    run_tests()

from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from redis import Redis
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.redis import RedisJobStore
from functools import wraps
import json
import requests
from datetime import datetime
import uuid
from typing import Optional
import mysql.connector
import os
from dotenv import load_dotenv
load_dotenv()

base_url = os.getenv('BASE_URL')
if base_url and not base_url.startswith('/'):
    base_url = f'/{base_url.strip("/")}'


# load login.py
from login import UserAuth

app = Flask(__name__)
app.secret_key = 'asidhaksaksjdajhioejdadh3j1'  # Change this to a secure secret key

# Initialize Redis client with password
redis_client = Redis(
    host=os.getenv('REDIS_HOST'),
    port=os.getenv('REDIS_PORT'),
    password=os.getenv('REDIS_PASS'),
    db=0,
    decode_responses=True  # This will automatically decode bytes to strings
)

# Initialize Redis jobstore with password
jobstores = {
    'default': RedisJobStore(
        host=os.getenv('REDIS_HOST'),
        port=os.getenv('REDIS_PORT'),
        password=os.getenv('REDIS_PASS'),
        db=1
    )
}

db_config = {
    'user': os.getenv('NPD_DB_USER'),
    'password': os.getenv('NPD_DB_PASS'),
    'host': os.getenv('NPD_DB_HOST'),
    'database': os.getenv('NPD_DB_NAME'),
    'auth_plugin': 'mysql_native_password'
}

db = mysql.connector.connect(**db_config)
cursor = db.cursor(dictionary=True)
# Initialize scheduler
scheduler = BackgroundScheduler(jobstores=jobstores)
scheduler.start()

# Custom functions that can be scheduled
def run_url_task(url, method='GET', headers=None, body=None):
    try:
        if method.upper() == 'GET':
            response = requests.get(url, headers=headers)
        elif method.upper() == 'POST':
            response = requests.post(url, headers=headers, json=body)
        print(f"Task executed: {url} - Status: {response.status_code}")
        return response.status_code
    except Exception as e:
        print(f"Error executing task: {str(e)}")
        return str(e)

def custom_function_example(param1: Optional[str] = None, param2: Optional[str] = None):    
    select_query = "SELECT * FROM bedah_deb WHERE tanggal = '2024-10-31'"
    cursor.execute(select_query)
    data = cursor.fetchall()
    for row in data:
        print(row)

# Login decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def has_session(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'session_id' in session:
            user_auth = UserAuth()
            if user_auth.validate_session(session['session_id']):
                return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

# Routes
@app.route('/login', methods=['GET', 'POST'])
@has_session
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        # Simple authentication - replace with proper authentication
        # if username == 'admin' and password == 'password':
        #     session['logged_in'] = True
        #     return redirect(url_for('dashboard'))
        user_auth = UserAuth()
        if user_auth.login(username, password):
            session_id = user_auth.create_session(username)
            print(f"Session ID: {session_id}")
            session['logged_in'] = True
            session['session_id'] = session_id
            return redirect(url_for('dashboard'))
        flash('Invalid credentials')
    return render_template('login.html', base_url=base_url)

@app.route('/register', methods=['GET', 'POST'])
@has_session
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user_auth = UserAuth()
        if user_auth.register_user(username, password):
            return redirect(url_for('login'))
        flash('User already exists')
    return render_template('register.html', base_url=base_url)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            'id': job.id,
            'name': job.name,
            'next_run': job.next_run_time
        })
    return render_template('dashboard.html', jobs=jobs, base_url=base_url)

@app.route('/add_task', methods=['GET', 'POST'])
@login_required
def add_task():
    if request.method == 'POST':
        task_type = request.form.get('task_type')
        schedule_type = request.form.get('schedule_type')
        
        job_id = str(uuid.uuid4())
        job_data = {
            'id': job_id,
            'type': task_type,
            'schedule_type': schedule_type
        }

        if task_type == 'url':
            url = request.form.get('url')
            method = request.form.get('method')
            job_data.update({
                'url': url,
                'method': method
            })
            job_func = run_url_task
            job_args = [url, method]
        else:
            # Custom function handling
            func_name = request.form.get('function_name')
            params = request.form.get('parameters')
            job_data.update({
                'function': func_name,
                'params': params
            })
            job_func = globals()[func_name]
            # params can be empty 
            if not params:
                params = '[]'
            job_args = json.loads(params)

        if schedule_type == 'once':
            run_time = datetime.strptime(request.form.get('run_time'), '%Y-%m-%dT%H:%M')
            scheduler.add_job(
                job_func,
                'date',
                run_date=run_time,
                args=job_args,
                id=job_id,
                name=f"Task_{job_id}"
            )
        else:
            cron_expression = request.form.get('cron_expression')
            scheduler.add_job(
                job_func,
                'cron',
                args=job_args,
                id=job_id,
                name=f"Task_{job_id}",
                **parse_cron(cron_expression)
            )

        # Store job data in Redis
        redis_client.set(f"job:{job_id}", json.dumps(job_data))
        flash('Task added successfully')
        return redirect(url_for('dashboard'))

    return render_template('add_task.html', base_url=base_url)

@app.route('/delete_task/<job_id>')
@login_required
def delete_task(job_id):
    try:
        scheduler.remove_job(job_id)
        redis_client.delete(f"job:{job_id}")
        flash('Task deleted successfully')
    except Exception as e:
        flash(f'Error deleting task: {str(e)}')
    return redirect(url_for('dashboard'))

@app.route('/get_task_details/<job_id>')
@login_required
def get_task_details(job_id):
    try:
        # Get job data from Redis
        job_data = redis_client.get(f"job:{job_id}")
        if job_data:
            job_details = json.loads(job_data)
            
            # Get scheduler job details
            scheduler_job = scheduler.get_job(job_id)
            if scheduler_job:
                job_details.update({
                    'next_run': scheduler_job.next_run_time.strftime('%Y-%m-%d %H:%M:%S') if scheduler_job.next_run_time else 'Not scheduled',
                    'last_run': scheduler_job.next_run_time.strftime('%Y-%m-%d %H:%M:%S') if hasattr(scheduler_job, 'last_run_time') and scheduler_job.last_run_time else 'Never'
                })
            
            return jsonify(job_details)
        return jsonify({'error': 'Job not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def parse_cron(expression):
    """Parse cron expression into kwargs for APScheduler"""
    parts = expression.split()
    if len(parts) != 5:
        raise ValueError("Invalid cron expression")
    
    return {
        'minute': parts[0],
        'hour': parts[1],
        'day': parts[2],
        'month': parts[3],
        'day_of_week': parts[4]
    }

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3080, debug=True)
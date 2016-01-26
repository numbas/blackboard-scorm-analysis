from functools import wraps
import os
from flask import Flask, request, redirect, url_for, render_template, send_from_directory
from blackboardscorm import BlackboardCourse
import zipfile
import json
from lxml import etree
from datetime import datetime
import shutil

app = Flask(__name__)

current_file = None
zip = None
course = None
scorms_by_pk = {}
extract_path = 'archive'
course = BlackboardCourse(extract_path)

def file_required(fn):
	@wraps(fn)
	def inner(*args,**kwargs):
		if course is None:
			return redirect(url_for('upload_zip')+'?next='+request.path)
		return fn(*args,**kwargs)
	return inner

@app.template_filter('percent')
def percent(n):
	return '{:.2%}'.format(n)

@app.template_filter('correctstyle')
def correctstyle(n,bins=10):
	bin = round(n*bins)
	return 'correct correct-{}'.format(bin)

@app.template_filter('pretty_json')
def pretty_json(d):
	return json.dumps(d,indent=4,separators=(',',': '))

@app.context_processor
def context_scorms():
	global current_file,course
	return {
			'current_file': current_file,
			'course': course,
	}

@app.route('/zip/<path:path>')
@file_required
def file_from_zip(path):
	return send_from_directory(extract_path,path)

@app.route("/")
def index():
	if course is not None and len(course.scorms):
		max_attempts = max(scorm.num_attempts for scorm in course.scorms)
	else:
		max_attempts = 0
	return render_template('index.html',max_attempts=max_attempts)

def allowed_file(filename):
	name,ext = os.path.splitext(filename)
	return ext=='.zip'

@app.route('/upload', methods=['GET', 'POST'])
def upload_zip():
	global current_file,course
	next = request.args.get('next',url_for('index'))
	file = None
	if request.method == 'POST':
		file = request.files['file']
		if file and allowed_file(file.filename):
			current_file = 'current_file.zip'
			zip = zipfile.ZipFile(file.stream)
			try:
				shutil.rmtree(extract_path)
			except FileNotFoundError:
				pass
			zip.extractall(extract_path)
			course = BlackboardCourse(extract_path)
			return redirect(next)

	return render_template('upload.html')


@app.route('/scorm/<pk>/')
@file_required
def view_scorm(pk):
	sort = request.args.get('sort','name')
	order = request.args.get('order','asc')

	sorts = {
		'name': lambda a: (a.user.last_name,a.user.first_name,a.start_time),
		'username': lambda a: (a.user.username,a.start_time),
		'score': lambda a: (a.scaled_score,a.user.last_name,a.user.first_name,a.number),
		'starttime': lambda a: a.start_time or datetime.fromtimestamp(0),
		'duration': lambda a: a.duration,
	}
	scorm = course.scorms_by_pk[pk]
	attempts = sorted(scorm.attempts,key=sorts[sort],reverse = order=='desc')
	return render_template('scorm/index.html',scorm=scorm,attempts=attempts,sort=sort,order=order)

@app.route('/scorm/<pk>/attempt/<attempt>')
@file_required
def attempt_report(pk,attempt):
	scorm = course.scorms_by_pk[pk]
	attempt = scorm.attempts_by_pk[attempt]
	return render_template('scorm/report.html',scorm=scorm,attempt=attempt)

@app.route('/scorm/<pk>/attempt/<attempt>/review')
@file_required
def review(pk,attempt):
	scorm = course.scorms_by_pk[pk]
	attempt = scorm.attempts_by_pk[attempt]
	
	iframe = url_for('file_from_zip',path='{}/index.html'.format(scorm.pk))

	cmi = {
		'cmi.mode': 'review',
		'cmi.entry': 'resume',
		'cmi.suspend_data': json.dumps(attempt.suspend_data),
		'cmi.objectives._count': len(attempt.objectives),
		'cmi.interactions._count': len(attempt.interactions),
		'cmi.learner_name': attempt.user.fullname,
		'cmi.learner_id': attempt.user.username,
		'cmi.location': attempt.location,
		'cmi.score.raw': attempt.raw_score,
		'cmi.score.scaled': attempt.scaled_score,
		'cmi.score.min': attempt.min_score,
		'cmi.score.max': attempt.max_score,
		'cmi.total_time': attempt.total_time,
		'cmi.completion_status': attempt.completion_status,
		'cmi.success_status': attempt.success_status
	}
	for i,objective in enumerate(attempt.objectives):
		p = 'cmi.objectives.{}'.format(i)
		d = {
			'id': objective.id,
			'score.scaled': objective.scaled_score,
			'score.raw': objective.raw_score,
			'score.min': objective.min_score,
			'score.max': objective.max_score,
			'success_status': objective.success_status,
			'completion_status': objective.completion_status,
			'progress_measure': objective.progress_measure,
			'description': objective.name,
		}
		for k,v in d.items():
			cmi['{}.{}'.format(p,k)] = v

	for i,interaction in enumerate(attempt.interactions):
		p = 'cmi.interactions.{}'.format(i)
		d = {
			'id': interaction.id,
			'type': interaction.interaction_type,
			'weighting': interaction.max_score,
			'learner_response': interaction.learner_response,
			'result': interaction.raw_score,
			'description': interaction.part_type,
		}
		for k,v in d.items():
			cmi['{}.{}'.format(p,k)] = v

	if interaction.objective:
		d['objectives._count'] = 1
		d['objectives.1.id'] = interaction.objective
	else:
		d['objectives._count'] = 0

	if interaction.scorm_correct_response:
		d['correct_responses._count'] = 1
		d['correct_responses.1.pattern'] = interaction.scorm_correct_response
	else:
		d['correct_responses._count'] = 0

	return render_template('scorm/review.html',scorm=scorm,attempt=attempt,iframe=iframe,cmi=cmi)

if __name__ == '__main__':
	app.run(debug=True)

from flask import Flask, request, redirect, url_for, render_template, send_from_directory, Response
from werkzeug.routing import BaseConverter
from functools import wraps
import os
import shutil
import json
import zipfile
from lxml import etree
from datetime import datetime,date,timedelta
from blackboardscorm import State,BlackboardCourse
import tempfile
import csv
import itertools
import pygal

app = Flask(__name__)

extract_root = 'courses'
state = State()
print("Ready")

## view decorator
def with_course(fn):
	@wraps(fn)
	def inner(*args,**kwargs):
		course = kwargs['course'] = state.courses_by_pk[kwargs['course']]
		if 'scorm' in kwargs:
			kwargs['scorm'] = course.scorms_by_pk[kwargs['scorm']]
		return fn(*args,**kwargs)
	return inner

## template filters

@app.template_filter('pluralize')
def percent(n):
	return '' if n==1 else 's'

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

## context processor

@app.context_processor
def context_scorms():
	return {
		'state': state,
	}

## views

@app.route("/")
def index():
	return render_template('index.html')

def allowed_file(filename):
	name,ext = os.path.splitext(filename)
	return ext=='.zip'

@app.route('/upload', methods=['GET', 'POST'])
def upload_zip():
	global state
	file = None
	if request.method == 'POST':
		file = request.files['file']
		if file and allowed_file(file.filename):
			name,_ = os.path.splitext(file.filename)
			zip = zipfile.ZipFile(file.stream)
			extract_path = os.path.join(extract_root,name)
			try:
				shutil.rmtree(extract_path)
			except FileNotFoundError:
				pass
			zip.extractall(extract_path)
			course = BlackboardCourse(extract_path)
			state.add_course(course)
			state.save()
			return redirect(url_for('course_index',course=course.pk))

	return render_template('upload.html')

@app.route('/course/<course>')
@with_course
def course_index(course):
	if len(course.scorms):
		max_attempts = max(scorm.num_attempts for scorm in course.scorms)
		min_attempts = min(scorm.num_attempts for scorm in course.scorms)
	else:
		max_attempts = 1
		min_attempts = 0
	return render_template('course/index.html',course=course,max_attempts=max_attempts,min_attempts=min_attempts,attempts_range=max(max_attempts-min_attempts,1))

@app.route('/course/<course>/file/<path:path>')
@with_course
def course_file(course,path):
	return send_from_directory(os.path.join(course.file_path),path)

def start_time_chart(attempts,width=800,height=250):
	get_start_time = lambda a: datetime(a.start_time.year,a.start_time.month,a.start_time.day)
	attempts_by_date = sorted([a for a in attempts if a.start_time is not None],key=get_start_time)
	attempts_by_day = {time:len(list(attempts)) for time,attempts in itertools.groupby(attempts_by_date,key=get_start_time)}

	aday = timedelta(days=1)
	start = min(attempts_by_day.keys())
	end = max(attempts_by_day.keys())
	num_days = (end-start).days
	days = [start+aday*i for i in range(num_days+1)]
	data = [(day,attempts_by_day.get(day,0)) for day in days]

	chart = pygal.DateLine(width=width,height=height,show_legend=False)
	chart.title = 'Start times of attempts'
	chart.add("Attempts started",data)

	return chart

def start_time_sparkline(attempts,width=800,height=250):
	get_start_time = lambda a: datetime(a.start_time.year,a.start_time.month,a.start_time.day)
	attempts_by_date = sorted([a for a in attempts if a.start_time is not None],key=get_start_time)
	attempts_by_day = {time:len(list(attempts)) for time,attempts in itertools.groupby(attempts_by_date,key=get_start_time)}

	aday = timedelta(days=1)
	start = min(attempts_by_day.keys())
	end = max(attempts_by_day.keys())
	num_days = (end-start).days
	data = [(i,attempts_by_day.get(start+aday*i,0)) for i in range(num_days+1)]

	chart = pygal.XY(width=width,height=height)
	chart.add("",data)

	return chart

def score_chart(attempts,width=800,height=250):
	score_bins = [len([a for a in attempts if a.scaled_score>=x/10 and a.scaled_score<(x+1)/10]) for x in range(10)]

	chart = pygal.Bar(width=width,height=height,show_legend=False,human_readable=True)
	chart.title = 'Score distribution'
	chart.add('Number of attempts',score_bins)
	chart.x_labels = ['{}-{}%'.format(i,i+10) for i in range(0,100,10)]

	return chart

@app.route('/course/<course>/scorm/<scorm>/start-times.svg')
@with_course
def start_time_chart_svg(course,scorm):
	return start_time_chart(scorm.attempts).render_response()

@app.route('/course/<course>/scorm/<scorm>/start-times-sparkline.svg')
@with_course
def start_time_sparkline_svg(course,scorm):
	return Response(start_time_sparkline(scorm.attempts).render_sparkline().decode('utf-8'),mimetype='image/svg+xml')

@app.route('/course/<course>/scorm/<scorm>/scores.svg')
@with_course
def score_chart_svg(course,scorm):
	return score_chart(scorm.attempts).render_response()

@app.route('/course/<course>/scorm/<scorm>/score-sparkline.svg')
@with_course
def score_sparkline_svg(course,scorm):
	chart = score_chart(scorm.attempts)
	chart.title = ''
	return Response(chart.render_sparkline().decode('utf-8'),mimetype='image/svg+xml')

@app.route('/course/<course>/scorm/<scorm>/')
@with_course
def view_scorm(course,scorm):
	sort = request.args.get('sort','name')
	order = request.args.get('order','asc')

	sorts = {
		'name': lambda a: (a.user.last_name,a.user.first_name,a.start_time),
		'username': lambda a: (a.user.username,a.start_time),
		'score': lambda a: (a.scaled_score,a.user.last_name,a.user.first_name,a.number),
		'starttime': lambda a: a.start_time or datetime.fromtimestamp(0),
		'duration': lambda a: a.duration,
		'attempt': lambda a: (a.number, a.user.last_name,a.user.first_name,a.start_time),
	}
	attempts = sorted(scorm.attempts,key=sorts[sort],reverse = order=='desc')

	return render_template('scorm/index.html',
			course=course,
			scorm=scorm,
			attempts=attempts,
			sort=sort,
			order=order,
			start_time_chart = start_time_chart(scorm.attempts).render().decode('utf-8'),
			score_chart = score_chart(scorm.attempts).render().decode('utf-8')
		)

@app.route('/course/<course>/scorm/<scorm>.csv')
@with_course
def scorm_csv(course,scorm):
	f = tempfile.TemporaryFile('w+',newline='')
	w = csv.writer(f,lineterminator='\n')
	w.writerow(['Full Name','Username','Start time','Time spent','Raw Score','Scaled Score']+['objective {}'.format(i) for i in scorm.objective_ids])
	for attempt in scorm.attempts:
		objective_scores = []
		for objective_id in scorm.objective_ids:
			if objective_id in attempt.objectives_by_id:
				objective_scores.append(attempt.objectives_by_id[objective_id].raw_score)
			else:
				objective_scores.append('')
		w.writerow([attempt.user.fullname,attempt.user.username,attempt.start_time,attempt.total_time,attempt.raw_score,attempt.scaled_score*100]+objective_scores)
	f.seek(0)
	return Response(f.read(),mimetype='text/csv')

@app.route('/course/<course>/scorm/<scorm>/attempt/<attempt>')
@with_course
def attempt_report(course,scorm,attempt):
	attempt = scorm.attempts_by_pk[attempt]
	return render_template('scorm/report.html',course=course,scorm=scorm,attempt=attempt)

@app.route('/course/<course>/scorm/<scorm>/attempt/<attempt>/review')
@with_course
def review(course,scorm,attempt):
	attempt = scorm.attempts_by_pk[attempt]
	
	iframe = url_for('course_file',course=course.pk,path='{}/index.html'.format(scorm.pk))

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

	return render_template('scorm/review.html',course=course,scorm=scorm,attempt=attempt,iframe=iframe,cmi=cmi)

if __name__ == '__main__':
	app.run(debug=True)

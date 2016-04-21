from lxml import etree
import json
import os
import re
import zipfile
from itertools import groupby
from datetime import datetime,timedelta
from unicodedata import normalize
from random import choice

_punct_re = re.compile(r'[\t !"#$%&\'()*\-/<=>?@\[\\\]^_`{|},.]+')

def slugify(text, delim='-'):
	result = []
	for word in _punct_re.split(text.lower()):
		word = normalize('NFKD', word)
		if word:
			result.append(word)
	return delim.join(result)


alphabet = 'abcdefghijklmnopqrstuvwxyz'

completion_statuses = [
	'',
	'not attempted',
	'',
	'incomplete',
	'',
	'complete',
]
success_statuses = [
	'',
	'unknown',
	'failed',
	'passed',
]

def fuzz(s):
	return s
	def fuzz_character(c):
		if c>='a' and c<='z':
			return choice('abcdefghijklmnopqrstuvwxyz')
		elif c>='A' and c<='Z':
			return choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ')
		elif c>='0' and c<='9':
			return choice('0123456789')
		elif c==' ':
			return ' '
		else:
			return '.'
	return ''.join(fuzz_character(c) for c in s)



class SCORM(object):
	def __init__(self,course,doc):
		self.course = course
		self.doc = doc
		self.pk = doc.xpath('/scormItem')[0].get('mappedContentId')
		self.title = self.doc.xpath('/scormItem/title')[0].text

		registrations = self.doc.xpath('//registration')
		self.attempts = sorted([Attempt(self,registration) for registration in registrations],key=lambda a:a.userid)
		self.objective_ids = list(set(sum([list(a.objectives_by_id.keys()) for a in self.attempts],[])))
		self.num_attempts = len(self.attempts)
		self.attempts_by_pk = {a.pk:a for a in self.attempts}
		
	def attempts_for_user(self,userid):
		return [a for a in self.attempts if a.userid==userid]

class Attempt(object):
	def __init__(self,scorm,element):
		self.scorm = scorm
		self.element = element
		activity = element.xpath('activities/Activity[@ItemIdentifier="item_1"]')[0]
		activity_run_time = activity.xpath('ActivityRunTime')[0]

		self.pk = element.get('scorm_registration_id')
		self.userid = element.get('mappedUserId')
		self.number = int(element.get('instanceId'))+1

		self.user = self.scorm.course.users[self.userid]

		self.duration = timedelta(seconds=round(float(activity.attrib.get('AttemptExperiencedDurationTracked','.'))/100))

		completion_status = int(activity_run_time.get('CompletionStatus'))
		self.completion_status = completion_statuses[completion_status]

		success_status = int(activity_run_time.get('SuccessStatus'))
		self.success_status = success_statuses[success_status]

		self.scaled_score = float(activity_run_time.get('ScoreScaled','0'))
		self.raw_score = float(activity_run_time.get('ScoreRaw','0'))
		self.min_score = float(activity_run_time.get('ScoreMin','0'))
		self.max_score = float(activity_run_time.get('ScoreMax','0'))
		start_time = activity.get('AttemptStartTimestampUtc')
		self.start_time = datetime.strptime(start_time,'%Y-%m-%dT%H:%M:%S') if start_time else None
		self.location = activity_run_time.get('Location')
		self.total_time = float(activity_run_time.get('TotalTimeTracked'))
		
		suspend_data = activity_run_time.get('SuspendData','')
		self.suspend_data = json.loads(suspend_data) if suspend_data else None
		
		self.objectives = sorted([Objective(self,objective) for objective in activity_run_time.xpath('ActivityRunTimeObjective')],key=lambda o: o.question)
		self.objectives_by_id = {o.question:o for o in self.objectives}

		self.interactions = [Interaction(interaction) for interaction in activity_run_time.xpath('ActivityRunTimeInteraction')]
		self.interactions_by_id = {i.id:i for i in self.interactions}

		for interaction in self.interactions:
			interaction.question = self.objectives_by_id.get(interaction.question_number)

		self.interactions_by_question = [(self.objectives_by_id.get(q,-1),sorted(list(interactions),key=lambda i:(i.part,i.gap or 0))) for q,interactions in groupby(self.interactions,key=lambda i: i.question_number)]

type_names = {
	'information': 'Information only',
	'gapfill': 'Gap-fill',
	'jme': 'Mathematical expression',
	'numberentry': 'Number entry',
	'matrix': 'Matrix entry',
	'patternmatch': 'Match text pattern',
	'1_n_2': 'Choose one from a list',
	'm_n_2': 'Choose several from a list',
	'm_n_x': 'Match choices with answers',
}

class Interaction(object):
	def __init__(self,element):
		self.element = element
		self.part_type = element.get('Description')
		self.part_type_name = type_names.get(self.part_type,self.part_type)
		interaction_type = int(element.get('Type'))
		interaction_types = [
			'',
			'true-false',
			'choice',
			'fill-in',
			'long-fill-in',
			'matching',
			'performance',
			'sequencing',
			'likert',
			'numeric',
			'other',
		]
		self.interaction_type = interaction_types[interaction_type]
		self.id = element.get('Id')

		m = re.match(r'q(?P<question>\d+)p(?P<part>\d+)(?:g(?P<gap>\d+))?(?:s(?P<step>\d+))?',self.id)
		self.question_number = int(m.group('question'))+1
		self.part = int(m.group('part'))
		self.gap = int(m.group('gap')) if m.group('gap') else None
		self.step = int(m.group('step')) if m.group('step') else None

		self.name = 'Part {}'.format(alphabet[self.part])
		if self.gap is not None:
			self.name += ', gap {}'.format(self.gap)
		if self.step is not None:
			self.name += ', step {}'.format(self.step)

		self.learner_response = element.get('LearnerResponse')
		self.max_score = element.get('Weighting')
		self.raw_score = element.get('ResultNumeric')
		objective = element.xpath('Objective')
		self.objective = objective[0].get('Id') if objective else None
		correct_response = element.xpath('CorrectResponse')
		self.scorm_correct_response = correct_response[0].get('value') if len(correct_response) else ''

		if self.scorm_correct_response:
			self.correct_response = re.sub(r'^{case_matters=.*}{order_matters=.*}','',self.scorm_correct_response)
		
class Objective(object):
	def __init__(self,attempt,element):
		self.attempt = attempt
		self.element = element
		self.id = element.get('Identifier')
		self.name = element.get('Description')
		completion_status = int(element.get('CompletionStatus'))
		self.completion_status = completion_statuses[completion_status]
		success_status = int(element.get('SuccessStatus'))
		self.success_status = success_statuses[success_status]
		self.progress_measure = float(element.get('ProgressMeasure'))
		self.raw_score = float(element.get('ScoreRaw'))
		self.min_score = float(element.get('ScoreMin'))
		self.max_score = float(element.get('ScoreMax'))
		self.scaled_score = float(element.get('ScoreScaled','0'))
		self.percent_score = self.raw_score/self.max_score if self.max_score>0 else 0

		m = re.match(r'^q(?P<question>\d+)',self.id)
		self.question = int(m.group('question'))+1

		self.suspend_data = self.attempt.suspend_data['questions'][self.question-1]
		self.submitted = self.suspend_data['submitted']
		self.answered = self.suspend_data['answered']
 
class User(object):
	def __init__(self,element):
		self.element = element
		self.id = element.get('id')
		self.username = fuzz(element.xpath('USERNAME')[0].get('value'))
		self.studentid = fuzz(element.xpath('STUDENTID')[0].get('value'))
		self.first_name = fuzz(element.xpath('NAMES/GIVEN')[0].get('value'))
		self.middle_name = fuzz(element.xpath('NAMES/MIDDLE')[0].get('value'))
		self.last_name = fuzz(element.xpath('NAMES/FAMILY')[0].get('value'))
		self.fullname = '{}{} {}'.format(self.first_name,' '+self.middle_name if self.middle_name else '',self.last_name)
		self.email = fuzz(element.xpath('EMAILADDRESS')[0].get('value'))

class HierarchyItem(object):
	def __init__(self,title):
		self.title = title
		self.subitems = []
		self.scorm = None

class BlackboardCourse(object):
	def __init__(self,file_path):
		self.file_path = file_path
		manifest = self.open_file('imsmanifest.xml')
		self.doc = etree.fromstring(manifest)

		self.title = self.doc.xpath('//resource[@type="course/x-bb-coursesetting"]')[0].get('{http://www.blackboard.com/content-packaging/}title')
		self.slug = self.pk = slugify(self.title)

		self.scorms = []
		self.scorms_by_pk = {}

		self.load_users()
		self.load_hierarchy()

	def open_file(self,path):
		return open(os.path.join(self.file_path,path),'rb').read()

	def load_users(self):
		user_filename = self.doc.xpath('//resource[@type="course/x-bb-user"]')[0].get('{http://www.blackboard.com/content-packaging/}file')
		user_doc = etree.fromstring(self.open_file(user_filename))

		self.users = {}
		for element in user_doc.xpath('//USER'):
			user = User(element)
			self.users[user.id] = user

	def load_hierarchy(self):
		organization = self.doc.xpath('//organization')[0]
		self.items = [self.load_item(item) for item in organization.xpath('item')]

	def load_item(self,element):
		title_element = element.xpath('title')
		title = title_element[0].text if len(title_element) else ''
		if re.match(r'^placeholder/',title):
			return self.load_item(element.xpath('item')[0])
		ref = element.get('identifierref')
		item_doc = etree.fromstring(self.open_file('{}.dat'.format(ref)))

		item = HierarchyItem(title)
		item.ref = ref
		item.doc = etree.tostring(item_doc,pretty_print=True)

		if item_doc.tag=='COURSETOC':
			item.kind = 'toc'
			item.subitems = [self.load_item(subelement) for subelement in element.xpath('item/item')]
		elif item_doc.tag=='CONTENT':
			contenthandler = item_doc.xpath('//CONTENTHANDLER')
			if len(contenthandler):
				item.contenthandler = contenthandler[0].get('value')

				content_kinds = {
					'resource/x-plugin-scormengine': 'scorm',
					'resource/x-bb-folder': 'folder',
				}
				item.kind = content_kinds.get(item.contenthandler,'other')

				if item.contenthandler=='resource/x-plugin-scormengine':
					content_id = item_doc.xpath('//CONTENT')[0].get('id')
					item.scorm = self.load_scorm(content_id)

			item.subitems = [self.load_item(subelement) for subelement in element.xpath('item')]

		return item

	def load_scorm(self,content_id):
		resource = self.doc.xpath('//resource[@type="resource/x-plugin-scormengine" and @bb:title="'+content_id+'"]',namespaces={'bb':'http://www.blackboard.com/content-packaging/'})[0]
		dat_filename = resource.get('{http://www.blackboard.com/content-packaging/}file')
		
		scorm_doc = etree.fromstring(self.open_file(dat_filename))
		scorm = SCORM(self,scorm_doc)
		self.scorms_by_pk[scorm.pk] = scorm
		self.scorms.append(scorm)
		return scorm

class State(object):
	def __init__(self):
		self.courses = []
		self.courses_by_pk = {}

		try:
			data = json.loads(open('state.json').read())
		except FileNotFoundError:
			return

		for course_data in data.get('courses',[]):
			course = BlackboardCourse(course_data['extract_path'])
			self.add_course(course)

	def add_course(self,course):
		if course.pk in self.courses_by_pk:
			i = [c.pk for c in self.courses].index(course.pk)
			self.courses[i] = course
		else:
			self.courses.append(course)
		self.courses_by_pk[course.pk] = course

	def save(self):
		data = {
			'courses': [{'extract_path': course.file_path} for course in self.courses]
		}
		f = open('state.json','w')
		f.write(json.dumps(data))
		f.close()
